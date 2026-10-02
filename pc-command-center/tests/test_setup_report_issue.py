"""ubuntu-setup's "Create GitHub issue" link: redacted and short enough for GitHub."""
import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SETUP = Path(__file__).resolve().parents[2] / "ubuntu-setup"


def load():
    spec = importlib.util.spec_from_file_location("report_issue", SETUP / "lib" / "report_issue.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_link_is_redacted_and_fits(tmp_path):
    m = load()
    home = str(Path.home())
    log = tmp_path / "log.txt"
    log.write_text("\n".join(f"line {i} {home}/x 192.168.1.20 aa:bb:cc:dd:ee:ff password=hunter2 a@b.com" for i in range(2000)))
    url = m.link("Couldn't install x", f"Couldn't install x in {home}", str(log))
    assert url.startswith("https://github.com/infinite4evr/vibes/issues/new?") and len(url) <= m.MAX_URL
    body = parse_qs(urlparse(url).query)["body"][0]
    for secret in ("192.168.1.20", "aa:bb:cc:dd:ee:ff", "hunter2", "a@b.com"):
        assert secret not in body
    assert home not in body or home == "/"
    assert "### Error" in body and "### Log (end)" in body and "line 1999" in body
