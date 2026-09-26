"""Regression tests for the 2.3 robustness work: streaming cache, downloads, folder saving, app lock,
duplicate counts, the single writer, connection status, uploads, folder sync guards and disk space."""
import asyncio
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from tests.fake import CH, make_account
from tests.test_core import _big_payload, index_all, run
from tgdrive.streaming import CHUNK, ChunkCache, StreamError


# ------------------------------------------------------------ stream cache
def test_chunk_cache_parallel_writes_to_a_new_file(tmp_path):
    """Many threads writing chunks of a cache file that doesn't exist yet: nothing is lost (the old
    open("wb") could truncate the file under another writer)."""
    for _round in range(5):
        d = tmp_path / f"r{_round}"
        d.mkdir()
        n = 24
        size = n * CHUNK - 1234
        cc = ChunkCache(d, "k", n, size)
        blobs = [bytes([i % 251]) * cc.expected(i) for i in range(n)]
        threads = [threading.Thread(target=cc.write, args=(i, blobs[i])) for i in range(n)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        cc.flush()
        assert cc.complete()
        again = ChunkCache(d, "k", n, size)   # reloaded from disk
        assert again.complete()
        for i in range(n):
            assert again.read(i) == blobs[i]


def test_chunk_cache_rejects_short_chunks_and_distrusts_stale_maps(tmp_path):
    cc = ChunkCache(tmp_path, "k", 4, 4 * CHUNK)
    with pytest.raises(ValueError):
        cc.write(0, b"short")
    assert not cc.has(0)
    cc.write(0, b"a" * CHUNK)
    cc.write(1, b"b" * CHUNK)
    cc.flush()
    # The map claims more than the file holds (e.g. the file was truncated): those bits are dropped.
    (tmp_path / "k.map").write_bytes(bytes([0b1111]))
    os.truncate(tmp_path / "k.bin", CHUNK + 10)
    cc2 = ChunkCache(tmp_path, "k", 4, 4 * CHUNK)
    assert cc2.has(0) and not cc2.has(1) and not cc2.has(2) and not cc2.has(3)


def test_evicted_cache_is_never_written_again(tmp_path):
    cc = ChunkCache(tmp_path, "k", 2, 2 * CHUNK)
    cc.dead = True
    cc.write(0, b"x" * CHUNK)
    assert not (tmp_path / "k.bin").exists()


def test_short_answers_from_telegram_are_never_served_or_cached(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        payload = _big_payload(acc, client)
        real = client.iter_download

        async def short(*a, **kw):
            async for chunk in real(*a, **kw):
                yield chunk[:1000]   # Telegram answers with less than asked for, every time

        client.iter_download = short
        src = await acc.streamer.source(-CH - 101, 1)
        acc.streamer.SLEEP = 0
        with pytest.raises(StreamError):
            await acc.streamer.chunk(src, 0)
        assert not acc.streamer.cache_for(src).has(0)
        client.iter_download = real
        assert await acc.streamer.chunk(src, 0) == payload[:CHUNK]
        acc.db.close()

    run(go())


def test_streaming_matches_the_file_under_concurrency(tmp_path):
    """Whole-file reads with prefetching, many times over: always byte-for-byte right."""
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        payload = _big_payload(acc, client, n=6_000_000)
        for _ in range(8):
            acc.streamer.clear_cache()
            src = await acc.streamer.source(-CH - 101, 1, fresh=True)
            got = b"".join([p async for p in acc.streamer.iter_range(src, 0, len(payload) - 1, prefetch=6)])
            assert got == payload
        acc.db.close()

    run(go())


# --------------------------------------------------------------- downloads
def test_download_ignores_map_bits_the_part_file_cannot_back(tmp_path, fresh_settings):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        payload = _big_payload(acc, client)
        tid = acc.transfers.add_download(-CH - 101, 1)
        acc.transfers.pause(tid)
        t = acc.db.get_transfer(tid)
        part = Path(t["path"] + ".part")
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(payload[:CHUNK])                       # only the first chunk is really there …
        Path(t["path"] + ".part.map").write_bytes(bytes([0b111111]))   # … but the map says all six
        acc.transfers.resume(tid)
        for _ in range(300):
            await asyncio.sleep(0.01)
            if acc.db.get_transfer(tid)["status"] in ("done", "error"):
                break
        t = acc.db.get_transfer(tid)
        assert t["status"] == "done", t
        assert Path(t["path"]).read_bytes() == payload
        acc.db.close()

    run(go())


def test_download_refuses_to_fill_the_disk(tmp_path, fresh_settings, monkeypatch):
    from tgdrive import transfers
    monkeypatch.setattr(transfers, "free_bytes", lambda p: 10 * 1024 * 1024)

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        _big_payload(acc, client)
        tid = acc.transfers.add_download(-CH - 101, 1)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if acc.db.get_transfer(tid)["status"] in ("done", "error"):
                break
        t = acc.db.get_transfer(tid)
        assert t["status"] == "error" and "Not enough free space" in t["error"], t
        acc.db.close()

    run(go())


# ------------------------------------------------------------- folder saving
def test_changes_made_while_folders_are_saving_are_saved_too(tmp_path, monkeypatch):
    from tgdrive import drive as drive_mod
    monkeypatch.setattr(drive_mod, "FLUSH_DELAY", 0.01)

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        d = acc.drive
        real_write = d._write_manifest
        writing = asyncio.Event()
        release = asyncio.Event()

        async def slow_write(peer, data):
            writing.set()
            await release.wait()
            await real_write(peer, data)

        d._write_manifest = slow_write
        await d.create_folder("First", None)
        await asyncio.wait_for(writing.wait(), 5)
        await d.create_folder("Second", None)      # made while the first save is uploading
        release.set()
        d._write_manifest = real_write
        for _ in range(300):
            await asyncio.sleep(0.01)
            if not d._dirty and (d._flush_task is None or d._flush_task.done()):
                break
        from tgdrive.drive import decode_manifest
        peer = d.channel_id
        msg = next(m for m in client.chats[peer] if m.id == d.manifest_msg_id)
        saved = decode_manifest(client.content[msg.media.document.id])
        assert {f["name"] for f in saved["folders"]} >= {"First", "Second"}
        assert acc.db.get_meta("drive_dirty") == "0"
        acc.db.close()

    run(go())


def test_unsaved_folder_changes_survive_a_restart(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        acc.status = "offline"               # can't save now
        await acc.drive.create_folder("Offline edit", None)
        await asyncio.sleep(0.05)
        assert acc.db.get_meta("drive_dirty") == "1"
        acc.drive._dirty = False             # as after a restart: only the stored flag is left
        acc.status = "online"
        acc.drive.resume_pending()
        for _ in range(500):
            await asyncio.sleep(0.01)
            if acc.db.get_meta("drive_dirty") == "0":
                break
        assert acc.db.get_meta("drive_dirty") == "0"
        acc.db.close()

    run(go())


# ------------------------------------------------------------------- app lock
def test_polling_does_not_keep_the_app_unlocked(tmp_path, fresh_settings):
    from fastapi.testclient import TestClient

    from tgdrive import api, maintenance
    acc, _ = make_account(tmp_path)
    api.manager.accounts = {acc.uid: acc}
    c = TestClient(api.app, base_url="http://127.0.0.1:8765")
    H = {"X-TGDrive": "1"}
    lock = maintenance.app_lock
    lock.last_activity = 0
    c.get("/api/status")
    c.get(f"/api/a/{acc.uid}/status")
    c.get("/api/events", params={"after": 0})
    assert lock.last_activity == 0                        # polling isn't activity
    c.get(f"/api/a/{acc.uid}/files/stats", headers={**H, "X-TGDrive-Bg": "1"})
    assert lock.last_activity == 0                        # neither is anything marked as background
    c.post("/api/activity", headers=H)
    assert lock.last_activity > 0                         # the window reporting input is
    lock.last_activity = 0
    c.get(f"/api/a/{acc.uid}/folders")
    assert lock.last_activity > 0                         # and so is a real request
    acc.db.close()


# ---------------------------------------------------------- duplicate counts
def test_counts_match_the_list_for_unfiled_files(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        folder = await acc.drive.create_folder("F", None)
        rows = acc.db.q("SELECT chat_id, msg_id FROM files WHERE chat_id=? LIMIT 6", (-CH - 101,))
        await acc.drive.place([(r["chat_id"], r["msg_id"]) for r in rows[:2]], folder["id"])
        for p in ({"chat_ids": str(-CH - 101), "filed": "0"}, {"chat_ids": str(-CH - 101), "filed": "1"},
                  {"chat_ids": str(-CH - 101), "filed": "0", "copies": "hide"},
                  {"chat_ids": str(-CH - 101), "starred": "0"}, {"filed": "0"}):
            items = (await acc.search.files({**p, "limit": 1000}))["items"]
            stats = await acc.search.stats(p)
            assert stats["total"] == len(items), (p, stats["total"], len(items))
        acc.db.close()

    run(go())


# ------------------------------------------------------------------ writer
def test_writer_thread_and_background_writers_never_hit_locked_errors(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        db = acc.db
        stop = threading.Event()
        errors = []

        def background():
            conn = sqlite3.connect(str(db.path), timeout=0.2, isolation_level=None, check_same_thread=False)
            try:
                while not stop.is_set():
                    with db.wlock:
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('bg', ?)", (str(time.time()),))
                        time.sleep(0.01)
                        conn.execute("COMMIT")
                    time.sleep(0.005)   # real background writers work between their transactions
            except Exception as exc:   # pragma: no cover - reported below
                errors.append(exc)
            finally:
                conn.close()

        th = threading.Thread(target=background)
        th.start()
        try:
            recs = [dict(r) for r in db.q("SELECT * FROM files LIMIT 50")]
            for _ in range(30):
                await db.write(db.index_page, recs, recs[0]["chat_id"])
                db.set_meta("fg", time.time())
        finally:
            stop.set()
            th.join()
        assert not errors, errors
        db.close()

    run(go())


# -------------------------------------------------------------- connection
def test_connection_loss_shows_offline_and_catches_up(tmp_path, monkeypatch):
    real_sleep = asyncio.sleep

    async def fast_sleep(s, *a, **kw):
        await real_sleep(min(s, 0.01))

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        monkeypatch.setattr(asyncio, "sleep", fast_sleep)
        watch = asyncio.get_running_loop().create_task(acc._watchdog())
        client.connected = False
        for _ in range(100):
            await real_sleep(0.01)
            if acc.status == "offline":
                break
        assert acc.status == "offline" and "Reconnecting" in acc.error
        client.connected = True
        for _ in range(100):
            await real_sleep(0.01)
            if acc.status == "online":
                break
        assert acc.status == "online" and client.caught_up == 1
        watch.cancel()
        acc.db.close()

    run(go())


# ------------------------------------------------------------------ uploads
def _wait_transfer(acc, tid, until=("done", "error"), n=400):
    async def w():
        for _ in range(n):
            await asyncio.sleep(0.01)
            if acc.db.get_transfer(tid)["status"] in until:
                break
        return acc.db.get_transfer(tid)
    return w()


def test_upload_retry_after_a_lost_answer_does_not_post_twice(tmp_path, fresh_settings):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        f = tmp_path / "notes.pdf"
        f.write_bytes(b"%PDF" + bytes(range(256)) * 900)
        client.lose_send_answer = 1
        tid = (await acc.transfers.add_upload_paths([str(f)], None))["ids"][0]
        t = await _wait_transfer(acc, tid)
        assert t["status"] == "error", t
        before = [m for m in client.chats[acc.drive.channel_id] if m.file and m.file.name == "notes.pdf"]
        assert len(before) == 1                   # it was posted, the answer got lost
        acc.transfers.resume(tid)
        t = await _wait_transfer(acc, tid)
        assert t["status"] == "done", t
        after = [m for m in client.chats[acc.drive.channel_id] if m.file and m.file.name == "notes.pdf"]
        assert len(after) == 1                    # the retry found it instead of posting again
        assert (t["chat_id"], t["msg_id"]) == (acc.drive.channel_id, after[0].id)
        acc.db.close()

    run(go())


def test_upload_of_a_file_that_changes_meanwhile_is_stopped(tmp_path, fresh_settings):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        f = tmp_path / "growing.log"
        f.write_bytes(b"x" * (CHUNK * 3))
        real = client.__call__

        class Hook:
            done = False

        async def call(req):
            from telethon.tl import functions
            if isinstance(req, (functions.upload.SaveFilePartRequest, functions.upload.SaveBigFilePartRequest)) \
                    and not Hook.done:
                Hook.done = True
                with open(f, "ab") as fh:
                    fh.write(b"more")
                t = time.time() + 5
                os.utime(f, (t, t))
            return await real(req)

        client.__class__ = type("Hooked", (client.__class__,), {"__call__": lambda self, req: call(req)})
        tid = (await acc.transfers.add_upload_paths([str(f)], None))["ids"][0]
        t = await _wait_transfer(acc, tid)
        assert t["status"] == "error" and "changed while it was uploading" in t["error"], t
        assert not [m for m in client.chats.get(acc.drive.channel_id, []) if m.file and m.file.name == "growing.log"]
        acc.db.close()

    run(go())


# --------------------------------------------------------------------- sync
def _pair(acc, tmp_path, name="S"):
    async def go():
        folder = await acc.drive.create_folder(name, None)
        root = tmp_path / name
        root.mkdir()
        pair = await acc.sync.add_pair(str(root), folder["id"])
        acc.sync.approve(pair["id"])
        return folder, root, pair
    return go()


async def _settle(acc, pid, rounds=40):
    for _ in range(rounds):
        plan = await acc.sync.run_pair(pid)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if not acc.db.one("SELECT 1 FROM transfers WHERE status IN ('queued','running')"):
                break
        pending = acc.db.one("SELECT COUNT(*) AS n FROM sync_files WHERE pair_id=? AND pending IS NOT NULL", (pid,))
        if not pending["n"] and not any(plan.get(k) for k in ("upload", "download", "conflict", "busy")):
            return plan
    return plan


def test_sync_waits_for_files_still_being_written(tmp_path, monkeypatch):
    from tgdrive import sync as sync_mod
    monkeypatch.setattr(sync_mod, "QUIET_SECONDS", 30)

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        folder, root, pair = await _pair(acc, tmp_path)
        (root / "new.txt").write_text("being written")
        plan = await acc.sync.run_pair(pair["id"])
        assert plan["busy"] == 1 and plan["upload"] == 0
        old = time.time() - 60
        os.utime(root / "new.txt", (old, old))
        plan = await acc.sync.run_pair(pair["id"])
        assert plan["upload"] == 1
        acc.db.close()

    run(go())


def test_sync_asks_before_many_removals_and_when_the_folder_is_empty(tmp_path, monkeypatch):
    from tgdrive import sync as sync_mod
    monkeypatch.setattr(sync_mod, "QUIET_SECONDS", 0)

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        folder, root, pair = await _pair(acc, tmp_path)
        for i in range(40):
            (root / f"f{i}.txt").write_text(f"file {i}")
        await _settle(acc, pair["id"])
        assert len(acc.db.q("SELECT 1 FROM sync_files WHERE pair_id=?", (pair["id"],))) == 40
        # 12 of 40 removed (30%): under 25 but over the share -> ask
        for i in range(13):
            (root / f"f{i}.txt").unlink()
        await acc.sync.run_pair(pair["id"])
        st = acc.db.one("SELECT state, approved FROM sync_pairs WHERE id=?", (pair["id"],))
        assert st["state"] == "needs approval" and st["approved"] == 0
        # Everything gone (a drive not plugged in?) -> ask, never remove
        acc.sync.approve(pair["id"])
        for p in root.iterdir():
            if p.is_file():
                p.unlink()
        await acc.sync.run_pair(pair["id"])
        st = acc.db.one("SELECT state, error FROM sync_pairs WHERE id=?", (pair["id"],))
        assert st["state"] == "needs approval" and "is empty" in st["error"]
        assert len(acc.db.q("SELECT 1 FROM placements WHERE folder_id=?", (folder["id"],))) == 40
        acc.db.close()

    run(go())


def test_sync_names_of_same_named_files_stay_put(tmp_path, monkeypatch):
    from tgdrive import sync as sync_mod
    monkeypatch.setattr(sync_mod, "QUIET_SECONDS", 0)

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        folder, root, pair = await _pair(acc, tmp_path)
        rows = acc.db.q("SELECT chat_id, msg_id FROM files WHERE kind='document' AND size < 300000 ORDER BY id LIMIT 3")
        for r in rows:
            acc.db.x("UPDATE files SET alias='same.pdf' WHERE chat_id=? AND msg_id=?", (r["chat_id"], r["msg_id"]))
        await acc.drive.place([(r["chat_id"], r["msg_id"]) for r in rows], folder["id"])
        await _settle(acc, pair["id"])
        names = sorted(p.name for p in root.iterdir() if p.is_file())
        assert names == ["same (2).pdf", "same (3).pdf", "same.pdf"], names
        before = {b["rel"]: (b["chat_id"], b["msg_id"]) for b in acc.db.q(
            "SELECT rel, chat_id, msg_id FROM sync_files WHERE pair_id=?", (pair["id"],))}
        first = before["same.pdf"]
        await acc.drive.place([first], None)          # take the first one out in TG Drive
        await _settle(acc, pair["id"])
        after = {b["rel"]: (b["chat_id"], b["msg_id"]) for b in acc.db.q(
            "SELECT rel, chat_id, msg_id FROM sync_files WHERE pair_id=?", (pair["id"],))}
        assert after == {k: v for k, v in before.items() if k != "same.pdf"}   # the others kept their names
        assert sorted(p.name for p in root.iterdir() if p.is_file()) == ["same (2).pdf", "same (3).pdf"]
        acc.db.close()

    run(go())


# ------------------------------------------------------------- disk space
def test_upload_endpoints_refuse_when_the_disk_is_full_and_leave_nothing(tmp_path, fresh_settings, monkeypatch):
    from fastapi.testclient import TestClient

    from tgdrive import api, dav, transfers
    from tgdrive.settings import settings
    acc, _ = make_account(tmp_path)
    api.manager.accounts = {acc.uid: acc}
    settings.update({"dav_enabled": True})
    dav.invalidate_all()
    monkeypatch.setattr(transfers, "free_bytes", lambda p: 1024)
    c = TestClient(api.app, base_url="http://127.0.0.1:8765")
    r = c.put(f"/api/a/{acc.uid}/upload", params={"name": "a.bin"}, content=b"x" * 5000,
              headers={"X-TGDrive": "1"})
    assert r.status_code >= 400 and "free space" in r.text
    r = c.put(f"/dav/{dav.dav_secret()}/My%20Drive/a.bin", content=b"x" * 5000)
    assert r.status_code == 507
    assert not list(acc.transfers.up_dir.iterdir())
    acc.db.close()


# ------------------------------------------------------------- crash reports
def test_crash_reports_carry_state_and_recent_log(tmp_path, monkeypatch):
    import logging

    from tgdrive import config, diagnostics
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    logging.getLogger().addHandler(diagnostics.ring)
    logging.getLogger("tgdrive.test").warning("something odd happened just before")
    diagnostics.add_state_provider("probe", lambda: {"answer": 42})
    rid = diagnostics.record_crash("test", "Traceback: boom")
    text = diagnostics.read_crash(rid)
    assert "--- state ---" in text and '"answer": 42' in text and "threads:" in text
    assert "something odd happened just before" in text
    diagnostics._providers.pop("probe", None)


def test_background_task_failures_become_crash_reports(tmp_path, monkeypatch):
    from tgdrive import config, diagnostics, tasks
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    async def go():
        async def boom():
            raise RuntimeError("task went wrong")
        t = tasks.spawn(boom(), "exploding task")
        await asyncio.sleep(0.05)
        assert t.done() and t not in tasks._live

    run(go())
    reports = diagnostics.list_crashes()["reports"]
    assert any(r["kind"] == "background" for r in reports)
    text = diagnostics.read_crash(reports[0]["id"])
    assert "exploding task" in text and "task went wrong" in text


def test_a_blocked_event_loop_is_reported_with_its_stack(tmp_path, monkeypatch):
    from tgdrive import config, diagnostics
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    def sleepy_blocking_function():
        time.sleep(1.8)

    async def go():
        wd = diagnostics.LoopWatchdog(asyncio.get_running_loop(), threshold=0.6)
        await asyncio.sleep(1.2)
        sleepy_blocking_function()          # blocks the loop
        await asyncio.sleep(1.2)
        wd.stop.set()

    run(go())
    reports = [r for r in diagnostics.list_crashes()["reports"] if r["kind"] == "hang"]
    assert reports
    assert "sleepy_blocking_function" in diagnostics.read_crash(reports[0]["id"])


def test_a_native_crash_found_at_startup_becomes_a_report(tmp_path, monkeypatch):
    from tgdrive import config, diagnostics
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (diagnostics.crash_dir() / "faulthandler-test.log").write_text(
        "Fatal Python error: Segmentation fault\n\nThread 0x01 (most recent call first):\n  File \"x.py\", line 1 in f\n")
    import faulthandler
    diagnostics.enable_faulthandler("test")
    try:
        reports = [r for r in diagnostics.list_crashes()["reports"] if r["kind"] == "native"]
        assert reports and "Segmentation fault" in diagnostics.read_crash(reports[0]["id"])
        assert (diagnostics.crash_dir() / "faulthandler-test.log").stat().st_size == 0
    finally:
        faulthandler.disable()


def test_a_superseded_query_answers_instead_of_vanishing(tmp_path):
    from tgdrive.db import QueryTimeout

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)

        def slow(r):
            time.sleep(0.4)
            return 1

        # Keep one reader busy so the next request waits in its queue, then replace that request.
        busy = asyncio.ensure_future(acc.db.read.run(slow, key="k"))
        queued = asyncio.ensure_future(acc.db.read.run(lambda r: 1, key="k", slot="s"))
        await asyncio.sleep(0.05)
        newer = asyncio.ensure_future(acc.db.read.run(lambda r: 2, slot="s"))
        with pytest.raises(QueryTimeout):
            await queued
        assert await newer == 2 and await busy == 1
        acc.db.close()

    run(go())


# ------------------------------------------------------------------ CPU use
def test_meaning_index_finishes_when_most_files_have_no_words(tmp_path, fresh_settings):
    """Photos without a name or caption have no words. The statistics used to be compared with the
    number of files *with* words, so a library of mostly photos recomputed them forever (a core at 100%)."""
    import sqlite3

    from tgdrive.semantic import SemanticIndex, _Model
    if _Model.get() is None:
        pytest.skip("meaning model not installed")
    fresh_settings.data["background_work"] = "full"
    db = tmp_path / "index.db"
    from tgdrive.db import Database
    d = Database(db)
    recs = []
    for i in range(1, 1201):
        named = i % 5 == 0   # four in five files have no words at all
        recs.append({"chat_id": -100, "msg_id": i, "kind": "photo" if not named else "document",
                     "name": f"Polity notes part {i}.pdf" if named else None, "caption": None, "date": 1_700_000_000,
                     "size": 1000})
    d.upsert_files(recs)
    d.close()
    s = SemanticIndex(tmp_path / "semantic", db)
    s.enabled = True
    calls = []
    real = s._compute_stats
    s._compute_stats = lambda conn, model: (calls.append(1), real(conn, model))
    s.start()
    for _ in range(200):
        time.sleep(0.05)
        if s.state == "ready":
            break
    s.stop()
    assert s.state == "ready", s.state
    assert len(calls) == 1, f"statistics computed {len(calls)} times"
    assert int(s.meta["stats_total"]) == 1200 and int(s.meta["stats_n"]) == 240
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1200


def test_background_work_modes(fresh_settings):
    from tgdrive import pace
    fresh_settings.data["background_work"] = "gentle"
    assert pace.rest_for(0.2) == pytest.approx(0.6) and pace.rest_for(100) == pace.MAX_REST
    fresh_settings.data["background_work"] = "full"
    assert pace.rest_for(5) == 0
    fresh_settings.data["background_work"] = "paused"
    stop = threading.Event()
    t0 = time.time()
    th = threading.Thread(target=pace.wait_while_paused, args=(stop,))
    th.start()
    time.sleep(0.3)
    assert th.is_alive()              # held while paused
    stop.set()
    th.join(2)
    assert not th.is_alive() and time.time() - t0 < 3


def test_cpu_by_part_reports_the_busy_thread():
    from tgdrive import diagnostics
    diagnostics.cpu_by_part()
    done, release = threading.Event(), threading.Event()

    def spin():
        end = time.time() + 0.6
        while time.time() < end:
            pass
        done.set()
        release.wait(5)   # stay alive until measured (a thread that ended has no CPU entry)
    threading.Thread(target=spin, name="tgdrive-semantic").start()
    done.wait(3)
    r = diagnostics.cpu_by_part()
    release.set()
    parts = dict(r["parts"])
    assert parts.get("Meaning index (smart search)", 0) > 20, r
