"""Portable data lifecycle, including reinstall selection and real SQLite path rebasing."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest
from tgdrive import data_location as location

@pytest.fixture
def locator(tmp_path,monkeypatch):
    f=tmp_path/'config'/'location.json';monkeypatch.setenv('TGDRIVE_LOCATION_FILE',str(f));monkeypatch.delenv('TGDRIVE_DATA',raising=False)
    monkeypatch.setattr(location,'default_dir',lambda:tmp_path/'default');return f


def test_first_selection_and_reinstall_restore_credentials(tmp_path,locator):
    folder=tmp_path/'chosen'
    assert location.activate(lambda default:folder)==folder
    (folder/'settings.json').write_text(json.dumps({'api_id':1234,'api_hash':'example-test-hash','theme':'dark'}))
    (folder/'accounts').mkdir();(folder/'accounts'/'test.session').write_bytes(b'fake-session')
    # Uninstall removes the locator, not the selected folder. Selecting it restores its bytes.
    locator.unlink();location.activate(lambda default:folder)
    assert json.loads((folder/'settings.json').read_text())['api_hash']=='example-test-hash'
    assert (folder/'accounts'/'test.session').read_bytes()==b'fake-session'


def test_existing_default_is_auto_detected(locator):
    folder=location.default_dir();folder.mkdir();(folder/'settings.json').write_text('{"api_id":1234}')
    assert location.activate(lambda _:pytest.fail('existing default should not prompt'))==folder


def test_pending_copy_keeps_source_and_rebases_database(tmp_path,locator):
    source=location.activate(lambda _:tmp_path/'old');target=tmp_path/'new'
    (source/'settings.json').write_text(json.dumps({'api_hash':'keep','download_dir':str(source/'downloads')}))
    (source/'accounts/1').mkdir(parents=True);db=source/'accounts/1/index.db'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE offline_pins(path TEXT)');c.execute('INSERT INTO offline_pins VALUES(?)',(str(source/'offline/file.pdf'),))
    location.rebase_owned_paths(source);location.schedule(str(target),source)
    assert location.selected()==source
    assert location.activate()==target;location.rebase_owned_paths(target)
    with sqlite3.connect(target/'accounts/1/index.db') as c:assert c.execute('SELECT path FROM offline_pins').fetchone()[0]==str(target/'offline/file.pdf')
    assert (source/'settings.json').exists()
    assert json.loads((target/'settings.json').read_text())=={'api_hash':'keep','download_dir':str(target/'downloads')}


def test_existing_folder_is_reused_without_merging(tmp_path,locator):
    source=location.activate(lambda _:tmp_path/'first');(source/'settings.json').write_text('{"api_id":1}')
    target=tmp_path/'other';target.mkdir();(target/'settings.json').write_text('{"api_id":2}')
    location.schedule(str(target),source);location.activate()
    assert json.loads((target/'settings.json').read_text())['api_id']==2
    assert json.loads((source/'settings.json').read_text())['api_id']==1


def test_failed_copy_never_switches_location(tmp_path,locator,monkeypatch):
    source=location.activate(lambda _:tmp_path/'old');(source/'settings.json').write_text('{}')
    location.schedule(str(tmp_path/'new'),source)
    def failure(*a,**kw):raise OSError('disk full')
    monkeypatch.setattr(location.shutil,'copytree',failure)
    with pytest.raises(OSError,match='disk full'):location.activate()
    assert location.selected()==source and (source/'settings.json').exists()


def test_live_database_blocks_copy_in_another_process(tmp_path,locator):
    source=location.activate(lambda _:tmp_path/'old')
    with location.DataLock(source):
        code='from pathlib import Path;from tgdrive.data_location import DataLock;DataLock(Path('+repr(str(source))+'))'
        p=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,cwd=Path(__file__).resolve().parents[1])
        assert p.returncode and 'another TG Drive process' in p.stderr


def test_rejects_nested_and_unrelated_directories(tmp_path,locator):
    source=location.activate(lambda _:tmp_path/'source')
    with pytest.raises(ValueError):location.schedule(str(source/'child'),source)
    unrelated=tmp_path/'documents';unrelated.mkdir();(unrelated/'keep.txt').write_text('keep')
    with pytest.raises(ValueError):location.schedule(str(unrelated),source)
    assert (unrelated/'keep.txt').read_text()=='keep'


def test_android_move_rebases_sibling_downloads_and_pending_uploads(tmp_path,locator):
    old=tmp_path/'phone-old';new=tmp_path/'phone-new';root=new/'service';root.mkdir(parents=True)
    (root/'.tgdrive-root.json').write_text(json.dumps({'root':str(old/'service')}))
    (root/'settings.json').write_text(json.dumps({'download_dir':str(old/'downloads')}))
    (root/'accounts/1').mkdir(parents=True)
    with sqlite3.connect(root/'accounts/1/index.db') as c:
        c.execute('CREATE TABLE transfers(path TEXT, dest_dir TEXT)')
        c.execute('INSERT INTO transfers VALUES(?,?)',(str(old/'android/state/upload-staging/a.bin'),str(old/'downloads')))
    location.rebase_owned_paths(root,portable_android=True)
    with sqlite3.connect(root/'accounts/1/index.db') as c:
        # Downloads may equal the root of the mapped subfolder, so exact suffixes are preserved.
        assert c.execute('SELECT path,dest_dir FROM transfers').fetchone()==(str(new/'android/state/upload-staging/a.bin'),str(new/'downloads'))
    assert json.loads((root/'settings.json').read_text())['download_dir']==str(new/'downloads')


def test_first_selection_rejects_an_unrelated_folder(tmp_path,locator):
    other=tmp_path/'personal';other.mkdir();(other/'keep').write_text('original')
    with pytest.raises(ValueError,match='empty folder'):location.activate(lambda _:other)
    assert not locator.exists() and (other/'keep').read_text()=='original'


def test_rebase_preserves_downloaded_databases_and_handles_windows_paths(tmp_path,locator):
    root=tmp_path/'profile';(root/'accounts/1').mkdir(parents=True)
    old='C:\\OldProfile'
    (root/'.tgdrive-root.json').write_text(json.dumps({'root':old}))
    downloads=root/'downloads';downloads.mkdir();foreign=downloads/'customer.db'
    foreign.write_bytes(b'This is a user file, not an app database')
    with sqlite3.connect(root/'accounts/1/index.db') as c:
        c.execute('CREATE TABLE transfers(path TEXT, dest_dir TEXT)')
        c.execute('INSERT INTO transfers VALUES(?,?)',(old+'\\downloads\\a.pdf',old))
    location.rebase_owned_paths(root)
    with sqlite3.connect(root/'accounts/1/index.db') as c:
        assert c.execute('SELECT path,dest_dir FROM transfers').fetchone()==(str(root)+'\\downloads\\a.pdf',str(root))
    assert foreign.read_bytes()==b'This is a user file, not an app database'


def test_failed_move_is_not_retried_on_every_start(tmp_path,locator,monkeypatch):
    source=location.activate(lambda _:tmp_path/'old');(source/'settings.json').write_text('{}')
    location.schedule(str(tmp_path/'new'),source)
    real=location.shutil.copytree
    def failure(*a,**kw):raise OSError('disk full')
    monkeypatch.setattr(location.shutil,'copytree',failure)
    with pytest.raises(OSError):location.activate()
    monkeypatch.setattr(location.shutil,'copytree',real)
    # The next start opens the original folder instead of failing again.
    assert location.activate()==source and 'pending' not in json.loads(locator.read_text())


def test_interrupted_publish_leaves_destination_empty(tmp_path,locator,monkeypatch):
    source=location.activate(lambda _:tmp_path/'old');(source/'settings.json').write_text('{}')
    (source/'accounts').mkdir();(source/'logs').mkdir()
    target=tmp_path/'new';location.schedule(str(target),source)
    real=Path.rename;calls=[]
    def flaky(self,dest):
        calls.append(dest)
        if len(calls)==2:raise OSError('device removed')
        return real(self,dest)
    monkeypatch.setattr(Path,'rename',flaky)
    with pytest.raises(OSError,match='device removed'):location.activate()
    assert [p.name for p in target.iterdir() if p.name!='.tgdrive-data.lock']==[]
    assert location.selected()==source and (source/'accounts').is_dir()


def test_pending_move_waits_while_the_folder_is_open(tmp_path,locator):
    source=location.activate(lambda _:tmp_path/'old');(source/'settings.json').write_text('{}')
    location.schedule(str(tmp_path/'new'),source)
    code='from pathlib import Path;from tgdrive.data_location import DataLock;import sys,time;l=DataLock(Path('+repr(str(source))+'));print("locked",flush=True);sys.stdin.read()'
    holder=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,cwd=Path(__file__).resolve().parents[1])
    try:
        assert holder.stdout.readline().strip()=='locked'
        # A second launch (e.g. "Send to TG Drive") keeps using the open folder and the move stays pending.
        assert location.activate()==source and json.loads(locator.read_text())['pending']==str(tmp_path/'new')
    finally:
        holder.stdin.close();holder.wait(10)
    assert location.activate()==tmp_path/'new'


def test_damaged_locator_does_not_stop_startup(tmp_path,locator):
    locator.parent.mkdir(parents=True);locator.write_text('{not json')
    assert location.activate(lambda default:tmp_path/'picked')==tmp_path/'picked'
    assert locator.with_name(locator.name+'.damaged').exists()


def test_missing_selected_folder_is_never_recreated_empty(tmp_path,locator):
    drive=tmp_path/'usb'/'TG Drive'
    assert location.activate(lambda _:drive)==drive;(drive/'settings.json').write_text('{}')
    import shutil;shutil.rmtree(tmp_path/'usb')
    with pytest.raises(location.DataUnavailable):location.activate()
    assert not drive.exists()
    assert location.use(tmp_path/'elsewhere')==tmp_path/'elsewhere' and location.selected()==tmp_path/'elsewhere'
