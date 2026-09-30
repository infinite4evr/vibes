"""Tests for the 2.1 features: folder sync, drive access (WebDAV), folder rules, subjects,
diagnostics, settings export/import and desktop integration."""
import asyncio
import json
import os
import time
import zipfile

import pytest

from tests.fake import CH, make_account
from tests.test_core import index_all, run, search


H = {"X-TGDrive": "1"}


async def wait_transfers(acc, ids, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        rows = [acc.db.get_transfer(i) for i in ids]
        if all(r and r["status"] in ("done", "error", "cancelled") for r in rows):
            return rows
        await asyncio.sleep(0.02)
    raise AssertionError([acc.db.get_transfer(i) for i in ids])


async def sync_until_settled(acc, pid, rounds=6):
    """Run the pair, wait for the transfers it started, run again to record them."""
    res = None
    for _ in range(rounds):
        res = await acc.sync.run_pair(pid)
        tids = [r["tid"] for r in acc.db.q("SELECT tid FROM sync_files WHERE pair_id=? AND tid IS NOT NULL", (pid,))]
        if not tids:
            return res
        await wait_transfers(acc, tids)
    return res


def folder_files(acc, fid):
    return {r["name"]: r for r in acc.db.q("SELECT f.* FROM files f JOIN placements p ON p.chat_id=f.chat_id "
                                           "AND p.msg_id=f.msg_id WHERE p.folder_id=?", (fid,))}


# -------------------------------------------------------------------- sync
def test_sync_two_way(tmp_path, fresh_settings, monkeypatch):
    from tgdrive import sync as sync_mod
    monkeypatch.setattr(sync_mod, "QUIET_SECONDS", 0)   # files here are "old enough" at once

    async def go():
        acc, client = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        folder = await acc.drive.create_folder("Notes", None)
        local = tmp_path / "Notes"
        (local / "sub").mkdir(parents=True)
        (local / "a.txt").write_text("alpha")
        (local / "sub" / "b.txt").write_text("bravo" * 100)
        (local / ".hidden").write_text("skip me")
        (local / "partial.part").write_text("skip me too")

        pair = await acc.sync.add_pair(str(local), folder["id"])
        assert pair["approved"] == 0 and pair["state"] == "needs approval"
        assert pair["stats"]["upload"] == 2 and pair["stats"]["mkdir_remote"] == 1
        # Nothing happens before approval, even when asked to run.
        await acc.sync.run_pair(pair["id"])
        assert not folder_files(acc, folder["id"])

        # Bad pairs are refused.
        from tgdrive.sync import SyncError
        with pytest.raises(SyncError):
            await acc.sync.add_pair(str(local / "sub"), folder["id"])  # overlaps
        with pytest.raises(SyncError):
            await acc.sync.add_pair("relative/path", folder["id"])
        with pytest.raises(SyncError):
            await acc.sync.add_pair(str(tmp_path / "missing"), folder["id"])

        acc.sync.approve(pair["id"])
        await sync_until_settled(acc, pair["id"])
        top = folder_files(acc, folder["id"])
        assert set(top) == {"a.txt"}
        sub = acc.db.one("SELECT id FROM folders WHERE parent_id=? AND name='sub'", (folder["id"],))
        assert set(folder_files(acc, sub["id"])) == {"b.txt"}
        p = acc.sync.pairs()[0]
        assert p["state"] == "up to date" and p["files"] == 2 and p["pending"] == 0

        # A second run with no changes does nothing.
        res = await acc.sync.run_pair(pair["id"])
        assert res["upload"] == res["download"] == 0 and res["same"] == 0

        # A file added in TG Drive downloads; a local edit uploads and replaces the old version.
        small = [x for x in await search(acc, "", sort="size", order="asc") if 0 < (x["size"] or 0) < 300_000 and x["name"] not in ("a.txt", "b.txt")]
        f, other = small[0], small[1]
        await acc.drive.place([(f["chat_id"], f["msg_id"])], folder["id"])
        time.sleep(0.01)
        (local / "a.txt").write_text("alpha, edited")
        os.utime(local / "a.txt", (time.time() + 10, time.time() + 10))
        await sync_until_settled(acc, pair["id"])
        assert (local / f["name"]).exists()
        top = folder_files(acc, folder["id"])
        assert set(top) == {"a.txt", f["name"]}
        assert top["a.txt"]["size"] == len("alpha, edited")

        # Removed in TG Drive -> moved to the sync trash here (never deleted).
        await acc.drive.place([(f["chat_id"], f["msg_id"])], None)
        await sync_until_settled(acc, pair["id"])
        assert not (local / f["name"]).exists()
        assert (local / ".tgdrive-trash" / f["name"]).exists()

        # Deleted here -> taken out of the TG Drive folder (the message stays in Telegram).
        (local / "sub" / "b.txt").unlink()
        await sync_until_settled(acc, pair["id"])
        assert not folder_files(acc, sub["id"])

        # Changed on both sides -> both kept.
        top = folder_files(acc, folder["id"])
        await acc.drive.place([(top["a.txt"]["chat_id"], top["a.txt"]["msg_id"])], None)
        await acc.drive.place([(other["chat_id"], other["msg_id"])], folder["id"])
        await acc.drive.rename_file(other["chat_id"], other["msg_id"], "a.txt") \
            if hasattr(acc.drive, "rename_file") else None
        acc.db.x("UPDATE files SET alias='a.txt' WHERE chat_id=? AND msg_id=?", (other["chat_id"], other["msg_id"]))
        (local / "a.txt").write_text("local change")
        os.utime(local / "a.txt", (time.time() + 20, time.time() + 20))
        await sync_until_settled(acc, pair["id"])
        names = sorted(x.name for x in local.iterdir())
        assert "a.txt" in names and any("conflicted copy" in n for n in names), names

        # Mass removal guard: deleting everything locally stops and asks again.
        for i in range(30):
            (local / f"n{i}.txt").write_text(str(i))
        await sync_until_settled(acc, pair["id"])
        for x in local.glob("n*.txt"):
            x.unlink()
        res = await acc.sync.run_pair(pair["id"])
        p = acc.sync.pairs()[0]
        assert p["approved"] == 0 and "remove" in (p["error"] or ""), p
        assert len([n for n in folder_files(acc, folder["id"]) if n.startswith("n")]) == 30

        # A missing local folder stops the pair without touching anything.
        acc.sync.approve(pair["id"])
        local.rename(tmp_path / "Moved")
        res = await acc.sync.run_pair(pair["id"])
        assert "error" in res and acc.sync.pairs()[0]["state"] == "stopped"
        acc.sync.remove(pair["id"])
        assert acc.sync.pairs() == []
        acc.db.close()

    run(go())


# -------------------------------------------------------------------- dav
def _dav_client(acc):
    from starlette.testclient import TestClient
    from tgdrive import api, dav
    from tgdrive.settings import settings
    api.manager.accounts = {acc.uid: acc}
    dav.invalidate_all()
    settings.update({"dav_enabled": True})
    c = TestClient(api.app, base_url="http://127.0.0.1:8765")
    return c, f"/dav/{dav.dav_secret()}"


@pytest.fixture
def portal():
    """One event loop for all requests of a test (like the real server), so work the app starts in the
    background (uploads) keeps running between requests."""
    from anyio.from_thread import start_blocking_portal
    with start_blocking_portal() as p:
        yield p


def test_webdav(tmp_path, fresh_settings, portal):
    acc, client = make_account(tmp_path)
    run(index_all(acc))
    c, base = _dav_client(acc)
    c.portal = portal
    assert c.request("PROPFIND", "/dav/wrong-secret/", headers={"Depth": "1"}).status_code == 404
    r = c.request("PROPFIND", base + "/", headers={"Depth": "1"})
    assert r.status_code == 207
    for name in ("My Drive", "Starred", "Chats", "Saved searches", "Subjects"):
        assert f"<D:displayname>{name}</D:displayname>" in r.text
    assert "<D:displayname>TG Drive</D:displayname>" in r.text
    assert "1970" not in r.text
    chats = c.request("PROPFIND", base + "/Chats/", headers={"Depth": "1"})
    assert chats.status_code == 207 and chats.text.count("<D:response>") > 3

    # Make a folder, upload into it, read it back with a range, rename, delete.
    assert c.request("MKCOL", base + "/My%20Drive/Docs").status_code == 201
    assert acc.db.one("SELECT id FROM folders WHERE name='Docs'")
    body = b"hello webdav " * 1000
    assert c.put(base + "/My%20Drive/Docs/hello.txt", content=body).status_code in (201, 204)

    async def settle():
        end = time.time() + 5
        while time.time() < end:
            if acc.db.one("SELECT 1 FROM files WHERE name='hello.txt'"):
                return
            await asyncio.sleep(0.05)
    # The upload runs on the app's loop in TestClient's portal; poll through requests.
    for _ in range(100):
        r = c.request("PROPFIND", base + "/My%20Drive/Docs/", headers={"Depth": "1"})
        if "hello.txt" in r.text and acc.db.one("SELECT 1 FROM files WHERE name='hello.txt'"):
            break
        time.sleep(0.05)
    assert acc.db.one("SELECT 1 FROM files WHERE name='hello.txt'"), acc.db.q("SELECT status, error FROM transfers")
    from tgdrive import dav
    dav.invalidate_all()
    g = c.get(base + "/My%20Drive/Docs/hello.txt", headers={"Range": "bytes=0-4"})
    assert g.status_code == 206 and g.content == b"hello"
    mv = c.request("MOVE", base + "/My%20Drive/Docs/hello.txt",
                   headers={"Destination": "http://127.0.0.1:8765" + base + "/My%20Drive/Docs/renamed.txt"})
    assert mv.status_code in (201, 204)
    dav.invalidate_all()
    listing = c.request("PROPFIND", base + "/My%20Drive/Docs/", headers={"Depth": "1"}).text
    assert "renamed.txt" in listing and "hello.txt" not in listing
    assert c.request("DELETE", base + "/My%20Drive/Docs/renamed.txt").status_code == 204
    dav.invalidate_all()
    assert "renamed.txt" not in c.request("PROPFIND", base + "/My%20Drive/Docs/", headers={"Depth": "1"}).text
    # Read-only areas refuse writes.
    assert c.put(base + "/Chats/x.txt", content=b"x").status_code in (403, 405, 409)
    # Turned off -> refused.
    from tgdrive.settings import settings
    settings.update({"dav_enabled": False})
    assert c.request("PROPFIND", base + "/", headers={"Depth": "0"}).status_code == 403
    acc.db.close()


# ----------------------------------------------------------- folder rules
def test_smart_and_auto_folders(tmp_path, fresh_settings):
    async def go():
        acc, _ = make_account(tmp_path)
        await index_all(acc)
        from tgdrive.drive import DriveError
        with pytest.raises(DriveError):
            await acc.drive.create_folder("Bad", None, rules={"q": "type:nope", "mode": "smart"})
        smart = await acc.drive.create_folder("Videos", None, emoji="🎬", rules={"q": "type:video", "mode": "smart"})
        assert smart["kind"] == "smart" and smart["emoji"] == "🎬"
        videos = await search(acc, "type:video")
        from tgdrive.autofile import folder_rules, rule_params
        inside = await search(acc, **rule_params(folder_rules(acc.db.get_folder(smart["id"]))))
        assert len(inside) == len(videos) > 0
        # Smart folders never move anything.
        assert not acc.db.q("SELECT 1 FROM placements WHERE folder_id=?", (smart["id"],))
        # …and files can't be put into one (it would hide them): moving, copying and uploading say why.
        one = videos[0]
        with pytest.raises(DriveError, match="smart folder"):
            await acc.drive.place([(one["chat_id"], one["msg_id"])], smart["id"])
        with pytest.raises(DriveError, match="smart folder"):
            await acc.drive.copy_to_drive(one["chat_id"], one["msg_id"], smart["id"])
        with pytest.raises(DriveError, match="smart folder"):
            acc.drive.require_files_folder(smart["id"])
        assert not acc.drive.accepts_files(smart["id"]) and acc.drive.accepts_files(None) is False
        from tgdrive.sync import SyncError
        (tmp_path / "local").mkdir()
        with pytest.raises(SyncError, match="smart folder"):
            await acc.sync.add_pair(str(tmp_path / "local"), smart["id"])
        assert not acc.db.q("SELECT 1 FROM placements WHERE folder_id=?", (smart["id"],))

        # Auto-filing moves unfiled matches, leaves hand-filed files alone.
        manual = await acc.drive.create_folder("Mine", None)
        keep = videos[0]
        await acc.drive.place([(keep["chat_id"], keep["msg_id"])], manual["id"])
        auto = await acc.drive.create_folder("Auto videos", None, rules={"q": "type:video", "mode": "auto"})
        n = await acc.autofile.run_folder(acc.db.get_folder(auto["id"]))
        assert n == len(videos) - 1
        f = acc.db.get_file(keep["chat_id"], keep["msg_id"])
        assert f["folder_id"] == manual["id"]
        assert await acc.autofile.run_folder(acc.db.get_folder(auto["id"])) == 0

        # Emoji and rules survive the manifest round trip; clearing rules makes a plain folder.
        snap = acc.drive.snapshot()
        row = next(x for x in snap["folders"] if x["id"] == auto["id"])
        assert json.loads(row["rules"])["mode"] == "auto" if isinstance(row["rules"], str) else row["rules"]["mode"]
        await acc.drive.update_folder(auto["id"], rules=None, emoji="📦")
        g = acc.db.get_folder(auto["id"])
        assert g["kind"] in (None, "", "plain") and g["emoji"] == "📦"
        acc.db.close()

    run(go())


# --------------------------------------------------------------- subjects
def test_subjects_classify_and_query(tmp_path):
    from tgdrive.subjects import build_subjects, classify
    subs = build_subjects()
    assert classify(subs, "Laxmikanth Indian Polity 7th edition.pdf")[0] == "polity"
    assert classify(subs, "Economic Survey 2025 summary.pdf")[0] == "economy"
    assert classify(subs, "भारतीय संविधान नोट्स.pdf")[0] == "polity"
    assert classify(subs, "IMG_2031.jpg")[0] is None
    custom = build_subjects("Chess: openings, endgame, sicilian", builtin=False)
    assert [s.name for s in custom] == ["Chess"]
    assert classify(custom, "Sicilian defence openings.pdf")[0] == custom[0].id

    async def go():
        acc, _ = make_account(tmp_path)
        await index_all(acc)
        rows = acc.db.q("SELECT id FROM files ORDER BY id LIMIT 3")
        acc.db.x("INSERT INTO file_subjects(file_id, subject, score, src) VALUES(?,?,?,?)",
                 (rows[0]["id"], "polity", 5, "kw"))
        acc.db.x("INSERT INTO file_subjects(file_id, subject, score, src) VALUES(?,?,?,?)",
                 (rows[1]["id"], "economy", 5, "kw"))
        assert len(await search(acc, "subject:polity")) == 1
        assert len(await search(acc, "subject:polity,economy")) == 2
        total = len(await search(acc, ""))
        assert len(await search(acc, "-subject:polity")) == total - 1
        acc.db.close()

    run(go())


# -------------------------------------------------- diagnostics & settings
def test_diagnostics_and_settings_io(tmp_path, fresh_settings):
    from tgdrive import diagnostics
    fresh_settings.update({"api_hash": "0123456789abcdef0123456789abcdef", "dav_enabled": True})
    secret = diagnostics.redact("hash 0123456789abcdef0123456789abcdef mail a.b@example.com "
                                "call +91 98765 43210 url /dav/abcdefghijklmnop/x Physics Notes.pdf",
                                ["Physics Notes.pdf"], include_names=False)
    assert "0123456789abcdef" not in secret and "example.com" not in secret
    assert "98765" not in secret and "abcdefghijklmnop" not in secret and "Physics Notes" not in secret

    acc, _ = make_account(tmp_path)
    run(index_all(acc))
    real_name = acc.db.one("SELECT name FROM files WHERE name LIKE '% %' ORDER BY length(name) DESC")["name"]
    try:
        raise ValueError(f"boom in {real_name}")
    except ValueError as exc:
        rid = diagnostics.record_exception("test", exc, {"where": "unit test"})
    assert rid
    lst = diagnostics.list_crashes()
    assert lst["unseen"] >= 1 and any(c["id"] == rid for c in lst["reports"])
    assert "ValueError" in diagnostics.read_crash(rid)
    diagnostics.mark_seen()
    assert diagnostics.list_crashes()["unseen"] == 0

    path = diagnostics.build_bundle([acc], include_names=False, dest_dir=tmp_path)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert "system.json" in names and any(n.startswith("crashes/") for n in names)
        blob = b"".join(z.read(n) for n in names)
    assert b"0123456789abcdef0123456789abcdef" not in blob
    assert real_name.encode() not in blob
    assert diagnostics.clear_crashes() >= 1

    # Settings export leaves out secrets; import validates and skips what it can't use.
    fresh_settings.update({"accent": "#e0457b", "font_scale": 1.1})
    doc = diagnostics.export_settings()
    assert doc["settings"]["accent"] == "#e0457b" and "api_hash" not in doc["settings"]
    assert "dav_secret" not in doc["settings"]
    fresh_settings.update({"accent": "", "font_scale": 1.0})
    doc["settings"]["lock_hash"] = "x"
    doc["settings"]["not_a_setting"] = 1
    doc["settings"]["font_scale"] = 1.15
    res = diagnostics.import_settings(doc)
    assert fresh_settings.get("accent") == "#e0457b" and fresh_settings.get("font_scale") == 1.15
    assert "lock_hash" in res["skipped"] and "not_a_setting" in res["skipped"]
    with pytest.raises(ValueError):
        diagnostics.import_settings({"app": "something else"})
    acc.db.close()


def test_crash_and_settings_api(tmp_path, fresh_settings):
    from starlette.testclient import TestClient
    from tgdrive import api
    acc, _ = make_account(tmp_path)
    run(index_all(acc))
    api.manager.accounts = {acc.uid: acc}
    c = TestClient(api.app, base_url="http://127.0.0.1:8765")
    r = c.post("/api/crash", json={"kind": "js", "message": "TypeError: x is undefined", "stack": "at files.js:10"},
               headers=H)
    assert r.status_code == 200
    assert c.get("/api/crashes").json()["reports"]
    ex = c.get("/api/settings/export")
    assert ex.status_code == 200 and ex.json()["app"] == "tgdrive-settings"
    assert c.post("/api/settings/import", json={"app": "nope"}, headers=H).status_code == 400
    assert c.post("/api/settings/import", json=ex.json(), headers=H).status_code == 200
    d = c.post("/api/diagnostics", json={"include_names": False}, headers=H)
    assert d.status_code == 200
    # The chat around a file.
    ctx = c.get(f"/api/a/{acc.uid}/context/{-CH - 101}/5", params={"before": 2, "after": 2})
    assert ctx.status_code == 200, ctx.text
    msgs = ctx.json()["messages"]
    ids = [m["id"] for m in msgs]
    assert ids == sorted(ids) and 5 in ids and len(ids) <= 5
    assert next(m for m in msgs if m["id"] == 5)["target"]
    # Removed features stay removed: no places or PDF marks routes.
    assert c.get(f"/api/a/{acc.uid}/places", headers=H).status_code == 404
    assert c.get(f"/api/a/{acc.uid}/marks/{-CH - 101}/1", headers=H).status_code == 404
    acc.db.close()


# ----------------------------------------------------------- integration
def test_desktop_integration(tmp_path, monkeypatch):
    from tgdrive import integration
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    launcher = tmp_path / "tg drive" / "tgdrive"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n")
    monkeypatch.setenv("TGDRIVE_LAUNCHER", str(launcher))
    monkeypatch.setattr(integration, "_refresh_caches", lambda: None)
    entry = integration.install_menu()
    text = entry.read_text()
    assert f'Exec="{launcher}" %U' in text and "Icon=" in text
    assert integration.menu_installed()
    integration.set_autostart(True)
    assert (tmp_path / "config" / "autostart").exists() and any((tmp_path / "config" / "autostart").iterdir())
    integration.set_autostart(False)
    installed = integration.install_file_manager_actions(only_present=False)
    assert installed
    for p in (tmp_path / "share").rglob("*"):
        if p.is_file() and p.suffix in (".desktop", ".nemo_action"):
            assert "--send" in p.read_text() or "Send to TG Drive" in p.read_text() or p == entry
    integration.uninstall_file_manager_actions()
    integration.uninstall_menu()
    assert not integration.menu_installed()


# ------------------------------------------------------------ 2.2: debug logging, meaning search
def test_debug_logging_switch(tmp_path, fresh_settings, monkeypatch):
    import logging
    from starlette.testclient import TestClient
    from tgdrive import api, config, maintenance
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    maintenance.setup_logging()
    acc, _ = make_account(tmp_path)
    run(index_all(acc))
    api.manager.accounts = {acc.uid: acc}
    c = TestClient(api.app, base_url="http://127.0.0.1:8765")
    try:
        assert not maintenance.debug_enabled()
        # Off: page logs are ignored and nothing detailed is written.
        assert c.post("/api/clientlog", json={"entries": [{"msg": "ignored"}]}, headers=H).json()["on"] is False
        # On, straight from the settings (no restart).
        assert c.patch("/api/settings", json={"debug_logging": True}, headers=H).status_code == 200
        assert maintenance.debug_enabled() and logging.getLogger().level == logging.DEBUG
        c.get(f"/api/a/{acc.uid}/files", params={"q": "polity"})
        r = c.post("/api/clientlog", headers=H, json={"entries": [
            {"t": time.time(), "level": "info", "cat": "nav", "msg": "→ #drive"},
            {"t": time.time(), "level": "error", "cat": "error", "msg": "TypeError: boom", "data": {"stack": "at x.js:1"}}]})
        assert r.json()["on"] is True
        for h in logging.getLogger().handlers:
            h.flush()
        text = (tmp_path / "logs" / "tgdrive-debug.log").read_text()
        assert "debug logging ON" in text
        assert "HTTP GET /api/a/" in text and "/files?q=polity" in text      # every request, with its timing
        assert "files q=['polity']" in text                                  # what the search did
        assert "[nav] → #drive" in text and "TypeError: boom" in text        # what the page did
        tail = c.get("/api/debuglog", params={"lines": 50}).json()
        assert tail["on"] and "TypeError: boom" in tail["text"]
        assert c.get("/api/logs/download", params={"which": "debug"}).status_code == 200
        # Clearing empties both logs.
        assert c.delete("/api/logs", headers=H).json()["freed"] > 0
        assert "TypeError" not in (tmp_path / "logs" / "tgdrive-debug.log").read_text()
        # Off again.
        c.patch("/api/settings", json={"debug_logging": False}, headers=H)
        assert not maintenance.debug_enabled() and logging.getLogger().level == logging.INFO
        assert c.post("/api/clientlog", json={"entries": [{"msg": "late"}]}, headers=H).json()["on"] is False
    finally:
        maintenance.set_debug_logging(False)
        acc.db.close()


def test_embed_parts_drop_noise():
    from tgdrive import textproc
    assert textproc.embed_parts("IMG_20240101_123456.jpg", "")[0] == ""
    assert textproc.embed_parts("PolityNotes_Chapter3.pdf", "")[0] == "Polity Notes Chapter 3"
    name, cap = textproc.embed_parts("x.pdf", "Join @upsc_hub https://t.me/upsc_hub for Budget analysis")
    assert "upsc_hub" not in cap and "Budget analysis" in cap


def test_semantic_v2_library_statistics(tmp_path, fresh_settings):
    import sqlite3
    from tgdrive import semantic
    if not semantic.available():
        pytest.skip("embedding model not installed")
    db = tmp_path / "i.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE files(id INTEGER PRIMARY KEY, name TEXT, alias TEXT, caption TEXT)")
    spam = "Join @freenotes for daily updates, share with friends #upsc"
    rows = [(f"Economy Mock Test {i}.pdf", spam) for i in range(300)]
    rows += [("Global warming and Paris agreement.pdf", spam), ("Carbon emissions and greenhouse gases.pdf", spam),
             ("Cricket world cup final highlights.mp4", spam), ("Honda City insurance renewal.pdf", "")]
    con.executemany("INSERT INTO files(name, alias, caption) VALUES (?, NULL, ?)", rows)
    con.commit()
    idx = semantic.SemanticIndex(tmp_path / "sem", db)
    model = semantic._Model.get()
    while idx._step(sqlite3.connect(db), model):
        pass
    assert idx.meta["version"] == semantic.VERSION and idx.meta["stats_n"] == len(rows)
    names = {i + 1: r[0] for i, r in enumerate(rows)}
    # Boilerplate every file shares doesn't make everything "related"; the topic does.
    hits = [names[i] for i, _ in idx.search("climate change")]
    assert hits[:2] and set(hits[:2]) == {"Global warming and Paris agreement.pdf", "Carbon emissions and greenhouse gases.pdf"}
    assert "Cricket world cup final highlights.mp4" not in hits[:3]
    # Other phrasings (synonyms, corrected spelling) steer the query too.
    assert idx.search("vehicle", extra=["car insurance"])[0][0] == len(rows)
    # An old-format index starts over.
    idx.meta["version"] = 1
    idx._save_meta()
    again = semantic.SemanticIndex(tmp_path / "sem", db)
    assert again.meta["built_until"] == 0 and again.meta["version"] == semantic.VERSION


def test_semantic_query_gets_synonyms(tmp_path, fresh_settings):
    pytest.importorskip("numpy")   # meaning search needs numpy; without it the plan has no meaning part
    fresh_settings.data.update(search_semantic=True, search_mode="smart")
    acc, _ = make_account(tmp_path)
    run(index_all(acc))

    class Sem:
        enabled = True
    acc.semantic = Sem()
    plan = acc.search.plan({"terms": ["pyq", "polity"], "phrases": [], "neg_terms": []})
    assert plan.semantic == "pyq polity"
    assert any("previous year" in x for x in plan.semantic_extra), plan.semantic_extra
    acc.db.close()


def test_hide_duplicates(tmp_path, fresh_settings):
    """Forwarded copies (same Telegram file) and re-uploads (same name and size) fold into one card."""
    import sqlite3
    from datetime import datetime, timezone
    from telethon.tl import types as tt
    from tests.fake import doc_msg, peer_of

    def fwd(cid, mid, doc_id, name, size, when):
        doc = tt.Document(id=doc_id, access_hash=1, file_reference=b"r", date=when, mime_type="application/pdf",
                          size=size, dc_id=2, attributes=[tt.DocumentAttributeFilename(name)])
        return tt.Message(id=mid, peer_id=peer_of(cid), date=when, message="",
                          media=tt.MessageMediaDocument(document=doc))

    acc, client = make_account(tmp_path)
    a, b, g = -CH - 101, -CH - 102, -55
    t1, t2, t3 = (datetime(2026, 1, d, tzinfo=timezone.utc) for d in (1, 2, 3))
    client.chats[a] += [fwd(a, 9001, 777001, "Polity Laxmikanth.pdf", 5_000_000, t1),
                        fwd(a, 9002, 777001, "Polity Laxmikanth.pdf", 5_000_000, t2)]   # twice in one chat
    client.chats[b].append(fwd(b, 9003, 777001, "Polity Laxmikanth.pdf", 5_000_000, t3))    # forwarded elsewhere
    client.chats[g].append(doc_msg(g, 9004, "Budget notes.pdf", "application/pdf", 2_000_000, t1))
    client.chats[b].append(doc_msg(b, 9005, "Budget notes.pdf", "application/pdf", 2_000_000, t2))  # re-upload
    run(index_all(acc))
    conn = sqlite3.connect(acc.db.path, isolation_level=None)
    st = acc.dupes.rebuild(conn)
    assert st["groups"] >= 2 and st["extra"] >= 3

    def names(**p):
        return [f["name"] for f in run(acc.search.files(dict(p, limit=500)))["items"]]

    every, one = names(copies="show"), names(copies="hide")
    assert every.count("Polity Laxmikanth.pdf") == 3 and one.count("Polity Laxmikanth.pdf") == 1
    assert every.count("Budget notes.pdf") == 2 and one.count("Budget notes.pdf") == 1
    # The oldest copy is the one shown; its card knows how many copies there are.
    shown = [f for f in run(acc.search.files({"copies": "hide", "limit": 500}))["items"] if f["name"] == "Polity Laxmikanth.pdf"]
    assert shown[0]["msg_id"] == 9001 and shown[0]["copies"] == 3
    # A chat still shows its own copy; repeats inside that chat fold.
    assert names(copies="hide", chat_ids=str(b)).count("Polity Laxmikanth.pdf") == 1
    assert names(copies="hide", chat_ids=str(a)).count("Polity Laxmikanth.pdf") == 1
    assert names(copies="hide", chat_ids=str(b)).count("Budget notes.pdf") == 1
    # Counts agree with the list, in every view.
    for p in ({}, {"chat_ids": str(a)}, {"chat_ids": str(b)}, {"kinds": "document"}, {"q": "polity"}):
        items = run(acc.search.files({**p, "copies": "hide", "limit": 500}))["items"]
        assert run(acc.search.stats({**p, "copies": "hide"}))["total"] == len(items), p
    # Search: one card, and a copies:show word in the query wins over the switch.
    assert names(q="laxmikanth", copies="hide").count("Polity Laxmikanth.pdf") == 1
    assert names(q="laxmikanth copies:show", copies="hide").count("Polity Laxmikanth.pdf") == 3
    # Starring a copy makes it the one shown.
    run(acc.drive.set_meta_items([(b, 9003)], starred=True))
    acc.dupes.rebuild(conn)
    shown = [f for f in run(acc.search.files({"copies": "hide", "limit": 500}))["items"] if f["name"] == "Polity Laxmikanth.pdf"]
    assert [(f["chat_id"], f["msg_id"]) for f in shown] == [(b, 9003)]
    # Deleting copies updates the groups.
    acc.db.delete_files(b, [9005])
    acc.dupes.rebuild(conn)
    assert names(copies="hide").count("Budget notes.pdf") == 1
    assert acc.db.one("SELECT COUNT(*) AS n FROM dups d JOIN files f ON f.id=d.file_id WHERE f.name='Budget notes.pdf'")["n"] == 0
    # The details list every copy, best first.
    from starlette.testclient import TestClient
    from tgdrive import api
    api.manager.accounts = {acc.uid: acc}
    det = TestClient(api.app, base_url="http://127.0.0.1:8765").get(f"/api/a/{acc.uid}/files/{a}/9002").json()
    assert [c["msg_id"] for c in det["copy_list"]][0] == 9003 and det["duplicates"] == 2
    conn.close()
    acc.db.close()
