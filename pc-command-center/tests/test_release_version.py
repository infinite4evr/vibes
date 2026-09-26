from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, still supported (Ubuntu 22.04)
    tomllib = None

PROJECT = Path(__file__).resolve().parents[1]
SETUP = PROJECT.parent / "ubuntu-setup"


def test_package_and_module_versions_match():
    text = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    if tomllib:
        version = tomllib.loads(text)["project"]["version"]
    else:
        version = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)
    init_text = (PROJECT / "src" / "pcctl" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', init_text)
    assert m
    assert version == m.group(1)


def test_installer_verifies_gui_version():
    text = (SETUP / "lib" / "install.sh").read_text(encoding="utf-8")
    assert 'Source version: $source_version' in text
    assert 'installed_version' in text
    assert 'Version verification failed' in text
    assert 'fully quit it (Ctrl+Q)' in text
