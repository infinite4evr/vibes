import asyncio
import gzip
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from telethon.tl import types

from tests.fake import CH, audio_attr, doc_msg, make_account, photo_msg, text_msg, video_attr
from tgdrive import query, textproc
from tgdrive.db import Database
from tgdrive.drive import DriveError, decode_manifest, encode_manifest, merge_manifests
from tgdrive.extract import MANIFEST_NAME, extract
from tgdrive.links import message_link

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


async def index_all(acc):
    await acc.indexer.sync_dialogs()
    for chat in acc.db.chats_needing_index():
        await acc.indexer.index_chat(acc.db.get_chat(chat["id"]))


async def search(acc, q="", **p):
    res = await acc.search.files({"q": q, "limit": 500, **p})
    return res["items"]


# ------------------------------------------------------------------ extract
def test_extract_kinds_and_names():
    cid = -CH - 5
    assert extract(photo_msg(cid, 1, NOW), cid)["kind"] == "photo"
    p = extract(photo_msg(cid, 1, NOW, w=4000, h=3000), cid)
    assert (p["width"], p["height"], p["size"], p["ext"]) == (4000, 3000, 210000, "jpg")
    assert p["stripped"].startswith(b"\x01\x28")  # inline preview kept
    v = extract(doc_msg(cid, 2, "clip.mp4", "video/mp4", 10, NOW, attrs=[video_attr(12)]), cid)
    assert v["kind"] == "video" and v["duration"] == 12
    r = extract(doc_msg(cid, 3, None, "video/mp4", 10, NOW, attrs=[video_attr(5, round_=True)]), cid)
    assert r["kind"] == "round" and r["name"].startswith("round_") and r["name"].endswith(".mp4")
    g = extract(doc_msg(cid, 4, "a.mp4", "video/mp4", 10, NOW,
                        attrs=[types.DocumentAttributeAnimated(), video_attr(2)]), cid)
    assert g["kind"] == "gif"
    a = extract(doc_msg(cid, 5, None, "audio/mpeg", 10, NOW, attrs=[audio_attr(title="Song", performer="Band")]), cid)
    assert a["kind"] == "audio" and a["name"] == "Band - Song.mp3"
    vo = extract(doc_msg(cid, 6, None, "audio/ogg", 10, NOW, attrs=[audio_attr(voice=True)]), cid)
    assert vo["kind"] == "voice" and vo["ext"] == "ogg"
    img = extract(doc_msg(cid, 7, "scan.PNG", "image/png", 10, NOW), cid)
    assert img["kind"] == "photo" and img["ext"] == "png"
    d = extract(doc_msg(cid, 8, "report.tar.gz", "application/gzip", 10, NOW, fwd="Alice"), cid)
    assert d["kind"] == "document" and d["ext"] == "gz" and d["is_forward"] == 1 and d["fwd_from"] == "Alice"
    sticker = doc_msg(cid, 9, "s.webp", "image/webp", 10, NOW,
                      attrs=[types.DocumentAttributeSticker(alt="x", stickerset=types.InputStickerSetEmpty())])
    assert extract(sticker, cid) is None
    assert extract(doc_msg(cid, 10, MANIFEST_NAME, "application/json", 10, NOW), cid) is None
    assert extract(text_msg(cid, 11, NOW), cid) is None


def test_links():
    assert message_link(-CH - 123, "channel", "news", 5) == "https://t.me/news/5"
    assert message_link(-CH - 123, "supergroup", None, 5) == "https://t.me/c/123/5"
    assert message_link(777, "user", "priya", 5) is None
    assert message_link(-55, "group", None, 5) is None


def test_keywords():
    kw = textproc.keywords("Mock_TestSeries-2024 Prelims.pdf", "Free test series")
    for w in ("test", "series", "mocktest", "testseries"):
        assert w in kw.split(), w
    assert "pyq" in textproc.keywords("Previous Year Questions 2011-2024.pdf").split()
    hindi = textproc.keywords("भारतीय संविधान नोट्स.pdf")
    assert "samvidhan" in hindi.split() and "samvidhana" in hindi.split()
    assert textproc.words("नमस्ते दुनिया") == ["नमस्ते", "दुनिया"]  # vowel signs stay inside words


# ------------------------------------------------------------------- query
def test_query_parser():
    f = query.parse('type:video,gif ext:.PDF in:"Physics Lectures" size>10mb size<=1g after:2024-01 '
                    'before:2025 dur>5m is:forwarded -is:mine has:caption "wave function" -spam lecture '
                    'is:starred tag:exam match:exact')
    assert f["kinds"] == {"video", "gif"} and f["exts"] == {"pdf"}
    assert f["chat_like"] == ["Physics Lectures"]
    assert f["size_min"] == 10 * 1024**2 + 1 and f["size_max"] == 1024**3 + 1
    assert f["dur_min"] == 300 and f["forwarded"] is True and f["mine"] is False and f["has_caption"] is True
    assert f["phrases"] == ["wave function"] and f["neg_terms"] == ["spam"] and f["terms"] == ["lecture"]
    assert f["starred"] is True and f["tags"] == ["exam"] and f["match"] == "exact"
    assert f["date_from"] < f["date_to"]
    assert query.parse("size:>2g")["size_min"] == 2 * 1024**3 + 1
    assert query.parse("https://example.com/x")["terms"]  # not an operator
    assert query.parse_date_range("today")[1] - query.parse_date_range("today")[0] == 86400
    with pytest.raises(query.QueryError):
        query.parse("type:spreadsheet")
    with pytest.raises(query.QueryError):
        query.parse("after:yesterday-ish")


def test_search_end_to_end(tmp_path):
    async def go():
        acc, _ = make_account(tmp_path)
        await index_all(acc)
        total = acc.db.totals()["files"]
        assert total == 18 + 20 + 24 + 12 + 16 + 12 + 2
        assert len(await search(acc)) == total
        assert all(r["kind"] == "video" for r in await search(acc, "type:video"))
        assert len(await search(acc, "type:video")) == 10
        assert {r["chat_title"] for r in await search(acc, "in:physics")} == {"Physics Lectures"}
        quant = await search(acc, "quant", match="exact")
        assert len(quant) == 10                                  # prefix match on file names
        assert len(await search(acc, '"wave functions"', match="exact")) == 10
        assert all("Invoice" in r["name"] for r in await search(acc, "invoice ext:pdf", match="exact"))
        assert len(await search(acc, "source:bot")) == 12
        assert len(await search(acc, "source:channel")) == 18 + 20
        assert len(await search(acc, "", chat_kinds="group")) == 12 + 24
        assert all(r["size"] > 300 * 1024**2 for r in await search(acc, "size>300mb"))
        assert len(await search(acc, "is:forwarded")) == 1
        assert len(await search(acc, "is:mine")) == 2
        big = await search(acc, "", sort="size", order="desc")
        assert big[0]["size"] >= big[-1]["size"]
        assert not await search(acc, "lecture -quantum type:video")
        st = await acc.search.stats({"q": "in:priya"})
        assert st["kind_counts"] == {"audio": 8, "gif": 8} and st["total"] == 16
        st = await acc.search.stats({"chat_ids": str(777)})  # answered from the stats table
        assert st["total"] == 16 and st["kind_counts"] == {"audio": 8, "gif": 8}
        # Keyset paging covers everything exactly once.
        seen, cursor = [], None
        while True:
            res = await acc.search.files({"limit": 7, **({"cursor": cursor} if cursor else {})})
            seen += [(r["chat_id"], r["msg_id"]) for r in res["items"]]
            cursor = res["next"]
            if not cursor:
                break
        assert len(seen) == len(set(seen)) == total
        acc.db.close()

    run(go())


def test_smart_search_finds_differently_written_forms(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        cid = -CH - 101
        names = ["Economy_TestSeries_2023.pdf", "Mock Test Series Polity.pdf", "series-test answer key.pdf",
                 "UPSCTestseries48.pdf", "Previous Year Questions Polity.pdf", "PYQ Economy 2024.pdf",
                 "भारतीय संविधान नोट्स.pdf", "Samvidhan short notes.pdf", "Polity notes.pdf"]
        for i, n in enumerate(names):
            client.chats[cid].append(doc_msg(cid, 1000 + i, n, "application/pdf", 1000 + i, NOW))
        await index_all(acc)

        async def names_for(q, **p):
            return {r["name"]: r["match"] for r in await search(acc, q, sort="relevance", **p)}

        ts = await names_for("test series")
        for n in names[:4]:
            assert n in ts, (n, ts)
        assert ts["Economy_TestSeries_2023.pdf"] == "exact"  # compound split at index time
        joined = await names_for("testseries")
        assert "Mock Test Series Polity.pdf" in joined and "series-test answer key.pdf" in joined
        assert "UPSCTestseries48.pdf" in await names_for("series")      # text inside a word
        typo = await acc.search.files({"q": "seires", "sort": "relevance"})
        assert any("Series" in r["name"] for r in typo["items"]) and typo.get("corrected") == "series"
        pyq = await names_for("pyq")
        assert "Previous Year Questions Polity.pdf" in pyq and "PYQ Economy 2024.pdf" in pyq
        pyq2 = await names_for("previous year questions")
        assert "PYQ Economy 2024.pdf" in pyq2
        sam = await names_for("samvidhan")
        assert "भारतीय संविधान नोट्स.pdf" in sam and "Samvidhan short notes.pdf" in sam
        assert "Samvidhan short notes.pdf" in await names_for("संविधान")
        # Built-in synonym group: polity ↔ constitution ↔ संविधान
        assert "भारतीय संविधान नोट्स.pdf" in await names_for("polity")
        # Exact mode switches all of that off.
        exact = await names_for("testseries", match="exact")
        assert "Mock Test Series Polity.pdf" not in exact
        # Suggestions and "did you mean".
        sug = await acc.search.suggest("seires")
        assert sug["did_you_mean"] == "series"
        sug = await acc.search.suggest("pdf")
        assert any(o["insert"] == "ext:pdf" for o in sug["operators"])
        acc.db.close()

    run(go())


def test_upgrade_of_old_index_keeps_everything(tmp_path):
    """An index written by TG Drive 0.1 is upgraded in place and searchable without re-indexing."""
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    from tgdrive.db import V1
    c.executescript(V1)
    c.executescript("""
      CREATE VIRTUAL TABLE files_fts USING fts5(name, alias, caption, chat_title, sender_name,
        content='files', content_rowid='id', tokenize='unicode61 remove_diacritics 2', prefix='2 3');
      CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
        INSERT INTO files_fts(rowid, name, alias, caption, chat_title, sender_name)
        VALUES (new.id, new.name, new.alias, new.caption, new.chat_title, new.sender_name); END;""")
    c.execute("INSERT INTO chats(id, title, kind) VALUES(-1000000000101, 'Design', 'channel')")
    for i in range(300):
        c.execute("INSERT INTO files(chat_id, msg_id, kind, name, size, date, chat_title) VALUES(?,?,?,?,?,?,?)",
                  (-1000000000101, i + 1, "document", f"TestSeries part{i}.pdf", 100, 1_700_000_000 + i, "Design"))
    c.execute("INSERT INTO placements(chat_id, msg_id, folder_id, alias) VALUES(-1000000000101, 1, NULL, 'Renamed')")
    c.commit()
    c.close()
    db = Database(path)
    from tgdrive.db import SCHEMA_VERSION
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 6
    st = db.search_upgrade_status()
    assert st["state"] == "migrating" and st["total"] == 300
    assert db.totals() == {"files": 300, "bytes": 30000}
    assert db.get_chat(-1000000000101)["file_count"] == 300
    while db.build_search_batch(batch=64):
        pass
    assert db.search_ready and not db.one("SELECT 1 FROM sqlite_master WHERE name='files_fts'")
    n = db.one("SELECT COUNT(*) AS n FROM search_fts WHERE search_fts MATCH '\"series\"*'")["n"]
    assert n == 300
    # Live writes after the upgrade keep both indexes and stats right.
    db.upsert_files([{"chat_id": -1000000000101, "msg_id": 999, "kind": "video", "name": "Clip.mp4", "size": 5,
                      "date": 1}])
    db.delete_files(-1000000000101, [2])
    assert db.totals() == {"files": 300, "bytes": 29905}
    assert db.one("SELECT COUNT(*) AS n FROM names_tri WHERE names_tri MATCH 'lip'")["n"] == 1
    db.close()


# ---------------------------------------------------------------- indexing
def test_backfill_resumes_after_interruption(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await acc.indexer.sync_dialogs()
        cid = -CH - 103  # 24 photos
        import tgdrive.indexer as ix
        ix.PAGE = 5
        client.fail_iter_after = 12
        await acc.indexer.index_chat(acc.db.get_chat(cid))
        chat = acc.db.get_chat(cid)
        assert chat["index_state"] == "error"
        prog = acc.db.get_progress(cid, "media")
        assert prog["done"] == 0 and prog["oldest_id"] > 0
        partial = acc.db.one("SELECT COUNT(*) n FROM files WHERE chat_id=?", (cid,))["n"]
        assert 10 <= partial < 24
        client.fail_iter_after = None
        await acc.indexer.index_chat(acc.db.get_chat(cid))
        assert acc.db.get_chat(cid)["index_state"] == "done"
        assert acc.db.get_chat(cid)["file_count"] == 24
        assert acc.db.get_progress(cid, "media")["done"] == 1
        ix.PAGE = 100
        acc.db.close()

    run(go())


def test_incremental_and_counters_skip_empty_filters(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        assert not acc.db.chats_needing_index()
        cid = -CH - 102
        client.chats[cid].append(doc_msg(cid, 500, "Lecture 99.mp4", "video/mp4", 5, NOW, attrs=[video_attr(9)]))
        await acc.indexer.sync_dialogs()
        todo = acc.db.chats_needing_index()
        assert [c["id"] for c in todo] == [cid]
        client.iter_calls = 0
        await acc.indexer.index_chat(acc.db.get_chat(cid))
        assert acc.db.get_file(cid, 500)["name"] == "Lecture 99.mp4"
        assert client.iter_calls == 2
        assert not acc.db.chats_needing_index()
        acc.db.close()

    run(go())


def test_index_policies_and_telegram_folders(tmp_path, fresh_settings):
    async def go():
        fresh_settings.data["index_kinds"] = ["document", "video"]
        fresh_settings.data["index_skip_kinds_of_chat"] = ["bot"]
        acc, client = make_account(tmp_path)
        await acc.indexer.sync_dialogs()
        await acc.indexer.sync_dialog_filters()
        filters = {r["title"]: json.loads(r["chat_ids"]) for r in acc.db.q("SELECT * FROM dialog_filters")}
        assert filters["Study"] == [-CH - 102] and filters["Bots"] == [888]
        for chat in acc.db.chats_needing_index():
            if chat["kind"] != "bot":
                await acc.indexer.index_chat(acc.db.get_chat(chat["id"]))
        kinds = {r["kind"] for r in acc.db.q("SELECT DISTINCT kind FROM files")}
        assert kinds <= {"document", "video", "photo"} and "audio" not in kinds
        assert not acc.db.q("SELECT 1 FROM files WHERE chat_id=888")
        res = await acc.search.files({"dialog_filter": "2"})
        assert {r["chat_id"] for r in res["items"]} == {-CH - 102}
        acc.db.close()

    run(go())


class Ev:
    def __init__(self, chat_id, message=None, deleted_ids=None, entity=None):
        self.chat_id, self.message, self.deleted_ids, self._entity = chat_id, message, deleted_ids, entity

    async def get_chat(self):
        return self._entity


def test_live_updates_and_deletion_check(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        cid = 777
        latest_before = acc.db.get_chat(cid)["latest_msg_id"]
        m = doc_msg(cid, latest_before + 1, "notes.txt", "text/plain", 42, NOW)
        await acc.indexer._on_new(Ev(cid, m))
        assert acc.db.get_file(cid, m.id)["name"] == "notes.txt"
        assert acc.db.get_progress(cid, "document")["newest_id"] == m.id
        edited = doc_msg(cid, m.id, "notes.txt", "text/plain", 42, NOW, caption="updated caption")
        await acc.indexer._on_edit(Ev(cid, edited))
        assert acc.db.get_file(cid, m.id)["caption"] == "updated caption"
        assert [r["name"] for r in await search(acc, "updated caption", match="exact")] == ["notes.txt"]
        await acc.indexer._on_delete(Ev(None, deleted_ids=[m.id]))
        assert acc.db.get_file(cid, m.id) is None
        from tests.fake import user
        stranger = user(4242, "New", "Person")
        client.entities[4242] = stranger
        await acc.indexer._on_new(Ev(4242, photo_msg(4242, 1, NOW), entity=stranger))
        assert acc.db.get_chat(4242)["title"] == "New Person"
        assert acc.db.get_file(4242, 1)["kind"] == "photo"
        # Deleted while TG Drive was closed: the background check notices.
        bot = 888
        before = acc.db.get_chat(bot)["file_count"]
        client.chats[bot] = client.chats[bot][2:]
        acc.db.x("UPDATE chats SET verified_until=0 WHERE id<>?", (bot,))
        acc.db.x("UPDATE chats SET index_state='pending' WHERE id<>?", (bot,))
        assert await acc.indexer.verify_step()
        assert acc.db.get_chat(bot)["file_count"] == before - 2
        acc.db.close()

    run(go())


# ------------------------------------------------------------------- drive
def test_folders_manifest_roundtrip_and_undo(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        d = acc.drive
        await d.load()
        assert d.channel_id == 0  # no channel until the first write
        work = await d.create_folder("Work", None, color="blue")
        tax = await d.create_folder("Tax", work["id"])
        with pytest.raises(DriveError):
            await d.create_folder("work", None)  # case-insensitive clash
        with pytest.raises(DriveError):
            await d.update_folder(work["id"], parent_id=tax["id"])  # cycle
        await d.place([(888, 1), (888, 2)], tax["id"])
        await d.rename_file(888, 1, "January invoice.pdf")
        await d.set_meta_items([(888, 1)], starred=True, tags_add=["Tax", "2026"])
        await d.set_meta_items([(888, 2)], note="Paid late")
        assert acc.db.get_file(888, 1)["alias"] == "January invoice.pdf"
        assert [p["name"] for p in d.path(tax["id"])] == ["Work", "Tax"]
        await d.flush_now()
        assert d.channel_id == -CH - 999
        manifest_id = client.pinned[d.channel_id]
        assert [r["msg_id"] for r in await search(acc, "january", match="exact")] == [1]
        assert [r["msg_id"] for r in await search(acc, "is:starred tag:tax")] == [1]
        assert [r["msg_id"] for r in await search(acc, "has:note")] == [2]

        # A second device (fresh local DB) sees the same folders, stars, tags and notes.
        acc2, _ = make_account(tmp_path / "other", world=(client.chats, client.entities, client.content))
        acc2.client = client
        await index_all(acc2)
        acc2.db.set_meta("drive_channel_id", d.channel_id)
        await acc2.drive.load()
        assert {f["name"] for f in acc2.drive.folders()} == {"Work", "Tax"}
        f1 = acc2.db.get_file(888, 1)
        assert f1["alias"] == "January invoice.pdf" and f1["folder_id"] == tax["id"] and f1["starred"] == 1
        assert f1["tags"] == "tax,2026" and acc2.db.get_file(888, 2)["note"] == "Paid late"

        # Both devices change things at the same time: the merge keeps both changes.
        await acc2.drive.create_folder("Receipts", None)
        await d.update_folder(tax["id"], name="Taxes")
        await acc2.drive.flush_now()
        await d.flush_now()  # d notices acc2's write, merges, then writes
        assert client.pinned[d.channel_id] == manifest_id
        data = await client.download_media(await client.get_messages(d.channel_id, manifest_id), file=bytes)
        names = {f["name"] for f in decode_manifest(data)["folders"]}
        assert names == {"Work", "Taxes", "Receipts"}

        # Undo, deletion with tombstones, and backups.
        await d.delete_folder(work["id"])
        assert {f["name"] for f in d.folders()} == {"Receipts"}
        assert acc.db.get_file(888, 1)["folder_id"] is None
        assert acc.db.get_file(888, 1)["alias"] == "January invoice.pdf"
        assert await d.undo() == "Delete folder “Work”"
        assert {f["name"] for f in d.folders()} == {"Work", "Taxes", "Receipts"}
        assert acc.db.get_file(888, 1)["folder_id"] == tax["id"]
        assert d.backups()

        # Bulk rename and saved searches.
        await d.bulk_rename([(888, 3), (888, 4)], "Bill {n:02}")
        assert acc.db.get_file(888, 3)["alias"] == "Bill 01.pdf" and acc.db.get_file(888, 4)["alias"] == "Bill 02.pdf"
        s = await d.save_search("Big videos", "type:video size>500mb", {})
        assert d.saved_searches()[0]["id"] == s["id"]

        # Copy a file into the Drive channel; send to another chat.
        new = await d.copy_to_drive(-CH - 101, 1, None)
        assert acc.db.get_file(new["chat_id"], new["msg_id"])["name"] == acc.db.get_file(-CH - 101, 1)["name"]
        res = await d.send_to([(-CH - 101, 1)], 1, "forward")
        assert res["sent"] == 1
        acc.db.close()
        acc2.db.close()

    run(go())


def test_manifest_merge_rules():
    a = {"folders": [{"id": "f1", "name": "A", "mtime": 10}], "items": [], "saved": [],
         "tombstones": [{"kind": "folder", "id": "f2", "at": 50}]}
    b = {"folders": [{"id": "f1", "name": "A2", "mtime": 20}, {"id": "f2", "name": "B", "mtime": 30}],
         "items": [{"chat_id": 1, "msg_id": 2, "folder_id": "f1", "mtime": 5}], "saved": []}
    m = merge_manifests(a, b)
    assert [f["name"] for f in m["folders"]] == ["A2"]      # newer rename wins, deleted folder stays deleted
    assert len(m["items"]) == 1
    big = {"app": "tgdrive", "items": [{"chat_id": i, "msg_id": i} for i in range(20000)]}
    blob = encode_manifest(big)
    assert blob[:2] == b"\x1f\x8b" and decode_manifest(blob) == big
    assert gzip.decompress(blob)


# --------------------------------------------------------------- transfers
def _big_payload(acc, client, cid=-CH - 101, mid=1, n=3_072_000):
    doc_id = next(m for m in client.chats[cid] if m.id == mid).media.document.id
    payload = bytes(range(256)) * (n // 256)
    client.content[doc_id] = payload
    acc.db.x("UPDATE files SET size=? WHERE chat_id=? AND msg_id=?", (len(payload), cid, mid))
    for m in client.chats[cid]:
        if m.id == mid:
            m.media.document.size = len(payload)
    return payload


def test_streaming_ranges_and_cache(tmp_path):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        payload = _big_payload(acc, client)
        src = await acc.streamer.source(-CH - 101, 1)
        assert src.size == len(payload) and src.chunks == 6
        got = b"".join([p async for p in acc.streamer.iter_range(src, 1000, 700_000, prefetch=0)])
        assert got == payload[1000:700_001]
        calls = client.download_calls
        again = b"".join([p async for p in acc.streamer.iter_range(src, 600_000, 1_000_000, prefetch=0)])
        assert again == payload[600_000:1_000_001] and client.download_calls == calls  # served from cache
        tail = b"".join([p async for p in acc.streamer.iter_range(src, len(payload) - 10, len(payload) - 1)])
        assert tail == payload[-10:]
        from tgdrive.streaming import parse_range
        assert parse_range("bytes=-500", 1000) == (500, 999) and parse_range("bytes=10-", 100) == (10, 99)
        acc.db.close()

    run(go())


def test_download_resumed_while_its_last_save_still_runs(tmp_path, fresh_settings, monkeypatch):
    """Pausing cancels a download while a worker thread may still be saving its .part.map; the
    cancelled download then saves once more. The two saves must not collide (they did: same temp
    file, "No such file or directory", and the download ended in an error)."""
    import threading
    from tgdrive import transfers as tr
    real_fsync, real_replace = tr.os.fsync, tr.os.replace
    started = threading.Event()
    both = threading.Barrier(2, timeout=1.5)
    calls = []

    def fsync(fd):
        calls.append(fd)
        if len(calls) <= 2:          # the first save, and the one the cancelled download makes
            started.set()
            try:
                both.wait()          # …run together (or one after the other, when they take turns)
            except threading.BrokenBarrierError:
                pass
        real_fsync(fd)

    def replace(src, dst):
        if str(dst).endswith(".part.map"):
            time.sleep(0.05)         # a slow disk: the window where the other save overwrites .tmp
        real_replace(src, dst)

    monkeypatch.setattr(tr.os, "fsync", fsync)
    monkeypatch.setattr(tr.os, "replace", replace)

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        cid, mid = -CH - 101, 1
        payload = _big_payload(acc, client)
        tid = acc.transfers.add_download(cid, mid)
        for _ in range(500):
            await asyncio.sleep(0.01)
            if started.is_set():
                break
        assert started.is_set(), "the download never saved its map"
        acc.transfers.pause(tid)
        await asyncio.sleep(0.3)
        acc.transfers.resume(tid)
        for _ in range(800):
            await asyncio.sleep(0.01)
            if acc.db.get_transfer(tid)["status"] in ("done", "error"):
                break
        await asyncio.sleep(0.3)
        t = acc.db.get_transfer(tid)
        assert t["status"] == "done", t
        assert Path(t["path"]).read_bytes() == payload
        acc.db.close()

    run(go())


def test_download_parallel_pause_resume_and_upload(tmp_path, fresh_settings):
    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        cid, mid = -CH - 101, 1
        payload = _big_payload(acc, client)
        gate = asyncio.Event()
        real = client.iter_download
        served = []

        async def gated(*a, **kw):
            async for chunk in real(*a, **kw):
                served.append(kw.get("offset"))
                if len(served) > 2 and not gate.is_set():
                    await gate.wait()
                yield chunk

        client.iter_download = gated
        tid = acc.transfers.add_download(cid, mid)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(served) >= 3:
                break
        acc.transfers.pause(tid)
        await asyncio.sleep(0.05)
        t = acc.db.get_transfer(tid)
        assert t["status"] == "paused"
        assert Path(t["path"]).parent == Path(fresh_settings.get("download_dir"))
        gate.set()
        acc.transfers.resume(tid)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if acc.db.get_transfer(tid)["status"] == "done":
                break
        t = acc.db.get_transfer(tid)
        assert t["status"] == "done", t
        assert Path(t["path"]).read_bytes() == payload
        assert not Path(t["path"] + ".part.map").exists()

        # Upload straight from a path on disk, into a folder, keeping the source file.
        folder = await acc.drive.create_folder("Uploads", None)
        src_dir = tmp_path / "Lecture notes"
        (src_dir / "week1").mkdir(parents=True)
        blob = bytes(range(256)) * 45_000
        (src_dir / "week1" / "backup.tar").write_bytes(blob)
        (src_dir / "readme.txt").write_text("hello")
        res = await acc.transfers.add_upload_paths([str(src_dir)], folder["id"])
        assert len(res["ids"]) == 2
        for _ in range(300):
            await asyncio.sleep(0.01)
            if all(acc.db.get_transfer(i)["status"] in ("done", "error") for i in res["ids"]):
                break
        ups = [acc.db.get_transfer(i) for i in res["ids"]]
        assert all(u["status"] == "done" for u in ups), ups
        assert (src_dir / "week1" / "backup.tar").exists()  # the original stays
        big = next(u for u in ups if u["name"] == "backup.tar")
        f = acc.db.get_file(big["chat_id"], big["msg_id"])
        assert f["size"] == len(blob)
        assert [p["name"] for p in acc.drive.path(f["folder_id"])] == ["Uploads", "Lecture notes", "week1"]

        # Download that folder tree as a zip.
        items = [(u["chat_id"], u["msg_id"]) for u in ups]
        b = acc.transfers.add_folder_download(folder["id"], items, as_zip=True, name="Uploads")
        for _ in range(300):
            await asyncio.sleep(0.02)
            zips = list(Path(fresh_settings.get("download_dir")).glob("Uploads*.zip"))
            if zips:
                break
        import zipfile
        with zipfile.ZipFile(zips[0]) as z:
            assert sorted(z.namelist()) == ["Lecture notes/readme.txt", "Lecture notes/week1/backup.tar"]
        assert b["batch"].startswith("zip:")
        acc.db.close()

    run(go())


# --------------------------------------------------------------------- api
def test_api(tmp_path):
    from starlette.testclient import TestClient

    from tgdrive import api, config

    acc, client = make_account(tmp_path)
    asyncio.run(index_all(acc))
    api.manager.accounts = {acc.uid: acc}
    c = TestClient(api.app, base_url="http://127.0.0.1:8765")
    H = {"X-TGDrive": "1"}
    st = c.get("/api/status").json()
    assert st["accounts"][0]["name"] == "Aarav Mehta" and st["api_configured"] is False
    r = c.get(f"/api/a/{acc.uid}/files", params={"q": "type:video in:physics", "sort": "size"}).json()
    assert len(r["items"]) == 10 and r["items"][0]["link"].startswith("https://t.me/c/102/")
    assert c.get(f"/api/a/{acc.uid}/files/stats", params={"q": "type:video in:physics"}).json()["total"] == 10
    assert c.get(f"/api/a/{acc.uid}/files", params={"q": "type:nope"}).status_code == 400
    f = c.post(f"/api/a/{acc.uid}/folders", json={"name": "Lectures"}, headers=H).json()
    items = [[x["chat_id"], x["msg_id"]] for x in r["items"][:3]]
    assert c.post(f"/api/a/{acc.uid}/files/place", json={"items": items, "folder_id": f["id"]}, headers=H).json()["ok"]
    inside = c.get(f"/api/a/{acc.uid}/files/stats", params={"folder_id": f["id"]}).json()
    assert inside["total"] == 3
    det = c.get(f"/api/a/{acc.uid}/files/{items[0][0]}/{items[0][1]}").json()
    assert det["folder_path"] == [{"id": f["id"], "name": "Lectures"}] and det["tg_link"].startswith("tg://")
    folders = c.get(f"/api/a/{acc.uid}/folders").json()
    assert folders["folders"][0]["file_count"] == 3
    chats = c.get(f"/api/a/{acc.uid}/chats").json()["chats"]
    assert {ch["kind"] for ch in chats} >= {"channel", "supergroup", "group", "user", "bot", "saved"}
    th = c.get(f"/api/a/{acc.uid}/thumb/{items[0][0]}/{items[0][1]}")
    assert th.status_code == 200 and th.headers["content-type"] == "image/jpeg"
    photos = c.get(f"/api/a/{acc.uid}/files", params={"q": "type:photo"}).json()["items"]
    photo = next(p for p in photos if p["inline"])
    assert c.get(f"/api/a/{acc.uid}/inline/{photo['chat_id']}/{photo['msg_id']}").content[:2] == b"\xff\xd8"
    # Streaming with ranges.
    payload = _big_payload(acc, client)
    s = c.get(f"/api/a/{acc.uid}/stream/{-CH - 101}/1/x.pdf", headers={"Range": "bytes=100-199"})
    assert s.status_code == 206 and s.content == payload[100:200]
    assert s.headers["content-range"] == f"bytes 100-199/{len(payload)}"
    whole = c.get(f"/api/a/{acc.uid}/stream/{-CH - 101}/1/x.pdf")
    assert whole.status_code == 200 and whole.content == payload
    # Resume playback: position, in-progress / watched filters, Continue watching count.
    vid = r["items"][0]
    pb = f"/api/a/{acc.uid}/playback/{vid['chat_id']}/{vid['msg_id']}"
    assert c.put(pb, json={"pos": 125.5, "dur": 3600}, headers=H).json() == {"pos": 125.5, "dur": 3600.0, "done": False}
    assert c.get(pb).json()["pos"] == 125.5
    inprog = c.get(f"/api/a/{acc.uid}/files", params={"q": "is:inprogress"}).json()["items"]
    assert [(x["chat_id"], x["msg_id"], x["play_pos"]) for x in inprog] == [(vid["chat_id"], vid["msg_id"], 125.5)]
    assert c.get(f"/api/a/{acc.uid}/folders").json()["continue"] == 1
    assert c.get(f"/api/a/{acc.uid}/files", params={"in_progress": 1, "sort": "played"}).json()["items"][0]["play_pos"]
    assert c.put(pb, json={"pos": 3590, "dur": 3600}, headers=H).json()["done"] is True   # near the end = watched
    w = c.get(f"/api/a/{acc.uid}/files", params={"q": "is:watched"}).json()["items"]
    assert len(w) == 1 and w[0]["watched"] and c.get(f"/api/a/{acc.uid}/folders").json()["continue"] == 0
    unw = c.get(f"/api/a/{acc.uid}/files/stats", params={"q": "type:video in:physics is:unwatched"}).json()["total"]
    assert unw == 9
    assert c.delete(pb, headers=H).json()["ok"] and not c.get(pb).json()["done"]
    # Settings, setup, suggestions, storage, duplicates, CSV.
    assert c.patch("/api/settings", json={"view": "list"}, headers=H).json()["settings"]["view"] == "list"
    assert c.patch("/api/settings", json={"view": "tiles"}, headers=H).status_code == 400
    assert c.post("/api/setup", json={"api_id": "12345", "api_hash": "0123456789abcdef0123456789abcdef"},
                  headers=H).json()["ok"]
    assert config.api_configured()
    assert "chats" in c.get(f"/api/a/{acc.uid}/suggest", params={"q": "phys"}).json()
    assert c.get(f"/api/a/{acc.uid}/storage").json()["total"]["n"] > 0
    assert "groups" in c.get(f"/api/a/{acc.uid}/duplicates").json()
    assert "groups" in c.get(f"/api/a/{acc.uid}/duplicates", params={"mode": "similar"}).json()
    csv_body = c.get(f"/api/a/{acc.uid}/export.csv", params={"q": "type:video"}).text
    assert csv_body.count("\n") == 11
    # Security: foreign Host, missing header, token.
    assert TestClient(api.app, base_url="http://evil.example").get("/api/status").status_code == 403
    assert c.post(f"/api/a/{acc.uid}/folders", json={"name": "X"}).status_code == 403
    config.ACCESS_TOKEN = "secret-token"
    try:
        assert c.get("/api/status").status_code == 401
        st = c.get("/api/status", headers={"X-TGDrive-Token": "secret-token"})
        assert st.status_code == 200 and st.json()["media_token"] == config.MEDIA_TOKEN
        # The stream-only token plays files and nothing else.
        c.cookies.clear()
        mt = {"t": config.MEDIA_TOKEN}
        sm = c.get(f"/api/a/{acc.uid}/stream/{-CH - 101}/1/x.pdf", params=mt, headers={"Range": "bytes=0-9"})
        assert sm.status_code == 206 and "set-cookie" not in sm.headers
        assert c.get("/api/status", params=mt).status_code == 401
        assert c.get(f"/api/a/{acc.uid}/files", params=mt).status_code == 401
        assert c.get(f"/api/a/{acc.uid}/thumb/{items[0][0]}/{items[0][1]}", params=mt).status_code == 401
        pl = c.get(f"/api/a/{acc.uid}/playlist.m3u", headers={"X-TGDrive-Token": "secret-token"}).text
        assert "secret-token" not in pl and (config.MEDIA_TOKEN in pl or "#EXTM3U" in pl)
        ix = c.get("/", headers={"X-TGDrive-Token": "secret-token"})
        assert "default-src 'self'" in ix.headers["content-security-policy"]
    finally:
        config.ACCESS_TOKEN = ""
    # Untrusted active content from Telegram is sandboxed when opened directly.
    from tgdrive.api import _is_active
    assert _is_active("text/html") and _is_active("image/svg+xml") and not _is_active("application/pdf")
    # App lock.
    assert c.post("/api/lock/set", json={"passcode": "4321"}, headers=H).json()["lock_set"]
    c.post("/api/lock/now", headers=H)
    assert c.get(f"/api/a/{acc.uid}/chats").status_code == 423
    assert c.post("/api/lock/unlock", json={"passcode": "0000"}, headers=H).status_code == 403
    assert c.post("/api/lock/unlock", json={"passcode": "4321"}, headers=H).json()["ok"]
    assert c.get(f"/api/a/{acc.uid}/chats").status_code == 200
    c.post("/api/lock/set", json={"passcode": "", "old": "4321"}, headers=H)


# ------------------------------------------------------------------- scale
def test_search_stays_fast_at_scale(tmp_path):
    """60k synthetic files: every kind of search answers well under a second."""
    from tests.bigdb import build
    db = build(tmp_path / "big.db", n=60_000, quiet=True)

    class Drive:
        def _descendants(self, fid):
            return set()

    class A:
        pass

    a = A()
    a.db, a.drive, a.semantic = db, Drive(), None
    from tgdrive.search import SearchEngine
    eng = SearchEngine(a)

    async def go():
        await db.read.run(eng.vocab.build, timeout=60)
        for q in ["", "polity", "test series", "testseries", "seires", "pyq", "संविधान", "notes ext:pdf size>5mb",
                  "vision type:document", "2024"]:
            t = time.perf_counter()
            res = await eng.files({"q": q, "sort": "relevance" if q else "date"})
            took = time.perf_counter() - t
            assert res["items"] or q in ("seires",), q
            assert took < 1.5, (q, took)
            t = time.perf_counter()
            await eng.stats({"q": q})
            assert time.perf_counter() - t < 1.5
    run(go())
    db.close()


def test_semantic_related_results(tmp_path):
    from tgdrive import semantic
    if not semantic.available():
        pytest.skip("embedding model not installed")
    acc, client = make_account(tmp_path)
    cid = -CH - 101
    for i, n in enumerate(["Environment and Ecology notes.pdf", "Indian Economy Ramesh Singh.pdf",
                           "Budget 2024 highlights GDP inflation.pdf", "Cricket world cup photos.zip"]):
        client.chats[cid].append(doc_msg(cid, 2000 + i, n, "application/pdf", 10, NOW))
    asyncio.run(index_all(acc))
    acc.semantic.enabled = True
    model = semantic._Model.get()
    while acc.semantic._step(sqlite3.connect(acc.db.path), model):
        pass
    from tgdrive.settings import settings
    settings.data["search_semantic"] = True
    res = asyncio.run(acc.search.files({"q": "climate change", "sort": "relevance"}))
    related = [r["name"] for r in res["items"] if r["match"] == "related"]
    assert "Environment and Ecology notes.pdf" in related
    assert "Cricket world cup photos.zip" not in related
    acc.db.close()
