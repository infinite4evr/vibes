"""Meaning-based ("related") search, fully offline.

Uses the small static embedding model bundled in the `wordllama` package
(256-dimensional token embeddings, average-pooled). Each file's name and caption
become one vector, stored on disk as int8 plus a per-row scale, indexed by the
file's row id. A 1-bit copy (32 bytes per file) stays in memory for a fast
Hamming pre-filter; the best few thousand candidates are then rescored exactly.

437k files: ~12 s to embed, ~115 MB on disk, ~14 MB in memory, ~40 ms per query.
"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from . import textproc

log = logging.getLogger("tgdrive.semantic")

DIM = 256
GROW = 65_536
BATCH = 4000
MIN_SIM = 0.25
REL_SIM = 0.6   # also within 60% of the best match


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

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        encs = self.tok.encode_batch([t or "" for t in texts], add_special_tokens=False)
        vocab = self.emb.shape[0]
        for i, enc in enumerate(encs):
            ids = [t for t in enc.ids if 0 <= t < vocab]
            if not ids or not texts[i]:
                continue
            v = self.emb[ids].mean(axis=0)
            n = np.linalg.norm(v)
            if n > 0:
                out[i] = v / n
        return out


def available() -> bool:
    return _Model.get() is not None


class SemanticIndex:
    def __init__(self, directory: Path, db_path: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.meta_path = self.dir / "meta.json"
        self.vec_path = self.dir / "vectors.i8"
        self.scale_path = self.dir / "vectors.scale"
        self.bits_path = self.dir / "vectors.bits"
        self.lock = threading.RLock()
        self.meta = {"built_until": 0, "capacity": 0, "count": 0, "version": 1}
        if self.meta_path.exists():
            try:
                self.meta.update(json.loads(self.meta_path.read_text()))
            except Exception:
                pass
        self.vec: Optional[np.memmap] = None
        self.scale: Optional[np.memmap] = None
        self.bits: Optional[np.ndarray] = None
        self.enabled = True
        self.state = "idle"
        self.error: Optional[str] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dirty: set[int] = set()
        self._open()

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

    # --------------------------------------------------------------- building
    def prewarm(self) -> None:
        from .db import prefetch_files
        prefetch_files(self.vec_path, self.scale_path, self.bits_path)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="tgdrive-semantic", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
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
                "error": self.error or _Model.error}

    def _loop(self) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute("PRAGMA query_only=1")
        try:
            while not self._stop.is_set():
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
                    worked = self._step(conn, model)
                except sqlite3.OperationalError as exc:
                    log.info("semantic step retry: %s", exc)
                    worked = False
                    time.sleep(2)
                except Exception as exc:
                    log.exception("semantic indexing failed")
                    self.state, self.error = "error", str(exc)
                    time.sleep(60)
                    continue
                if not worked:
                    self.state = "ready"
                    self.flush()
                    self._wake.wait(45)
                    self._wake.clear()
        finally:
            conn.close()

    def _step(self, conn: sqlite3.Connection, model: _Model) -> bool:
        dirty = []
        if self._dirty:
            dirty, self._dirty = list(self._dirty)[:BATCH], set(list(self._dirty)[BATCH:])
        start = int(self.meta.get("built_until") or 0)
        rows = conn.execute("SELECT id, name, alias, caption FROM files WHERE id > ? ORDER BY id LIMIT ?",
                            (start, BATCH)).fetchall()
        if dirty:
            marks = ",".join("?" * len(dirty))
            rows += conn.execute(f"SELECT id, name, alias, caption FROM files WHERE id IN ({marks})", dirty).fetchall()
        if not rows:
            return False
        self.state = "building"
        texts = [textproc.embed_text(r[1], r[3], r[2]) for r in rows]
        vecs = model.embed(texts)
        ids = [r[0] for r in rows]
        self._write(ids, vecs)
        new_rows = [r for r in rows if r[0] > start]
        if new_rows:
            self.meta["built_until"] = max(r[0] for r in new_rows)
            self.meta["count"] = int(self.meta.get("count") or 0) + sum(1 for t in texts if t)
        if self.meta["built_until"] % (BATCH * 25) < BATCH:
            self.flush()
        return True

    # ---------------------------------------------------------------- search
    def ready_fraction(self, max_id: int) -> float:
        return min(1.0, int(self.meta.get("built_until") or 0) / max(1, max_id))

    def search(self, text: str, k: int = 300, min_sim: float = MIN_SIM,
               allowed: Optional[np.ndarray] = None) -> list[tuple[int, float]]:
        model = _Model.get()
        if model is None or self.bits is None or not text.strip():
            return []
        qv = model.embed([text])[0]
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
            take = min(len(ham), 4000)
            top = np.argpartition(ham, take - 1)[:take]
            ids = cand_pool[top] if cand_pool is not None else top
            vec = np.asarray(self.vec[ids], dtype=np.float32)
            sc = np.asarray(self.scale[ids], dtype=np.float32)
        sims = (vec @ qv) * sc
        order = np.argsort(-sims)[:k]
        if not len(order):
            return []
        cutoff = max(min_sim, float(sims[order[0]]) * REL_SIM)
        return [(int(ids[i]), float(sims[i])) for i in order if sims[i] >= cutoff and ids[i] > 0]
