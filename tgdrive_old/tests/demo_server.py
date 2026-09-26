"""Serve the UI against the fake Telegram world (no network needed).

    python -m tests.demo_server      then open http://127.0.0.1:8766
"""
import asyncio
import io
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("TGDRIVE_DATA", tempfile.mkdtemp(prefix="tgdrive-demo-"))

from telethon.tl import types  # noqa: E402

from tests.fake import CH, doc_msg, make_account, sample_world  # noqa: E402
from tgdrive import api  # noqa: E402
from tgdrive.settings import settings  # noqa: E402


def fake_jpeg(seed: int, w=320, h=240) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return b""
    rnd = random.Random(seed)
    palette = [(70, 120, 150), (190, 140, 90), (90, 150, 110), (160, 90, 110), (120, 110, 170), (200, 170, 120)]
    base = rnd.choice(palette)
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    for _ in range(6):
        c = tuple(min(255, max(0, v + rnd.randint(-60, 60))) for v in base)
        x, y = rnd.randint(-40, w), rnd.randint(-40, h)
        r = rnd.randint(30, 160)
        d.ellipse([x, y, x + r * 2, y + r], fill=c)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def demo_pdf() -> bytes:
    """A real multi-page PDF with selectable text, for the PDF reader."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return b""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    body = ("Article 14 guarantees equality before the law and the equal protection of the laws within the territory "
            "of India. Article 15 prohibits discrimination on grounds of religion, race, caste, sex or place of birth. "
            "Article 16 provides equality of opportunity in matters of public employment. Article 17 abolishes "
            "untouchability and forbids its practice in any form. Article 19 protects six freedoms of citizens.")
    for p in range(1, 13):
        c.setFont("Helvetica-Bold", 20)
        c.drawString(60, h - 80, f"Fundamental Rights — Part {p}")
        c.setFont("Helvetica", 12)
        y = h - 120
        words = (body + " ") * 3
        line = ""
        for word in words.split():
            if c.stringWidth(line + " " + word, "Helvetica", 12) > w - 120:
                c.drawString(60, y, line)
                y -= 18
                line = word
                if y < 80:
                    break
            else:
                line = (line + " " + word).strip()
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(w / 2 - 20, 40, f"Page {p}")
        c.showPage()
    c.save()
    return buf.getvalue()


EXTRA = [
    ("Economy_TestSeries_2023.pdf", "application/pdf"), ("Mock Test Series Polity.pdf", "application/pdf"),
    ("Previous Year Questions Polity 2011-2024.pdf", "application/pdf"), ("PYQ Economy 2024.pdf", "application/pdf"),
    ("भारतीय संविधान नोट्स.pdf", "application/pdf"), ("Monthly Current Affairs Magazine September.pdf", "application/pdf"),
    ("Environment and Ecology notes.docx", "application/msword"), ("Budget 2024 highlights.pptx", "application/vnd.ms-powerpoint"),
    ("NCERT Class 11 History.epub", "application/epub+zip"), ("Answer writing sheet.xlsx", "application/vnd.ms-excel"),
    ("UPSC Mains 2025 papers.zip", "application/zip"), ("syllabus.txt", "text/plain"),
]


async def setup(tmp: Path):
    world = sample_world(scale=3)
    acc, client = make_account(tmp, world=world)
    cid = -CH - 101
    for i, (n, mime) in enumerate(EXTRA):
        m = doc_msg(cid, 5000 + i, n, mime, random.Random(i).randint(200_000, 40_000_000), world[0][cid][0].date,
                    thumb=n.endswith(".pdf") and i % 2 == 0, caption="Free test series for all aspirants" if i < 2 else "")
        client.chats[cid].append(m)
        if n.endswith(".txt"):
            client.content[m.media.document.id] = ("PRELIMS SYLLABUS\n\n" + "General Studies Paper I\n- Current events\n- History of India\n" * 30).encode()
            m.media.document.size = len(client.content[m.media.document.id])
    pdf = demo_pdf()
    if pdf:
        m = doc_msg(cid, 6000, "Indian Polity - Fundamental Rights (notes).pdf", "application/pdf", len(pdf),
                    world[0][cid][0].date, caption="Chapter 7 notes with PYQs")
        client.content[m.media.document.id] = pdf
        client.chats[cid].append(m)
    for msgs in client.chats.values():  # full-size photos for the viewer
        for m in msgs:
            if isinstance(m.media, types.MessageMediaPhoto):
                client.content[m.media.photo.id] = fake_jpeg(m.id * 7 + 3, 1280, 960)
    real_download = client.download_media

    async def download_media(msg, file=None, thumb=None):
        seed = msg.id * 31 + abs(msg.peer_id.to_dict().get("channel_id", 0) or 0)
        data = fake_jpeg(seed, 800 if thumb in ("x", "y") or thumb is None else 320,
                         600 if thumb in ("x", "y") or thumb is None else 240)
        if not data:
            return await real_download(msg, file, thumb)
        if file is bytes:
            return data
        Path(file).write_bytes(data)
        return file

    client.download_media = download_media
    await acc.indexer.sync_dialogs()
    await acc.indexer.sync_dialog_filters()
    for chat in acc.db.chats_needing_index():
        await acc.indexer.index_chat(acc.db.get_chat(chat["id"]))
    d = acc.drive
    await d.load()
    study = await d.create_folder("Study", None, color="blue")
    phys = await d.create_folder("Quantum mechanics", study["id"])
    await d.create_folder("Design inspiration", None, color="purple")
    home = await d.create_folder("Home and bills", None, color="green")
    await d.create_folder("Travel 2026", None, color="orange")
    lectures = acc.db.q("SELECT chat_id, msg_id FROM files WHERE chat_title='Physics Lectures' LIMIT 8")
    await d.place([(r["chat_id"], r["msg_id"]) for r in lectures], phys["id"])
    bills = acc.db.q("SELECT chat_id, msg_id FROM files WHERE name LIKE 'electricity%' OR name LIKE 'Invoice%' LIMIT 10")
    await d.place([(r["chat_id"], r["msg_id"]) for r in bills], home["id"])
    stars = acc.db.q("SELECT chat_id, msg_id FROM files WHERE kind='photo' LIMIT 4")
    await d.set_meta_items([(r["chat_id"], r["msg_id"]) for r in stars], starred=True, tags_add=["family"])
    await d.set_meta_items([(cid, 5000), (cid, 5002)], tags_add=["exam", "polity"])
    await d.save_search("Big lectures", "type:video size>500mb", {})
    # Folder looks, a smart folder and an auto-filing folder.
    await d.update_folder(study["id"], emoji="📚")
    await d.update_folder(home["id"], emoji="🏠")
    trav = next(f for f in acc.db.q("SELECT id FROM folders WHERE name='Travel 2026'"))
    await d.update_folder(trav["id"], emoji="✈️")
    await d.create_folder("Polity (smart)", study["id"], color="teal", emoji="⚖️",
                          rules={"mode": "smart", "q": "polity", "params": {}})
    await d.create_folder("PDF notes", study["id"], color="red", emoji="📝",
                          rules={"mode": "auto", "q": "notes", "params": {"exts": "pdf"}})
    for i, name in enumerate(["Economy", "History", "Geography", "Environment", "Current Affairs", "Ethics",
                              "Science & Tech", "Art & Culture", "Answer writing", "Maps", "Newspapers", "Tests"]):
        await d.create_folder(name, study["id"], color=["blue", "orange", "green", "teal", "red", "purple",
                                                        "pink", "yellow", "grey", "blue", "orange", "green"][i],
                              emoji="📈 🏛️ 🗺️ 🌿 📰 🧭 🔬 🎨 ✍️ 🧭 🗞️ 📝".split()[i])
    # Photo locations (as if found in EXIF) for the Places map.
    import random as _r
    rnd = _r.Random(3)
    spots = [(28.61, 77.21), (19.08, 72.88), (12.97, 77.59), (26.91, 75.79), (32.24, 77.19), (15.30, 74.12),
             (48.86, 2.35), (51.51, -0.13), (35.68, 139.69), (40.71, -74.0)]
    photos = acc.db.q("SELECT id, date FROM files WHERE kind='photo' LIMIT 60")
    for i, r in enumerate(photos):
        lat, lon = spots[i % len(spots)]
        acc.db.x("INSERT OR REPLACE INTO geo(file_id, lat, lon, taken, checked) VALUES(?,?,?,?,?)",
                 (r["id"], lat + rnd.uniform(-.05, .05), lon + rnd.uniform(-.05, .05), r["date"], 1))
    await d.flush_now()
    for r in acc.db.q("SELECT chat_id, msg_id FROM files WHERE chat_title='Design Resources' LIMIT 6"):
        await d.copy_to_drive(r["chat_id"], r["msg_id"], None)
    fam = acc.db.q("SELECT id FROM files WHERE chat_title='Family Photos' AND kind='photo' ORDER BY date DESC, msg_id DESC LIMIT 12")
    for i, r in enumerate(fam):  # albums (photos sent together) for the stacked cards
        acc.db.x("UPDATE files SET grouped_id=? WHERE id=?", (777000 + i // 4, r["id"]))
    print("albums:", len(fam), acc.db.q("SELECT COUNT(*) AS n FROM files WHERE grouped_id IS NOT NULL"), flush=True)
    return acc


def main():
    tmp = Path(tempfile.mkdtemp())
    settings.data.update(api_id=1, api_hash="0" * 32, search_semantic=True, download_dir=str(tmp / "Downloads"))
    acc = asyncio.run(setup(tmp))
    api.manager.accounts = {acc.uid: acc}

    async def noop():
        return None

    async def startup():
        acc.semantic.start()
        acc.subjects.start()
        acc.autofile.start()

    api.manager.startup = startup
    api.manager.shutdown = noop
    acc.indexer.phase = "indexing"
    acc.indexer.current_title = "Physics Lectures"
    import run
    port = int(os.environ.get("DEMO_PORT", "8766"))
    server, socks = run.make_server(port=port, media_port=port + 1, fallback=False)
    print(f"demo on http://127.0.0.1:{socks[0].getsockname()[1]}", flush=True)
    server.run(sockets=socks)


if __name__ == "__main__":
    main()
