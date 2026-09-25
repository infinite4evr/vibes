"""Keep tests away from the real data folder and settings."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="tgdrive-test-")
os.environ["TGDRIVE_DATA"] = _TMP
os.environ.pop("TG_API_ID", None)
os.environ.pop("TG_API_HASH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_settings(tmp_path):
    from tgdrive import settings as st
    st.reload_for_tests(tmp_path / "settings.json")
    st.settings.data.update(search_semantic=False, download_dir=str(tmp_path / "Downloads"), notifications=True,
                            verify_deleted=False)
    st.settings.listeners = [fn for fn in st.settings.listeners if not getattr(fn, "__self__", None)
                             or type(fn.__self__).__name__ not in ("Transfers",)]
    yield st.settings
