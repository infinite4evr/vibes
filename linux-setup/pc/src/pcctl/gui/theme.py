"""Colours: a clean, neutral "Modern" look (default) or Catppuccin Latte/Mocha, each in light and dark.

Light/dark follows GNOME's style (or the user's choice), and in the Modern look the accent follows GNOME's accent colour.
style.css is a template: `$name` tokens are filled from the active palette, and the whole stylesheet is reloaded when
the style or accent changes, so the app switches live together with the rest of the desktop.

Palettes keep Catppuccin's token names (mauve = accent, surface0 = tracks, overlay1 = dim text…) so every widget and
page works with any of them.
"""

from __future__ import annotations

import os
import re
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

MOCHA = {
    "rosewater": "#f5e0dc", "flamingo": "#f2cdcd", "pink": "#f5c2e7", "mauve": "#cba6f7", "red": "#f38ba8", "maroon": "#eba0ac",
    "peach": "#fab387", "yellow": "#f9e2af", "green": "#a6e3a1", "teal": "#94e2d5", "sky": "#89dceb", "sapphire": "#74c7ec",
    "blue": "#89b4fa", "lavender": "#b4befe", "text": "#cdd6f4", "subtext1": "#bac2de", "subtext0": "#a6adc8", "overlay2": "#9399b2",
    "overlay1": "#7f849c", "overlay0": "#6c7086", "surface2": "#585b70", "surface1": "#45475a", "surface0": "#313244",
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    # roles
    "window": "#1e1e2e", "view": "#181825", "headerbar": "#181825", "sidebar": "#181825", "card": "#262637", "popover": "#313244",
    "dialog": "#1e1e2e", "code": "#11111b", "on_color": "#11111b", "accent_fg": "#11111b", "sel_fg": "#f5e0dc",
    "track": "#313244", "grid": "#45475a",
}

LATTE = {
    "rosewater": "#dc8a78", "flamingo": "#dd7878", "pink": "#ea76cb", "mauve": "#8839ef", "red": "#d20f39", "maroon": "#e64553",
    "peach": "#fe640b", "yellow": "#df8e1d", "green": "#40a02b", "teal": "#179299", "sky": "#04a5e5", "sapphire": "#209fb5",
    "blue": "#1e66f5", "lavender": "#7287fd", "text": "#4c4f69", "subtext1": "#5c5f77", "subtext0": "#6c6f85", "overlay2": "#7c7f93",
    "overlay1": "#8c8fa1", "overlay0": "#9ca0b0", "surface2": "#acb0be", "surface1": "#bcc0cc", "surface0": "#ccd0da",
    "base": "#eff1f5", "mantle": "#e6e9ef", "crust": "#dce0e8",
    "window": "#eff1f5", "view": "#fbfbfd", "headerbar": "#e6e9ef", "sidebar": "#e6e9ef", "card": "#ffffff", "popover": "#ffffff",
    "dialog": "#f4f5f8", "code": "#e6e9ef", "on_color": "#ffffff", "accent_fg": "#ffffff", "sel_fg": "#4c4f69",
    "track": "#dce0e8", "grid": "#ccd0da",
}
MOCHA.update({"line": "#313244", "line_soft": "#2a2b3c", "hover": "#2a2b3c", "accent_bg": "#cba6f7", "field": "#262637", "shadow": "rgba(0,0,0,0.35)"})
LATTE.update({"line": "#dce0e8", "line_soft": "#e6e9ef", "hover": "#eceef3", "accent_bg": "#8839ef", "field": "#e6e9ef", "shadow": "rgba(16,24,40,0.08)"})

# Modern: neutral greys, white cards with hairline borders, one accent colour (GNOME's), readable status colours.
MODERN_LIGHT = {
    "rosewater": "#e11d48", "flamingo": "#f43f5e", "pink": "#db2777", "mauve": "#2563eb", "red": "#dc2626", "maroon": "#be123c",
    "peach": "#d97706", "yellow": "#ca8a04", "green": "#16a34a", "teal": "#0d9488", "sky": "#0284c7", "sapphire": "#0891b2",
    "blue": "#2563eb", "lavender": "#6366f1", "text": "#1f2329", "subtext1": "#373d47", "subtext0": "#555d69", "overlay2": "#6b7380",
    "overlay1": "#7f8794", "overlay0": "#9aa1ac", "surface2": "#c7ccd4", "surface1": "#dde1e7", "surface0": "#eceff3",
    "base": "#ffffff", "mantle": "#f6f7f9", "crust": "#eceff3",
    "window": "#ffffff", "view": "#ffffff", "headerbar": "#ffffff", "sidebar": "#f6f7f9", "card": "#ffffff", "popover": "#ffffff",
    "dialog": "#ffffff", "code": "#f6f8fa", "on_color": "#ffffff", "accent_fg": "#ffffff", "sel_fg": "#1f2329",
    "track": "#eceff3", "grid": "#e8ebef", "line": "#e4e7ec", "line_soft": "#eef0f3", "hover": "#f4f6f8", "accent_bg": "#2563eb",
    "field": "#f1f3f6", "shadow": "rgba(16,24,40,0.08)",
}
MODERN_DARK = {
    "rosewater": "#fb7185", "flamingo": "#fda4af", "pink": "#f472b6", "mauve": "#7cacf8", "red": "#f87171", "maroon": "#fb7185",
    "peach": "#fbbf24", "yellow": "#facc15", "green": "#4ade80", "teal": "#2dd4bf", "sky": "#38bdf8", "sapphire": "#22d3ee",
    "blue": "#60a5fa", "lavender": "#a5b4fc", "text": "#e7e9ed", "subtext1": "#c9ced6", "subtext0": "#a9b0bb", "overlay2": "#949ba7",
    "overlay1": "#7d8591", "overlay0": "#666d78", "surface2": "#4a505a", "surface1": "#3a3f48", "surface0": "#2c3038",
    "base": "#17191d", "mantle": "#1d2025", "crust": "#121417",
    "window": "#17191d", "view": "#17191d", "headerbar": "#17191d", "sidebar": "#1d2025", "card": "#1f2227", "popover": "#262a30",
    "dialog": "#1f2227", "code": "#121417", "on_color": "#ffffff", "accent_fg": "#ffffff", "sel_fg": "#e7e9ed",
    "track": "#2c3038", "grid": "#2a2e35", "line": "#2d3139", "line_soft": "#24272d", "hover": "#23262c", "accent_bg": "#3b82f6",
    "field": "#23262c", "shadow": "rgba(0,0,0,0.4)",
}
THEMES = {"modern": (MODERN_LIGHT, MODERN_DARK), "catppuccin": (LATTE, MOCHA)}

# GNOME accent names -> (fill, text on light, text on dark); used when libadwaita can't tell us (older than 1.6)
ACCENTS = {
    "blue": ("#3584e4", "#0461be", "#81d0ff"), "teal": ("#2190a4", "#007184", "#7bdff4"), "green": ("#3a944a", "#15772e", "#8de698"),
    "yellow": ("#c88800", "#905300", "#ffc057"), "orange": ("#ed5b00", "#c34100", "#ff9c5b"), "red": ("#e62d42", "#c30000", "#ff888c"),
    "pink": ("#d56199", "#a2326c", "#ffa0d8"), "purple": ("#9141ac", "#8939a4", "#fba7ff"), "slate": ("#6f8396", "#526678", "#bbd1e5"),
}

_dark = True
_look = "modern"
_accent: tuple[str, str] | None = None  # (fill, text) for the current light/dark
_provider: Gtk.CssProvider | None = None
_listeners: list[Callable[[bool], None]] = []


def is_dark() -> bool:
    return _dark


def palette() -> dict[str, str]:
    light, dark = THEMES.get(_look, THEMES["modern"])
    pal = dict(dark if _dark else light)
    if _look == "modern" and _accent:
        pal["accent_bg"], pal["mauve"] = _accent
    return pal


def _rgba_hex(c) -> str:
    return "#{:02x}{:02x}{:02x}".format(round(c.red * 255), round(c.green * 255), round(c.blue * 255))


def _acc_fn(name: str):
    """adw_accent_color_* helpers: PyGObject exposes them either on the module or on the AccentColor enum."""
    f = getattr(Adw, f"accent_color_{name}", None)
    return f if f is not None else getattr(getattr(Adw, "AccentColor", None), name, None)


def system_accent(dark: bool) -> tuple[str, str] | None:
    """GNOME's accent colour as (fill, text) hex, from libadwaita 1.6+ or the GNOME setting; None if unknown."""
    sm = Adw.StyleManager.get_default()
    to_rgba, to_text = _acc_fn("to_rgba"), _acc_fn("to_standalone_rgba")
    if hasattr(sm, "get_accent_color") and to_rgba is not None:
        try:
            if hasattr(sm, "get_system_supports_accent_colors") and not sm.get_system_supports_accent_colors():
                return None
            ac = sm.get_accent_color()
            fill = _rgba_hex(to_rgba(ac))
            text = _rgba_hex(to_text(ac, dark)) if to_text is not None else fill
            return fill, text
        except Exception:  # noqa: BLE001
            pass
    try:
        from gi.repository import Gio
        src = Gio.SettingsSchemaSource.get_default()
        schema = src.lookup("org.gnome.desktop.interface", True) if src else None
        if schema is not None and schema.has_key("accent-color"):
            name = Gio.Settings.new("org.gnome.desktop.interface").get_string("accent-color")
            if name in ACCENTS:
                fill, light_text, dark_text = ACCENTS[name]
                return fill, dark_text if dark else light_text
    except Exception:  # noqa: BLE001
        pass
    return None


def look() -> str:
    return _look


def hex(name: str) -> str:  # noqa: A001
    return palette().get(name, name if name.startswith("#") else "#ff00ff")


def span(name: str, text_markup: str) -> str:
    """Pango markup in a palette colour (text_markup must already be escaped)."""
    return f"<span foreground='{hex(name)}'>{text_markup}</span>"


def on_change(fn: Callable[[bool], None]) -> None:
    _listeners.append(fn)


def _css_text() -> str:
    path = os.path.join(os.path.dirname(__file__), "style.css")
    with open(path, encoding="utf-8") as f:
        tpl = f.read()
    pal = palette()
    if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 16):  # CSS variables (:root) arrived in GTK 4.16
        tpl = re.sub(r":root\s*\{[^}]*\}", "", tpl)
    return re.sub(r"\$([a-z_0-9]+)", lambda m: pal.get(m.group(1), m.group(0)), tpl)


def _load_css() -> None:
    global _provider
    display = Gdk.Display.get_default()
    if display is None:
        return
    css = _css_text()
    if _provider is None:
        _provider = Gtk.CssProvider()
        add = getattr(Gtk, "style_context_add_provider_for_display", None) or Gtk.StyleContext.add_provider_for_display
        add(display, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    if hasattr(_provider, "load_from_string"):
        _provider.load_from_string(css)
    else:  # GTK < 4.12
        _provider.load_from_data(css, -1)


SCHEMES = {"system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}


def setup(mode: str = "system", look_name: str = "modern") -> None:
    """Call once at startup."""
    global _look
    _look = look_name if look_name in THEMES else "modern"
    sm = Adw.StyleManager.get_default()
    sm.set_color_scheme(SCHEMES.get(mode, Adw.ColorScheme.DEFAULT))
    sm.connect("notify::dark", lambda *_: _refresh())
    if hasattr(sm, "get_accent_color"):
        sm.connect("notify::accent-color", lambda *_: _refresh(force=True))
    _refresh(initial=True)


def set_mode(mode: str) -> None:
    Adw.StyleManager.get_default().set_color_scheme(SCHEMES.get(mode, Adw.ColorScheme.DEFAULT))
    _refresh()


def set_look(name: str) -> None:
    global _look
    _look = name if name in THEMES else "modern"
    _refresh(force=True)


def _refresh(initial: bool = False, force: bool = False) -> None:
    global _dark, _accent
    dark = Adw.StyleManager.get_default().get_dark()
    changed = dark != _dark
    _dark = dark
    if initial or changed or force:
        _accent = system_accent(dark)
        _load_css()
        for fn in list(_listeners):
            try:
                fn(dark)
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()


def redraw_tree(widget: Gtk.Widget) -> None:
    """Custom-drawn widgets (graphs, gauges, bars) paint with palette colours; repaint them after a switch."""
    if isinstance(widget, Gtk.DrawingArea):
        widget.queue_draw()
    child = widget.get_first_child()
    while child is not None:
        redraw_tree(child)
        child = child.get_next_sibling()
