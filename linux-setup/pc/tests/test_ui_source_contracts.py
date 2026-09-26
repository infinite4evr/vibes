"""Static UI contracts that must stay testable even on non-GTK build hosts.

The normal GTK screenshot suite is intentionally skipped when PyGObject/libadwaita
is not installed.  These checks catch source-level UI breakages that previously
slipped through that gap (notably unsupported keyword arguments passed to the
responsive ``flow`` helper, which made entire pages disappear at runtime).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "pcctl"
GUI = SRC / "gui"
PAGES = GUI / "pages"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _flow_signature_keywords() -> set[str]:
    tree = _tree(GUI / "util.py")
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "flow")
    return {a.arg for a in (*fn.args.args, *fn.args.kwonlyargs)} - {"children"}


def test_every_flow_call_uses_supported_keywords() -> None:
    supported = _flow_signature_keywords()
    bad: list[str] = []
    for path in GUI.rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            called_flow = isinstance(node.func, ast.Name) and node.func.id == "flow"
            if not called_flow:
                continue
            unknown = sorted(kw.arg for kw in node.keywords if kw.arg and kw.arg not in supported)
            if unknown:
                bad.append(f"{path.relative_to(ROOT)}:{node.lineno}: {', '.join(unknown)}")
    assert not bad, "flow() calls use unsupported keyword(s):\n" + "\n".join(bad)


def test_sidebar_sections_have_real_page_modules_with_matching_ids() -> None:
    window_tree = _tree(GUI / "window.py")
    sections_node = next(
        n for n in window_tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SECTIONS" for t in n.targets)
    )
    sections = ast.literal_eval(sections_node.value)
    missing: list[str] = []
    mismatched: list[str] = []
    for _section, ids in sections:
        for pid in ids:
            page_file = PAGES / f"{pid}.py"
            if not page_file.exists():
                missing.append(pid)
                continue
            ids_found = {
                n.value.value
                for n in ast.walk(_tree(page_file))
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "ID" for t in n.targets)
                and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)
            }
            if pid not in ids_found:
                mismatched.append(f"{pid} -> {sorted(ids_found)}")
    assert not missing, f"sidebar page modules missing: {missing}"
    assert not mismatched, f"sidebar page IDs do not match modules: {mismatched}"


def test_page_construction_failure_is_not_hidden_from_sidebar() -> None:
    source = (GUI / "window.py").read_text(encoding="utf-8")
    assert "self.rows[pid].set_visible(False)" not in source
    assert "_UnavailablePage(self, pid, cls, exc, trace)" in source


def test_sidebar_width_is_content_aware_not_desktop_fixed() -> None:
    source = (GUI / "window.py").read_text(encoding="utf-8")
    assert "proportional = int(width * 0.28)" in source
    assert "CONTENT_MIN_WHILE_SIDEBAR_VISIBLE = 650" in source
    assert "SIDEBAR_MAX = 300" in source


def test_compact_header_keeps_search_reachable() -> None:
    source = (GUI / "window.py").read_text(encoding="utf-8")
    assert "search_compact_btn" in source
    assert "content_width < COMPACT_HEADER_AT" in source
    assert 'self.search_compact_btn.connect("clicked", lambda *_: self.palette())' in source


def test_page_header_actions_can_wrap_on_compact_windows() -> None:
    source = (PAGES / "base.py").read_text(encoding="utf-8")
    assert 'css="page-header-flow"' in source
    assert "row = hbox(t, acts, spacing=12)" not in source
    assert "notify::width" in source and "_adapt_page_spacing" in source
