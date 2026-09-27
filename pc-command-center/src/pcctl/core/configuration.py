"""Typed configuration inventory for settings PC Command Center can inspect/manage.

UI code deliberately does not know how individual subsystems are probed.  New
configuration providers can be added here without growing the Configuration page.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from . import privacy, tweaks


@dataclass(frozen=True, slots=True)
class ConfigItem:
    id: str
    section: str
    title: str
    value: str
    source: str
    description: str = ""
    recommended: bool | None = None
    available: bool = True


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    items: tuple[ConfigItem, ...]
    provider_errors: tuple[str, ...] = ()

    @property
    def sections(self) -> int:
        return len({item.section for item in self.items})

    @property
    def unknown(self) -> int:
        return sum(item.value.lower() in {"unknown", "unavailable", "?"} for item in self.items)


def _desktop() -> Iterable[ConfigItem]:
    for switch, enabled in tweaks.desktop_switches():
        yield ConfigItem(
            id=f"gsettings:{switch.schema}:{switch.key}", section=switch.group,
            title=switch.title, value="On" if enabled else "Off",
            source=f"GNOME · {switch.schema} · {switch.key}", description=switch.desc,
        )


def _privacy() -> Iterable[ConfigItem]:
    for setting in privacy.settings():
        if isinstance(setting.value, bool):
            value = "On" if setting.value else "Off"
        elif setting.value is None:
            value = "Unknown"
        else:
            value = str(setting.value)
        yield ConfigItem(
            id=f"gsettings:{setting.schema}:{setting.key}", section="Privacy",
            title=setting.title, value=value,
            source=f"GNOME · {setting.schema} · {setting.key}", description=setting.desc,
        )


def _system_tweaks() -> Iterable[ConfigItem]:
    for tweak in tweaks.system_tweaks():
        yield ConfigItem(
            id=f"tweak:{tweak.id}", section=f"System · {tweak.group}", title=tweak.title,
            value=tweak.state or "Unknown", source="PC Command Center system probe",
            description=tweak.desc, recommended=tweak.applied,
        )


PROVIDERS: tuple[tuple[str, Callable[[], Iterable[ConfigItem]]], ...] = (
    ("Desktop", _desktop), ("Privacy", _privacy), ("System", _system_tweaks),
)


def snapshot() -> ConfigSnapshot:
    """Collect all providers independently; one broken probe never blanks the page."""
    items: list[ConfigItem] = []
    errors: list[str] = []
    seen: set[str] = set()
    for name, provider in PROVIDERS:
        try:
            for item in provider():
                if item.id in seen:
                    continue
                seen.add(item.id)
                items.append(item)
        except Exception as exc:  # noqa: BLE001 - inventory must remain partially useful
            errors.append(f"{name}: {exc}")
    items.sort(key=lambda x: (x.section.casefold(), x.title.casefold()))
    return ConfigSnapshot(tuple(items), tuple(errors))
