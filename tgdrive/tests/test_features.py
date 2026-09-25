"""Tests for the 2.1 features: folder sync, drive access (WebDAV), folder rules, subjects, PDF marks,
photo places, diagnostics, settings export/import and desktop integration."""
import asyncio
import io
import json
import os
import struct
import time
import zipfile
from pathlib import Path

import pytest

from tests.fake import CH, make_account
from tests.test_core import index_all, run, search
from tgdrive.drive import merge_manifests

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
def test_sync_two_way(tmp_path, fresh_settings):
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
    from fastapi.testclient import TestClient
    from tgdrive import api, dav
    from tgdrive.settings import settings
    api.manager.accounts = {acc.uid: acc}
    dav.invalidate_all()
    settings.update({"dav_enabled": True})
    c = TestClient(api.app, base_url="http://127.0.0.1:8765")
    return c, f"/dav/{dav.dav_secret()}"


def test_webdav(tmp_path, fresh_settings):
    acc, client = make_account(tmp_path)
    run(index_all(acc))
    c, base = _dav_client(acc)
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
    assert acc.db.one("SELECT 1 FROM files WHERE name='hello.txt'"), r.text
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


# ------------------------------------------------------------------ marks
def test_pdf_marks_and_manifest_merge(tmp_path):
    async def go():
        acc, _ = make_account(tmp_path)
        await index_all(acc)
        await acc.drive.load()
        cid, mid = -CH - 101, 1
        m = await acc.drive.save_mark(cid, mid, {"kind": "highlight", "page": 3, "color": "yellow",
                                                 "data": {"rects": [[0.1, 0.2, 0.3, 0.02]], "text": "Article 21"}})
        b = await acc.drive.save_mark(cid, mid, {"kind": "bookmark", "page": 7, "note": "Chapter 2"})
        marks = acc.drive.marks_for(cid, mid)
        assert [x["page"] for x in marks] == [3, 7]
        from tgdrive.drive import DriveError
        with pytest.raises(DriveError):
            await acc.drive.save_mark(cid, mid, {"kind": "scribble"})
        snap = acc.drive.snapshot()
        assert {x["id"] for x in snap["marks"]} == {m["id"], b["id"]}

        # Deleting on one computer wins over an older copy on another.
        await acc.drive.delete_mark(b["id"])
        mine = acc.drive.snapshot()
        merged = merge_manifests(mine, snap)
        assert [x["id"] for x in merged["marks"]] == [m["id"]]
        # A newer edit elsewhere wins.
        other = json.loads(json.dumps(mine))
        other["marks"][0]["note"] = "edited elsewhere"
        other["marks"][0]["mtime"] += 1000
        merged = merge_manifests(mine, other)
        assert merged["marks"][0]["note"] == "edited elsewhere"
        acc.drive.apply(merged)
        assert acc.drive.marks_for(cid, mid)[0]["note"] == "edited elsewhere"
        acc.db.close()

    run(go())


# ----------------------------------------------------------------- places
def _jpeg_with_gps(lat, lon):
    """A minimal big-endian EXIF block with GPS lat/lon and DateTimeOriginal."""
    def rat(v):
        d = int(v)
        m = int((v - d) * 60)
        s = round(((v - d) * 60 - m) * 60 * 100)
        return struct.pack(">IIIIII", d, 1, m, 1, s, 100)
    entries_ifd0 = 2
    ifd0_off = 8
    ifd0_size = 2 + entries_ifd0 * 12 + 4
    exif_off = ifd0_off + ifd0_size
    exif_size = 2 + 1 * 12 + 4
    date_off = exif_off + exif_size
    date = b"2024:03:05 10:20:30\x00"
    gps_off = date_off + len(date)
    gps_entries = 4
    gps_size = 2 + gps_entries * 12 + 4
    lat_off = gps_off + gps_size
    lon_off = lat_off + 24
    t = b"MM\x00*" + struct.pack(">I", ifd0_off)
    t += struct.pack(">H", entries_ifd0)
    t += struct.pack(">HHII", 0x8769, 4, 1, exif_off)
    t += struct.pack(">HHII", 0x8825, 4, 1, gps_off)
    t += struct.pack(">I", 0)
    t += struct.pack(">H", 1) + struct.pack(">HHII", 0x9003, 2, len(date), date_off) + struct.pack(">I", 0)
    t += date
    t += struct.pack(">H", gps_entries)
    t += struct.pack(">HHI", 1, 2, 2) + (b"N" if lat >= 0 else b"S") + b"\x00\x00\x00"
    t += struct.pack(">HHII", 2, 5, 3, lat_off)
    t += struct.pack(">HHI", 3, 2, 2) + (b"E" if lon >= 0 else b"W") + b"\x00\x00\x00"
    t += struct.pack(">HHII", 4, 5, 3, lon_off)
    t += struct.pack(">I", 0)
    t += rat(abs(lat)) + rat(abs(lon))
    app1 = b"Exif\x00\x00" + t
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


def test_exif_gps():
    from tgdrive.places import parse_exif
    r = parse_exif(_jpeg_with_gps(28.6139, 77.209))
    assert abs(r["lat"] - 28.6139) < 0.001 and abs(r["lon"] - 77.209) < 0.001
    r = parse_exif(_jpeg_with_gps(-33.8688, -151.2093))
    assert r["lat"] < 0 and r["lon"] < 0
    assert parse_exif(b"\xff\xd8no exif here") == {}
    assert parse_exif(b"Exif\x00\x00MM\x00*\xff\xff\xff\xff") == {}  # broken offsets don't crash


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
    from fastapi.testclient import TestClient
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
    # Marks through the API.
    mk = c.post(f"/api/a/{acc.uid}/marks/{-CH - 101}/1", json={"kind": "bookmark", "page": 2}, headers=H).json()
    assert c.get(f"/api/a/{acc.uid}/marks/{-CH - 101}/1").json()["marks"][0]["id"] == mk["id"]
    assert c.delete(f"/api/a/{acc.uid}/marks/{mk['id']}", headers=H).json()["ok"]
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
