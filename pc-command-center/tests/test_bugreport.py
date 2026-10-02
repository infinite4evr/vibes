"""Error reporting: every error can become a redacted, pre-filled GitHub issue."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from pcctl import cli
from pcctl.core import bugreport

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "src" / "pcctl" / "gui"


@pytest.fixture(autouse=True)
def _isolated_logs(monkeypatch, tmp_path):
    monkeypatch.setattr(bugreport, "ERRORS_LOG", tmp_path / "gui-errors.log")
    monkeypatch.setattr(bugreport.debug, "LOG_FILE", tmp_path / "debug.log")


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_report_is_redacted(monkeypatch):
    monkeypatch.setattr(bugreport.socket, "gethostname", lambda: "kitchen-laptop")
    monkeypatch.setattr(bugreport.getpass, "getuser", lambda: "alice")
    home = str(Path.home())
    err = (f'File "{home}/proj/x.py", line 3\nOSError: alice on kitchen-laptop token=abcd1234efgh '
           "from 192.168.1.44 mac 20:c1:9b:92:15:ad v6 2606:4700:cf1:1000::1 at 08:37:12")
    q = _query(bugreport.Report(err, "Test").url())
    text = q["title"] + q["body"]
    for leaked in (home, "alice", "kitchen-laptop", "abcd1234efgh", "192.168.1.44", "20:c1:9b", "2606:4700"):
        assert leaked not in text
    assert "~/proj/x.py" in text and "08:37:12" in text, "useful context must survive redaction"


def test_title_uses_the_exception_line():
    tb = 'Traceback (most recent call last):\n  File "x.py", line 1\n    boom()\nKeyError: \'missing\''
    assert bugreport.Report(tb, "Network page").title == "[Network page] KeyError: 'missing'"


def test_url_fits_github_limit_and_keeps_the_end_of_the_trace(tmp_path):
    bugreport.ERRORS_LOG.write_text(time.strftime("== %Y-%m-%d %H:%M:%S ==\n") + "log line\n" * 5000)
    huge = "frame\n" * 4000 + "ValueError: the real cause"
    rep = bugreport.Report(huge, "Test")
    url = rep.url()
    assert url.startswith("https://github.com/infinite4evr/vibes/issues/new?")
    assert len(url) <= bugreport.MAX_URL
    body = _query(url)["body"]
    assert "ValueError: the real cause" in body
    assert "labels=bug" in url
    assert len(rep.full_text()) > len(body), "Copy/Save keep everything the link had to trim"


def test_only_recent_error_log_entries_are_attached():
    old = time.strftime("== %Y-%m-%d %H:%M:%S ==", time.localtime(time.time() - 5 * 86400))
    new = time.strftime("== %Y-%m-%d %H:%M:%S ==")
    bugreport.ERRORS_LOG.write_text(f"{old}\nOLD crash\n{new}\nNEW crash\n")
    logs = bugreport.recent_logs()
    assert "NEW crash" in logs and "OLD crash" not in logs


def test_save_is_private(tmp_path):
    p = bugreport.Report("ValueError: x", "Test").save(tmp_path)
    assert p.stat().st_mode & 0o777 == 0o600
    assert "ValueError: x" in p.read_text()


def test_cli_crash_prints_report_link(monkeypatch, capsys):
    def boom(_a):
        raise RuntimeError("kaboom")
    import argparse
    real = argparse.ArgumentParser.parse_args

    def parse(self, *a, **k):
        ns = real(self, *a, **k)
        ns.fn = boom
        return ns
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse)
    assert cli.main(["ports"]) == 1
    err = capsys.readouterr().err
    assert "RuntimeError: kaboom" in err
    assert "https://github.com/infinite4evr/vibes/issues/new?" in err
    assert "kaboom" in bugreport.ERRORS_LOG.read_text()


@pytest.mark.parametrize("path,needle", [
    ("main.py", "report_text(text"),                 # sys.excepthook (main-loop/signal callbacks)
    ("main.py", "threading.excepthook"),             # raw threads
    ("util.py", "Background task failed"),           # every bg() worker failure
    ("pages/base.py", "report_exception(e"),         # live-refresh timers
    ("window.py", "page could not be loaded"),       # page construction / import failures
    ("dialogs.py", "self.report_btn"),               # failed actions (not user-cancelled)
])
def test_every_gui_error_path_reaches_the_report_dialog(path, needle):
    assert needle in (GUI / path).read_text(encoding="utf-8")
