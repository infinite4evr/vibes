"""Text processing shared by indexing and searching.

Indexing: every file gets a hidden `keywords` field so that differently-written
forms of the same words meet in the full-text index:

* compound words are split: TestSeries → test series, Pillar5 → pillar 5,
  GS_Paper-2 → gs paper 2 (camelCase, letter/digit and punctuation boundaries);
* neighbouring words are joined: "Test Series" → testseries, so a search for the
  joined form finds the spaced one;
* acronyms of runs of words in the name: "Previous Year Questions" → pyq;
* Devanagari words are transliterated to Latin: संविधान → samvidhana, samvidhan.

Searching: the same helpers produce query variants (joined words, splits,
acronyms, transliterations, synonyms) that the search engine ORs together.
"""
import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Optional

# Letters, digits and combining marks (so Hindi vowel signs stay inside words).
_MARKS = "̀-ͯ҃-҉֑-ֽؐ-ًؚ-ٰٟۖ-ۭ" \
         "ऀ-෿ัิ-ฺ็-๎᪰-᫿᷀-᷿⃐-⃿︠-︯"
WORD_RE = re.compile(rf"(?:[^\W_]|[{_MARKS}])+", re.UNICODE)
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z]{2,})|(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")
EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")
STOP = {"a", "an", "and", "the", "of", "for", "to", "in", "on", "by", "with", "at", "is", "or", "from", "ka", "ki",
        "ke", "se", "me", "aur", "का", "की", "के", "में", "से", "और"}

MAX_CAPTION_WORDS = 60
MAX_KEYWORDS_CHARS = 2000


def words(text: Optional[str]) -> list[str]:
    return WORD_RE.findall(text or "")


def fold(s: str) -> str:
    """Lowercase and strip Latin diacritics (keeps Indic marks)."""
    s = s.lower()
    if s.isascii():
        return s
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.category(ch) == "Mn" and ord(ch) < 0x0900:
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def split_compound(w: str) -> list[str]:
    parts = [p for p in CAMEL_RE.split(w) if p]
    return parts if len(parts) > 1 else [w]


def strip_ext(name: Optional[str]) -> str:
    return EXT_RE.sub("", name or "")


# ------------------------------------------------------------ transliteration
try:
    from indic_transliteration import sanscript as _sanscript
except Exception:  # optional dependency
    _sanscript = None


@lru_cache(maxsize=50_000)
def translit(word: str) -> tuple[str, ...]:
    """Latin spellings for a Devanagari word: [full, without final schwa]."""
    if not _sanscript or not DEVANAGARI_RE.search(word):
        return ()
    try:
        latin = _sanscript.transliterate(word, _sanscript.DEVANAGARI, _sanscript.HK)
    except Exception:
        return ()
    latin = re.sub(r"[^a-z0-9]", "", latin.lower())
    if len(latin) < 2:
        return ()
    out = [latin]
    if len(latin) > 3 and latin.endswith("a") and latin[-2] not in "aeiou":
        out.append(latin[:-1])
    return tuple(out)


def acronyms(ws: list[str]) -> set[str]:
    """Initials of runs of 3–5 alphabetic words, with and without stop words."""
    out: set[str] = set()
    alpha = [w for w in ws if w.isalpha() and len(w) > 1]
    for seq in (alpha, [w for w in alpha if w.lower() not in STOP]):
        for n in range(3, 6):
            for i in range(0, len(seq) - n + 1):
                out.add("".join(w[0] for w in seq[i:i + n]).lower())
    return out


def keywords(name: Optional[str], caption: Optional[str] = None, alias: Optional[str] = None) -> str:
    """Hidden search keywords for a file (see module docstring)."""
    out: dict[str, None] = {}

    def add(w: str) -> None:
        w = fold(w)
        if 1 < len(w) <= 40:
            out[w] = None

    for text, is_name in ((strip_ext(name), True), (strip_ext(alias), True), (caption, False)):
        if not text:
            continue
        ws = words(text)
        if not is_name:
            ws = ws[:MAX_CAPTION_WORDS]
        pieces: list[str] = []
        for w in ws:
            parts = split_compound(w)
            if len(parts) > 1:
                for p in parts:
                    add(p)
            pieces.extend(parts)
            for t in translit(w):
                add(t)
        for a, b in zip(pieces, pieces[1:]):
            if not (a.isdigit() and b.isdigit()) and a.lower() not in STOP and b.lower() not in STOP:
                add(a + b)
        if is_name:
            for ac in acronyms(pieces):
                add(ac)
    s = " ".join(out)
    return s[:MAX_KEYWORDS_CHARS]


# ------------------------------------------------------------------- queries
def query_words(text: str) -> list[str]:
    return [fold(w) for w in words(text)]


def joined_variants(ws: list[str]) -> list[str]:
    """'test series 2024' → ['testseries', 'series2024', 'testseries2024']."""
    out = []
    if 2 <= len(ws) <= 4:
        for a, b in zip(ws, ws[1:]):
            out.append(a + b)
        if len(ws) > 2:
            out.append("".join(ws))
    return [w for w in dict.fromkeys(out) if len(w) <= 40]


def compound_split(w: str) -> list[str]:
    """Query-side split of a typed compound ('TestSeries', 'part1')."""
    parts = [fold(p) for p in split_compound(w)]
    return parts if len(parts) > 1 else []


def vocab_splits(w: str, freq: dict[str, int], min_part: int = 3, min_freq: int = 2) -> list[tuple[str, str]]:
    """'testseries' → [('test','series')] when both halves are known words."""
    out = []
    if len(w) < 2 * min_part or not freq:
        return out
    for i in range(min_part, len(w) - min_part + 1):
        a, b = w[:i], w[i:]
        if freq.get(a, 0) >= min_freq and freq.get(b, 0) >= min_freq:
            out.append((a, b))
    out.sort(key=lambda p: -(min(freq.get(p[0], 0), freq.get(p[1], 0))))
    return out[:2]


def query_acronym(ws: list[str]) -> Optional[str]:
    alpha = [w for w in ws if w.isalpha() and w not in STOP]
    if 3 <= len(alpha) <= 6:
        return "".join(w[0] for w in alpha)
    return None


def translit_query(ws: Iterable[str]) -> list[str]:
    out = []
    for w in ws:
        out.extend(translit(w))
    return out


# -------------------------------------------------------------- synonyms
# Built-in groups (lower-case). Users add their own in Settings → Search.
BUILTIN_SYNONYMS = """
pyq, previous year questions, previous year papers, pyqs
ca, current affairs, करंट अफेयर्स
ts, test series, टेस्ट सीरीज
gs, general studies, सामान्य अध्ययन
polity, राजव्यवस्था, constitution, संविधान
economy, economics, अर्थव्यवस्था
history, इतिहास
geography, भूगोल
environment, पर्यावरण, ecology
science, विज्ञान
notes, नोट्स
magazine, मैगज़ीन, monthly compilation
question paper, प्रश्न पत्र
answer writing, उत्तर लेखन
prelims, प्रारंभिक परीक्षा, preliminary
mains, मुख्य परीक्षा
ncert, एनसीईआरटी
upsc, cse, civil services, ias
maths, math, mathematics, गणित
english, अंग्रेजी
hindi, हिंदी
photo, picture, image, pic
video, movie, clip
song, music, track, audio
book, ebook, pdf book
"""


def parse_synonyms(text: str) -> dict[str, list[list[str]]]:
    """Map each word-sequence (joined by space) to the other members of its group, tokenised."""
    groups: dict[str, list[list[str]]] = {}
    for line in (text or "").splitlines():
        members = [query_words(m) for m in line.split(",")]
        members = [m for m in members if m]
        if len(members) < 2:
            continue
        for m in members:
            key = " ".join(m)
            others = groups.setdefault(key, [])
            for o in members:
                if o != m and o not in others:
                    others.append(o)
    return groups


def synonym_expansions(ws: list[str], groups: dict[str, list[list[str]]]) -> list[tuple[int, int, list[list[str]]]]:
    """Find synonym-group matches inside the query: [(start, end, alternatives)]."""
    out = []
    i = 0
    while i < len(ws):
        hit = None
        for j in range(min(len(ws), i + 4), i, -1):
            key = " ".join(ws[i:j])
            if key in groups:
                hit = (i, j, groups[key])
                break
        if hit:
            out.append(hit)
            i = hit[1]
        else:
            i += 1
    return out


_LINK_RE = re.compile(r"(?:https?://|www\.|t\.me/)\S+|@\w{3,}", re.I)
_GENERIC_NAME_RE = re.compile(r"(photo|video|voice|round|gif|audio|document|file|IMG|VID|PXL|DSC|WA|Screenshot|Scan|"
                              r"animation|Screen Recording|Recording)[\s_\-]*[\dA-Z_\-\s:.()]*", re.I)


def embed_parts(name: Optional[str], caption: Optional[str], alias: Optional[str] = None) -> tuple[str, str]:
    """(name text, caption text) for the meaning-based index. Camera / auto-generated names and
    links or @handles in captions carry no meaning and are left out."""
    n = strip_ext(alias or name)
    if _GENERIC_NAME_RE.fullmatch(n or ""):
        n = ""
    ws: list[str] = []
    for w in words(n):
        ws.extend(split_compound(w))
    cap = " ".join(words(_LINK_RE.sub(" ", caption or ""))[:48])
    return " ".join(ws).strip(), cap.strip()


def embed_text(name: Optional[str], caption: Optional[str], alias: Optional[str] = None) -> str:
    """Text used for the meaning-based index; empty for generic camera names without captions."""
    n = strip_ext(alias or name)
    if re.fullmatch(r"(photo|video|voice|round|gif|audio|document|IMG|VID|Screenshot|Scan|animation)"
                    r"[\s_\-]*[\d_\-\s:.]*", n or "", re.I):
        n = ""
    ws = []
    for w in words(n):
        ws.extend(split_compound(w))
    text = " ".join(ws)
    if caption:
        text = f"{text}. {' '.join(words(caption)[:48])}" if text else " ".join(words(caption)[:48])
    return text.strip()
