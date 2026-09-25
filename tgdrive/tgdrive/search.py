"""Smart search.

A text query is answered in layers ("tiers"), so wording differences don't hide files:

  0  exact     every word matches (any order, word prefixes, word endings via stemming;
               compound forms meet through hidden keywords: TestSeries ↔ test series)
  1  variant   joined/split forms (test series ↔ testseries), text inside words
               (series ↔ MockTestSeries2024), acronyms (pyq ↔ previous year questions),
               Hindi ↔ Latin script, built-in and user synonyms
  2  similar   likely typos corrected against the index vocabulary (seires → series),
               and files that match all but one of 3+ words
  3  related   meaning-based neighbours from the offline embedding model

Candidates are materialised per query into a TEMP table on a reader connection
(cached briefly, so paging and counts reuse it); filters, sorting and paging
then run as ordinary SQL. Everything runs on reader threads, never on the
event loop, and a newer search from the same client interrupts the older one.
"""
import asyncio
import base64
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import query, textproc
from .db import Reader

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.search")

try:
    import snowballstemmer
    _STEM = snowballstemmer.stemmer("porter")
except Exception:  # pragma: no cover
    _STEM = None

try:
    from rapidfuzz import distance as _rf_distance, process as _rf_process
except Exception:  # pragma: no cover
    _rf_process = None

WEIGHTS = "10.0, 12.0, 2.0, 1.2, 1.0, 5.0"  # name, alias, caption, chat_title, sender_name, keywords
OLD_WEIGHTS = "10.0, 12.0, 2.0, 1.2, 1.0"
TIER_NAMES = {0: "exact", 1: "variant", 2: "similar", 3: "related"}
CAND_TTL = 45.0
PAGE_MAX = 500


def stem(w: str) -> str:
    return _STEM.stemWord(w) if _STEM and w.isascii() else w


def fts_term(w: str, prefix: bool = True) -> str:
    w = w.replace('"', '""')
    return f'"{w}"*' if prefix and len(w) >= 2 else f'"{w}"'


def fts_and(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else "(" + " AND ".join(parts) + ")"


def fts_or(parts: list[str]) -> str:
    parts = list(dict.fromkeys(p for p in parts if p))
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


# ------------------------------------------------------------------ vocabulary
class Vocab:
    """Stemmed terms of the index with document frequencies (for typo fixes and splits)."""

    REFRESH = 20 * 60

    def __init__(self):
        self.terms: list[str] = []
        self.freq: dict[str, int] = {}
        self.built = 0.0
        self.building = False
        self.lock = threading.Lock()

    def stale(self) -> bool:
        return not self.building and time.time() - self.built > self.REFRESH

    def build(self, reader: Reader) -> None:
        with self.lock:
            if self.building:
                return
            self.building = True
        try:
            c = reader.conn
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.vocab_row USING fts5vocab(main, search_fts, row)")
            rows = c.execute("SELECT term, doc FROM temp.vocab_row WHERE doc >= 2 AND length(term) BETWEEN 2 AND 30"
                             ).fetchall()
            freq = {t: d for t, d in rows if not t.isdigit()}
            terms = [t for t in freq if len(t) >= 3]
            self.freq, self.terms, self.built = freq, terms, time.time()
            log.info("search vocabulary: %d terms", len(terms))
        finally:
            self.building = False

    def corrections(self, word: str, limit: int = 3) -> list[str]:
        """Likely intended spellings (stems) for a word that is rare or absent in the index."""
        if not _rf_process or not self.terms or len(word) < 4 or word.isdigit() or not word.isascii():
            return []
        s = stem(word)
        own = self.freq.get(s, 0)
        max_d = 1 if len(s) <= 5 else 2
        cands = _rf_process.extract(s, self.terms, scorer=_rf_distance.DamerauLevenshtein.distance,
                                    score_cutoff=max_d, limit=40)
        best = []
        for term, dist, _ in cands:
            if term == s or term.startswith(s) or s.startswith(term):
                continue
            f = self.freq.get(term, 0)
            # Typed word unknown → any known neighbour; otherwise it must be far more common than what was typed.
            if (own == 0 and f >= 1) or (own > 0 and f >= max(3, own * 20)):
                best.append((dist, -f, term))
        best.sort()
        return [t for _, _, t in best[:limit]]

    def splits(self, word: str) -> list[tuple[str, str]]:
        if len(word) < 6 or not word.isascii() or not self.freq:
            return []
        out = []
        for i in range(3, len(word) - 2):
            a, b = word[:i], word[i:]
            fa, fb = self.freq.get(stem(a), 0), self.freq.get(stem(b), 0)
            if fa >= 3 and fb >= 3:
                out.append((min(fa, fb), a, b))
        out.sort(reverse=True)
        return [(a, b) for _, a, b in out[:2]]


# ------------------------------------------------------------------- planning
@dataclass
class TextPlan:
    words: list[str]
    steps: list[tuple[int, str, str, bool]] = field(default_factory=list)  # (tier, table, expr, ranked)
    neg: str = ""
    semantic: str = ""
    corrected: Optional[str] = None
    signature: str = ""
    exact_only: bool = False


class SearchEngine:
    def __init__(self, account: "Account"):
        self.acc = account
        self.vocab = Vocab()
        self._syn_src: Optional[str] = None
        self._syn: dict = {}
        self._sem_cache: dict[str, tuple[float, list]] = {}
        self._vocab_future = None

    @property
    def db(self):
        return self.acc.db

    # ---------------------------------------------------------- settings
    def synonyms(self) -> dict:
        from .settings import settings
        src = textproc.BUILTIN_SYNONYMS if settings.get("search_builtin_synonyms", True) else ""
        src += "\n" + (settings.get("search_synonyms") or "")
        if src != self._syn_src:
            self._syn_src, self._syn = src, textproc.parse_synonyms(src)
        return self._syn

    def mode(self, f: dict) -> str:
        from .settings import settings
        return f.get("match") or settings.get("search_mode", "smart")

    def semantic_enabled(self) -> bool:
        from .settings import settings
        sem = getattr(self.acc, "semantic", None)
        return bool(sem and settings.get("search_semantic", True) and sem.enabled)

    # ------------------------------------------------------------- plan
    def plan(self, f: dict) -> Optional[TextPlan]:
        raw_terms = list(f["terms"])
        phrases = [p for p in f["phrases"] if textproc.words(p)]
        if not raw_terms and not phrases:
            return None
        ready = self.db.search_ready
        table = "search_fts" if ready else "files_fts"
        ws: list[str] = []
        camel: dict[str, list[str]] = {}
        for t in raw_terms:
            for w_raw in textproc.words(t):
                parts = textproc.compound_split(w_raw)
                if parts:
                    camel[textproc.fold(w_raw)] = parts
            ws.extend(textproc.query_words(t))
        phrase_exprs = ['"' + " ".join(textproc.query_words(p)).replace('"', '""') + '"' for p in phrases]
        plan = TextPlan(words=ws, exact_only=self.mode(f) == "exact" or not ready)

        def term(w: str) -> str:
            return fts_term(w, prefix=len(w) >= 2)

        exact = fts_and([term(w) for w in ws] + phrase_exprs)
        if exact:
            if plan.exact_only and ready:  # only the visible text, not the hidden keyword forms
                plan.steps.append((0, table, "{name alias caption chat_title sender_name}: " + exact, True))
            else:
                plan.steps.append((0, table, exact, True))

        if not plan.exact_only and ws:
            syn = self.synonyms()
            spans = {s: (e, alts) for s, e, alts in textproc.synonym_expansions(ws, syn)}
            groups: list[str] = []
            i = 0
            while i < len(ws):
                alts: list[str] = []
                if i in spans:
                    end, syn_alts = spans[i]
                    alts.append(fts_and([fts_or([term(w)] + [term(t) for t in textproc.translit(w)])
                                         for w in ws[i:end]]))
                    for a in syn_alts:  # short alternates ("ts", "ca") only as whole words
                        alts.append(fts_and([fts_term(w, prefix=len(w) >= 4) for w in a]))
                    i_next = end
                else:
                    w = ws[i]
                    alts.append(term(w))
                    for t in textproc.translit(w):
                        alts.append(term(t))
                    parts = camel.get(w)
                    if parts:
                        alts.append(fts_and([term(p) for p in parts]))
                    for a, b in self.vocab.splits(w):
                        alts.append(fts_and([term(a), term(b)]))
                    i_next = i + 1
                groups.append(fts_or(alts))
                i = i_next
            variant_parts = [fts_and(groups + phrase_exprs)]
            for j in textproc.joined_variants(ws):
                variant_parts.append(term(j))
            ac = textproc.query_acronym(ws)
            if ac:
                variant_parts.append(fts_term(ac, prefix=False))
            variants = fts_or(variant_parts)
            if variants and variants != exact:
                plan.steps.append((1, table, variants, True))
            # Text inside words (names only), for words of 3+ characters.
            subs = [w for w in ws if len(w) >= 3]
            tri_parts = []
            if subs:
                tri_parts.append(fts_and(['"' + w.replace('"', '""') + '"' for w in subs]))
            for j in textproc.joined_variants(ws):
                tri_parts.append('"' + j.replace('"', '""') + '"')
            tri = fts_or(tri_parts)
            if tri:
                plan.steps.append((1, "names_tri", tri, False))
            # Typos.
            fixed_groups, corrected_words, any_fix = [], [], False
            for w in ws:
                fixes = self.vocab.corrections(w)
                if fixes:
                    any_fix = True
                    corrected_words.append(fixes[0])
                    fixed_groups.append(fts_or([term(w)] + [fts_term(x) for x in fixes]))
                else:
                    corrected_words.append(w)
                    fixed_groups.append(term(w))
            if any_fix:
                plan.steps.append((2, table, fts_and(fixed_groups + phrase_exprs), True))
                plan.corrected = " ".join(corrected_words)
            # All-but-one of 3+ words.
            if len(ws) >= 3:
                partial = fts_or([fts_and([term(x) for k, x in enumerate(ws) if k != skip]) for skip in range(len(ws))])
                plan.steps.append((2, table, partial, True))
            if self.semantic_enabled():
                plan.semantic = " ".join(raw_terms + phrases)

        neg = []
        for t in f["neg_terms"]:
            neg.extend(term(w) for w in textproc.query_words(t))
        plan.neg = fts_or(neg)
        plan.signature = hashlib.sha1(json.dumps([plan.steps, plan.neg, plan.semantic, ready]).encode()).hexdigest()
        return plan

    # ------------------------------------------------------------ public
    def warm_up(self) -> None:
        """Build the vocabulary right after start instead of on the first search."""
        if self.db.search_ready and not self.vocab.built and (self._vocab_future is None or self._vocab_future.done()):
            self.vocab.building = False
            self._vocab_future = self.db.read.submit(self.vocab.build, timeout=120)
            self._vocab_future.add_done_callback(
                lambda fu: fu.exception() and log.warning("vocab build: %s", fu.exception()))

    async def _ensure_vocab(self) -> None:
        """The first text search waits for the vocabulary (a fraction of a second) instead of missing splits."""
        if self.vocab.built or not self.db.search_ready:
            return
        if self._vocab_future is None or self._vocab_future.done() and not self.vocab.built:
            self.vocab.building = False
            self._vocab_future = self.db.read.submit(self.vocab.build, timeout=120)
        try:
            await asyncio.wait_for(asyncio.wrap_future(self._vocab_future), 5)
        except Exception as exc:
            log.warning("vocabulary not ready: %s", exc)

    async def _parse(self, p: dict) -> tuple[dict, Optional[TextPlan]]:
        f = query.from_params(p)
        if query.has_text(f):
            await self._ensure_vocab()
        return f, self.plan(f)

    def _where(self, f: dict) -> tuple[str, list]:
        return query.build_where(f, descendants=self.acc.drive._descendants)

    async def files(self, p: dict, slot: Optional[str] = None) -> dict:
        t0 = time.perf_counter()
        f, plan = await self._parse(p)
        where, params = self._where(f)
        sort = p.get("sort") or ("relevance" if plan else "date")
        if sort == "relevance" and not plan:
            sort = "date"
        order = "ASC" if p.get("order") == "asc" else "DESC"
        limit = max(1, min(int(p.get("limit") or 120), PAGE_MAX))
        cursor = p.get("cursor") or None
        sem_ids = await self._semantic_ids(plan, f, where, params) if plan and plan.semantic else None
        self._maybe_refresh_vocab()
        self._scope_signature(plan, where, params)
        res = await self.db.read.run(self._page_job, plan, sem_ids, where, params, sort, order, limit, cursor,
                                     key=plan.signature if plan else None, slot=slot, timeout=25)
        res["took_ms"] = round((time.perf_counter() - t0) * 1000)
        res["sort"] = sort
        if plan and plan.corrected and plan.corrected != " ".join(plan.words):
            res["corrected"] = await self.readable(
                [c if c != w else None for c, w in zip(plan.corrected.split(" "), plan.words)], plan.words)
        if plan:
            res["words"] = plan.words
        return res

    async def stats(self, p: dict, slot: Optional[str] = None) -> dict:
        f, plan = await self._parse(p)
        if not plan:
            scope = query.only_scope_filters(f)
            if scope is not None:
                chat_ids, kinds = scope
                return self._stats_from_table(chat_ids, kinds)
        where, params = self._where(f)
        kwhere, kparams = query.build_where(f, skip_kinds=True, descendants=self.acc.drive._descendants)
        sem_ids = await self._semantic_ids(plan, f, where, params) if plan and plan.semantic else None
        self._scope_signature(plan, where, params)
        return await self.db.read.run(self._stats_job, plan, sem_ids, where, params, kwhere, kparams,
                                      key=plan.signature if plan else None, slot=slot, timeout=40)

    def _stats_from_table(self, chat_ids: Optional[list[int]], kinds: set) -> dict:
        if chat_ids:
            marks = ",".join("?" * len(chat_ids))
            rows = self.db.q(f"SELECT kind, SUM(n) AS n, SUM(bytes) AS bytes FROM stats WHERE chat_id IN ({marks}) "
                             f"GROUP BY kind", chat_ids)
        else:
            rows = self.db.q("SELECT kind, SUM(n) AS n, SUM(bytes) AS bytes FROM stats GROUP BY kind")
        kc = {r["kind"]: r["n"] for r in rows if r["n"]}
        sel = [r for r in rows if not kinds or r["kind"] in kinds]
        return {"total": sum(r["n"] or 0 for r in sel), "total_bytes": sum(r["bytes"] or 0 for r in sel),
                "kind_counts": kc, "tiers": {}, "exact": True}

    @staticmethod
    def _scope_signature(plan: Optional[TextPlan], where: str, params: list) -> None:
        """Related results depend on the filters, so their candidate cache must too."""
        if plan and plan.semantic and not plan.signature.endswith("+scoped"):
            plan.signature = hashlib.sha1((plan.signature + where + json.dumps(params, default=str)).encode()
                                          ).hexdigest() + "+scoped"

    async def _semantic_ids(self, plan: TextPlan, f: dict, where: str, params: list):
        key = hashlib.sha1((plan.semantic + where + json.dumps(params, default=str)).encode()).hexdigest()
        hit = self._sem_cache.get(key)
        if hit and time.time() - hit[0] < CAND_TTL:
            return hit[1]
        res = await self._semantic_ids_uncached(plan, where, params)
        self._sem_cache[key] = (time.time(), res)
        if len(self._sem_cache) > 32:
            self._sem_cache.pop(next(iter(self._sem_cache)))
        return res

    async def _semantic_ids_uncached(self, plan: TextPlan, where: str, params: list):
        sem = self.acc.semantic
        allowed = None
        if where != "1":
            ids = await self.db.read.run(
                lambda r: np.fromiter((row[0] for row in r.conn.execute(
                    f"SELECT f.id FROM files f WHERE {where} LIMIT 400000", params)), dtype=np.int64),
                timeout=10)
            if not len(ids):
                return []
            allowed = ids
        return await asyncio.get_running_loop().run_in_executor(None, lambda: sem.search(plan.semantic,
                                                                                        allowed=allowed))

    def _maybe_refresh_vocab(self) -> None:
        if self.db.search_ready and self.vocab.stale():
            self.vocab.building = False
            fut = self.db.read.submit(self.vocab.build, timeout=120)
            fut.add_done_callback(lambda fu: fu.exception() and log.warning("vocab build: %s", fu.exception()))

    # --------------------------------------------------------- reader jobs
    def _ensure_cand(self, r: Reader, plan: TextPlan, sem_ids) -> dict:
        cache = r.cache
        if cache.get("sig") == plan.signature and time.time() - cache.get("at", 0) < CAND_TTL:
            return cache["info"]
        c = r.conn
        c.execute("CREATE TEMP TABLE IF NOT EXISTS cand(id INTEGER PRIMARY KEY, tier INTEGER, score REAL)")
        c.execute("CREATE INDEX IF NOT EXISTS temp.cand_rank ON cand(tier, score, id)")
        c.execute("DELETE FROM cand")
        cache["sig"] = None
        for tier, table, expr, ranked in plan.steps:
            if table == "names_tri":
                sql = f"INSERT OR IGNORE INTO cand(id, tier, score) SELECT rowid, {tier}, 0 FROM names_tri " \
                      f"WHERE names_tri MATCH ?"
            else:
                weights = WEIGHTS if table == "search_fts" else OLD_WEIGHTS
                score = f"bm25({table}, {weights})" if ranked else "0"
                sql = f"INSERT OR IGNORE INTO cand(id, tier, score) SELECT rowid, {tier}, {score} FROM {table} " \
                      f"WHERE {table} MATCH ?"
            try:
                c.execute(sql, (expr,))
            except Exception as exc:
                if "interrupt" in str(exc):
                    raise
                log.warning("search step %s failed (%s): %s", tier, exc, expr[:200])
        if sem_ids:
            c.executemany("INSERT OR IGNORE INTO cand(id, tier, score) VALUES(?, 3, ?)",
                          [(i, -s) for i, s in sem_ids])
        if plan.neg:
            table = plan.steps[0][1] if plan.steps else "search_fts"
            try:
                c.execute(f"DELETE FROM cand WHERE id IN (SELECT rowid FROM {table} WHERE {table} MATCH ?)",
                          (plan.neg,))
            except Exception as exc:
                if "interrupt" in str(exc):
                    raise
        info = {"n": c.execute("SELECT COUNT(*) FROM cand").fetchone()[0]}
        cache.update(sig=plan.signature, at=time.time(), info=info)
        return info

    def _page_job(self, r: Reader, plan: Optional[TextPlan], sem_ids, where: str, params: list, sort: str,
                  order: str, limit: int, cursor: Optional[str]) -> dict:
        c = r.conn
        cur = _decode_cursor(cursor)
        use_keyset = sort in ("date", "size", "name")
        key = {"date": "f.date", "size": "f.size", "name": "COALESCE(f.alias, f.name) COLLATE NOCASE"}.get(sort) \
            or query.SORTS.get(sort, "f.date")
        cmp = "<" if order == "DESC" else ">"
        extra, extra_params = "", []
        offset = 0
        if cur is not None:
            if use_keyset and isinstance(cur, list):
                extra = f" AND ({key}, f.id) {cmp} (?, ?)"
                extra_params = list(cur)
            elif isinstance(cur, int):
                offset = cur
        if plan:
            self._ensure_cand(r, plan, sem_ids)
            if sort == "relevance":
                order_sql = "cand.tier, cand.score, cand.id"
                use_keyset = False
                tier_filter = ""
            else:
                order_sql = f"{key} {order}, f.id {order}"
                tier_filter = " AND cand.tier < 3"
            sql = (f"SELECT f.id, cand.tier AS tier, {key} AS k FROM cand JOIN files f ON f.id=cand.id "
                   f"WHERE {where}{tier_filter}{extra} ORDER BY {order_sql} LIMIT ? OFFSET ?")
        else:
            order_sql = f"{key} {order}, f.id {order}"
            sql = f"SELECT f.id, 0 AS tier, {key} AS k FROM files f WHERE {where}{extra} ORDER BY {order_sql} " \
                  f"LIMIT ? OFFSET ?"
        rows = c.execute(sql, [*params, *extra_params, limit + 1, offset]).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        ids = [row[0] for row in rows]
        tiers = {row[0]: row[1] for row in rows}
        items = []
        if ids:
            marks = ",".join("?" * len(ids))
            full = {row["id"]: dict(row) for row in c.execute(
                "SELECT f.*, p.folder_id, p.starred, p.tags, p.note, c.kind AS chat_kind, c.username AS chat_username, "
                "pb.pos AS play_pos, pb.dur AS play_dur, pb.done AS play_done, "
                "(SELECT s.subject FROM file_subjects s WHERE s.file_id=f.id) AS subject "
                "FROM files f LEFT JOIN placements p ON p.chat_id=f.chat_id AND p.msg_id=f.msg_id "
                "LEFT JOIN chats c ON c.id=f.chat_id "
                f"LEFT JOIN playback pb ON pb.chat_id=f.chat_id AND pb.msg_id=f.msg_id WHERE f.id IN ({marks})", ids)}
            for i in ids:
                if i in full:
                    row = full[i]
                    row["match"] = TIER_NAMES.get(tiers.get(i, 0), "exact") if plan else None
                    items.append(row)
        next_cursor = None
        if more and rows:
            last = rows[-1]
            next_cursor = _encode_cursor([last[2], last[0]] if use_keyset else offset + limit)
        return {"items": items, "next": next_cursor, "limit": limit}

    def _stats_job(self, r: Reader, plan: Optional[TextPlan], sem_ids, where: str, params: list, kwhere: str,
                   kparams: list) -> dict:
        c = r.conn
        if plan:
            self._ensure_cand(r, plan, sem_ids)
            src = "cand JOIN files f ON f.id=cand.id"
            grouped = c.execute(f"SELECT cand.tier, f.kind, COUNT(*), COALESCE(SUM(f.size),0) FROM {src} "
                                f"WHERE {where} GROUP BY cand.tier, f.kind", params).fetchall()
            tiers: dict[str, int] = {}
            for tier, _, n, _ in grouped:
                tiers[TIER_NAMES[tier]] = tiers.get(TIER_NAMES[tier], 0) + n
            tot = (sum(g[2] for g in grouped), sum(g[3] for g in grouped))
            if kwhere == where:
                kc: dict[str, int] = {}
                for _, kind, n, _ in grouped:
                    kc[kind] = kc.get(kind, 0) + n
            else:
                kc = {row[0]: row[1] for row in c.execute(
                    f"SELECT f.kind, COUNT(*) FROM {src} WHERE {kwhere} GROUP BY f.kind", kparams)}
        else:
            tiers = {}
            tot = c.execute(f"SELECT COUNT(*), COALESCE(SUM(f.size),0) FROM files f WHERE {where}", params).fetchone()
            kc = {row[0]: row[1] for row in c.execute(
                f"SELECT f.kind, COUNT(*) FROM files f WHERE {kwhere} GROUP BY f.kind", kparams)}
        return {"total": tot[0], "total_bytes": tot[1], "kind_counts": kc, "tiers": tiers, "exact": True}

    # ------------------------------------------------------------ suggest
    async def suggest(self, q: str) -> dict:
        q = (q or "").strip()
        await self._ensure_vocab()
        self._maybe_refresh_vocab()
        f = query.parse(q) if q else query.empty_filters()
        ws = []
        for t in f["terms"]:
            ws.extend(textproc.query_words(t))
        last = ws[-1] if ws else ""
        text = " ".join(ws)

        def job(r: Reader) -> dict:
            out: dict[str, Any] = {"chats": [], "folders": [], "files": [], "history": [], "saved": []}
            like = query._like(text) if text else None
            if like:
                out["chats"] = r.q("SELECT id, title, kind, file_count FROM chats WHERE (title LIKE ? ESCAPE '\\' "
                                   "OR username LIKE ? ESCAPE '\\') AND file_count > 0 ORDER BY file_count DESC LIMIT 6",
                                   (like, like))
                out["folders"] = r.q("SELECT id, name, parent_id FROM folders WHERE name LIKE ? ESCAPE '\\' "
                                     "ORDER BY name COLLATE NOCASE LIMIT 5", (like,))
                if self.db.search_ready and ws:
                    expr = "{name alias keywords}: " + fts_and([fts_term(w) for w in ws])
                    try:
                        out["files"] = r.q(
                            "SELECT f.chat_id, f.msg_id, COALESCE(f.alias, f.name) AS name, f.kind, f.ext, "
                            "f.chat_title, f.has_thumb FROM files f WHERE f.id IN (SELECT rowid FROM search_fts WHERE "
                            "search_fts MATCH ? ORDER BY rank LIMIT 6)", (expr,))
                    except Exception as exc:
                        if "interrupt" in str(exc):
                            raise
                out["history"] = r.q("SELECT q FROM search_history WHERE q LIKE ? ESCAPE '\\' ORDER BY at DESC "
                                     "LIMIT 5", (like,))
                out["saved"] = r.q("SELECT id, name, q FROM saved_searches WHERE name LIKE ? ESCAPE '\\' "
                                   "OR q LIKE ? ESCAPE '\\' LIMIT 5", (like, like))
            else:
                out["history"] = r.q("SELECT q FROM search_history ORDER BY at DESC LIMIT 8")
                out["saved"] = r.q("SELECT id, name, q FROM saved_searches ORDER BY name COLLATE NOCASE LIMIT 8")
            return out

        res = await self.db.read.run(job, slot="suggest", timeout=5)
        corrected = [(self.vocab.corrections(w, limit=1) or [None])[0] for w in ws]
        if any(corrected):
            res["did_you_mean"] = await self.readable(corrected, ws)
        res["operators"] = operator_hints(last, q)
        return res

    async def readable(self, stems: list[Optional[str]], typed: list[str]) -> str:
        """Turn corrected stems back into real words as they appear in the index ('seri' → 'series')."""
        async def surface(st: str) -> str:
            def job(r: Reader) -> str:
                counts: dict[str, int] = {}
                for name, cap in r.conn.execute(
                        "SELECT name, substr(caption, 1, 400) FROM files WHERE id IN (SELECT rowid FROM search_fts "
                        "WHERE search_fts MATCH ? LIMIT 40)", (fts_term(st, prefix=False),)):
                    for w in textproc.words(f"{name or ''} {cap or ''}"):
                        for part in [w, *textproc.split_compound(w)]:
                            lw = textproc.fold(part)
                            if stem(lw) == st:
                                counts[lw] = counts.get(lw, 0) + 1
                return max(counts, key=counts.get) if counts else st
            try:
                return await self.db.read.run(job, timeout=3)
            except Exception:
                return st
        out = []
        for st, w in zip(stems, typed):
            out.append(await surface(st) if st else w)
        return " ".join(out)


def operator_hints(last: str, q: str) -> list[dict]:
    out = []
    lw = last.lower()
    exts = {"pdf", "zip", "rar", "mp4", "mkv", "mp3", "epub", "docx", "doc", "pptx", "xlsx", "apk", "jpg", "png",
            "txt", "srt", "7z", "iso", "exe", "m4a", "flac", "opus", "webm"}
    if lw in exts:
        out.append({"insert": f"ext:{lw}", "label": f"Only .{lw} files"})
    if lw in query.KIND_WORDS:
        out.append({"insert": f"type:{query.KIND_WORDS[lw]}", "label": f"Only {query.KIND_WORDS[lw]}s"})
    if lw in ("today", "yesterday"):
        out.append({"insert": f"date:{lw}", "label": f"Sent {lw}"})
    m = re.fullmatch(r"(19|20)\d\d", lw)
    if m:
        out.append({"insert": f"date:{lw}", "label": f"Sent in {lw}"})
    if re.fullmatch(r"\d+(\.\d+)?(k|kb|m|mb|g|gb)", lw):
        out.append({"insert": f"size>{lw}", "label": f"Bigger than {lw}"})
    return out


def _encode_cursor(v) -> str:
    return base64.urlsafe_b64encode(json.dumps(v).encode()).decode()


def _decode_cursor(s: Optional[str]):
    if not s:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(s.encode()).decode())
    except Exception:
        raise query.QueryError("That page link is out of date. Reload the list.")
