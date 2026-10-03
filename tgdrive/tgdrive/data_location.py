"""Persistent desktop data selection. No settings/secrets are stored in the locator.
A folder change is copied only at the next start, before the service opens databases.
"""
from __future__ import annotations
import errno
import json
import logging
import os
import shutil
import sys
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


class DataInUse(RuntimeError):
    """Another TG Drive process has this data folder open."""


class DataUnavailable(RuntimeError):
    """The selected data folder is missing (an unplugged drive, a deleted folder)."""


def default_dir() -> Path:
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'TG Drive'
    if sys.platform == 'darwin':
        return Path.home()/'Library'/'Application Support'/'TG Drive'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'tgdrive'


def locator() -> Path:
    if os.environ.get('TGDRIVE_LOCATION_FILE'):return Path(os.environ['TGDRIVE_LOCATION_FILE'])
    if sys.platform == 'win32':base=Path(os.environ.get('APPDATA',Path.home()/'AppData/Roaming'))
    elif sys.platform == 'darwin':base=Path.home()/'Library/Application Support'
    else:base=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))
    return base/'tgdrive'/'data-location.json'


def _read() -> dict:
    path=locator()
    try:value=json.loads(path.read_text())
    except FileNotFoundError:return {}
    except (OSError,ValueError) as exc:
        # A damaged pointer must never stop TG Drive from starting: set it aside and ask again.
        log.warning('unreadable data-folder locator %s: %s', path, exc)
        try:path.replace(path.with_name(path.name+'.damaged'))
        except OSError:pass
        return {}
    return value if isinstance(value,dict) else {}


def _write(value):
    path=locator();path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)


def selected() -> Path:
    return Path(os.environ.get('TGDRIVE_DATA') or _read().get('path') or default_dir()).expanduser().resolve()


def existing(path:Path) -> bool:
    return (path/'settings.json').is_file() or (path/'accounts').is_dir()


def validate(path:str|Path) -> Path:
    p=Path(path).expanduser().resolve()
    if p==Path(p.anchor):raise ValueError('Choose a dedicated TG Drive folder, not the root of a drive.')
    p.mkdir(parents=True,exist_ok=True)
    probe=p/f'.tgdrive-write-{uuid.uuid4().hex}'
    try:probe.write_bytes(b'write check')
    finally:probe.unlink(missing_ok=True)
    return p


def schedule(target:str,current:Path):
    p=validate(target);current=current.resolve()
    if p==current:return {'path':str(p),'pending':False}
    if p.is_relative_to(current) or current.is_relative_to(p):raise ValueError('The new folder must not contain, or be inside, the current data folder.')
    # Never merge into another application's directory or overwrite an existing TG Drive profile.
    if any(p.iterdir()) and not existing(p):raise ValueError('Choose an empty folder or an existing TG Drive data folder.')
    value={'path':str(current),'pending':str(p),'reuse':existing(p)};_write(value)
    return {**value,'restart_required':True}


class DataLock:
    def __init__(self,path:Path):
        path.mkdir(parents=True,exist_ok=True);self.file=open(path/'.tgdrive-data.lock','a+b')
        try:
            if os.name=='nt':
                import msvcrt
                self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN,errno.EWOULDBLOCK,errno.EACCES,getattr(errno,'EDEADLOCK',errno.EDEADLK)):
                self.file.close();raise DataInUse('This data folder is open in another TG Drive process. Close it before switching folders.') from exc
            # Some filesystems (network shares, a few phone/SD card mounts) can't lock files at all:
            # run unlocked there rather than refusing to start.
            log.warning('data folder %s cannot be locked (%s); continuing without the lock', path, exc)
    def close(self):self.file.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def _copy_into(current:Path, target:Path) -> None:
    if any(p.name!='.tgdrive-data.lock' for p in target.iterdir()):
        raise ValueError('The destination changed after it was chosen. Choose it again in Settings.')
    stage=target.parent/f'.tgdrive-copy-{uuid.uuid4().hex}'
    published=[]
    try:
        shutil.copytree(current,stage,ignore=shutil.ignore_patterns('.tgdrive-data.lock'),symlinks=False)
        # All copying must succeed before anything becomes the selected data folder.
        for child in stage.iterdir():
            child.rename(target/child.name);published.append(target/child.name)
    except BaseException:
        # Leave the destination empty again (these are copies; the original is untouched).
        for p in published:
            shutil.rmtree(p,ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        raise
    finally:shutil.rmtree(stage,ignore_errors=True)


def activate(choose=None, legacy=None) -> Path:
    if os.environ.get('TGDRIVE_DATA'):return validate(selected())
    saved=_read();current=selected()
    if not saved and legacy and existing(legacy) and not existing(current):current=legacy.resolve()
    if saved.get('pending'):
        try:
            target=validate(saved['pending'])
            with DataLock(current),DataLock(target):
                if not saved.get('reuse'):_copy_into(current,target)
        except DataInUse:
            # TG Drive is still running from the current folder (e.g. a second launch handing files
            # over to it): keep the move for the next full restart.
            return validate(current)
        except BaseException:
            # A move that failed once is not retried on every start: keep the current folder.
            _write({'path':str(current)})
            raise
        current=target
    elif not saved and not existing(current) and choose:
        picked=choose(current)
        if picked is None:raise SystemExit(0)
        current=validate(picked)
        if any(current.iterdir()) and not existing(current):
            raise ValueError('Choose an empty folder or an existing TG Drive data folder.')
    else:
        if saved.get('path') and not current.is_dir():
            # Never create an empty profile in place of one on a drive that isn't connected.
            raise DataUnavailable(f'The data folder {current} is not available. Connect its drive, or choose another folder.')
        current=validate(current)
    _write({'path':str(current)})
    return current


def use(path:str|Path) -> Path:
    """Select `path` right away (the startup recovery screen): empty, or an existing TG Drive folder."""
    p=validate(path)
    if any(x.name!='.tgdrive-data.lock' for x in p.iterdir()) and not existing(p):
        raise ValueError('Choose an empty folder or an existing TG Drive data folder.')
    _write({'path':str(p)})
    return p


def rebase_owned_paths(root:Path, portable_android=False):
    """Repair only this profile's absolute paths before its databases are opened."""
    root = root.resolve()
    marker = root / '.tgdrive-root.json'
    old = json.loads(marker.read_text()).get('root') if marker.exists() else None
    if old == str(root):
        return
    with DataLock(root):
        moves = [(old, str(root))] if old else []
        if old and portable_android and Path(old).name == 'service':
            moves.append((str(Path(old).parent), str(root.parent)))
        if moves:
            import contextlib
            import sqlite3
            # Never inspect or modify downloaded databases, sessions, or browser caches.
            for db in (root / 'accounts').glob('*/index.db'):
                with contextlib.closing(sqlite3.connect(db)) as c, c:
                    for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                        if table not in ('transfers', 'sync_pairs', 'offline_pins'):
                            continue
                        for col in c.execute(f'PRAGMA table_info("{table}")').fetchall():
                            name = col[1]
                            if name in ('path', 'local_path', 'dest_dir', 'download_dir'):
                                for source, target in moves:
                                    c.execute(f'UPDATE "{table}" SET "{name}"=? || substr("{name}",?) WHERE "{name}"=? OR substr("{name}",1,?) IN (?,?)',
                                              (target, len(source)+1, source, len(source)+1, source+'/', source+'\\'))
            settings = root / 'settings.json'
            if settings.exists():
                value = json.loads(settings.read_text())
                for key, v in value.items():
                    if isinstance(v, str):
                        for source, target in moves:
                            if v == source or v.startswith((source+'/', source+'\\')):
                                value[key] = target + v[len(source):]
                                break
                tmp = settings.with_suffix('.tmp')
                tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
                tmp.replace(settings)
        tmp = marker.with_suffix('.tmp')
        tmp.write_text(json.dumps({'root':str(root)}))
        tmp.replace(marker)
