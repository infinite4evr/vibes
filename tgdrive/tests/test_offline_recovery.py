"""HTTP -> SQLite -> real transfer jobs, with the deterministic sample Telegram transport."""
import asyncio
from pathlib import Path
import httpx
from tests.fake import make_account
from tests.test_core import index_all
from tests.test_features import wait_transfers
from tgdrive import api
from tgdrive.offline import Offline, store
from tgdrive.settings import settings

H={'x-tgdrive':'1'}
def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://127.0.0.1:8765',headers=H)
def small(a):
    return a.db.one('SELECT * FROM files WHERE size>0 AND size<1000000 LIMIT 1')


def test_pin_download_restart_cache_cleanup_open_unpin(tmp_path,monkeypatch):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);monkeypatch.setattr(api.manager,'accounts',{1:a})
        f=small(a);cid,mid=f['chat_id'],f['msg_id']
        async with client() as c:
            r=await c.post('/api/a/1/offline',json={'items':[[cid,mid]]});assert r.status_code==200,r.text
            tid=r.json()['items'][0]['tid'];assert (await wait_transfers(a,[tid]))[0]['status']=='done'
            a.thumbs.clear();a.streamer.clear_cache();a._offline_store=Offline(a)
            assert (await c.get('/api/a/1/offline')).json()['items'][0]['status']=='ready'
            blob=await c.get(f'/api/a/1/offline/{cid}/{mid}/file');assert len(blob.content)==f['size']
            again=await c.post('/api/a/1/offline',json={'items':[[cid,mid],[cid,mid]]});assert len(again.json()['items'])==1
            out=await c.delete(f'/api/a/1/offline/{cid}/{mid}');assert out.json()['items']==[]
            assert a.db.get_file(cid,mid)
        await a.stop()
    asyncio.run(go())


def test_storage_budget_rejects_before_partial_pin(tmp_path,monkeypatch):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);monkeypatch.setattr(api.manager,'accounts',{1:a})
        f=small(a);settings.data['offline_limit_mb']=0
        async with client() as c:
            r=await c.post('/api/a/1/offline',json={'items':[[f['chat_id'],f['msg_id']]]})
            assert r.status_code==400 and 'limit' in r.json()['error']
            assert not (await c.get('/api/a/1/offline')).json()['items']
        await a.stop()
    asyncio.run(go())


def test_folder_daily_budget_missing_file_and_manual_recovery(tmp_path,monkeypatch):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);monkeypatch.setattr(api.manager,'accounts',{1:a})
        f=small(a);ref=(f['chat_id'],f['msg_id']);folder=await a.drive.create_folder('Offline test',None)
        await a.drive.place([ref],folder['id']);settings.data['automatic_download_daily_mb']=0
        s=store(a);r=s.pin([],folder_id=folder['id'],automatic=True)
        assert 'budget' in r['items'][0]['error'] and r['items'][0]['tid'] is None
        async with client() as c:
            assert (await c.get('/api/a/1/recovery')).json()['issues']
            r=await c.post('/api/a/1/offline/retry');tid=r.json()['items'][0]['tid']
            assert (await wait_transfers(a,[tid]))[0]['status']=='done'
            s.file(*ref).unlink()
            assert any(i['kind']=='offline' for i in (await c.get('/api/a/1/recovery')).json()['issues'])
            await c.delete(f'/api/a/1/offline/folders/{folder["id"]}')
            assert not s.summary()['folders'] and len(s.summary()['items'])==1
        await a.stop()
    asyncio.run(go())


def test_upload_receipt_prevents_duplicate_handoff_and_recovery_resumes(tmp_path,monkeypatch):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);monkeypatch.setattr(api.manager,'accounts',{1:a})
        monkeypatch.setattr(a.transfers,'_spawn',lambda tid:None);await a.drive.ensure_channel()
        async with client() as c:
            url='/api/a/1/upload?name=handoff.txt&upload_id=regression-123'
            first=await c.put(url,content=b'persistent');assert first.status_code==200,first.text
            second=await c.put(url,content=b'persistent');assert second.json()['id']==first.json()['id']
            assert a.db.one("SELECT COUNT(*) AS n FROM transfers WHERE direction='up'")['n']==1
            tid=first.json()['id'];a.db.update_transfer(tid,status='error',error='temporary failure')
            assert any(i['id']==str(tid) for i in (await c.get('/api/a/1/recovery')).json()['issues'])
            assert (await c.post(f'/api/a/1/recovery/transfer/{tid}')).status_code==200
            assert a.db.get_transfer(tid)['status']=='queued'
            a.indexer.phase='error';a.indexer.error='disconnected'
            assert any(i['kind']=='index' for i in (await c.get('/api/a/1/recovery')).json()['issues'])
        await a.stop()
    asyncio.run(go())


def test_thumbnail_budget_does_not_touch_pins(tmp_path):
    async def go():
        a,_=make_account(tmp_path);settings.data['thumb_cache_mb']=1
        for i in range(3):a.thumbs._path(1,i,'s').write_bytes(b'x'*700000)
        a.thumbs.trim();assert a.thumbs.usage()['bytes']<=1024*1024
        private=store(a).root/'kept';private.write_text('pinned bytes')
        a.thumbs.clear();a.streamer.clear_cache();assert private.read_text()=='pinned bytes'
        await a.stop()
    asyncio.run(go())


def test_unpin_in_subscribed_folder_stays_removed_until_explicit_repin(tmp_path):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);f=small(a);ref=(f['chat_id'],f['msg_id'])
        folder=await a.drive.create_folder('Subscribe',None);await a.drive.place([ref],folder['id']);s=store(a)
        r=s.pin([],folder_id=folder['id']);await wait_transfers(a,[r['items'][0]['tid']])
        s.unpin(*ref);s.sync_folders();assert not s.summary()['items']
        r=s.pin([ref]);await wait_transfers(a,[r['items'][0]['tid']]);assert s.file(*ref).is_file()
        await a.stop()
    asyncio.run(go())


def test_download_while_offline_copy_is_fetched_still_goes_to_downloads(tmp_path,monkeypatch):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);f=small(a);ref=(f['chat_id'],f['msg_id'])
        monkeypatch.setattr(a.transfers,'_spawn',lambda tid:None)   # both downloads stay queued
        pin=store(a).pin([ref])['items'][0]['tid']
        a.db.update_transfer(pin,status='paused')   # the offline copy is still on its way
        mine=a.transfers.add_download(*ref)
        assert mine!=pin and not Path(a.db.get_transfer(mine)['path']).is_relative_to(a.dir/'offline')
        assert a.transfers.add_download(*ref)==mine   # a second click still reuses the person's download
        await a.stop()
    asyncio.run(go())


def test_unpin_removes_its_folder_and_bad_recovery_keys_are_rejected(tmp_path,monkeypatch):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);monkeypatch.setattr(api.manager,'accounts',{1:a})
        f=small(a);ref=(f['chat_id'],f['msg_id']);s=store(a)
        await wait_transfers(a,[s.pin([ref])['items'][0]['tid']])
        folder=s.file(*ref).parent;s.unpin(*ref);assert not folder.exists()
        async with client() as c:
            r=await c.post('/api/a/1/recovery/transfer/not-a-number');assert r.status_code==400,r.text
        await a.stop()
    asyncio.run(go())


def test_upload_receipts_stay_bounded(tmp_path,monkeypatch):
    async def go():
        a,_=make_account(tmp_path);await index_all(a);monkeypatch.setattr(api.manager,'accounts',{1:a})
        monkeypatch.setattr(a.transfers,'_spawn',lambda tid:None);await a.drive.ensure_channel();store(a)
        for i in range(2500):a.db.x("INSERT INTO upload_receipts(key,tid) VALUES(?,?)",(f'old-{i}',i))
        async with client() as c:
            url='/api/a/1/upload?name=r.txt&upload_id=new-receipt'
            r=await c.put(url,content=b'hello');assert r.status_code==200,r.text
            again=await c.put(url,content=b'hello');assert again.json()=={'id':r.json()['id'],'recovered':True}
        assert a.db.one('SELECT COUNT(*) AS n FROM upload_receipts')['n']<=2001
        assert a.db.one("SELECT tid FROM upload_receipts WHERE key='new-receipt'")
        await a.stop()
    asyncio.run(go())
