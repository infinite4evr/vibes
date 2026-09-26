"""Automatic subject tags (Polity, Economy, History …) for every file, fully offline.

Each file's name, caption and chat title are matched against keyword lists (English,
Hindi and common abbreviations). When no keyword decides it and the meaning model
is available, the file's meaning vector is compared with each subject's; only clear
winners are tagged. Your own subjects and keywords (Settings → Subjects) are added
to the built-in list; subjects you set by hand are never overwritten.

Subjects are stored locally per file (they'd make the synced manifest huge); use
“Apply as tags” to turn them into real, synced tags for the files you care about.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import pace
from . import textproc

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.subjects")

try:
    import snowballstemmer
    _STEM = snowballstemmer.stemmer("porter")
except Exception:  # pragma: no cover
    _STEM = None

BATCH = 4000
MIN_SCORE = 2.0      # one keyword in the file name, or two in the caption
# Calibrated for the weighted, centered vectors of semantic.py v2 (≈86% agree with keyword subjects).
MEANING_SIM = 0.26
MEANING_MARGIN = 0.06


def _stem(w: str) -> str:
    return _STEM.stemWord(w) if _STEM and w.isascii() else w


# id, name, emoji, keywords (comma-separated; phrases allowed; English, Hindi, abbreviations)
BUILTIN = [
    ("polity", "Polity", "⚖️", "polity, constitution, constitutional, laxmikanth, lakshmikanth, parliament, lok sabha, "
     "rajya sabha, judiciary, supreme court, high court, fundamental rights, directive principles, dpsp, preamble, "
     "amendment, governance, panchayati raj, federalism, election commission, president, governor, cag, "
     "राजव्यवस्था, संविधान, संसद, न्यायपालिका, मौलिक अधिकार, पंचायती राज, शासन"),
    ("economy", "Economy", "📈", "economy, economics, economic survey, budget, gdp, inflation, monetary policy, fiscal, "
     "rbi, banking, taxation, gst, ramesh singh, sriram economy, mrunal, agriculture, msp, trade, balance of payments, "
     "niti aayog, finance, microeconomics, macroeconomics, अर्थव्यवस्था, अर्थशास्त्र, बजट, मुद्रास्फीति, आर्थिक सर्वेक्षण, कृषि, बैंकिंग"),
    ("history", "History", "🏛️", "history, ancient history, medieval history, modern history, indian history, "
     "spectrum, bipin chandra, freedom struggle, national movement, mughal, maurya, gupta, harappan, indus valley, "
     "vedic, british rule, world history, world war, revolution, इतिहास, प्राचीन भारत, मध्यकालीन, आधुनिक भारत, स्वतंत्रता संग्राम, राष्ट्रीय आंदोलन"),
    ("art_culture", "Art & Culture", "🎨", "art and culture, culture, nitin singhania, architecture, temple architecture, "
     "painting, dance forms, classical dance, music, festivals, heritage, unesco, sculpture, literature, "
     "कला एवं संस्कृति, संस्कृति, कला, वास्तुकला, नृत्य"),
    ("geography", "Geography", "🌍", "geography, physical geography, indian geography, world geography, g c leong, "
     "goh cheng leong, majid husain, atlas, maps, map, climate, monsoon, rivers, soils, oceanography, geomorphology, "
     "climatology, mapping, भूगोल, मानचित्र, जलवायु, मानसून, नदियां"),
    ("environment", "Environment", "🌿", "environment, ecology, biodiversity, climate change, shankar ias environment, "
     "pollution, wildlife, national parks, sanctuaries, conservation, wetlands, ramsar, cop, unfccc, forest, "
     "पर्यावरण, पारिस्थितिकी, जैव विविधता, जलवायु परिवर्तन, प्रदूषण"),
    ("science", "Science & Tech", "🔬", "science, science and technology, s&t, biology, physics, chemistry, space, isro, "
     "biotechnology, nanotechnology, defence technology, ai, artificial intelligence, computer science, health, disease, "
     "vaccine, nuclear, विज्ञान, विज्ञान एवं प्रौद्योगिकी, जीव विज्ञान, भौतिकी, रसायन, अंतरिक्ष"),
    ("ir", "International Relations", "🌐", "international relations, ir, foreign policy, bilateral, united nations, un, "
     "g20, brics, quad, sco, asean, saarc, wto, imf, world bank, diplomacy, geopolitics, "
     "अंतर्राष्ट्रीय संबंध, विदेश नीति, कूटनीति"),
    ("security", "Internal Security", "🛡️", "internal security, security, terrorism, insurgency, naxalism, left wing "
     "extremism, cyber security, border management, disaster management, money laundering, "
     "आंतरिक सुरक्षा, आपदा प्रबंधन, साइबर सुरक्षा"),
    ("society", "Society & Social Justice", "🤝", "society, indian society, social justice, social issues, women "
     "empowerment, population, urbanisation, urbanization, poverty, education, welfare schemes, schemes, "
     "vulnerable sections, भारतीय समाज, सामाजिक न्याय, जनसंख्या, कल्याणकारी योजनाएं, योजनाएं"),
    ("ethics", "Ethics", "🧭", "ethics, integrity, aptitude, ethics integrity and aptitude, case studies, lexicon, "
     "moral, values, emotional intelligence, gs4, gs 4, gs paper 4, नीतिशास्त्र, सत्यनिष्ठा, नैतिकता"),
    ("current_affairs", "Current Affairs", "📰", "current affairs, ca, monthly magazine, monthly compilation, daily news, "
     "news analysis, editorial, editorials, the hindu, indian express, pib, yojana, kurukshetra, down to earth, "
     "vision ias monthly, drishti, insights, करंट अफेयर्स, समसामयिकी, मासिक पत्रिका, संपादकीय"),
    ("csat", "CSAT & Maths", "🧮", "csat, aptitude test, quantitative aptitude, quant, reasoning, logical reasoning, "
     "comprehension, maths, math, mathematics, arithmetic, algebra, geometry, data interpretation, "
     "गणित, तर्कशक्ति, सीसैट"),
    ("essay", "Essay & Answer Writing", "✍️", "essay, essays, answer writing, model answers, answer copy, toppers copy, "
     "topper copy, answer sheet, निबंध, उत्तर लेखन"),
    ("languages", "Languages", "🔤", "english, grammar, vocabulary, hindi grammar, compulsory english, compulsory hindi, "
     "अंग्रेजी, व्याकरण, हिंदी"),
    ("optional", "Optional Subjects", "📚", "optional, sociology, anthropology, public administration, pub ad, psir, "
     "political science, philosophy, psychology, geography optional, history optional, mathematics optional, "
     "वैकल्पिक विषय, लोक प्रशासन, समाजशास्त्र, दर्शनशास्त्र"),
]


@dataclass
class Subject:
    id: str
    name: str
    emoji: str = ""
    words: dict[str, float] = field(default_factory=dict)      # single stemmed words → weight
    phrases: dict[tuple[str, ...], float] = field(default_factory=dict)  # stemmed word sequences → weight


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for w in textproc.words(text or ""):
        for p in textproc.split_compound(w):
            f = textproc.fold(p)
            if f:
                out.append(_stem(f))
    return out


def _add_terms(s: Subject, terms: str, boost: float = 1.0) -> None:
    for raw in terms.split(","):
        toks = _tokens(raw.strip())
        if not toks:
            continue
        if len(toks) == 1:
            w = toks[0]
            # Very short abbreviations (ca, ir, un, ai) count less: they collide with other words.
            s.words[w] = max(s.words.get(w, 0), (0.6 if len(w) <= 2 else 1.0) * boost)
        else:
            s.phrases[tuple(toks)] = max(s.phrases.get(tuple(toks), 0), 1.4 * boost)


def _slug(name: str) -> str:
    s = re.sub(r"[^\w]+", "_", textproc.fold(name)).strip("_")
    return s[:40] or "subject"


def build_subjects(custom: str = "", builtin: bool = True) -> list[Subject]:
    """Built-in subjects plus lines like `Tax Law: income tax, gst, itr` from Settings."""
    out: dict[str, Subject] = {}
    if builtin:
        for sid, name, emoji, terms in BUILTIN:
            s = Subject(sid, name, emoji)
            _add_terms(s, name + ", " + terms)
            out[sid] = s
    for line in (custom or "").splitlines():
        if ":" not in line:
            continue
        name, _, terms = line.partition(":")
        name = " ".join(name.split())
        if not name:
            continue
        emoji = ""
        m = re.match(r"^(\W{1,3})\s+(.+)$", name)
        if m and not m.group(1).isascii():
            emoji, name = m.group(1), m.group(2)
        existing = next((s for s in out.values() if s.name.lower() == name.lower()), None)
        s = existing or Subject(_slug(name), name, emoji)
        if emoji:
            s.emoji = emoji
        _add_terms(s, name + ", " + terms, boost=1.3)  # your own keywords win ties with built-in ones
        out[s.id] = s
    return list(out.values())


def classify(subjects: list[Subject], name: str, caption: str = "", chat_title: str = "") -> tuple[Optional[str], float]:
    """Best subject for a file by keywords, and its score (0 when nothing matched)."""
    scores: dict[str, float] = {}
    for text, weight in ((textproc.strip_ext(name), 2.0), (caption or "", 1.0), (chat_title or "", 0.7)):
        toks = _tokens(text)[:120]
        if not toks:
            continue
        tokset = set(toks)
        for s in subjects:
            sc = 0.0
            for w, wt in s.words.items():
                if w in tokset:
                    sc += wt
            for ph, wt in s.phrases.items():
                n = len(ph)
                if ph[0] in tokset:
                    for i in range(len(toks) - n + 1):
                        if tuple(toks[i:i + n]) == ph:
                            sc += wt
                            break
            if sc:
                scores[s.id] = scores.get(s.id, 0.0) + sc * weight
    if not scores:
        return None, 0.0
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    best, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if score < MIN_SCORE or score < second * 1.25:
        return None, score
    return best, score


class SubjectIndex:
    """Background tagger: one worker thread per account, resumable (meta key subjects_until)."""

    def __init__(self, account: "Account"):
        self.acc = account
        self.enabled = True
        self.state = "idle"
        self.error: Optional[str] = None
        self.done = 0
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subjects: list[Subject] = []
        self._sig = None
        self._protos = None
        self._dirty: set[int] = set()

    @property
    def db_path(self) -> Path:
        return self.acc.db.path

    def subjects(self) -> list[Subject]:
        from .settings import settings
        sig = (settings.get("subjects_custom") or "", bool(settings.get("subjects_builtin", True)))
        if sig != self._sig:
            self._subjects, self._sig, self._protos = build_subjects(sig[0], sig[1]), sig, None
        return self._subjects

    def info(self) -> list[dict]:
        return [{"id": s.id, "name": s.name, "emoji": s.emoji} for s in self.subjects()]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tgdrive-subjects", daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        """Ask the worker to stop now; a database query it is running is interrupted."""
        self._stop.set()
        self._wake.set()
        conn = getattr(self, "_conn", None)
        if conn is not None:
            try:
                conn.interrupt()
            except Exception:
                pass

    def join(self, timeout: float = 5) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    def stop(self) -> None:
        self.request_stop()
        self.join(5)

    def poke(self, file_id: Optional[int] = None) -> None:
        if file_id is not None:
            self._dirty.add(int(file_id))
        self._wake.set()

    def rebuild(self) -> None:
        """Subjects or keywords changed: classify everything again (hand-set subjects stay)."""
        self.acc.db.set_meta("subjects_until", 0)
        self._protos = None
        self._wake.set()

    def status(self) -> dict:
        return {"enabled": self.enabled, "state": self.state, "error": self.error,
                "until": int(self.acc.db.get_meta("subjects_until") or 0)}

    # ------------------------------------------------------------- worker
    def _loop(self) -> None:
        pace.lower_priority()
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None, check_same_thread=False)
        self._conn = conn
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            while not self._stop.is_set():
                pace.wait_while_paused(self._stop, lambda: setattr(self, "state", "paused"))
                if self._stop.is_set():
                    break
                if not self.enabled:
                    self.state = "off"
                    self._wake.wait(30)
                    self._wake.clear()
                    continue
                try:
                    t0 = time.thread_time()
                    worked = self._step(conn)
                    if worked:
                        pace.rest(time.thread_time() - t0, self._stop)
                except sqlite3.OperationalError as exc:
                    if self._stop.is_set():
                        break
                    log.info("subjects step retry: %s", exc)
                    worked = False
                    self._stop.wait(2)
                except Exception as exc:  # keep the app running; report in status
                    log.exception("subject tagging failed")
                    self.state, self.error = "error", str(exc)
                    self._stop.wait(60)
                    continue
                if not worked:
                    self.state = "ready"
                    self._wake.wait(60)
                    self._wake.clear()
        finally:
            self._conn = None
            conn.close()

    def _step(self, conn: sqlite3.Connection) -> bool:
        subjects = self.subjects()
        start = int((conn.execute("SELECT value FROM meta WHERE key='subjects_until'").fetchone() or [0])[0] or 0)
        rows = conn.execute("SELECT id, COALESCE(alias, name), caption, chat_title FROM files WHERE id > ? "
                            "ORDER BY id LIMIT ?", (start, BATCH)).fetchall()
        dirty = []
        if self._dirty:
            dirty, self._dirty = list(self._dirty)[:BATCH], set(list(self._dirty)[BATCH:])
            marks = ",".join("?" * len(dirty))
            rows += conn.execute(f"SELECT id, COALESCE(alias, name), caption, chat_title FROM files "
                                 f"WHERE id IN ({marks})", dirty).fetchall()
        if not rows:
            return False
        self.state = "building"
        manual = {r[0] for r in conn.execute(
            f"SELECT file_id FROM file_subjects WHERE src='manual' AND file_id IN "
            f"({','.join(str(int(r[0])) for r in rows)})")}
        out, unresolved = [], []
        for fid, name, cap, chat in rows:
            if fid in manual:
                continue
            sid, score = classify(subjects, name or "", cap or "", chat or "")
            if sid:
                out.append((fid, sid, round(score, 2), "keywords"))
            else:
                unresolved.append(fid)
        out += self._by_meaning(unresolved, subjects)
        ids = [r[0] for r in rows if r[0] not in manual]
        with self.acc.db.wlock:  # one writer at a time (see Database.wlock)
            conn.execute("BEGIN IMMEDIATE")
            try:
                if ids:
                    conn.execute(f"DELETE FROM file_subjects WHERE src<>'manual' AND file_id IN ({','.join(map(str, ids))})")
                conn.executemany("INSERT OR REPLACE INTO file_subjects(file_id, subject, score, src) VALUES(?,?,?,?)", out)
                new_until = max((r[0] for r in rows if r[0] > start), default=start)
                conn.execute("INSERT INTO meta(key, value) VALUES('subjects_until', ?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(new_until),))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        self.done += len(out)
        return True

    def _by_meaning(self, ids: list[int], subjects: list[Subject]) -> list[tuple]:
        """Files no keyword decided: nearest subject by meaning, when it is clearly the nearest."""
        sem = getattr(self.acc, "semantic", None)
        if not ids or sem is None or sem.vec is None or not sem.enabled:
            return []
        try:
            import numpy as np
            from .semantic import _Model
            model = _Model.get()
            if model is None:
                return []
            if self._protos is None or getattr(self, "_protos_at", None) != sem.meta.get("stats_at"):
                self._protos_at = sem.meta.get("stats_at")
                texts = [f"{s.name}. " + " ".join(sorted(
                    {w for w in s.words} | {" ".join(p) for p in s.phrases}))[:600] for s in subjects]
                self._protos = sem.embed_query(texts)   # same space as the stored file vectors
            n = min(int(sem.meta.get("built_until") or 0) + 1, sem.vec.shape[0])
            arr = np.asarray([i for i in ids if 0 < i < n], dtype=np.int64)
            if not len(arr):
                return []
            with sem.lock:
                vec = np.asarray(sem.vec[arr], dtype=np.float32) * np.asarray(sem.scale[arr], dtype=np.float32)[:, None]
            norms = np.linalg.norm(vec, axis=1)
            ok = norms > 0
            sims = (vec[ok] / norms[ok][:, None]) @ self._protos.T
            out = []
            for fid, row in zip(arr[ok], sims):
                order = np.argsort(-row)
                best, second = row[order[0]], row[order[1]] if len(order) > 1 else 0
                if best >= MEANING_SIM and best - second >= MEANING_MARGIN:
                    out.append((int(fid), subjects[int(order[0])].id, round(float(best), 3), "meaning"))
            return out
        except Exception as exc:
            log.debug("meaning-based subjects unavailable: %s", exc)
            return []
