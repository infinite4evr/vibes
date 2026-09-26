from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def test_package_and_module_versions_match():
    pyproject = tomllib.loads((ROOT / "pc" / "pyproject.toml").read_text(encoding="utf-8"))
    init_text = (ROOT / "pc" / "src" / "pcctl" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', init_text)
    assert m
    assert pyproject["project"]["version"] == m.group(1)


def test_installer_verifies_gui_version():
    text = (ROOT / "lib" / "install.sh").read_text(encoding="utf-8")
    assert 'Source version: $source_version' in text
    assert 'installed_version' in text
    assert 'Version verification failed' in text
    assert 'fully quit it (Ctrl+Q)' in text
