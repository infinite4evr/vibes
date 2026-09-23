"""Rendering of marked text to Markdown / plain text runs.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from .segmentation import sentence_bounds, trim_ws


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def md_escape(s):
    s = s.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_")
    s = s.replace("<", "\\<").replace("[", "\\[").replace("]", "\\]").replace("`", "\\`")
    return s


_PAREN_RE = re.compile(r"^(\s*)\((?:[0-9]{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,7})\)(?=\s)")
_ORDERED_RE = re.compile(r"^(\s*)([0-9]{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,7})([.)])(\s)")


def md_guard(line):
    """Neutralise Markdown block markers at the very start of a rendered
    line so a snippet prints exactly as written. In particular an ordered
    list marker like "3." keeps its real number: pandoc would otherwise
    renumber it (changing the very fact you highlighted), and an older
    version of this guard turned "3." into "\\3". We escape the dot/paren,
    never the number -- "3." -> "3\\.". recall-sheet's parser strips the
    backslash again, so this only ever affects the direct notes->PDF path."""
    m = re.match(r"^(\s*)([#>+]|-(?!-)|=+\s*$)", line)
    if m:
        pre = m.group(1)
        return pre + "\\" + line[len(pre):]
    m = _ORDERED_RE.match(line)
    if m:
        pre, tok, punct, _sp = m.groups()
        return f"{pre}{tok}\\{punct}{line[m.end() - 1:]}"
    # "(a)", "(i)", "(1)" -- pandoc would renumber these too ("(i)" after
    # "(b)" printed as "(c)"), so escape the opening bracket
    m = _PAREN_RE.match(line)
    if m:
        pre = m.group(1)
        return pre + "\\" + line[len(pre):]
    return line


MARK_STYLES = ("bold", "italic", "skip")   # 'underline' waits on the JSON model (needs raw LaTeX; soul is not portable)


def mark_style(cols, cfg):
    """Which emphasis a marked run gets, from its highlight colour(s).
    A --color-map wins; otherwise --italic-colors makes non-yellow italic;
    otherwise everything is bold."""
    cmap = getattr(cfg, "color_map", None)
    if cmap:
        for c in sorted(cols):
            if c in cmap:
                return cmap[c]
        return cmap.get("*", "bold")
    if getattr(cfg, "italic_colors", False) and cols and "yellow" not in cols:
        return "italic"
    return "bold"


def render_range(p, s, e, fmt, ctx, head=False, tail=False):
    """Render p.text[s:e] with marked characters emphasised (bold by default).
    Returns the string and records which marks were rendered (coverage)."""
    text, marks = p.text, p.marks
    parts = []
    i = s
    while i < e:
        m = marks[i]
        j = i
        while j < e and (marks[j] >= 0) == (m >= 0):
            j += 1
        seg = text[i:j]
        if m >= 0:
            lead = seg[:len(seg) - len(seg.lstrip())]
            trail = seg[len(seg.rstrip()):]
            core = seg.strip()
            ids = [marks[k] for k in range(i, j) if marks[k] >= 0]
            if fmt == "md":
                cols = {ctx.marks[k].color for k in ids}
                style = mark_style(cols, ctx.cfg) if core else "bold"
                if not core:
                    piece = ""
                elif style == "skip":
                    # intentionally not emphasised: keep the text as plain
                    # context and record that the mark was shown, not lost
                    piece = md_escape(core)
                    for k in ids:
                        ctx.marks[k].used = True
                        ctx.marks[k].skipped = True
                else:
                    esc = md_escape(core)
                    if style == "italic":
                        piece = f"***{esc}***"
                    else:
                        piece = f"**{esc}**"
                    if getattr(ctx.cfg, "color_tags", False) and cols and cols != {"yellow"}:
                        piece += "{" + ",".join(sorted(cols)) + "}"
                    for k in ids:
                        ctx.marks[k].used = True
            else:
                piece = core
                for k in ids:
                    ctx.marks[k].used = True
            parts.append(lead + piece + trail)
        else:
            parts.append(md_escape(seg) if fmt == "md" else seg)
        i = j
    out = "".join(parts).strip()
    if head:
        out = "… " + out
    if tail:
        out = out.rstrip(",;:—– ") + " …"
    return out


def leadin_text(p, cfg):
    """The sentence of the lead-in paragraph that introduces the list."""
    text = p.text
    ends = sentence_bounds(text[:-1] + "." if text.endswith((":", "—")) else text)
    starts = [0] + ends[:-1]
    s = starts[-1] if starts else 0
    s, e = trim_ws(text, s, len(text))
    words = text[s:e].split()
    head = False
    # with --word-window the lead-in is held to the same number of words
    limit = cfg.word_window if getattr(cfg, "word_window", 0) > 0 else cfg.max_words
    if len(words) > limit:
        cut = s + len(" ".join(words[:-limit])) + 1
        marked = [i for i in range(s, e) if p.marks[i] >= 0]
        if marked and marked[0] < cut:
            # a highlight inside the lead-in must stay visible: start a few
            # words before it instead
            back = max(1, limit // 2) if limit != cfg.max_words else 0
            k = marked[0]
            while k > s and text[k - 1] != " ":
                k -= 1
            for _ in range(back):
                j = k - 1
                while j > s and text[j - 1] == " ":
                    j -= 1
                while j > s and text[j - 1] != " ":
                    j -= 1
                if j <= s:
                    break
                k = j
            cut = min(cut, k)
        head = cut > s
        s = cut
    return s, e, head
