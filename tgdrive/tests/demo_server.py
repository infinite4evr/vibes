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

from tests.fake import CH, audio_attr, doc_msg, make_account, sample_world  # noqa: E402
from tgdrive import api  # noqa: E402
from tgdrive.settings import settings  # noqa: E402


def fake_jpeg(seed: int, w=320, h=240) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError:   # the Android app has no Pillow: the same kind of picture, as a PNG
        return fake_png(seed, w, h)
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


def demo_wav(seconds: int = 12, rate: int = 8000) -> bytes:
    """A real, playable recording (a soft two-note tone, 16-bit mono WAV): the other sample songs are
    made-up bytes, and the phone's player tests need one that actually plays."""
    import math
    import struct
    frames = bytearray()
    for i in range(seconds * rate):
        f = 440.0 if (i // rate) % 2 == 0 else 660.0
        frames += struct.pack("<h", int(6000 * math.sin(2 * math.pi * f * i / rate)))
    header = b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVE" + b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(frames))
    return header + bytes(frames)


def demo_pdf() -> bytes:
    """A real multi-page PDF with selectable text, for the PDF reader."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return simple_pdf()
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


PDF_BODY = ("Article 14 guarantees equality before the law and the equal protection of the laws within the territory "
            "of India. Article 15 prohibits discrimination on grounds of religion, race, caste, sex or place of birth. "
            "Article 16 provides equality of opportunity in matters of public employment. Article 17 abolishes "
            "untouchability and forbids its practice in any form. Article 19 protects six freedoms of citizens.")


def fake_png(seed: int, w: int = 320, h: int = 240) -> bytes:
    """fake_jpeg's picture (a colour and a few soft blobs) without Pillow: rows of spans, zlib, PNG chunks."""
    import struct
    import zlib
    rnd = random.Random(seed)
    palette = [(70, 120, 150), (190, 140, 90), (90, 150, 110), (160, 90, 110), (120, 110, 170), (200, 170, 120)]
    base = rnd.choice(palette)
    blobs = []
    for _ in range(6):
        c = bytes(min(255, max(0, v + rnd.randint(-60, 60))) for v in base)
        x, y = rnd.randint(-40, w), rnd.randint(-40, h)
        r = rnd.randint(30, 160) * max(1.0, w / 320)
        blobs.append((x + r, y + r / 2, r, r / 2, c))   # centre, radii (as PIL's ellipse box [x, y, x+2r, y+r])
    rows = []
    for yy in range(h):
        row = bytearray(bytes(base) * w)
        for cx, cy, rx, ry, c in blobs:
            dy = (yy + 0.5 - cy) / ry
            if abs(dy) >= 1:
                continue
            half = rx * (1 - dy * dy) ** 0.5
            a, b = max(0, int(cx - half)), min(w, int(cx + half))
            if a < b:
                row[a * 3:b * 3] = c * (b - a)
        rows.append(b"\0" + bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


def simple_pdf(pages: int = 12) -> bytes:
    """demo_pdf's document without reportlab: A4 pages of Helvetica text, written by hand."""
    import textwrap
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"]
    kids = []
    for p in range(1, pages + 1):
        lines = textwrap.wrap((PDF_BODY + " ") * 3, 88)[:36]
        esc = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text = [f"BT /F2 20 Tf 60 762 Td (Fundamental Rights - Part {p}) Tj ET", "BT /F1 12 Tf 60 722 Td 18 TL"]
        text += [f"({esc(t)}) '" for t in lines] + ["ET", f"BT /F1 9 Tf 278 40 Td (Page {p}) Tj ET"]
        stream = "\n".join(text).encode("latin-1")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n" + stream.decode("latin-1") + "\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {len(objs)} 0 R "
                    "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {pages} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


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
    wav = demo_wav()
    m = doc_msg(cid, 6001, "Morning raga (sample recording).wav", "audio/x-wav", len(wav), world[0][cid][0].date,
                attrs=[audio_attr(12, title="Morning raga", performer="TG Drive sample")], caption="A sample that really plays")
    client.content[m.media.document.id] = wav
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
    await d.flush_now()
    for r in acc.db.q("SELECT chat_id, msg_id FROM files WHERE chat_title='Design Resources' LIMIT 6"):
        await d.copy_to_drive(r["chat_id"], r["msg_id"], None)
    fam = acc.db.q("SELECT id FROM files WHERE chat_title='Family Photos' AND kind='photo' ORDER BY date DESC, msg_id DESC LIMIT 12")
    for i, r in enumerate(fam):  # albums (photos sent together) for the stacked cards
        acc.db.x("UPDATE files SET grouped_id=? WHERE id=?", (777000 + i // 4, r["id"]))
    print("albums:", len(fam), acc.db.q("SELECT COUNT(*) AS n FROM files WHERE grouped_id IS NOT NULL"), flush=True)
    return acc


def prepare(tmp: Path, download_dir: str = "", loop: asyncio.AbstractEventLoop = None):
    """Build the made-up account and make it the server's only account (desktop demo and the Android
    app's "Try it with sample data")."""
    settings.data.update(api_id=1, api_hash="0" * 32, search_semantic=True,
                         download_dir=download_dir or str(tmp / "Downloads"))
    acc = (loop.run_until_complete(setup(tmp)) if loop else asyncio.run(setup(tmp)))
    api.manager.accounts = {acc.uid: acc}

    async def noop():
        return None

    async def startup():
        acc.semantic.start()
        acc.subjects.start()
        acc.dupes.start()
        acc.autofile.start()

    api.manager.startup = startup
    api.manager.shutdown = noop
    acc.indexer.phase = "indexing"
    acc.indexer.current_title = "Physics Lectures"
    return acc


def main():
    prepare(Path(tempfile.mkdtemp()))
    import run
    port = int(os.environ.get("DEMO_PORT", "8766"))
    server, socks = run.make_server(port=port, media_port=port + 1, fallback=False)
    print(f"demo on http://127.0.0.1:{socks[0].getsockname()[1]}", flush=True)
    server.run(sockets=socks)


if __name__ == "__main__":
    main()
