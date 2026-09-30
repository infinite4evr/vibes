"""Pure-Python stand-ins for the two compiled libraries the meaning model is read with.

`tokenizers` (Hugging Face) and `safetensors` are Rust extensions with no Android build. The
model TG Drive ships (wordllama's l2_supercat: a Llama-2 SentencePiece-style BPE vocabulary and a
float16 embedding table) needs very little of either, so this module implements that part:

  * BPETokenizer reads the same tokenizer JSON and produces the same ids as
    `tokenizers.Tokenizer` for it: added tokens split out first, then the Prepend("▁") and
    Replace(" ", "▁") normalizers, then BPE by merge rank with byte fallback. tests/test_tok.py
    checks it id for id against the real library on thousands of names, captions and odd inputs.
  * load_tensor reads one tensor out of a .safetensors file (a JSON header and raw little-endian
    data) with numpy.

Only used where the compiled libraries can't be imported (semantic.py tries them first).
"""
from __future__ import annotations

import json
import re
import struct
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Iterable, Optional, Sequence

SPACE = "▁"   # ▁
# A chunk is a run of ▁ followed by other characters. No token and no merge in a SentencePiece
# vocabulary puts ▁ after another character, so BPE never joins two chunks and each can be
# tokenized (and cached) on its own. BPETokenizer checks that the vocabulary really is like that.
_CHUNK = re.compile(f"{SPACE}*[^{SPACE}]+|{SPACE}+")


class Encoding:
    __slots__ = ("ids",)

    def __init__(self, ids: list[int]):
        self.ids = ids


class BPETokenizer:
    """The subset of `tokenizers.Tokenizer` that semantic.py uses, for SentencePiece-style BPE JSON."""

    CACHE = 200_000

    def __init__(self, spec: dict):
        model = spec.get("model") or {}
        if model.get("type") != "BPE":
            raise ValueError(f"unsupported tokenizer model {model.get('type')!r}")
        if model.get("dropout") or model.get("continuing_subword_prefix") or model.get("end_of_word_suffix"):
            raise ValueError("unsupported BPE options")
        if spec.get("pre_tokenizer") is not None:
            raise ValueError("unsupported pre-tokenizer")
        self.prepend, self.replace = self._normalizers(spec.get("normalizer"))
        self.vocab: dict[str, int] = {str(k): int(v) for k, v in model["vocab"].items()}
        self.inv: dict[int, str] = {v: k for k, v in self.vocab.items()}
        self.unk_id: Optional[int] = self.vocab.get(model.get("unk_token")) if model.get("unk_token") else None
        self.byte_fallback = bool(model.get("byte_fallback"))
        self.fuse_unk = bool(model.get("fuse_unk"))
        self.merges: dict[tuple[int, int], tuple[int, int]] = {}
        for rank, m in enumerate(model.get("merges") or []):
            a, b = m.split(" ", 1) if isinstance(m, str) else m
            ia, ib, inew = self.vocab.get(a), self.vocab.get(b), self.vocab.get(a + b)
            if ia is None or ib is None or inew is None:
                raise ValueError(f"merge {a!r} {b!r} refers to unknown tokens")
            self.merges.setdefault((ia, ib), (rank, inew))
        for tok in self.vocab:
            if SPACE in tok.lstrip(SPACE):
                raise ValueError("vocabulary has tokens with ▁ inside; chunked BPE would be wrong")
        added = [t for t in spec.get("added_tokens") or [] if not t.get("normalized")]
        self.added = {t["content"]: int(t["id"]) for t in added}
        for t in added:
            self.inv.setdefault(int(t["id"]), t["content"])
        self._added_re = re.compile("|".join(re.escape(t) for t in sorted(self.added, key=len, reverse=True))) \
            if self.added else None
        self.max_length: Optional[int] = None
        self._cache: OrderedDict[str, tuple[int, ...]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _normalizers(spec: Optional[dict]) -> tuple[str, Optional[tuple[str, str]]]:
        if spec is None:
            return "", None
        steps = spec.get("normalizers") if spec.get("type") == "Sequence" else [spec]
        prepend, replace = "", None
        for i, step in enumerate(steps):
            kind = step.get("type")
            if kind == "Prepend" and i == 0:
                prepend = step["prepend"]
            elif kind == "Replace" and "String" in (step.get("pattern") or {}):
                replace = (step["pattern"]["String"], step["content"])
            else:
                raise ValueError(f"unsupported normalizer {kind!r}")
        return prepend, replace

    @classmethod
    def from_file(cls, path: str) -> "BPETokenizer":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- the tokenizers.Tokenizer API
    def enable_truncation(self, max_length: int, **_) -> None:
        self.max_length = int(max_length)

    def no_padding(self) -> None:
        pass

    def id_to_token(self, i: int) -> Optional[str]:
        return self.inv.get(int(i))

    def encode(self, text: str, add_special_tokens: bool = False) -> Encoding:
        ids: list[int] = []
        for segment, added_id in self._split_added(text or ""):
            if added_id is not None:
                ids.append(added_id)
            elif segment:
                ids.extend(self._encode_normalized(self._normalize(segment)))
        if self.max_length is not None:
            ids = ids[:self.max_length]
        return Encoding(ids)

    def encode_batch(self, texts: Iterable[str], add_special_tokens: bool = False) -> list[Encoding]:
        return [self.encode(t, add_special_tokens) for t in texts]

    # -- internals
    def _split_added(self, text: str):
        if not self._added_re:
            yield text, None
            return
        pos = 0
        for m in self._added_re.finditer(text):
            if m.start() > pos:
                yield text[pos:m.start()], None
            yield m.group(0), self.added[m.group(0)]
            pos = m.end()
        if pos < len(text):
            yield text[pos:], None

    def _normalize(self, s: str) -> str:
        if self.prepend and s:
            s = self.prepend + s
        if self.replace:
            s = s.replace(*self.replace)
        return s

    def _encode_normalized(self, s: str) -> list[int]:
        out: list[int] = []
        for chunk in _CHUNK.findall(s):
            hit = self._cache.get(chunk)
            if hit is None:
                hit = tuple(self._bpe(chunk))
                with self._lock:
                    self._cache[chunk] = hit
                    if len(self._cache) > self.CACHE:
                        self._cache.popitem(last=False)
            out.extend(hit)
        return out

    def _initial(self, word: str) -> list[int]:
        syms: list[int] = []
        unk_run = False
        for ch in word:
            i = self.vocab.get(ch)
            if i is not None:
                syms.append(i)
                unk_run = False
                continue
            if self.byte_fallback:
                bs = [self.vocab.get(f"<0x{b:02X}>") for b in ch.encode("utf-8")]
                if all(b is not None for b in bs):
                    syms.extend(bs)   # type: ignore[arg-type]
                    unk_run = False
                    continue
            if self.unk_id is None:
                raise ValueError(f"character {ch!r} is not in the vocabulary")
            if not (self.fuse_unk and unk_run):
                syms.append(self.unk_id)
            unk_run = True
        return syms

    def _bpe(self, word: str) -> list[int]:
        syms = self._initial(word)
        merges = self.merges
        while len(syms) > 1:
            best_rank, best_at, best_new = None, -1, -1
            for i in range(len(syms) - 1):
                m = merges.get((syms[i], syms[i + 1]))
                if m is not None and (best_rank is None or m[0] < best_rank):
                    best_rank, best_at, best_new = m[0], i, m[1]
            if best_rank is None:
                break
            syms[best_at:best_at + 2] = [best_new]
        return syms


# ------------------------------------------------------------------ safetensors
_DTYPES = {"F64": "<f8", "F32": "<f4", "F16": "<f2", "I64": "<i8", "I32": "<i4", "I16": "<i2", "I8": "i1",
           "U8": "u1", "BOOL": "?"}


def load_tensor(path: str, name: str):
    """One tensor from a .safetensors file as a numpy array (a private copy, not a view of the file)."""
    import numpy as np
    with open(path, "rb") as fh:
        (n,) = struct.unpack("<Q", fh.read(8))
        if n > 100 * 1024 * 1024:
            raise ValueError("safetensors header is implausibly large")
        header = json.loads(fh.read(n))
        meta = header.get(name)
        if not meta:
            raise KeyError(f"{name} is not in {Path(path).name}")
        start, end = meta["data_offsets"]
        shape: Sequence[int] = meta["shape"]
        fh.seek(8 + n + start)
        raw = fh.read(end - start)
    if len(raw) != end - start:
        raise ValueError(f"{Path(path).name} is truncated")
    dtype = meta["dtype"]
    if dtype == "BF16":   # numpy has no bfloat16: widen the 16 bits into the top of a float32
        arr = (np.frombuffer(raw, dtype="<u2").astype(np.uint32) << 16).view(np.float32)
    elif dtype in _DTYPES:
        arr = np.frombuffer(raw, dtype=_DTYPES[dtype]).copy()
    else:
        raise ValueError(f"unsupported tensor type {dtype}")
    count = 1
    for d in shape:
        count *= int(d)
    if arr.size != count:
        raise ValueError(f"{name}: {arr.size} values for shape {list(shape)}")
    return arr.reshape([int(d) for d in shape])
