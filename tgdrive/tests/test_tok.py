"""The pure-Python tokenizer and tensor reader (used where the compiled ones can't be installed,
i.e. the Android app) must give exactly what the real libraries give for the bundled model."""
import random
import string

import numpy as np
import pytest

from tgdrive import semantic
from tgdrive.tok import BPETokenizer, load_tensor

tokenizers = pytest.importorskip("tokenizers")


def _paths():
    try:
        return semantic._Model.locate()
    except FileNotFoundError:
        pytest.skip("wordllama model files not installed")


def _samples(n: int = 4000) -> list[str]:
    rnd = random.Random(7)
    words = ("polity notes ncert class 11 history pdf Lecture 01 Quantum Mechanics.mp4 upsc mains 2025 papers "
             "TestSeries test_series GS2 Paper1 photo_2026-05-07_01-50-00.jpg संविधान samvidhan अर्थव्यवस्था "
             "economy एक यह वह Indian Polity Fundamental Rights (notes) join @channel #upsc 🔥📚 ✈️ 東京 привет "
             "naïve café Ωmega <s> </s> <unk> ▁ __init__ a.b-c,d;e e-mail@x.y 1,234.56 ₹500 ").split()
    out = ["", " ", "  ", "a", "   leading", "trailing   ", "double  space", "tab\there", "new\nline", "<s>", "x<s>y",
           "<s><s>", " <s> ", "</s>end", "<unk>", "▁", "▁▁x", "\x00\x01", "🧪" * 5, "é" * 40,
           "a" * 300, "ab" * 200, " ".join(words)]
    for _ in range(n):
        k = rnd.randint(1, 9)
        parts = [rnd.choice(words) for _ in range(k)]
        if rnd.random() < 0.25:
            parts.append("".join(rnd.choice(string.printable) for _ in range(rnd.randint(1, 12))))
        sep = rnd.choice([" ", "  ", "_", "-", " - ", ""])
        out.append(sep.join(parts))
    return out


def test_bpe_matches_huggingface_tokenizers():
    tok_path, _ = _paths()
    ref = tokenizers.Tokenizer.from_file(str(tok_path))
    ref.enable_truncation(max_length=96)
    ref.no_padding()
    mine = BPETokenizer.from_file(str(tok_path))
    mine.enable_truncation(max_length=96)
    mine.no_padding()
    texts = _samples()
    want = [e.ids for e in ref.encode_batch(texts, add_special_tokens=False)]
    got = [e.ids for e in mine.encode_batch(texts, add_special_tokens=False)]
    bad = [(t, w, g) for t, w, g in zip(texts, want, got) if w != g]
    assert not bad, f"{len(bad)} of {len(texts)} differ, first: {bad[0]!r}"
    for i in (0, 1, 2, 3, 259, 1000, 31999):
        assert mine.id_to_token(i) == ref.id_to_token(i)


def test_tensor_reader_matches_safetensors():
    safetensors = pytest.importorskip("safetensors")
    _, w_path = _paths()
    with safetensors.safe_open(str(w_path), framework="np") as f:
        want = f.get_tensor("embedding.weight")
    got = load_tensor(str(w_path), "embedding.weight")
    assert got.dtype == want.dtype and got.shape == want.shape
    assert np.array_equal(got, want)


def test_tensor_reader_rejects_truncated_files(tmp_path):
    import json
    import struct
    head = json.dumps({"w": {"dtype": "F32", "shape": [4], "data_offsets": [0, 16]}}).encode()
    p = tmp_path / "t.safetensors"
    p.write_bytes(struct.pack("<Q", len(head)) + head + b"\0" * 8)
    with pytest.raises(ValueError):
        load_tensor(str(p), "w")
    p.write_bytes(struct.pack("<Q", len(head)) + head + np.arange(4, dtype="<f4").tobytes())
    assert load_tensor(str(p), "w").tolist() == [0.0, 1.0, 2.0, 3.0]
