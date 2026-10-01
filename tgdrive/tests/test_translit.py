"""translit.py (the Android app's Devanagari → Latin conversion) must match indic-transliteration."""
import random

import pytest

from tgdrive.translit import devanagari_to_hk

sanscript = pytest.importorskip("indic_transliteration.sanscript")

WORDS = ("संविधान भारतीय नोट्स अर्थव्यवस्था क़िला ज्ञान क्षत्रिय हिंदी हिन्दी ॐ इतिहास भूगोल पर्यावरण "
         "राजव्यवस्था करेंट अफेयर्स प्रश्न उत्तर पिछले वर्ष के प्रश्नपत्र गणित विज्ञान सामान्य अध्ययन "
         "मौलिक अधिकार ड़ढ़ ऋषि कृष्ण ऐतिहासिक औद्योगिक श्रीमान् दुःख अँधेरा सिंह १२३४ २०२४ ।॥").split()


def _random_words(n=5000):
    rnd = random.Random(3)
    block = [chr(c) for c in range(0x0900, 0x0980)] + ["़", "्"] * 6 + list("ab1 _-")
    out = list(WORDS)
    for _ in range(n):
        out.append("".join(rnd.choice(block) for _ in range(rnd.randint(1, 10))))
        out.append(" ".join(rnd.choice(WORDS) for _ in range(rnd.randint(1, 4))))
    return out


def test_matches_indic_transliteration():
    bad = []
    for w in _random_words():
        want = sanscript.transliterate(w, sanscript.DEVANAGARI, sanscript.HK)
        got = devanagari_to_hk(w)
        if want != got:
            bad.append((w, want, got))
    assert not bad, f"{len(bad)} differ, e.g. {bad[:3]!r}"
