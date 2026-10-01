"""Sign-in reaches Telegram: with a made-up API key, Telegram itself must answer that the key is
wrong (not a timeout, not a crash). Exercises Telethon, the crypto stand-in and the sign-in API as
the app uses them.   python telegram_check.py <port>"""
import json
import sys
import urllib.request

port = sys.argv[1]
H = {"x-tgdrive-token": "contract-token", "x-tgdrive": "1", "content-type": "application/json"}


def call(path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers=H, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


print("setup:", call("/api/setup", {"api_id": "1234567", "api_hash": "0123456789abcdef0123456789abcdef"}))
code, res = call("/api/login/start", {"phone": "+15550100000"})
print("login/start:", code, res)
msg = str(res.get("error", ""))
if "rejected the API ID" in msg:
    print("OK: Telegram answered (the made-up key was rejected, as it should be)")
    sys.exit(0)
print("FAIL: expected Telegram to reject the made-up API key")
sys.exit(1)
