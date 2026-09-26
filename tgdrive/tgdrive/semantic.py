"""Meaning-based ("related") search, fully offline.

Uses the small static embedding model bundled in the `wordllama` package (256-dimensional
token embeddings). Each file becomes one vector, stored on disk as int8 plus a per-row scale,
indexed by the file's row id. A 1-bit copy (32 bytes per file) stays in memory for a fast
Hamming pre-filter; the best few thousand candidates are then rescored exactly.

How a vector is made (version 2):
  * Token weights from this library itself (smoothed IDF over every file's name and caption),
    so words on every other file — "pdf", "notes", "join @channel", "#upsc", file-name years —
    count for little and the words that tell files apart count for a lot. Common English and
    Hindi function words are damped from the start, which helps while a library is still small.
  * The name counts twice as much as the caption (captions are often channel boilerplate).
  * The library's average vector is subtracted ("centering"). Averaged word vectors all lean
    the same way, which squeezes every similarity into a narrow band and makes the sign bits
    of the fast pre-filter nearly useless; centering spreads them out again. It is phased in
    as the library grows, since the average of a handful of files says little.
  * Queries go through the same steps, and can carry extra phrasings (synonyms, the
    spelling-corrected query, transliterations) that are blended in at a lower weight.

The statistics are rebuilt (and every vector with them) when the library has grown by about
a third, so they keep describing it; that takes seconds even for hundreds of thousands of files.

437k files: ~15 s to build, ~115 MB on disk, ~14 MB in memory, ~40 ms per query.
"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from . import pace
from . import textproc

log = logging.getLogger("tgdrive.semantic")

DIM = 256
GROW = 65_536
BATCH = 4000


class _Stopped(Exception):
    """TG Drive is quitting: leave the current job (it starts over next time)."""
VERSION = 2
PREFILTER = 6000       # candidates kept by the Hamming pre-filter before exact scoring
MIN_SIM = 0.30         # absolute floor (centered cosine); 0.25 for small libraries, where junk is rare anyway
REL_SIM = 0.50         # and at least half as close as the best match
NAME_WEIGHT = 2.0      # name vs caption
EXTRA_WEIGHT = 0.6     # alternate phrasings of the query vs the query itself
CENTER_FULL_AT = 3000  # files; centering is phased in up to this size
REBUILD_GROWTH = 1.33  # rebuild statistics when the library grew by a third
RESTAT_MIN_GAP = 15 * 60  # … but at most every 15 minutes
STATS_SAMPLE = 40_000  # files embedded to estimate the library's average vector

# Damped from the start (the library's own statistics take over as it grows).
FUNCTION_WORDS = (
    "a an and the of for to in on by with at is are was were be or from as it its this that these those "
    "into about over under after before between up down out not no yes you your our we they he she his her "
    "their them my me i do does did can will just new final copy part vol file files pdf doc docx pptx zip "
    "rar mp4 mkv mp3 jpg jpeg png ka ki ke se me mein aur hai hain ko bhi "
    "का की के में से और है हैं को भी पर एक यह वह"
).split()
FUNCTION_DAMP = 0.3


class _Model:
    _lock = threading.Lock()
    _inst: Optional["_Model"] = None
    error: Optional[str] = None

    TOKENIZER = "l2_supercat_tokenizer_config.json"
    WEIGHTS = "l2_supercat_256.safetensors"

    @classmethod
    def locate(cls) -> tuple[Path, Path]:
        """The model files: bundled with the app, or from an installed `wordllama` package
        (found without importing it — its __init__ pulls in heavy optional dependencies)."""
        import importlib.util
        import os
        from . import config
        roots = [Path(p) for p in (os.environ.get("TGDRIVE_MODEL_DIR"),) if p]
        roots.append(config.ROOT / "models" / "wordllama")
        try:
            spec = importlib.util.find_spec("wordllama")
            if spec and spec.submodule_search_locations:
                roots.extend(Path(p) for p in spec.submodule_search_locations)
        except (ImportError, ValueError):
            pass
        for root in roots:
            for tok, w in ((root / cls.TOKENIZER, root / cls.WEIGHTS),
                           (root / "tokenizers" / cls.TOKENIZER, root / "weights" / cls.WEIGHTS)):
                if tok.exists() and w.exists():
                    return tok, w
        raise FileNotFoundError("embedding model files not found (install the 'wordllama' package)")

    def __init__(self):
        from safetensors import safe_open
        from tokenizers import Tokenizer
        tok_path, w_path = self.locate()
        self.tok = Tokenizer.from_file(str(tok_path))
        self.tok.enable_truncation(max_length=96)
        self.tok.no_padding()
        with safe_open(str(w_path), framework="np") as f:
            self.emb = f.get_tensor("embedding.weight").astype(np.float32)
        self.vocab = self.emb.shape[0]
        prior = np.ones(self.vocab, dtype=np.float32)
        for enc in self.tok.encode_batch(FUNCTION_WORDS + [w.capitalize() for w in FUNCTION_WORDS if w.isascii()],
                                         add_special_tokens=False):
            ids = [t for t in enc.ids if 0 <= t < self.vocab]
            if len(ids) == 1:  # only whole-word tokens; pieces of longer words stay untouched
                prior[ids[0]] = FUNCTION_DAMP
        self.prior = prior

    @classmethod
    def get(cls) -> Optional["_Model"]:
        with cls._lock:
            if cls._inst is None and cls.error is None:
                try:
                    cls._inst = cls()
                except Exception as exc:  # optional feature
                    cls.error = f"{exc.__class__.__name__}: {exc}"
                    log.warning("meaning-based search unavailable: %s", cls.error)
            return cls._inst

    def ids(self, texts: Sequence[str]) -> list[np.ndarray]:
        encs = self.tok.encode_batch([t or "" for t in texts], add_special_tokens=False)
        out = []
        for t, enc in zip(texts, encs):
            a = np.asarray(enc.ids, dtype=np.int64) if t else np.zeros(0, dtype=np.int64)
            out.append(a[(a >= 0) & (a < self.vocab)])
        return out

    def pool(self, ids: Sequence[np.ndarray], weights: Optional[np.ndarray] = None) -> np.ndarray:
        """Weighted average of token vectors, one unit vector per text (zeros for empty text)."""
        out = np.zeros((len(ids), DIM), dtype=np.float32)
        w_all = weights if weights is not None else self.prior
        emb = self.emb
        for i, a in enumerate(ids):   # a plain loop beats every vectorised variant here (short texts)
            if len(a):
                out[i] = w_all[a] @ emb[a]
        return _unit(out)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Plain (library-independent) vectors; kept for callers that compare raw texts to each other."""
        return self.pool(self.ids(texts))


def available() -> bool:
    return _Model.get() is not None


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    n[n == 0] = 1
    return m / n


class SemanticIndex:
    def __init__(self, directory: Path, db_path: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.meta_path = self.dir / "meta.json"
        self.vec_path = self.dir / "vectors.i8"
        self.scale_path = self.dir / "vectors.scale"
        self.bits_path = self.dir / "vectors.bits"
        self.stats_path = self.dir / "stats.npz"
        self.lock = threading.RLock()
        self.meta = {"built_until": 0, "capacity": 0, "count": 0, "version": VERSION}
        if self.meta_path.exists():
            try:
                self.meta.update(json.loads(self.meta_path.read_text()))
            except Exception:
                pass
        if int(self.meta.get("version") or 1) != VERSION:
            log.info("meaning index: new format (v%s → v%s), rebuilding", self.meta.get("version"), VERSION)
            self.meta.update(built_until=0, count=0, version=VERSION, stats_n=0)
        self.vec: Optional[np.memmap] = None
        self.scale: Optional[np.memmap] = None
        self.bits: Optional[np.ndarray] = None
        self.weights: Optional[np.ndarray] = None   # per-token weight from this library
        self.center: Optional[np.ndarray] = None    # library mean vector (already scaled by its strength)
        self.enabled = True
        self.state = "idle"
        self.error: Optional[str] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dirty: set[int] = set()
        self._open()
        self._load_stats()

    # --------------------------------------------------------------- storage
    def _open(self) -> None:
        cap = int(self.meta.get("capacity") or 0)
        if cap and self.vec_path.exists():
            self.vec = np.memmap(self.vec_path, dtype=np.int8, mode="r+", shape=(cap, DIM))
            self.scale = np.memmap(self.scale_path, dtype=np.float16, mode="r+", shape=(cap,))
            self.bits = np.fromfile(self.bits_path, dtype=np.uint8).reshape(-1, DIM // 8)[:cap].copy() \
                if self.bits_path.exists() else np.zeros((cap, DIM // 8), dtype=np.uint8)
            if self.bits.shape[0] < cap:
                self.bits = np.vstack([self.bits, np.zeros((cap - self.bits.shape[0], DIM // 8), np.uint8)])

    def _ensure(self, max_id: int) -> None:
        cap = int(self.meta.get("capacity") or 0)
        if max_id < cap:
            return
        new_cap = ((max_id // GROW) + 1) * GROW
        for path, width, dtype in ((self.vec_path, DIM, np.int8), (self.scale_path, 1, np.float16)):
            with open(path, "ab") as fh:
                fh.truncate(new_cap * width * np.dtype(dtype).itemsize)
        self.vec = np.memmap(self.vec_path, dtype=np.int8, mode="r+", shape=(new_cap, DIM))
        self.scale = np.memmap(self.scale_path, dtype=np.float16, mode="r+", shape=(new_cap,))
        bits = np.zeros((new_cap, DIM // 8), dtype=np.uint8)
        if self.bits is not None:
            bits[: self.bits.shape[0]] = self.bits
        self.bits = bits
        self.meta["capacity"] = new_cap

    def _save_meta(self) -> None:
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.meta))
        tmp.replace(self.meta_path)

    def _write(self, ids: list[int], vecs: np.ndarray) -> None:
        with self.lock:
            self._ensure(max(ids))
            m = np.abs(vecs).max(axis=1)
            m[m == 0] = 1
            q = np.round(vecs / m[:, None] * 127).astype(np.int8)
            idx = np.asarray(ids)
            self.vec[idx] = q
            self.scale[idx] = (m / 127).astype(np.float16)
            self.bits[idx] = np.packbits(vecs > 0, axis=1)

    def flush(self) -> None:
        with self.lock:
            if self.vec is not None:
                self.vec.flush()
                self.scale.flush()
                self.bits.tofile(self.bits_path)
            self._save_meta()

    # ------------------------------------------------------------ statistics
    def _load_stats(self) -> None:
        if not self.stats_path.exists() or not int(self.meta.get("stats_n") or 0):
            return
        try:
            with np.load(self.stats_path) as z:
                self.weights = z["weights"].astype(np.float32)
                self.center = z["center"].astype(np.float32)
        except Exception as exc:
            log.info("meaning index statistics unreadable (%s); rebuilding", exc)
            self.weights = self.center = None
            self.meta.update(built_until=0, count=0, stats_n=0)

    @staticmethod
    def _texts(rows) -> tuple[list[str], list[str]]:
        names, caps = [], []
        for r in rows:
            n, c = textproc.embed_parts(r[1], r[3], r[2])
            names.append(n)
            caps.append(c)
        return names, caps

    def _compute_stats(self, conn: sqlite3.Connection, model: _Model) -> None:
        """Token document frequencies and the library's mean vector, from every file."""
        t0 = time.time()
        df = np.zeros(model.vocab, dtype=np.int64)
        n_docs = 0
        last = 0
        while True:
            if self._stop.is_set():
                raise _Stopped()
            rows = conn.execute("SELECT id, name, alias, caption FROM files WHERE id > ? ORDER BY id LIMIT 20000",
                                (last,)).fetchall()
            if not rows:
                break
            last = rows[-1][0]
            names, caps = self._texts(rows)
            docs = [f"{a} {b}".strip() for a, b in zip(names, caps)]
            per_doc = [np.unique(a) for a in model.ids(docs) if len(a)]
            n_docs += len(per_doc)
            if per_doc:
                df += np.bincount(np.concatenate(per_doc), minlength=model.vocab)
        idf = np.log1p((n_docs + 1) / (df + 1)).astype(np.float32)
        # Words (almost) nobody uses get the weight of a rare word, not an extreme one.
        weights = np.minimum(idf, idf.max()) * model.prior
        self.weights = weights.astype(np.float32)
        # The library's average direction, from a sample.
        center = np.zeros(DIM, dtype=np.float32)
        if n_docs:
            total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] or 1
            step = max(1, total // STATS_SAMPLE)
            rows = conn.execute("SELECT id, name, alias, caption FROM files WHERE id % ? = 0 LIMIT ?",
                                (step, STATS_SAMPLE)).fetchall()
            if len(rows) < min(total, 200):
                rows = conn.execute("SELECT id, name, alias, caption FROM files LIMIT ?", (STATS_SAMPLE,)).fetchall()
            vecs = self._raw(model, rows)
            vecs = vecs[np.linalg.norm(vecs, axis=1) > 0]
            if len(vecs):
                strength = min(1.0, n_docs / CENTER_FULL_AT)
                center = vecs.mean(axis=0) * strength
                self.meta["center_strength"] = round(strength, 4)
        self.center = center.astype(np.float32)
        tmp = self.dir / "stats.tmp.npz"
        np.savez(tmp, weights=self.weights, center=self.center, n=np.int64(n_docs))
        tmp.replace(self.stats_path)
        self.meta["stats_n"] = int(n_docs)
        # How many files the library had: what "grew by a third" is measured against. (Not n_docs: files
        # without any words, like most photos, never count there, so a library of mostly photos looked as
        # if it had always grown too much, and the statistics were computed again, forever.)
        self.meta["stats_total"] = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] or 0)
        self.meta["stats_at"] = int(time.time())
        log.info("meaning index statistics: %d files, %d distinct tokens, %.1f s", n_docs, int((df > 0).sum()),
                 time.time() - t0)

    def _raw(self, model: _Model, rows) -> np.ndarray:
        """Unit vectors before centering: name and caption pooled separately, the name counting double."""
        names, caps = self._texts(rows)
        w = self.weights if self.weights is not None else model.prior
        vn = model.pool(model.ids(names), w)
        vc = model.pool(model.ids(caps), w)
        return _unit(vn * NAME_WEIGHT + vc)

    def _final(self, raw: np.ndarray) -> np.ndarray:
        empty = ~raw.any(axis=1)
        if self.center is not None:
            raw = raw - self.center
        out = _unit(raw)
        out[empty] = 0
        return out

    def _needs_restat(self, conn: sqlite3.Connection) -> bool:
        if not int(self.meta.get("stats_n") or 0) or self.weights is None:
            return True
        now = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] or 0
        have = int(self.meta.get("stats_total") or 0)
        if not have:   # statistics from before 2.3.1: count from now on instead of starting over
            self.meta["stats_total"] = now
            return False
        if time.time() - int(self.meta.get("stats_at") or 0) < RESTAT_MIN_GAP:
            return False   # never more often than this, however fast files arrive
        return now > have * REBUILD_GROWTH and now - have >= 50

    # --------------------------------------------------------------- building
    def prewarm(self) -> None:
        from .db import prefetch_files
        prefetch_files(self.vec_path, self.scale_path, self.bits_path)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="tgdrive-semantic", daemon=True)
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
        try:
            self.flush()
        except Exception:
            pass

    def poke(self, file_id: Optional[int] = None) -> None:
        if file_id is not None:
            self._dirty.add(file_id)
        self._wake.set()

    def status(self) -> dict:
        return {"enabled": self.enabled, "available": _Model.error is None, "state": self.state,
                "count": int(self.meta.get("count") or 0), "built_until": int(self.meta.get("built_until") or 0),
                "error": self.error or _Model.error, "version": VERSION, "stats_files": int(self.meta.get("stats_n") or 0)}

    def rebuild(self) -> None:
        """Start over: new statistics, every vector again."""
        self.meta.update(built_until=0, count=0, stats_n=0)
        self.poke()

    def _loop(self) -> None:
        pace.lower_priority()
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        self._conn = conn
        conn.execute("PRAGMA query_only=1")
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
                model = _Model.get()
                if model is None:
                    self.state, self.error = "unavailable", _Model.error
                    return
                try:
                    t0 = time.thread_time()
                    worked = self._step(conn, model)
                    if worked:
                        pace.rest(time.thread_time() - t0, self._stop)
                except _Stopped:
                    break
                except sqlite3.OperationalError as exc:
                    if self._stop.is_set():
                        break
                    log.info("semantic step retry: %s", exc)
                    worked = False
                    self._stop.wait(2)
                except Exception as exc:
                    log.exception("semantic indexing failed")
                    self.state, self.error = "error", str(exc)
                    self._stop.wait(60)
                    continue
                if not worked:
                    self.state = "ready"
                    self.flush()
                    self._wake.wait(45)
                    self._wake.clear()
        finally:
            self._conn = None
            conn.close()

    def _step(self, conn: sqlite3.Connection, model: _Model) -> bool:
        start = int(self.meta.get("built_until") or 0)
        if (start == 0 and not int(self.meta.get("stats_n") or 0)) or (not self._dirty and self._needs_restat(conn)):
            self.state = "building"
            self._compute_stats(conn, model)
            self.meta.update(built_until=0, count=0)
            self._dirty.clear()
            start = 0
        dirty = []
        if self._dirty:
            dirty, self._dirty = list(self._dirty)[:BATCH], set(list(self._dirty)[BATCH:])
        rows = conn.execute("SELECT id, name, alias, caption FROM files WHERE id > ? ORDER BY id LIMIT ?",
                            (start, BATCH)).fetchall()
        if dirty:
            marks = ",".join("?" * len(dirty))
            rows += conn.execute(f"SELECT id, name, alias, caption FROM files WHERE id IN ({marks})", dirty).fetchall()
        if not rows:
            return False
        self.state = "building"
        vecs = self._final(self._raw(model, rows))
        ids = [r[0] for r in rows]
        self._write(ids, vecs)
        new_rows = [r for r in rows if r[0] > start]
        if new_rows:
            self.meta["built_until"] = max(r[0] for r in new_rows)
            self.meta["count"] = int(self.meta.get("count") or 0) + int(
                vecs[[i for i, r in enumerate(rows) if r[0] > start]].any(axis=1).sum())
        if self.meta["built_until"] % (BATCH * 25) < BATCH:
            self.flush()
        return True

    # ---------------------------------------------------------------- search
    def ready_fraction(self, max_id: int) -> float:
        return min(1.0, int(self.meta.get("built_until") or 0) / max(1, max_id))

    def embed_query(self, texts: Sequence[str]) -> np.ndarray:
        """Query-side vectors in the same space as the stored ones (weights and centering applied)."""
        model = _Model.get()
        if model is None:
            return np.zeros((len(texts), DIM), dtype=np.float32)
        w = self.weights if self.weights is not None else model.prior
        clean = [" ".join(w2 for t in textproc.words(x) for w2 in textproc.split_compound(t)) for x in texts]
        return self._final(model.pool(model.ids(clean), w))

    def query_vector(self, text: str, extra: Sequence[str] = ()) -> np.ndarray:
        texts = [text] + [e for e in extra if e and e.strip() and e.strip().lower() != text.strip().lower()]
        vs = self.embed_query(texts)
        q = vs[0]
        others = [v for v in vs[1:] if v.any()]
        if others:
            q = q + EXTRA_WEIGHT * np.mean(others, axis=0) if q.any() else np.mean(others, axis=0)
        n = np.linalg.norm(q)
        return q / n if n > 0 else q

    def search(self, text: str, k: int = 300, min_sim: Optional[float] = None,
               allowed: Optional[np.ndarray] = None, extra: Sequence[str] = ()) -> list[tuple[int, float]]:
        model = _Model.get()
        if model is None or self.bits is None or not text.strip():
            return []
        t0 = time.perf_counter()
        qv = self.query_vector(text, extra)
        if not qv.any():
            return []
        with self.lock:
            n = min(int(self.meta.get("built_until") or 0) + 1, self.bits.shape[0])
            if n <= 1:
                return []
            qbits = np.packbits(qv > 0)
            if allowed is not None:
                allowed = allowed[allowed < n]
                if not len(allowed):
                    return []
                cand_pool = allowed
                ham = np.bitwise_count(np.bitwise_xor(self.bits[cand_pool], qbits)).sum(axis=1, dtype=np.int32)
            else:
                cand_pool = None
                ham = np.bitwise_count(np.bitwise_xor(self.bits[:n], qbits)).sum(axis=1, dtype=np.int32)
            take = min(len(ham), PREFILTER)
            top = np.argpartition(ham, take - 1)[:take]
            ids = cand_pool[top] if cand_pool is not None else top
            vec = np.asarray(self.vec[ids], dtype=np.float32)
            sc = np.asarray(self.scale[ids], dtype=np.float32)
        sims = (vec @ qv) * sc
        order = np.argsort(-sims)[:k]
        if not len(order):
            return []
        best = float(sims[order[0]])
        if min_sim is None:
            min_sim = MIN_SIM - 0.05 * (1 - float(self.meta.get("center_strength") or 0))
        cutoff = max(min_sim, best * REL_SIM)
        out = [(int(ids[i]), float(sims[i])) for i in order if sims[i] >= cutoff and ids[i] > 0]
        log.debug("meaning search %r (+%d phrasings): %d candidates, best %.3f, cutoff %.3f → %d results in %.1f ms",
                  text, len(extra), take, best, cutoff, len(out), (time.perf_counter() - t0) * 1000)
        return out

