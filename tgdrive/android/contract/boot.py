"""Start TG Drive's service the way the Android app does (tgdrive.mobile.start), print its info as
one JSON line, and keep it running.   python boot.py <demo|real> <data_dir>"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # tgdrive/ (the package, run.py, tests)
from tgdrive import mobile  # noqa: E402

info = json.loads(mobile.start(json.dumps({
    "data_dir": sys.argv[2], "download_dir": sys.argv[2] + "/downloads", "model_dir": "", "fts5_library": "libtgfts5.so",
    "token": "contract-token", "media_token": "contract-media", "demo": sys.argv[1] == "demo"})))
print(json.dumps(info), flush=True)
while True:
    time.sleep(3600)
