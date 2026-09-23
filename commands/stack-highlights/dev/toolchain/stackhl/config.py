"""Config file, presets and publisher profiles.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import os
import sys
from pathlib import Path
from .driver import find_pdfs, process_pdf, render
from .cli import build_parser, config_from_args


# ---------------------------------------------------------------------------
# Config file, presets and publisher profiles
#
# Resolution order, lowest precedence first:
#   built-in defaults  <  config [defaults]  <  --profile  <  --preset  <  CLI flags
# so an explicit flag always wins, and "no config, no preset" is byte-for-byte
# identical to the built-in defaults. Config is TOML; keys are the long flag
# names (hyphens or underscores both work), e.g. context, plain-titles, margin.
# ---------------------------------------------------------------------------
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover  (Python < 3.11)
    tomllib = None

# Named flag bundles. Editable/extendable in the config file under
# [preset.<name>]; a preset there overrides the built-in of the same name.
BUILTIN_PRESETS = {
    "print":  {"context": "sentence"},                     # clean full sentences to print
    "revise": {"context": "clause", "max_words": 25},      # tighter, for revision
    "dense":  {"context": "comma"},                        # tightest snippets
    "act":    {"context": "clause"},                       # bare acts read better clause-tight
}
# Publisher layout tuning. Left empty on purpose: good values must be measured
# per book. Define your own in the config under [profile.<name>], e.g.
#   [profile.laxmikanth]
#   margin = 0.08
#   column-tolerance = 24
BUILTIN_PROFILES = {}


def _norm_key(k):
    return k.strip().lstrip("-").replace("-", "_")


def _config_files(explicit, input_path):
    """Config files to read, lowest precedence first. Personal defaults from
    ~/.config/stack-highlights.toml, then a notes.toml sitting next to the
    book (which overrides personal settings for that book)."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            sys.exit(f"error: --config file not found: {p}")
        return [p]
    out = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    personal = base / "stack-highlights.toml"
    if personal.is_file():
        out.append(personal)
    if input_path:
        ip = Path(input_path).expanduser()
        book_dir = ip if ip.is_dir() else ip.parent
        book_cfg = book_dir / "notes.toml"
        if book_cfg.is_file():
            out.append(book_cfg)
    return out


def _load_toml(path):
    if tomllib is None:
        sys.exit("error: reading a config file needs Python 3.11+ (tomllib)")
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception as ex:
        sys.exit(f"error: could not read config {path}: {ex}")


def _valid_dests(parser):
    return {a.dest: a for a in parser._actions if a.dest not in ("help", "input")}


def _coerce(dest, value, action, where):
    """Light validation of a config-supplied value against the flag it maps to."""
    if action.choices is not None and value not in action.choices:
        sys.exit(f"error: {where}: {dest} must be one of {list(action.choices)}, got {value!r}")
    if action.type is float and isinstance(value, int):
        value = float(value)
    return value


def _apply_table(dst, table, valid, where):
    """Merge a TOML table of flag=value into dst (a dest->value dict)."""
    for raw, value in table.items():
        dest = _norm_key(raw)
        if dest not in valid:
            print(f"  warning  {where}: unknown setting {raw!r} ignored", file=sys.stderr)
            continue
        dst[dest] = _coerce(dest, value, valid[dest], where)


def resolve_args(argv=None):
    """Parse argv, then layer config, profile and preset underneath the
    explicit flags, and return the final namespace for config_from_args."""
    parser = build_parser()
    args = parser.parse_args(argv)
    valid = _valid_dests(parser)

    # which flags were given explicitly on the command line (they win)
    given = set()
    optmap = parser._option_string_actions
    for tok in (argv if argv is not None else sys.argv[1:]):
        key = tok.split("=", 1)[0]
        if key in optmap:
            given.add(optmap[key].dest)

    # collect config: [defaults], and preset/profile registries
    presets = {k: dict(v) for k, v in BUILTIN_PRESETS.items()}
    profiles = {k: dict(v) for k, v in BUILTIN_PROFILES.items()}
    conf_defaults = {}
    for path in _config_files(args.config, args.input):
        data = _load_toml(path)
        where = str(path)
        _apply_table(conf_defaults, data.get("defaults", {}), valid, f"{where} [defaults]")
        for name, tbl in (data.get("preset", {}) or {}).items():
            reg = {}
            _apply_table(reg, tbl, valid, f"{where} [preset.{name}]")
            presets.setdefault(name, {}).update(reg)
        for name, tbl in (data.get("profile", {}) or {}).items():
            reg = {}
            _apply_table(reg, tbl, valid, f"{where} [profile.{name}]")
            profiles.setdefault(name, {}).update(reg)

    # build the layered value set (low -> high precedence), tracking where
    # each setting's final value came from (for --explain)
    source = {dest: "default" for dest in valid}
    for dest in conf_defaults:
        source[dest] = "config"
    if args.profile:
        if args.profile not in profiles:
            sys.exit(f"error: unknown profile {args.profile!r} "
                     f"(define [profile.{args.profile}] in your config)")
        for dest in profiles[args.profile]:
            source[dest] = f"profile:{args.profile}"
    if args.preset:
        if args.preset not in presets:
            sys.exit(f"error: unknown preset {args.preset!r} "
                     f"(define [preset.{args.preset}] in your config)")
        for dest in presets[args.preset]:
            source[dest] = f"preset:{args.preset}"

    layered = dict(conf_defaults)
    if args.profile:
        layered.update(profiles[args.profile])
    if args.preset:
        layered.update(presets[args.preset])
    # apply config/profile/preset only where the user did NOT pass the flag
    for dest, value in layered.items():
        if dest not in given:
            setattr(args, dest, value)
    for dest in given:
        if dest in valid:
            source[dest] = "flag"

    args._source = source
    args._presets, args._profiles = presets, profiles
    return args


def explain(args):
    """Print the settings actually in effect (with where each came from) plus
    a small sample, without generating the full output. Answers --dry-run."""
    src = getattr(args, "_source", {})
    interesting = [
        "input", "format", "out", "context", "word_window", "word_side",
        "max_words", "min_words", "kinds", "colors", "plain_titles",
        "italic_colors", "color_tags", "headings", "heading_depth", "tables",
        "table_style", "footnotes", "dehyphenate", "keep_markers", "snap",
        "space_every", "page_refs", "margin", "sup_ratio", "footnote_ratio",
        "row_tolerance", "column_tolerance",
    ]
    print("Settings in effect:", file=sys.stderr)
    for dest in interesting:
        if not hasattr(args, dest):
            continue
        val = getattr(args, dest)
        origin = src.get(dest, "default")
        tag = "" if origin == "default" else f"   [{origin}]"
        print(f"  {dest:18} = {val!r}{tag}", file=sys.stderr)
    if args.preset:
        print(f"\n  preset  : {args.preset}", file=sys.stderr)
    if args.profile:
        print(f"  profile : {args.profile}", file=sys.stderr)

    # a small sample so a setup can be sanity-checked before a long run
    cfg = config_from_args(args)
    src_path = Path(cfg.input).expanduser()
    if src_path.is_dir():
        pdfs = find_pdfs(src_path, not cfg.no_recursive)
        src_path = pdfs[0] if pdfs else None
    if src_path and src_path.suffix.lower() == ".pdf":
        try:
            entries, ctx, _ = process_pdf(src_path, cfg, log=False)
        except Exception as ex:
            print(f"\n  (could not build sample: {ex})", file=sys.stderr)
            return
        print(f"\nSample -- first entries of {src_path.name}:", file=sys.stderr)
        shown = render(entries[:3], ctx, cfg) if entries else "(no highlighted entries found)"
        for line in shown.splitlines()[:24]:
            print("  " + line, file=sys.stderr)
