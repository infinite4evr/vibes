"""Devanagari to Latin letters (Harvard-Kyoto), for matching Hindi names typed in either script.

TG Drive uses the indic-transliteration package for this where it's installed. That package needs
the compiled `regex` module, which has no reliable Android build, so the Android app uses this
port instead: the same algorithm (indic_transliteration.sanscript.brahmic_mapper._brahmic) over
the same tables, taken from indic-transliteration 2.3.82 (DEVANAGARI → HK).
tests/test_translit.py checks both give the same result.
"""
from __future__ import annotations

VOWEL_MARKS = {
    'ा': 'A', 'ि': 'i', 'ी': 'I', 'ु': 'u', 'ू': 'U', 'ृ': 'R', 'ॄ': 'RR', 'ॆ': 'è', 'े': 'e', 'ै': 'ai',
    'ॊ': 'ò', 'ो': 'o', 'ौ': 'au', 'ॢ': 'lR', 'ॣ': 'lRR',
}
VIRAMA = {
    '्': '',
}
CONSONANTS = frozenset({
    'क', 'क़', 'क्ष', 'ख', 'ख़', 'ग', 'ग़', 'घ', 'ङ',
    'च', 'छ', 'ज', 'ज़', 'ज्ञ', 'झ', 'ञ', 'ट', 'ठ',
    'ड', 'ड़', 'ढ', 'ढ़', 'ण', 'त', 'थ', 'द', 'ध',
    'न', 'ऩ', 'ऩ', 'प', 'फ', 'फ़', 'ब', 'भ', 'म',
    'य', 'य़', 'र', 'ऱ', 'ऱ', 'ल', 'ळ', 'ऴ', 'ऴ',
    'व', 'श', 'ष', 'स', 'ह', 'क़', 'ख़', 'ग़', 'ज़',
    'ड़', 'फ़', 'य़',
})
NON_MARKS_VIRAMA = {
    'ँ': '~', 'ं': 'M', 'ः': 'H', 'अ': 'a', 'आ': 'A', 'इ': 'i', 'ई': 'I', 'उ': 'u', 'ऊ': 'U', 'ऋ': 'R',
    'ऌ': 'lR', 'ऎ': 'è', 'ए': 'e', 'ऐ': 'ai', 'ऒ': 'ò', 'ओ': 'o', 'औ': 'au', 'क': 'k', 'क़': 'q',
    'क्ष': 'kS', 'ख': 'kh', 'ख़': 'qh', 'ग': 'g', 'ग़': 'g2', 'घ': 'gh', 'ङ': 'G', 'च': 'c', 'छ': 'ch',
    'ज': 'j', 'ज़': 'z2', 'ज्ञ': 'jJ', 'झ': 'jh', 'ञ': 'J', 'ट': 'T', 'ठ': 'Th', 'ड': 'D', 'ड़': 'r3',
    'ढ': 'Dh', 'ढ़': 'r3h', 'ण': 'N', 'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n', 'ऩ': 'n2',
    'ऩ': 'n2', 'प': 'p', 'फ': 'ph', 'फ़': 'f', 'ब': 'b', 'भ': 'bh', 'म': 'm', 'य': 'y', 'य़': 'Y', 'र': 'r',
    'ऱ': 'r2', 'ऱ': 'r2', 'ल': 'l', 'ळ': 'L', 'ऴ': 'zh', 'ऴ': 'zh', 'व': 'v', 'श': 'z', 'ष': 'S', 'स': 's',
    'ह': 'h', 'ऽ': "'", 'ॐ': 'OM', 'क़': 'q', 'ख़': 'qh', 'ग़': 'g2', 'ज़': 'z2', 'ड़': 'r3', 'फ़': 'f', 'य़': 'Y',
    'ॠ': 'RR', 'ॡ': 'lRR', '।': '|', '॥': '||', '०': '0', '१': '1', '२': '2', '३': '3', '४': '4', '५': '5',
    '६': '6', '७': '7', '८': '8', '९': '9',
}
MAX_KEY = 6


def devanagari_to_hk(data: str) -> str:
    buf: list[str] = []
    append = buf.append
    i = 0
    had_consonant = found = False
    while i <= len(data):
        token = data[i:i + MAX_KEY]
        while token:
            if len(token) == 1:
                if token in VOWEL_MARKS:
                    append(VOWEL_MARKS[token])
                elif token in VIRAMA:
                    append(VIRAMA[token])
                else:
                    if had_consonant:
                        append("a")
                    append(NON_MARKS_VIRAMA.get(token, token))
                found = True
            elif token in NON_MARKS_VIRAMA:
                if had_consonant:
                    append("a")
                append(NON_MARKS_VIRAMA[token])
                found = True
            if found:
                had_consonant = token in CONSONANTS
                i += len(token)
                break
            token = token[:-1]
        if not found:
            if had_consonant:
                append(next(iter(VIRAMA.values())))
            if i < len(data):
                append(data[i])
                had_consonant = False
            i += 1
        found = False
    if had_consonant:
        append("a")
    return "".join(buf)
