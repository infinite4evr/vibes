"""The pieces that let the server run inside the Android app (where FastAPI, rapidfuzz, cryptg and
friends have no builds) must behave exactly like what they stand in for."""
import os
import random
import string

import pytest

# ------------------------------------------------------------------ native AES


def _pyaes_ige(data: bytes, key: bytes, iv: bytes, encrypt: bool) -> bytes:
    import pyaes
    aes = pyaes.AES(key)
    iv1, iv2 = iv[:16], iv[16:]
    out = bytearray()
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        if encrypt:
            c = bytes(a ^ b for a, b in zip(aes.encrypt([x ^ y for x, y in zip(block, iv1)]), iv2))
            iv1, iv2 = c, block
        else:
            p = bytes(a ^ b for a, b in zip(aes.decrypt([x ^ y for x, y in zip(block, iv2)]), iv1))
            iv1, iv2 = block, p
            c = p
        out += c
    return bytes(out)


def test_openssl_ige_matches_reference():
    from tgdrive import fastcrypto
    lib = fastcrypto.load_libcrypto()
    if lib is None:
        pytest.skip("no libcrypto on this system")
    ige = fastcrypto.IGE(lib)
    rnd = random.Random(1)
    for n in (16, 32, 160, 4096):
        data, key, iv = rnd.randbytes(n), rnd.randbytes(32), rnd.randbytes(32)
        enc = ige.encrypt(data, key, iv)
        assert enc == _pyaes_ige(data, key, iv, True)
        assert ige.decrypt(enc, key, iv) == data
        assert _pyaes_ige(enc, key, iv, False) == data


def test_openssl_ctr_matches_pyaes_across_uneven_chunks():
    import pyaes
    from tgdrive import fastcrypto
    lib = fastcrypto.load_libcrypto()
    if lib is None:
        pytest.skip("no libcrypto on this system")
    ctr_cls = fastcrypto._ctr_class(lib)
    rnd = random.Random(2)
    key, iv = rnd.randbytes(32), rnd.randbytes(16)
    ref = pyaes.AESModeOfOperationCTR(key)
    ref._counter._counter = list(iv)
    mine = ctr_cls(key, iv)
    for n in (1, 15, 16, 17, 100, 1000, 0, 4096, 3):
        chunk = rnd.randbytes(n)
        assert mine.encrypt(chunk) == ref.encrypt(chunk)


def test_install_makes_telethon_use_native_code():
    from tgdrive import fastcrypto
    if fastcrypto.load_libcrypto() is None:
        pytest.skip("no libcrypto on this system")
    used = fastcrypto.install()
    assert used in ("cryptg", "openssl")
    from telethon.crypto import AES, AESModeCTR
    key, iv = os.urandom(32), os.urandom(32)
    data = os.urandom(1024)
    assert AES.decrypt_ige(AES.encrypt_ige(data, key, iv), key, iv) == data
    c1, c2 = AESModeCTR(key, iv[:16]), AESModeCTR(key, iv[:16])
    assert c2.decrypt(c1.encrypt(data)) == data


# ------------------------------------------------------------ typo correction
def _vocab(n=6000):
    rnd = random.Random(5)
    base = "series polity economy history geography notes lecture quantum mechanics physics current affairs " \
           "environment ethics answer writing mains prelims syllabus magazine monthly".split()
    out = set(base)
    while len(out) < n:
        w = rnd.choice(base)
        op = rnd.random()
        if op < 0.5:
            w = "".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(3, 12)))
        else:
            i = rnd.randrange(len(w))
            w = w[:i] + rnd.choice(string.ascii_lowercase) + w[i + 1:]
        out.add(w)
    return sorted(out)


def test_fuzzy_numpy_matches_plain_osa():
    from tgdrive import fuzzy
    terms = _vocab()
    m = fuzzy.Matcher(terms)
    for q in ("seires", "polty", "economi", "histroy", "mechanisc", "lectrue", "zzzzqq", "notes", "abcd"):
        for k in (1, 2):
            want = sorted(((i, d) for i, t in enumerate(m.terms) for d in (fuzzy.osa(q, t, k),) if d is not None),
                          key=lambda h: (h[1], h[0]))[:40]
            assert m.within(q, k) == [(m.terms[i], d) for i, d in want], (q, k)


def test_fuzzy_agrees_with_rapidfuzz():
    rf = pytest.importorskip("rapidfuzz")
    from rapidfuzz import distance, process
    from tgdrive import fuzzy
    terms = _vocab()
    m = fuzzy.Matcher(terms)
    for q in ("seires", "polty", "economi", "histroy", "mechanisc", "lectrue", "sylabus", "magzine"):
        for k in (1, 2):
            want = {(t, d) for t, d, _ in process.extract(q, terms, scorer=distance.DamerauLevenshtein.distance,
                                                          score_cutoff=k, limit=None)}
            got = set(m.within(q, k, limit=10_000))
            assert got == want, (q, k, want ^ got)
    assert rf


def test_fuzzy_without_numpy(monkeypatch):
    from tgdrive import fuzzy
    monkeypatch.setattr(fuzzy, "np", None)
    m = fuzzy.Matcher(["series", "serious", "polity", "policy"])
    assert m.within("seires", 2) == [("series", 1)]
    assert m.within("seriou", 2) == [("serious", 1), ("series", 2)]
    assert [t for t, _ in m.within("polty", 1)] == ["polity"]


# --------------------------------------------------------------- web adapter
def test_lite_adapter_behaves_like_fastapi():
    from starlette.testclient import TestClient
    from tgdrive._lite import Body, FastAPI, Request
    from typing import Optional

    app = FastAPI()

    @app.get("/n/{a}/{b}")
    async def nums(a: int, b: str, q: Optional[int] = None, flag: bool = False):
        return {"a": a, "b": b, "q": q, "flag": flag}

    @app.post("/body")
    async def body(body: dict = Body(...)):
        return body

    @app.post("/opt")
    async def opt(body: dict = Body(default={})):
        body["seen"] = True
        return body

    @app.get("/req/{rest:path}")
    def sync(rest: str, request: Request):
        return {"rest": rest, "m": request.method}

    c = TestClient(app)
    assert c.get("/n/-100123/x?q=-5&flag=yes").json() == {"a": -100123, "b": "x", "q": -5, "flag": True}
    assert c.get("/n/1.5/x").status_code == 422
    assert c.get("/n/1/x?q=abc").status_code == 422
    assert c.post("/body", json={"k": 1}).json() == {"k": 1}
    assert c.post("/body").status_code == 422
    assert c.post("/body", json=[1, 2]).status_code == 422
    assert c.post("/opt").json() == {"seen": True}
    assert c.post("/opt").json() == {"seen": True}   # the default is copied, not shared between requests
    assert c.get("/req/a/b/c.txt").json() == {"rest": "a/b/c.txt", "m": "GET"}
    r = c.get("/missing")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_qr_sign_in_result_can_be_collected_after_it_finishes():
    """Finishing a QR sign-in removes the attempt; the app's next status poll must still see "done"
    with the account (it used to get "This sign-in attempt expired")."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from tgdrive import accounts

    class Qr:
        expires = datetime.now(timezone.utc) + timedelta(seconds=60)

        async def wait(self, timeout=None):
            return None

    mgr = accounts.AccountManager.__new__(accounts.AccountManager)
    mgr.accounts, mgr.logins, mgr.done_logins = {}, {}, {}
    lg = SimpleNamespace(id="abc", qr=Qr(), qr_state="waiting", qr_error=None, hint="", result=None, created=0, qr_task=None)
    mgr.logins[lg.id] = lg

    async def finish(login):
        mgr.logins.pop(login.id, None)
        return {"id": 42, "name": "Priya"}

    mgr._finish = finish

    async def go():
        await mgr._qr_wait(lg)
        return await mgr.login_qr_status("abc")

    st = asyncio.run(go())
    assert st["state"] == "done" and st["account"]["name"] == "Priya"
