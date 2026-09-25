"""Synthetic large index shaped like a real heavy user's (≈437k files, ≈1,700 chats).

Used by the scale tests and by `python -m tests.bigdb <path> [n]` for benchmarking.
Records go through Database.upsert_files, so triggers, search keywords and stats
are produced exactly as the indexer would produce them.
"""
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CH = 1_000_000_000_000

KIND_MIX = [("photo", 272_095), ("document", 146_336), ("video", 15_168), ("voice", 2_749),
            ("audio", 701), ("gif", 622), ("round", 17)]

CHANNEL_WORDS = ["Vision IAS", "Vajiram and Ravi", "InsightsIAS", "MixRoot Mods", "theIAShub", "The Hindu NewsPaper",
                 "Pradhaan IAS", "Tnpsc", "Sarkari Ujala", "Rau's IAS Study Circle", "Apnagovtjob", "UPSC 2026 STUDY",
                 "CSE WARRIORS", "PDF Magazines", "THE MAGAZINE INDIA", "DL Magazines", "Tnpsc Pre Coaching",
                 "INDIAN HISTORY BOOKS", "CSAC-COEP", "Convert IAS", "UPSC PIB NEWS current affairs",
                 "LEGEND BHAIYA MAINS", "IAS PCS Pathshala", "Free Study Materials", "UPSC NCERT BOOKS",
                 "Mission Sarkari Exams", "CSE RESOURCES", "CSE FILES", "Drishti IAS", "Next IAS", "Forum IAS",
                 "StudyIQ", "Unacademy UPSC", "Only IAS", "Shankar IAS", "Mrunal Economy", "Sleepy Classes",
                 "Edukemy", "PW OnlyIAS", "Testbook", "Adda247", "Physics Wallah", "Khan Sir Official",
                 "Current Affairs Daily", "Yojana Kurukshetra", "Down To Earth", "EPW Journal", "Science Reporter"]
SUBJECTS = ["Polity", "Economy", "History", "Geography", "Environment", "Ecology", "Ethics", "Essay",
            "Science and Tech", "International Relations", "Governance", "Social Justice", "Art and Culture",
            "Modern History", "Ancient History", "Medieval History", "Indian Society", "Internal Security",
            "Disaster Management", "Agriculture", "Budget", "Economic Survey", "Constitution", "Fundamental Rights"]
DOC_KINDS = ["Test Series", "TestSeries", "Mock Test", "PYQ", "Previous Year Questions", "Notes", "Handwritten Notes",
             "Summary", "Compiled", "Mains Answer Writing", "Prelims", "Mains", "Current Affairs", "Magazine",
             "Monthly Magazine", "Daily News Analysis", "Editorial", "Quick Revision", "Mindmap", "Booklet",
             "Value Addition", "Answer Key", "Solution", "Question Paper", "Syllabus", "Timetable", "Strategy"]
AUTHORS = ["Laxmikanth", "Spectrum", "Ramesh Singh", "Shankar", "NCERT Class 11", "NCERT Class 12", "Bipan Chandra",
           "Nitin Singhania", "GC Leong", "Majid Husain", "Lexicon", "Vajiram Yellow Book", "Sriram"]
HINDI = ["संविधान", "अर्थव्यवस्था", "इतिहास", "भूगोल", "पर्यावरण", "करंट अफेयर्स", "टेस्ट सीरीज", "नोट्स",
         "प्रारंभिक परीक्षा", "मुख्य परीक्षा", "प्रश्न पत्र", "उत्तर लेखन", "सामान्य अध्ययन", "राजव्यवस्था", "योजना"]
CAPTION_BITS = ["Join for daily updates", "Share with your friends", "Download the PDF", "Important for prelims 2026",
                "#UPSC #IAS #CurrentAffairs", "Daily quiz at 9 PM", "Link: https://t.me/example", "Must read",
                "Answer writing practice day", "Revise before the exam", "Free test series for all aspirants",
                "PIB summary of the week", "The Hindu editorial explained", "Monthly compilation is out"]


def _name(rnd: random.Random, kind: str, stamp: str) -> tuple[str, str, str]:
    if kind == "photo":
        if rnd.random() < 0.93:
            return f"photo_{stamp}.jpg", "jpg", "image/jpeg"
        return f"{rnd.choice(['IMG', 'Screenshot', 'Scan'])}_{rnd.randint(1000, 9999)}.png", "png", "image/png"
    if kind == "video":
        base = rnd.choice([f"video_{stamp}", f"{rnd.choice(SUBJECTS)} Lecture {rnd.randint(1, 80)}",
                           f"{rnd.choice(DOC_KINDS)} Discussion {rnd.randint(1, 40)}"])
        return f"{base}.mp4", "mp4", "video/mp4"
    if kind in ("voice", "round"):
        return f"{kind}_{stamp}.{'ogg' if kind == 'voice' else 'mp4'}", "ogg" if kind == "voice" else "mp4", \
            "audio/ogg" if kind == "voice" else "video/mp4"
    if kind == "audio":
        return f"{rnd.choice(SUBJECTS)} podcast {rnd.randint(1, 200)}.mp3", "mp3", "audio/mpeg"
    if kind == "gif":
        return "animation.mp4", "mp4", "video/mp4"
    style = rnd.random()
    subj, dk = rnd.choice(SUBJECTS), rnd.choice(DOC_KINDS)
    year = rnd.choice(["2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026", "2011-2026"])
    if style < 0.25:
        base = f"{subj} {dk} {year}"
    elif style < 0.45:
        base = f"{subj.replace(' ', '')}_{dk.replace(' ', '')}_{year}"
    elif style < 0.6:
        base = f"Pillar{rnd.randint(1, 9)}(Compiled)_PCB{rnd.randint(1, 20)}_{dk.replace(' ', '')}"
    elif style < 0.72:
        base = f"{rnd.choice(AUTHORS)} {subj} {rnd.choice(['Chapter', 'Ch', 'Part'])}{rnd.randint(1, 30)}"
    elif style < 0.82:
        base = f"{rnd.choice(HINDI)} {rnd.choice(HINDI)} {year}"
    elif style < 0.9:
        base = f"THEME UPSC - {subj.upper()} ({rnd.choice(['CSN', 'CSE', 'GS'])})"
    else:
        base = f"{rnd.choice(CHANNEL_WORDS).split()[0]}{dk.replace(' ', '')}{rnd.randint(1, 60)}"
    ext, mime = rnd.choice([("pdf", "application/pdf")] * 8 + [("docx", "application/msword"), ("zip", "application/zip"),
                                                            ("pptx", "application/vnd.ms-powerpoint")])
    return f"{base}.{ext}", ext, mime


def _caption(rnd: random.Random, kind: str) -> str:
    p = 0.45 if kind == "document" else 0.25 if kind in ("photo", "video") else 0.05
    if rnd.random() > p:
        return ""
    parts = [rnd.choice(CAPTION_BITS)]
    for _ in range(rnd.randint(0, 5)):
        r = rnd.random()
        if r < 0.35:
            parts.append(f"{rnd.choice(SUBJECTS)} {rnd.choice(DOC_KINDS)}")
        elif r < 0.6:
            parts.append(" ".join(rnd.sample(HINDI, 3)))
        else:
            parts.append(rnd.choice(CAPTION_BITS))
    return "\n".join(parts)


def build(path: Path, n: int = 437_688, seed: int = 11, batch: int = 5000, quiet: bool = False):
    from tgdrive.db import Database
    rnd = random.Random(seed)
    db = Database(path)
    # ~1,700 chats with Zipf-like file counts.
    chats = []
    for i in range(620):
        title = CHANNEL_WORDS[i] if i < len(CHANNEL_WORDS) else f"{rnd.choice(CHANNEL_WORDS)} {rnd.choice(['Official', 'Hindi', 'PDF', 'Notes', 'Group', str(i)])}"
        chats.append({"id": -CH - 1000 - i, "title": title, "kind": "channel", "username": f"chan{i}" if i % 3 else None})
    for i in range(220):
        chats.append({"id": -CH - 5000 - i, "title": f"{rnd.choice(SUBJECTS)} discussion {i}", "kind": "supergroup",
                      "username": None})
    for i in range(830):
        chats.append({"id": 10_000 + i, "title": f"Person {i}", "kind": "user", "username": None})
    for i in range(40):
        chats.append({"id": 90_000 + i, "title": f"Helper Bot {i}", "kind": "bot", "username": f"helper{i}bot"})
    chats.append({"id": 1, "title": "Saved Messages", "kind": "saved", "username": None})
    for c in chats:
        c.update(is_creator=0, is_admin=0, noforwards=0, latest_msg_id=0)
        db.upsert_chat(c)
    weights = [1 / (i + 1) ** 1.05 for i in range(len(chats))]
    kinds = [k for k, c in KIND_MIX for _ in range(max(1, round(c * n / 437_688)))][:n]
    rnd.shuffle(kinds)
    msg_ids: dict[int, int] = {}
    t0, now = time.time(), 1_790_000_000
    recs = []
    for i, kind in enumerate(kinds):
        chat = rnd.choices(chats, weights)[0]
        mid = msg_ids[chat["id"]] = msg_ids.get(chat["id"], 0) + rnd.randint(1, 4)
        date = now - int(rnd.random() ** 1.6 * 5 * 365 * 86400)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.gmtime(date))
        name, ext, mime = _name(rnd, kind, stamp)
        size = int(rnd.lognormvariate(13.5 if kind != "video" else 17, 1.3))
        recs.append({
            "chat_id": chat["id"], "msg_id": mid, "kind": kind, "name": name, "ext": ext, "mime": mime,
            "size": size, "date": date, "caption": _caption(rnd, kind) or None, "sender_id": None,
            "sender_name": None, "chat_title": chat["title"], "width": 1280 if kind == "photo" else None,
            "height": 960 if kind == "photo" else None,
            "duration": rnd.randint(5, 5000) if kind in ("video", "audio", "voice", "round") else None,
            "performer": None, "audio_title": None, "media_id": rnd.getrandbits(62), "grouped_id": None,
            "is_forward": int(rnd.random() < 0.3), "fwd_from": None, "has_thumb": int(kind != "document" or rnd.random() < 0.6),
            "is_out": 0,
        })
        if len(recs) >= batch:
            db.upsert_files(recs)
            recs = []
            if not quiet and (i + 1) % 50_000 < batch:
                print(f"  {i + 1:,} files, {time.time() - t0:.0f}s", flush=True)
    db.upsert_files(recs)
    for c in chats:
        db.x("UPDATE chats SET latest_msg_id=?, index_state='done' WHERE id=?", (msg_ids.get(c["id"], 0), c["id"]))
        db.refresh_file_count(c["id"])
    if not quiet:
        print(f"built {n:,} files in {time.time() - t0:.0f}s -> {path} ({path.stat().st_size / 1e6:.0f} MB)")
    return db


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/big/index.db")
    out.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(out) + suffix).unlink(missing_ok=True)
    build(out, int(sys.argv[2]) if len(sys.argv) > 2 else 437_688).close()
