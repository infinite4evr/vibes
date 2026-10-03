"""End-to-end tests: the whole interface in a real browser (Chromium via Playwright), against the demo
server (a made-up Telegram account, no network). Every screen is visited and the everyday flows are clicked
through; failures (Telegram offline, a slow upload, a server error) are simulated by intercepting requests.

    pip install playwright pillow reportlab && python -m playwright install chromium
    python -m pytest tests/test_e2e.py -v

Skipped when Playwright or a Chromium build isn't available. Screenshots go to tests/.e2e-shots.
"""
import glob
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "tests" / ".e2e-shots"
H = {"X-TGDrive": "1"}

# Console messages that are expected in these tests: resources we made fail on purpose, and media that the
# demo's made-up files can't decode.
EXPECTED = re.compile(r"Failed to load resource|net::ERR_|MEDIA_ERR|NotSupportedError|no supported source|"
                      r"pdf page|Refused to|favicon|bug in the window|The play\(\) request was interrupted|DEMUXER_ERROR")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    while True:   # the media port is the next one; both must be free
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port + 1))
            break
        except OSError:
            port = _free_port()
    env = dict(os.environ, DEMO_PORT=str(port), TGDRIVE_DATA=tempfile.mkdtemp(prefix="tgdrive-e2e-"),
               PYTHONUNBUFFERED="1")
    env["TGDRIVE_LOCATION_FILE"] = str(Path(env["TGDRIVE_DATA"]) / "test-location.json")
    proc = subprocess.Popen([sys.executable, "-m", "tests.demo_server"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    end = time.time() + 120
    while time.time() < end:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        lines.append(line)
        if "demo on" in line:
            break
    else:
        proc.kill()
    if proc.poll() is not None or not any("demo on" in x for x in lines):
        proc.kill()
        pytest.fail("demo server didn't start:\n" + "".join(lines[-40:]))
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=os.environ.get("TGDRIVE_TEST_CHROMIUM"), args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Exception:
            exe = sorted(glob.glob(os.path.join(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"),
                                                "chromium-*/chrome-linux/chrome")))
            if not exe:
                pytest.skip("no Chromium for Playwright")
            b = p.chromium.launch(executable_path=exe[-1])
        yield b
        b.close()


class App:
    """One browser tab on TG Drive, with the problems it logged."""

    def __init__(self, page, base):
        self.page = page
        self.base = base
        self.problems = []
        page.on("pageerror", lambda e: self.problems.append(f"page error: {e}"))
        page.on("console", lambda m: m.type == "error" and not EXPECTED.search(m.text)
                and self.problems.append(f"console: {m.text}"))

    def open(self, hash_="#drive"):
        self.page.goto(f"{self.base}/{hash_}")
        self.page.wait_for_function("window.tgdrive && window.tgdrive.ready", timeout=30000)
        self.settle()
        return self

    def go(self, hash_):
        self.page.evaluate("h => { location.hash = h; }", hash_)
        self.settle()

    def settle(self, ms=350):
        self.page.wait_for_timeout(ms)
        self.page.wait_for_function("!document.documentElement.classList.contains('is-busy')", timeout=20000)

    def api(self, path, method="GET", body=None):
        r = self.page.request.fetch(f"{self.base}{path}", method=method,
                                    headers={**H, "Content-Type": "application/json"} if body is not None else H,
                                    data=json.dumps(body) if body is not None else None)
        assert r.ok, f"{method} {path}: {r.status} {r.text()[:300]}"
        return r.json()

    def aid(self):
        return self.page.evaluate("window.tgdrive.S.aid")

    def toast(self, text, timeout=8000):
        """A message: a toast, or for an error the error dialog (closed again here)."""
        dlg = self.page.locator(".error-dialog", has_text=text)
        expect(self.page.locator("#toasts .toast", has_text=text).or_(dlg).first).to_be_visible(timeout=timeout)
        if dlg.count():
            self.close_error_dialogs()

    def error_dialog(self, text, timeout=15000):
        """The "What went wrong" dialog for `text`, with its "Create GitHub issue" button; closed after."""
        dlg = self.page.locator(".error-dialog", has_text=text).first
        expect(dlg).to_be_visible(timeout=timeout)
        expect(dlg.get_by_role("button", name="Create GitHub issue")).to_be_visible()
        self.close_error_dialogs()

    def close_error_dialogs(self):
        for _ in range(20):
            dlg = self.page.locator(".backdrop:not(.leaving) .error-dialog")
            if not dlg.count():
                self.page.wait_for_timeout(300)   # the next waiting error opens a moment after one closes
                if not dlg.count():
                    return
            dlg.first.locator(".d-foot .btn", has_text="Close").click()
            self.page.wait_for_timeout(250)

    def shot(self, name):
        SHOTS.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(SHOTS / f"{name}.png"))

    def card(self, name):
        return self.page.locator(f"#grid [data-key] .name", has_text=name).first


@pytest.fixture
def app(server, browser, request):
    ctx = browser.new_context(viewport={"width": 1400, "height": 900}, bypass_csp=True, accept_downloads=True)
    page = ctx.new_page()
    a = App(page, server)
    yield a
    rep = getattr(request.node, "rep_call", None)   # set by the hook in conftest.py
    if rep is not None and rep.failed:
        a.shot(f"FAILED-{request.node.name}")
    ctx.close()
    assert not a.problems, "\n".join(a.problems)


def upload(p, path):
    """New → Upload files, and pick `path` in the file chooser."""
    p.locator("#newBtn").click()
    with p.expect_file_chooser() as fc:
        p.locator(".menu [role=menuitem]", has_text="Upload files").click()
    fc.value.set_files(str(path))


def first_file(a, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    items = a.api(f"/api/a/{a.aid()}/files?{q}&limit=50")["items"]
    assert items, params
    return items


# ------------------------------------------------------------------ start-up and every screen
def test_startup_screen_then_app(app):
    p = app.page
    p.goto(app.base + "/#drive")
    # The startup screen shows first (CSS hides it by itself once the app is in).
    expect(p.locator("#boot")).to_be_attached()
    p.wait_for_function("window.tgdrive && window.tgdrive.ready", timeout=30000)
    expect(p.locator("#boot")).to_be_hidden()
    expect(p.locator("#app")).to_be_visible()
    # The new icon everywhere: favicon, top bar, served file.
    assert "#38B6FF" in p.request.get(app.base + "/favicon.svg").text()
    expect(p.locator(".brand img.mark")).to_be_visible()


def test_not_responding_has_try_again(app):
    p = app.page
    state = {"fail": True}

    def handle(route):
        if state["fail"]:
            route.abort()
        else:
            route.continue_()
    p.route("**/api/status", handle)
    p.goto(app.base + "/#drive")
    expect(p.locator("#login h1", has_text="isn't responding")).to_be_visible(timeout=15000)
    state["fail"] = False
    p.locator("#bootRetry").click()
    p.wait_for_function("window.tgdrive && window.tgdrive.ready", timeout=30000)
    expect(p.locator("#app")).to_be_visible()
    # Set-up that runs once: the Transfers button still has exactly one icon.
    assert p.locator("#transfersBtn > svg:not(.t-ring)").count() == 1


ROUTES = ["#drive", "#all", "#starred", "#recent", "#photos", "#storage", "#duplicates", "#index", "#activity",
          "#sync", "#search/polity", "#search/pyq", "#search/seires", "#search/संविधान"] + \
    [f"#settings/{s}" for s in ("general appearance search subjects photos downloads streaming indexing drive sync "
                                "network telegram accounts security desktop data about").split()]


def test_every_screen_loads_cleanly(app):
    app.open()
    for r in ROUTES:
        app.go(r)
        app.page.wait_for_timeout(250)
        expect(app.page.locator(".page-loading:visible")).to_have_count(0, timeout=15000)
        app.shot("screen-" + r.strip("#").replace("/", "-"))


def test_every_screen_on_a_phone(server, browser):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, bypass_csp=True, is_mobile=True, has_touch=True)
    a = App(ctx.new_page(), server).open()
    for r in ("#drive", "#all", "#photos", "#settings/general", "#search/polity"):
        a.go(r)
        width = a.page.evaluate("document.documentElement.scrollWidth")
        assert width <= 391, f"{r} scrolls sideways on a phone ({width}px)"
        a.shot("phone-" + r.strip("#").replace("/", "-"))
    ctx.close()
    assert not a.problems, a.problems


# ------------------------------------------------------------------ browsing and search
def test_browse_folders_and_breadcrumbs(app):
    p = app.open().page
    p.locator("#folderArea", has_text="Study").locator("text=Study").first.click()
    app.settle()
    expect(p.locator("#crumbs .crumb", has_text="Study")).to_be_visible()
    p.locator("#crumbs .crumb", has_text="My Drive").click()
    app.settle()
    expect(p.locator("#crumbs .crumb")).to_have_count(1)


def test_search_smart_matching_and_filters(app):
    p = app.open().page
    p.locator("#q").fill("seires")
    p.keyboard.press("Enter")
    app.settle()
    expect(p.locator("#searchInfo .dym")).to_be_visible(timeout=10000)
    p.locator("#q").fill("test series")
    p.keyboard.press("Enter")
    app.settle()
    expect(p.locator("#grid [data-key]").first).to_be_visible()
    p.locator("#filtersBtn").click()
    expect(p.locator("#chips")).to_be_visible()
    p.locator("[data-tchip='starred']").click()
    app.settle()
    expect(p.locator("#filtersOn")).to_be_visible()
    p.locator("[data-clear-filters]").click()
    app.settle()
    expect(p.locator("#filtersOn")).to_be_hidden()


def test_keyboard_shortcuts(app):
    p = app.open("#all").page
    p.keyboard.press("?")
    expect(p.locator(".dialog h2", has_text="Keyboard shortcuts")).to_be_visible()
    p.keyboard.press("Escape")
    expect(p.locator(".dialog")).to_have_count(0)
    p.keyboard.press("/")
    assert p.evaluate("document.activeElement.id") == "q"
    p.keyboard.press("Escape")
    p.keyboard.press("Escape")
    p.locator("#grid [data-key]").first.click()
    expect(p.locator("#drawer .d-info .d-title")).to_be_visible()
    p.keyboard.press("Escape")
    p.keyboard.press("Escape")
    expect(p.locator("#drawer")).to_be_hidden()


def test_later_page_failure_offers_try_again(app):
    p = app.page
    state = {"n": 0}

    def handle(route):
        if "cursor=" in route.request.url and state["n"] == 0:
            state["n"] += 1
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "Telegram is slow"}))
        else:
            route.continue_()
    p.route("**/api/a/*/files?*", handle)
    app.open("#all")
    p.locator("#content").evaluate("el => el.scrollTo(0, el.scrollHeight)")
    expect(p.locator("#loadMoreError")).to_contain_text("Couldn't load more files", timeout=15000)
    app.error_dialog("Couldn't load more files")
    before = p.locator("#grid [data-key]").count()
    p.locator("#loadMoreError [data-act='load-more']").click()
    expect(p.locator("#loadMoreError")).to_have_count(0, timeout=15000)
    app.settle()
    p.locator("#content").evaluate("el => el.scrollTo(0, el.scrollHeight)")
    app.settle()
    assert p.evaluate("window.tgdrive.S.items.length") > 0 and before > 0


# ------------------------------------------------------------------ details panel, notes, stars, tags
def test_note_is_saved_to_the_right_file(app):
    p = app.open("#all").page
    cards = p.locator("#grid [data-key]")
    k1 = cards.nth(0).get_attribute("data-key")
    k2 = cards.nth(1).get_attribute("data-key")
    cards.nth(0).click()
    note = p.locator("#noteInput")
    expect(note).to_be_visible()
    note.fill("")
    note.type("revise before the test")
    # Switch files straight away, before the note's save timer ran.
    p.locator(f"#grid [data-key='{k2}']").click()
    expect(p.locator("#noteInput")).to_be_visible()
    app.settle(1500)
    c1, m1 = k1.split(":")
    c2, m2 = k2.split(":")
    d1 = app.api(f"/api/a/{app.aid()}/files/{c1}/{m1}")
    d2 = app.api(f"/api/a/{app.aid()}/files/{c2}/{m2}")
    assert d1["note"] == "revise before the test"
    assert (d2.get("note") or "") != "revise before the test"
    # Typing and closing the panel at once keeps the note too.
    p.locator("#noteInput").type("second file note")
    p.locator("#drawer [data-close]").click()
    app.settle(1500)
    assert app.api(f"/api/a/{app.aid()}/files/{c2}/{m2}")["note"].endswith("second file note")


def test_star_tag_rename_and_undo(app):
    p = app.open("#all").page
    card = p.locator("#grid [data-key]").first
    key = card.get_attribute("data-key")
    card.click()
    p.locator("#starBtn").click()
    app.toast("Starred")
    p.locator("#tagsBtn").click()
    p.locator("#tagInput").type("e2e-tag")
    p.keyboard.press("Enter")
    p.locator(".dialog [data-submit]").click()
    app.toast("Tags saved")
    c, m = key.split(":")
    det = app.api(f"/api/a/{app.aid()}/files/{c}/{m}")
    assert det["starred"] and "e2e-tag" in det["tags"]
    p.locator("#drawer .d-title").click()
    p.locator("#renameInput").fill("Renamed by e2e.pdf")
    p.keyboard.press("Enter")
    app.toast("Renamed")
    assert app.api(f"/api/a/{app.aid()}/files/{c}/{m}")["name"] == "Renamed by e2e.pdf"
    p.keyboard.press("Control+z")
    app.toast("Undone")
    app.settle(600)
    assert app.api(f"/api/a/{app.aid()}/files/{c}/{m}")["name"] != "Renamed by e2e.pdf"


def test_move_dialog_greys_out_smart_folders(app):
    p = app.open("#all").page
    p.locator("#grid [data-key]").first.click()
    p.keyboard.press("m")
    dlg = p.locator(".dialog")
    expect(dlg.locator(".picker")).to_be_visible()
    smart = dlg.locator(".picker label", has_text="Polity (smart)")
    expect(smart).to_have_class(re.compile("is-disabled"))
    expect(smart.locator("input")).to_be_disabled()
    p.keyboard.press("Escape")


def test_smart_folder_refuses_files_on_the_server(app):
    app.open()
    folders = app.api(f"/api/a/{app.aid()}/folders")["folders"]
    smart = next(f for f in folders if f.get("kind") == "smart")
    f = first_file(app)[0]
    r = app.page.request.post(f"{app.base}/api/a/{app.aid()}/files/place", headers={**H, "Content-Type": "application/json"},
                              data=json.dumps({"items": [[f["chat_id"], f["msg_id"]]], "folder_id": smart["id"]}))
    assert r.status == 400 and "smart folder" in r.json()["error"]


# ------------------------------------------------------------------ viewer: pictures, PDF, text, audio
def test_pdf_opens_and_draws_pages(app):
    p = app.open("#search/Fundamental Rights").page
    p.locator("#grid [data-key]").first.dblclick()
    expect(p.locator(".viewer")).to_be_visible()
    expect(p.locator(".pdf-page-box").first).to_be_visible(timeout=20000)
    expect(p.locator(".pdf-page-box.drawn").first).to_be_visible(timeout=20000)
    expect(p.locator("[data-pdf-total]")).to_have_text("12")
    p.keyboard.press("PageDown")
    app.settle(600)
    app.shot("viewer-pdf")
    p.keyboard.press("Escape")
    expect(p.locator(".viewer")).to_have_count(0)


def test_pdf_page_that_fails_offers_try_again(app):
    p = app.page
    state = {"fail": 0}

    def handle(route):
        # Let the start of the file through (to open it), then fail the ranges pages need.
        rng = route.request.headers.get("range", "")
        if rng and not rng.startswith("bytes=0-") and state["fail"] < 40:
            state["fail"] += 1
            route.abort()
        else:
            route.continue_()
    app.open("#search/Fundamental Rights")
    p.route("**/stream/**", handle)
    p.locator("#grid [data-key]").first.dblclick()
    expect(p.locator(".pdf-page-box").first).to_be_visible(timeout=20000)
    # Either every page drew (the file was small enough to come in the first range) or failed pages say so.
    p.wait_for_timeout(3000)
    if p.locator(".pdf-fail").count():
        p.unroute("**/stream/**")
        p.locator(".pdf-fail [data-pdf-retry]").first.click()
        expect(p.locator(".pdf-page-box.drawn").first).to_be_visible(timeout=20000)
    p.keyboard.press("Escape")


def test_text_file_shows_and_errors_have_a_way_out(app):
    p = app.open("#search/syllabus").page
    p.locator("#grid [data-key]").first.dblclick()
    expect(p.locator(".v-text")).to_contain_text("PRELIMS SYLLABUS", timeout=15000)
    p.keyboard.press("Escape")
    p.route("**/stream/**", lambda r: r.fulfill(status=500, content_type="application/json",
                                                  body=json.dumps({"error": "Telegram didn't answer"})))
    p.locator("#grid [data-key]").first.dblclick()
    expect(p.locator(".v-textbox")).to_contain_text("Telegram didn't answer", timeout=15000)
    assert "PRELIMS" not in p.locator(".v-textbox").inner_text()
    app.error_dialog("Telegram didn't answer")
    p.unroute("**/stream/**")
    p.locator("[data-v='retrytext']").click()
    expect(p.locator(".v-text")).to_contain_text("PRELIMS SYLLABUS", timeout=15000)
    p.keyboard.press("Escape")


def test_photo_viewer_and_slideshow(app):
    p = app.open("#photos").page
    expect(p.locator(".ph-cell[data-ph]").first).to_be_visible(timeout=15000)
    # A picture that can't be shown says so, with a way forward (never an empty screen).
    fail = {"on": True}

    def handle(route):
        if fail["on"]:
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "offline"}))
        else:
            route.continue_()
    p.route(re.compile(r".*/(stream|thumb)/.*"), handle)
    p.locator(".ph-cell[data-ph]:not(:has(.ph-dur))").nth(1).click()
    expect(p.locator(".viewer [data-v='retryimg']")).to_be_visible(timeout=15000)
    app.error_dialog("This picture couldn't be shown")
    fail["on"] = False
    p.locator(".viewer [data-v='retryimg']").click()
    expect(p.locator(".viewer .v-img.loaded")).to_be_visible(timeout=20000)
    p.unroute(re.compile(r".*/(stream|thumb)/.*"))
    p.keyboard.press("ArrowRight")
    p.keyboard.press("Escape")
    expect(p.locator(".viewer")).to_have_count(0)
    p.locator("[data-phshow]").click()
    expect(p.locator(".viewer.show-mode")).to_be_visible(timeout=15000)
    total = p.evaluate("document.querySelector('.viewer .v-title small').textContent")
    # All photos (from the month on screen), not only the months already loaded.
    photos = app.api(f"/api/a/{app.aid()}/timeline?kinds=photo")["total"]
    assert f"of {photos}" in total, (total, photos)
    p.locator("[data-v='showexit']").click()
    p.keyboard.press("Escape")


def test_photos_month_failure_shows_retry_not_toasts(app):
    p = app.page
    state = {"fail": True}

    def handle(route):
        if state["fail"] and "date_from=" in route.request.url:
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "offline"}))
        else:
            route.continue_()
    p.route("**/api/a/*/files?*", handle)
    app.open("#photos")
    expect(p.locator(".ph-failed").first).to_be_visible(timeout=15000)
    p.locator("#phScroll").evaluate("el => el.scrollBy(0, 400)")
    p.wait_for_timeout(800)
    assert p.locator("#toasts .toast.err").count() == 0
    state["fail"] = False
    p.locator("[data-ph-retry]").first.click()
    expect(p.locator(".ph-cell[data-ph]").first).to_be_visible(timeout=15000)


def test_audio_that_cannot_play_says_so(app):
    p = app.open("#search/Track 1").page
    p.locator("#grid [data-key]").first.click()
    audio = p.locator("#drawer .pv audio")
    expect(audio).to_be_attached(timeout=10000)
    # The demo's songs are random bytes: the preview must say it couldn't play, with Try again.
    p.wait_for_timeout(600)
    p.evaluate("document.querySelector('#drawer .pv audio').play().catch(() => {})")
    expect(p.locator("#drawer .pv-note")).to_contain_text("audio", timeout=15000)
    expect(p.locator("#drawer [data-pv-retry]")).to_be_visible()


def test_songs_play_on_to_the_next_one(app):
    p = app.open("#search/Track").page
    p.locator("#grid [data-key]").first.dblclick()
    title = p.locator(".viewer .v-title strong")
    expect(title).to_be_visible()
    first = title.inner_text()
    # The end of a song (the demo's songs can't really play, so the end is signalled by hand).
    p.evaluate("document.querySelector('.viewer audio').dispatchEvent(new Event('ended'))")
    expect(title).not_to_have_text(first, timeout=5000)
    expect(p.locator(".viewer audio")).to_be_attached()
    p.keyboard.press("Escape")


def test_mini_player_speed_and_skipping(app):
    p = app.open("#search/Track").page
    # Start the background player from the viewer, on the search results (songs).
    p.locator("#grid [data-key]").first.dblclick()
    app.settle(800)
    app.close_error_dialogs()   # the demo's made-up songs can't be decoded by the browser: that is reported
    p.locator(".viewer [data-v='background']").click()
    expect(p.locator(".viewer")).to_have_count(0)
    mp = p.locator("#miniPlayer")
    expect(mp).to_be_visible()
    expect(mp.locator(".mp-seek")).to_be_disabled()
    # Unplayable tracks are skipped (then it stops after three in a row) instead of silently stopping, and
    # each one is reported in the error dialog.
    app.error_dialog("skipping to the next one")
    app.close_error_dialogs()
    sp = mp.locator(".mp-speed")
    expect(sp).to_have_text("1×")
    sp.click()
    expect(sp).to_have_text("1.25×")
    app.close_error_dialogs()
    mp.locator("[data-mp='speed']").click()
    app.close_error_dialogs()
    mp.locator("[data-mp='close']").click()
    expect(mp).to_be_hidden()


# ------------------------------------------------------------------ pages: storage, duplicates, activity
def test_storage_error_then_retry(app):
    p = app.page
    state = {"fail": True}
    p.route("**/api/a/*/storage", lambda r: r.fulfill(status=500, content_type="application/json",
                                                       body=json.dumps({"error": "disk busy"})) if state["fail"] else r.continue_())
    app.open("#storage")
    expect(p.locator(".page-error")).to_contain_text("disk busy", timeout=10000)
    expect(p.locator(".page-loading")).to_have_count(0)
    app.error_dialog("disk busy")
    state["fail"] = False
    p.locator("[data-storage-retry]").click()
    expect(p.locator(".kpis")).to_be_visible(timeout=15000)


def test_duplicates_show_more(app):
    p = app.page
    calls = []

    def handle(route):
        url = route.request.url
        calls.append(url)
        resp = route.fetch()
        data = resp.json()
        if "offset=0" in url or "offset" not in url:
            data["groups"] = data["groups"][:1]
            data["more"] = True
        route.fulfill(response=resp, body=json.dumps(data))
    p.route("**/api/a/*/duplicates?*", handle)
    app.open("#duplicates")
    expect(p.locator(".dup")).to_have_count(1, timeout=10000)
    p.locator("[data-dup-more]").click()
    expect(p.locator(".dup").nth(1)).to_be_visible(timeout=10000)
    assert any("offset=1" in c for c in calls)
    p.locator("[data-dup-select]").click()
    app.toast("Selected")


# ------------------------------------------------------------------ transfers: download, upload, cancel, retry
def test_download_and_upload(app, tmp_path):
    p = app.open("#drive").page
    f = first_file(app, kinds="document")[0]
    app.go(f"#search/{f['name'].rsplit('.', 1)[0]}")
    p.locator("#grid [data-key]").first.click()
    p.locator("#drawer [data-one='download']").click()
    app.toast("Download started")
    expect(p.locator("#drawer .t-row").first).to_be_visible(timeout=10000) if p.locator("#drawer h2", has_text="Transfers").count() else None
    # Upload from this window (browser mode): a row while sending, then a transfer.
    up = tmp_path / "e2e-upload.txt"
    up.write_text("hello from the e2e test\n" * 50)
    app.go("#drive")
    upload(p, up)
    expect(p.locator("#drawer h2", has_text="Transfers")).to_be_visible()
    expect(p.locator("#drawer .t-row .t-name", has_text="e2e-upload.txt").first).to_be_visible(timeout=15000)
    # …and it really arrives: the row ends as "Uploaded", and the file is in My Drive.
    expect(p.locator("#drawer .t-row.done", has_text="e2e-upload.txt")).to_be_visible(timeout=30000)
    app.shot("transfers")
    app.go("#drive")
    expect(app.card("e2e-upload.txt")).to_be_visible(timeout=15000)


def test_upload_can_be_cancelled_and_retried(app, tmp_path):
    p = app.page
    state = {"mode": "hang"}

    def handle(route):
        if route.request.method == "PUT" and state["mode"] == "hang":
            return   # never answer: the upload stays "sending" until cancelled
        if route.request.method == "PUT" and state["mode"] == "fail":
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "disk full"}))
            return
        route.continue_()
    p.route("**/api/a/*/upload?*", handle)
    app.open("#drive")
    up = tmp_path / "slow.bin"
    up.write_bytes(b"x" * 200_000)
    upload(p, up)
    row = p.locator("#drawer .t-row", has_text="slow.bin")
    expect(row.locator("[data-t='cancel']")).to_be_visible(timeout=10000)
    row.locator("[data-t='cancel']").click()
    app.toast("cancelled")
    expect(row).to_have_count(0, timeout=10000)
    state["mode"] = "fail"
    upload(p, up)
    expect(row.locator(".t-sub.err")).to_contain_text("disk full", timeout=10000)
    expect(row.locator("[data-t='resume']")).to_be_visible()
    # Retry goes straight to TG Drive (re-sending an intercepted upload body isn't reliable in Playwright).
    app.close_error_dialogs()   # "couldn't be uploaded: disk full" (checked in the row above)
    p.unroute("**/api/a/*/upload?*")
    row.locator("[data-t='resume']").click()
    expect(p.locator("#drawer .t-row.done", has_text="slow.bin")).to_be_visible(timeout=30000)
    expect(row.filter(has=p.locator(".t-sub.err"))).to_have_count(0)


# ------------------------------------------------------------------ show in chat, exports, settings
def test_show_in_chat_and_its_errors(app):
    p = app.open("#all").page
    p.locator("#grid [data-key]").first.click()
    p.keyboard.press("c")
    expect(p.locator("#drawer .ctx-msg.target")).to_be_visible(timeout=15000)
    # A failing "earlier messages" keeps what's shown.
    p.route("**/api/a/*/context/**", lambda r: r.fulfill(status=500, content_type="application/json",
                                                          body=json.dumps({"error": "Telegram is offline"})))
    shown = p.locator("#drawer .ctx-msg").count()
    more = p.locator("[data-ctx='older']")
    if more.count():
        more.click()
        app.toast("Telegram is offline")
        assert p.locator("#drawer .ctx-msg").count() == shown


def test_export_errors_do_not_replace_the_app(app):
    p = app.open("#all").page
    p.route("**/export.csv*", lambda r: r.fulfill(status=400, content_type="application/json",
                                                   body=json.dumps({"error": "That search can't be exported"})))
    p.locator("#moreBtn").click()
    p.locator(".menu [role=menuitem]", has_text="Export list as CSV").click()
    app.toast("That search can't be exported")
    expect(p.locator("#app")).to_be_visible()
    p.unroute("**/export.csv*")
    p.locator("#moreBtn").click()
    with p.expect_download() as dl:
        p.locator(".menu [role=menuitem]", has_text="Export list as CSV").click()
    assert dl.value.suggested_filename.endswith(".csv")


def test_settings_save_and_search(app):
    p = app.open("#settings/general").page
    sw = p.locator("[data-set='group_by_date']")
    was = sw.is_checked()
    sw.locator("xpath=..").click()
    expect(p.locator("#savedFlash")).to_be_attached()
    app.settle(400)
    assert app.api("/api/settings")["group_by_date"] is (not was)
    sw.locator("xpath=..").click()
    app.settle(400)
    p.locator("#setFind").fill("proxy")
    expect(p.locator(".set-hit").first).to_be_visible(timeout=5000)
    p.locator("#setFind").fill("")
    p.locator(".set-nav [data-sec='appearance']").click()
    expect(p.locator("#setBody h2", has_text="Appearance")).to_be_visible()


def test_remove_types_no_longer_indexed(app):
    """Settings → Indexing: a type turned off shows how many of its files are still in the index, with
    a button that removes them (after asking); turned back on, nothing is left to remove."""
    p = app.open("#settings/indexing").page
    aid = app.aid()
    expect(p.locator("#unindexedTypes")).to_be_hidden()
    gifs = app.api(f"/api/a/{aid}/files?kinds=gif&limit=200")["items"]
    assert gifs, "the demo has no GIFs"
    box = p.locator("[data-kind-toggle='gif']")
    try:
        box.uncheck()
        expect(p.locator("#unindexedTypes")).to_be_visible(timeout=8000)
        expect(p.locator("#unindexedTypes p")).to_contain_text("gif")
        p.locator("[data-remove-unindexed]").click()
        expect(p.locator(".dialog h2", has_text="from the index")).to_be_visible()
        p.locator(".dialog [data-submit]").click()
        app.toast("Removed")
        expect(p.locator("#unindexedTypes")).to_be_hidden(timeout=8000)
        assert app.api(f"/api/a/{aid}/files?kinds=gif&limit=5")["items"] == []
        assert app.api(f"/api/a/{aid}/files?kinds=photo&limit=5")["items"], "other types must stay"
    finally:
        box.check()
        app.settle(400)
    assert "gif" in app.api("/api/settings")["index_kinds"]
    expect(p.locator("#unindexedTypes")).to_be_hidden()
    assert not app.problems, app.problems


def test_add_account_qr_failure_has_a_way_forward(app):
    p = app.open().page
    p.locator("#accountBtn").click()
    p.locator(".menu [role=menuitem]", has_text="Add account").click()
    # The demo has no real Telegram: getting a QR code fails, and the page must offer a new one.
    expect(p.locator("[data-qr-retry]")).to_be_visible(timeout=40000)
    expect(p.locator("#login .err")).not_to_be_empty()
    p.locator("[data-mode='phone']").click()
    expect(p.locator("#login input[name='phone']")).to_be_visible()
    p.locator("#cancelLogin").click()
    expect(p.locator("#app")).to_be_visible()


# ------------------------------------------------------------------ errors: "Create GitHub issue"
def test_every_error_opens_dialog_with_github_issue(app):
    p = app.open("#all").page
    p.evaluate("""() => { window.__opened = []; window.open = (u) => { window.__opened.push(u); return {}; }; }""")
    # A failed action (an error toast before) and an error in the page itself, both while the first is open.
    p.evaluate("""async () => { const ui = await import(document.querySelector('script[type=module]').src.replace('app.js', 'ui.js')); ui.toast('Something small failed', { err: true });
                                ui.fail(new Error('Second problem')); }""")
    p.evaluate("window.dispatchEvent(new ErrorEvent('error', { message: 'bug in the window', error: new Error('bug in the window') }))")
    dlg = p.locator(".error-dialog", has_text="Something small failed")
    expect(dlg).to_be_visible(timeout=8000)
    dlg.get_by_role("button", name="Create GitHub issue").click()
    p.wait_for_function("window.__opened.length > 0", timeout=10000)
    url = p.evaluate("window.__opened[0]")
    assert url.startswith("https://github.com/infinite4evr/vibes/issues/new?labels=bug&title=TG%20Drive%3A%20Something%20small%20failed")
    assert "What%20happened" in url and "System" in url and len(url) <= 7600
    app.close_error_dialogs()   # closes the two that waited their turn as well
    assert p.locator(".error-dialog").count() == 0
    app.api("/api/crashes", "DELETE")  # remove intentionally planted crash before later journeys


# Offline / recovery journeys: real browser and service, sample Telegram transport.
def test_offline_pin_open_and_remove_via_ui(app):
    a=app.open('#all');p=a.page
    f=next(x for x in first_file(a,kinds='document') if 0<x['size']<1000000)
    a.api(f'/api/a/{a.aid()}/offline','POST',{'items':[[f['chat_id'],f['msg_id']]]})
    a.go('#offline');expect(p.get_by_role('heading',name='Offline & recovery',exact=True)).to_be_visible()
    row=p.locator('.setting-row').filter(has=p.locator('strong',has_text=f['name'])).last
    for _ in range(30):
        p.get_by_role('button',name='Refresh',exact=True).click();p.wait_for_timeout(300)
        if row.get_by_role('link',name='Open copy').count():break
    with p.expect_download() as dl:row.get_by_role('link',name='Open copy').click()
    assert Path(dl.value.path()).stat().st_size==f['size']
    row.get_by_role('button',name='Remove offline copy').click();p.locator('.dialog [data-submit]').click()
    expect(p.locator('[data-unpin-file="%s/%s"]'%(f['chat_id'],f['msg_id']))).to_have_count(0)
    assert a.api(f'/api/a/{a.aid()}/files?limit=1')['items']


def test_offline_budgets_persist_across_reload(app):
    a=app.open('#offline');p=a.page;field=p.locator('[data-budget="offline_limit_mb"]')
    expect(field).to_be_visible();original=field.input_value()
    try:
        field.fill('2048');p.get_by_role('button',name='Save limits',exact=True).click();a.toast('Limits saved')
        a.open('#offline');expect(field).to_have_value('2048')
    finally:a.api('/api/settings','PATCH',{'offline_limit_mb':int(original)})


def test_file_menu_offline_action_and_recovery_empty_state(app):
    a=app.open('#all');p=a.page;p.locator('#grid [data-key]').first.click(button='right')
    expect(p.get_by_role('menuitem',name='Keep available offline',exact=True)).to_be_visible();p.keyboard.press('Escape')
    a.go('#offline');expect(p.get_by_role('heading',name='Recovery',exact=True)).to_be_visible()
    expect(p.get_by_role('heading',name='Pinned folders',exact=True)).to_be_visible()


def test_folder_pin_and_stop_automatic_downloads(app):
    a=app.open();p=a.page
    p.locator('#newBtn').click();p.get_by_role('menuitem',name='New folder',exact=True).click()
    p.locator('.dialog input').first.fill('Offline E2E Folder');p.locator('.dialog [data-submit]').click()
    a.settle()
    fid=next(f['id'] for f in a.api(f'/api/a/{a.aid()}/folders')['folders'] if f['name']=='Offline E2E Folder')
    # Use another file: the previous journey explicitly excluded its file from automatic pins.
    f=[x for x in first_file(a,kinds='document') if 0<x['size']<1000000][-1]
    a.api(f'/api/a/{a.aid()}/files/place','POST',{'items':[[f['chat_id'],f['msg_id']]],'folder_id':fid})
    try:
        a.go('#drive')
        p.locator(f'[data-folder-menu="{fid}"]').click()
        p.get_by_role('menuitem',name='Keep folder offline',exact=True).click();a.go('#offline')
        expect(p.locator(f'[data-unpin-folder="{fid}"]')).to_be_visible();p.locator(f'[data-unpin-folder="{fid}"]').click()
        expect(p.locator(f'[data-unpin-folder="{fid}"]')).to_have_count(0)
        assert a.api(f'/api/a/{a.aid()}/offline')['items']
    finally:
        a.api(f'/api/a/{a.aid()}/offline/{f["chat_id"]}/{f["msg_id"]}','DELETE');a.api(f'/api/a/{a.aid()}/folders/{fid}','DELETE')


def test_recovery_resumes_indexing_through_ui(app):
    a=app.open();p=a.page;a.api(f'/api/a/{a.aid()}/index/pause','POST')
    try:
        a.go('#offline');b=p.locator('[data-recover-kind="index"]');expect(b).to_be_visible();b.click()
        expect(p.locator('[data-recover-kind="index"]')).to_have_count(0)
    finally:a.api(f'/api/a/{a.aid()}/index/resume','POST')


def test_data_folder_selection_is_scheduled_from_settings(app,tmp_path):
    p=app.open('#settings/data').page
    p.locator('[data-data-folder]').click()
    expect(p.locator('.dialog h2',has_text='TG Drive data folder')).to_be_visible()
    p.locator('.dialog input').fill(str(tmp_path/'portable'))
    p.locator('.dialog [data-submit]').click()
    app.toast('Data folder selected')
    result=app.api('/api/data-location')
    assert result['pending']==str(tmp_path/'portable')
    assert result['path']!=result['pending']  # no copy while databases are live
