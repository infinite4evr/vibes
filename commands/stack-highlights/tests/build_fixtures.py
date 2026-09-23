#!/usr/bin/env python3
"""Build tiny deterministic PDFs used by the legacy golden harness."""
from pathlib import Path
import pymupdf as fitz  # the old "fitz" name is deprecated

ROOT=Path(__file__).resolve().parent
F=ROOT/'fixtures'; F.mkdir(exist_ok=True)

def highlight(page, needle, color=(1,1,0)):
    rects=page.search_for(needle)
    if not rects:
        raise RuntimeError(f"could not find {needle!r}")
    a=page.add_highlight_annot(rects)
    a.set_colors(stroke=color)
    a.update()

def prose_list():
    out=F/'prose_list.pdf'
    doc=fitz.open(); p=doc.new_page(width=612,height=792)
    p.insert_text((72,72),'CHAPTER 1  TEST NOTES',fontsize=16,fontname='helv')
    p.insert_text((72,110),'The features of the system are:',fontsize=11,fontname='helv')
    p.insert_text((90,135),'1. First item keeps the important fact.',fontsize=11,fontname='helv')
    p.insert_text((90,158),'2. Second item has another key detail.',fontsize=11,fontname='helv')
    p.insert_text((72,200),'A separate sentence provides useful surrounding context.',fontsize=11,fontname='helv')
    p.insert_text((72,240),'A co-',fontsize=11,fontname='helv')
    p.insert_text((72,256),'operation example crosses a line break.',fontsize=11,fontname='helv')
    highlight(p,'important fact')
    highlight(p,'Second item')
    highlight(p,'useful surrounding')
    # NOTE: search_for('co-') finds nothing here, so this annotation covers only
    # "operation". The real split-word case is tested by hyphen_break.pdf below.
    rects=p.search_for('co-')+p.search_for('operation')
    a=p.add_highlight_annot(rects); a.update()
    doc.save(out); doc.close()

def legal():
    out=F/'legal_clause.pdf'
    doc=fitz.open(); p=doc.new_page(width=612,height=792)
    p.insert_text((72,72),'CHAPTER II',fontsize=15,fontname='helv')
    p.insert_text((72,94),'PROCEDURE',fontsize=15,fontname='helv')
    p.insert_text((72,130),'11. Procedure and powers.-(1) The authority may conduct the inquiry in the prescribed manner.',fontsize=10.5,fontname='helv')
    p.insert_text((72,154),'(2) The authority shall record reasons before making the final order.',fontsize=10.5,fontname='helv')
    p.insert_text((72,200),'STATE AMENDMENT',fontsize=13,fontname='helv')
    p.insert_text((72,224),'Example State.-After sub-section (2), insert the following local provision.',fontsize=10.5,fontname='helv')
    highlight(p,'record reasons')
    highlight(p,'final order')
    highlight(p,'local provision')
    doc.save(out); doc.close()

# ---------------------------------------------------------------------------
# Fixtures for the areas where real bugs have lived. They use PyMuPDF's
# built-in Times fonts so em dashes and bold survive, and add highlights over
# whole words found in the page's own word list (not text search), so each
# annotation covers exactly what the test says it covers.
# ---------------------------------------------------------------------------
REG, BOLD = "TR", "TB"
LEAD = 14

def new_page(doc, printed=None, header=None):
    p = doc.new_page(width=612, height=792)
    p.insert_font(fontname=REG, fontbuffer=fitz.Font("tiro").buffer)
    p.insert_font(fontname=BOLD, fontbuffer=fitz.Font("tibo").buffer)
    if header:
        p.insert_text((72, 40), header, fontsize=8, fontname=REG)
    if printed:
        p.insert_text((300, 770), str(printed), fontsize=9, fontname=REG)
    return p

def lines(p, y, texts, size=10.5, font=REG, x=72):
    for t in texts:
        p.insert_text((x, y), t, fontsize=size, fontname=font)
        y += LEAD
    return y

def runs(p, y, parts, size=10.5, x=72):
    """One line made of (text, font) pieces, e.g. a bold run-in title then body text."""
    for text, font in parts:
        p.insert_text((x, y), text, fontsize=size, fontname=font)
        x += fitz.Font("tibo" if font == BOLD else "tiro").text_length(text, fontsize=size)
    return y + LEAD

def _page_chars(p):
    """[(char, bbox or None)] in reading order; lines are joined by one space."""
    out = []
    for b in p.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            if out:
                out.append((" ", None))
            for sp in l["spans"]:
                for ch in sp["chars"]:
                    out.append((ch["c"], fitz.Rect(ch["bbox"])))
    return out

def mark_words(p, phrase, *, occurrence=0, color=(1, 1, 0), content=None):
    """Highlight exactly the characters of `phrase` (it may run across a line
    break, written with one space there) as ONE annotation."""
    chars = _page_chars(p)
    text = "".join(c for c, _ in chars)
    i = -1
    for _ in range(occurrence + 1):
        i = text.find(phrase, i + 1)
        if i < 0:
            raise RuntimeError(f"could not find {phrase!r}")
    rows = {}
    for c, r in chars[i:i + len(phrase)]:
        if r is not None and c.strip():
            key = round((r.y0 + r.y1) / 2)
            rows[key] = rows[key] | r if key in rows else fitz.Rect(r)
    a = p.add_highlight_annot([rows[k] for k in sorted(rows)])
    a.set_colors(stroke=color)
    if content:
        a.set_info(content=content)
    a.update()
    return a

def mark_part_of_word(p, word, fraction=0.2):
    """Highlight only the first `fraction` of a word (less than half of it)."""
    w = next(w for w in p.get_text("words") if w[4] == word)
    r = fitz.Rect(w[0], w[1], w[0] + (w[2] - w[0]) * fraction, w[3])
    a = p.add_highlight_annot(r); a.update()

def page_break():
    """A paragraph split across a page break, a page ending on a dangling word,
    running headers and printed page numbers. Tested in full and with a page
    gap (--pages 1,3), which is where text from skipped pages gets spliced."""
    out = F / 'page_break.pdf'
    doc = fitz.open()
    p1 = new_page(doc, printed=12, header="A TEST BOOK OF HISTORY")
    p1.insert_text((72, 90), "CHAPTER 2", fontsize=16, fontname=BOLD)
    p1.insert_text((72, 112), "The Treaty", fontsize=13, fontname=BOLD)
    lines(p1, 140, ["The two armies met near the river after a long campaign that lasted",
                    "through the monsoon. The treaty that ended the war was signed in 1782,",
                    "and it promised that the two sides would stay at peace for"])
    mark_words(p1, "signed in 1782,")
    p2 = new_page(doc, printed=13, header="A TEST BOOK OF HISTORY")
    y = lines(p2, 90, ["twenty years. The treaty also returned the captured forts to their",
                       "old owners, which was its most important term."])
    lines(p2, y + 10, ["A later chapter explains how the peace broke down after the death of",
                       "the old regent, when the courts began to hear the claims of the heirs."])
    mark_words(p2, "twenty years.")
    mark_words(p2, "most important term.")
    p3 = new_page(doc, printed=14, header="A TEST BOOK OF HISTORY")
    lines(p3, 90, ["They voted in, stood for, and got elected to local bodies. Rani Laxmibai",
                   "led the revolt at Jhansi and became its best-known leader."])
    mark_words(p3, "Rani Laxmibai")
    doc.save(out); doc.close()

def hyphen_break():
    """Highlights running across a line-break hyphen: a lowercase split word
    (co- / operation) and a capitalised compound (inter- / State)."""
    out = F / 'hyphen_break.pdf'
    doc = fitz.open(); p = new_page(doc)
    p.insert_text((72, 90), "COOPERATION", fontsize=14, fontname=BOLD)
    lines(p, 120, ["The members of the council agreed on close co-",
                   "operation between the states and the centre in every field.",
                   "Disputes over the waters of inter-",
                   "State rivers are settled by a tribunal set up by Parliament."])
    mark_words(p, "close co- operation")
    mark_words(p, "inter- State rivers")
    doc.save(out); doc.close()

def table_footnote():
    """A small table with highlighted cells, a footnote marker in the body and a
    highlighted footnote at the foot of the page."""
    out = F / 'table_footnote.pdf'
    doc = fitz.open(); p = new_page(doc)
    p.insert_text((72, 90), "Table 1.1 Interim Government (1946)", fontsize=11, fontname=BOLD)
    cols = (72, 140, 330)
    y = 118
    for row, font in ((("Sl. No.", "Members", "Portfolios Held"), BOLD),
                      (("1.", "Jawaharlal Nehru", "External Affairs"), REG),
                      (("2.", "Sardar Patel", "Home and Information"), REG),
                      (("3.", "Rajendra Prasad", "Food and Agriculture"), REG)):
        for x, cell in zip(cols, row):
            p.insert_text((x, y), cell, fontsize=10.5, fontname=font)
        y += 18
    mark_words(p, "Sardar Patel")
    mark_words(p, "Food and Agriculture")
    y += 20
    p.insert_text((72, y), "The interim government was formed in September 1946.", fontsize=10.5, fontname=REG)
    x = 72 + fitz.Font("tiro").text_length("The interim government was formed in September 1946.", fontsize=10.5)
    p.insert_text((x + 0.5, y - 4), "1", fontsize=6.5, fontname=REG)
    lines(p, y + LEAD, ["It stayed in office until the country became independent in 1947."])
    mark_words(p, "September 1946.1")   # the footnote marker sits right after the full stop
    p.insert_text((72, 735), "1 The Muslim League joined the interim government in October 1946.",
                  fontsize=8, fontname=REG)
    mark_words(p, "October 1946.")
    doc.save(out); doc.close()

def legal_emdash():
    """Real legal typesetting: bold run-in section titles ending in ".\u2014",
    a STATE AMENDMENT block, then a central section resuming after it."""
    out = F / 'legal_emdash.pdf'
    doc = fitz.open(); p = new_page(doc)
    p.insert_text((72, 90), "CHAPTER VA", fontsize=13, fontname=BOLD)
    p.insert_text((72, 110), "LAY-OFF AND RETRENCHMENT", fontsize=12, fontname=BOLD)
    y = runs(p, 140, [("25C. Right of workmen laid-off for compensation.", BOLD),
                      ("\u2014(1) Whenever a workman whose name is", REG)])
    y = lines(p, y, ["borne on the muster rolls is laid-off, he shall be paid compensation for all days of lay-off."])
    p.insert_text((72, y + 14), "STATE AMENDMENT", fontsize=10.5, fontname=BOLD)
    y = runs(p, y + 34, [("Maharashtra.", REG),
                         ("\u2014In section 25C, for the words \u201call days\u201d, substitute \u201cforty-five days\u201d.", REG)])
    y = runs(p, y + 10, [("26. Penalty for illegal strikes.", BOLD),
                         ("\u2014(1) Any workman who commences an illegal strike", REG)])
    lines(p, y, ["shall be punishable with imprisonment for a term which may extend to one month."])
    mark_words(p, "Right of workmen laid-off for compensation.")
    mark_words(p, "paid compensation")
    mark_words(p, "\u201cforty-five days\u201d.")
    mark_words(p, "one month.")
    doc.save(out); doc.close()

def misses():
    """Highlights that cannot be placed: one covering less than half of a word
    and one over an image with no text under it (with a note on it), next to a
    normal highlight. These must show up in the "Check in book" list."""
    out = F / 'misses.pdf'
    doc = fitz.open(); p = new_page(doc, printed=57)
    p.insert_text((72, 90), "LIMITED GOVERNMENT", fontsize=14, fontname=BOLD)
    lines(p, 120, ["Constitutionalism means a government limited by a written charter.",
                   "The map below shows the provinces in 1935."])
    mark_part_of_word(p, "Constitutionalism", 0.2)
    mark_words(p, "limited by a written charter.")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 60), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    img = fitz.Rect(72, 170, 312, 290)
    p.insert_image(img, pixmap=pix)
    a = p.add_highlight_annot(fitz.Rect(90, 200, 290, 260)); a.set_info(content="see the map"); a.update()
    doc.save(out); doc.close()

if __name__=='__main__':
    prose_list(); legal()
    page_break(); hyphen_break(); table_footnote(); legal_emdash(); misses()
    print('fixtures built')
