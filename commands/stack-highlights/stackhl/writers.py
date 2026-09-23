"""Writers: Markdown, plain text and JSON output.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import json
from .rendering import md_guard
from .checklist import check_in_book_json


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_markdown(entries, cfg, level_shift=0):
    out = []
    shown = []
    last_text = None
    n_since = 0
    for e in entries:
        path = e.crumbs
        if cfg.headings:
            k = 0
            while k < len(path) and k < len(shown) and path[k][2] == shown[k][2] and path[k][1] == shown[k][1]:
                k += 1
            for lvl, htxt, _ in path[k:]:
                if e.kind == "heading" and (lvl, htxt, _) == path[-1]:
                    break
                n = min(6, max(1, lvl + level_shift))
                out.append("#" * n + " " + htxt)
                out.append("")
            shown = path
        if e.kind == "heading":
            if not path:          # heading filtered out by --heading-depth; nothing to emit
                continue
            lvl, htxt, _ = path[-1]
            n = min(6, max(1, lvl + level_shift))
            out.append("#" * n + " " + htxt)
            out.append("")
            continue
        body_lines = [md_guard(l) for l in e.lines]
        if cfg.page_refs:
            body_lines[-1] += f" (p. {e.page_label})"
        text = "\\\n".join(body_lines)
        if text == last_text and not e.subs:
            continue
        last_text = text
        out.append(text)
        out.append("")
        for label, sub in e.subs:
            out.append(f"> {label}: {sub}")
            out.append("")
        n_since += 1
        if cfg.space_n and n_since % cfg.space_n == 0:
            # raw LaTeX so the space survives (pandoc collapses blank lines)
            style = getattr(cfg, "space_style", "blank")
            out.append("```{=latex}")
            if style in ("ruled", "dotted"):
                fill = r"\rule{\linewidth}{0.2pt}" if style == "ruled" else r"\leavevmode\dotfill"
                line = r"\par\noindent\textcolor[gray]{0.72}{%s}\vspace{\baselineskip}" % fill
                out.append(r"\par\vspace{0.5\baselineskip}" + line * cfg.space_m)
            else:
                out.append(f"\\vspace{{{cfg.space_m}\\baselineskip}}")
            out.append("```")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_text(entries, cfg):
    out = []
    shown = []
    for e in entries:
        path = e.crumbs
        if cfg.headings:
            k = 0
            while k < len(path) and k < len(shown) and path[k][2] == shown[k][2]:
                k += 1
            for lvl, htxt, _ in path[k:]:
                out.append(("=" * max(1, 4 - lvl)) + " " + htxt + " " + ("=" * max(1, 4 - lvl)))
                out.append("")
            shown = path
        if e.kind == "heading":
            continue
        lines = list(e.lines)
        if cfg.page_refs:
            lines[-1] += f" (p. {e.page_label})"
        out.append("\n".join(lines))
        for label, sub in e.subs:
            out.append(f"    {label}: {sub}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def runs_from_md(line):
    """Tokenise one rendered Markdown line into runs -- the single source of
    truth for what recall-sheet (and any JSON consumer) needs, so no one has
    to re-parse Markdown or undo escaping. Each run is
    {"text": unescaped, "mark": bool, "italic": bool}; **bold** is a mark,
    ***bold+italic*** a non-yellow mark, plain text is context."""
    runs, buf, bold, ital, i, n = [], [], False, False, 0, len(line)

    def flush():
        if buf:
            runs.append({"text": "".join(buf), "mark": bold, "italic": ital})
            buf.clear()

    while i < n:
        c = line[i]
        if c == "\\" and i + 1 < n:          # escaped char: keep the char, drop the backslash
            buf.append(line[i + 1]); i += 2
        elif line.startswith("***", i):
            flush(); bold = not bold; ital = not ital; i += 3
        elif line.startswith("**", i):
            flush(); bold = not bold; i += 2
        elif c == "*":
            flush(); ital = not ital; i += 1
        else:
            buf.append(c); i += 1
    flush()
    return runs


def write_json(entries, ctx):
    data = {
        "highlights": len(ctx.marks),
        "entries": [
            {
                "kind": e.kind,
                "headings": [{"level": lvl, "text": "".join(r["text"] for r in runs_from_md(h))}
                             for lvl, h, _ in e.crumbs],
                "page": e.page + 1,
                "page_label": e.page_label,
                "lines": [{"runs": runs_from_md(ln)} for ln in e.lines],
                "subs": [{"label": l, "runs": runs_from_md(t)} for l, t in e.subs],
                "marks": [{"kind": ctx.marks[m].kind, "color": ctx.marks[m].color,
                           "text": "".join(ctx.marks[m].text)} for m in sorted(e.mark_ids)],
            }
            for e in entries
        ],
    }
    unplaced = check_in_book_json(ctx)
    if unplaced:
        data["check_in_book"] = unplaced
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
