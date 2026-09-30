# TG Drive for Android: handover

Read this first if you are picking up work on the Android app. It records what exists, what the
owner decided is out of scope, how to build and verify changes, what went wrong before (so it isn't
repeated) and what is still open. `README.md` in this folder is the shorter, user-facing overview.

- Repository: `infinite4evr/vibes`, private. The app is `tgdrive/android`; the service it runs is
  the desktop app's Python package `tgdrive/tgdrive`.
- Working branch so far: `claude/admiring-goodall-822mrh`. No pull request has been opened (the
  owner asks for one when wanted).

## 1. What the app is

A native Android client of the TG Drive desktop app with the same features, built after the
desktop design. The desktop's Python service runs on the phone (Chaquopy, Python 3.13) in its own
process (`:engine`, `EngineService`). The Jetpack Compose interface talks to it over HTTP on
127.0.0.1 with a per-start secret. The owner's requirements, in their words: production grade,
dependable, sleek, "not AI slop", no flimsy libraries.

## 2. Scope decisions (from the owner, don't reopen them)

**Deliberately not on Android.** The owner said: "I don't need the folder sync and drive on the
computer feature on the android. other things that are computer native and don't need to be on
android too, i don't need them."

| Desktop feature | Desktop code / API | Why not on Android |
| --- | --- | --- |
| Folder sync (a folder on the computer ↔ a TG Drive folder, both ways) | `web/js/sync.js`, `tgdrive/sync.py`, `GET/POST /api/a/{aid}/sync…` | Owner declined. The service still runs `SyncEngine` (it has nothing to do without pairs). Don't build a UI for it. |
| "Drive on this computer" (WebDAV mount) | `tgdrive/dav.py`, `/api/dav`, `/api/dav/mount`, `/api/dav/unmount` | Owner declined. That also covers an Android equivalent: don't build a DocumentsProvider (TG Drive inside the system Files app). |
| Desktop integration: tray, autostart, title bar, window, file-manager menus | `tgdrive/integration.py`, `/api/integration…`, `/api/open`, `/api/focus`, `web/js/wintitle.js`, Settings → Desktop | Computer-only. |
| Split view and column view | `web/js/split.js`, `web/js/columns.js` | Desktop layouts; the phone has one pane (with a drawer). |
| Keyboard shortcuts, drag and drop | `web/js/*` | Computer-only. |
| Import from older desktop versions | `/api/legacy`, `/api/legacy/import` | Only for desktop upgrades. |
| "Open in VLC / mpv" launcher and the `.m3u` playlist | `/api/a/{aid}/play_external/…`, `/api/a/{aid}/playlist.m3u` | Android hands a stream to any installed player through "Open with another app", and plays queues in its own background player. |
| Download the log file, client log | `/api/logs/download`, `/api/clientlog` | Android has its own: Settings → About & diagnostics → Send report (see §6). |
| Path check for the download folder | `/api/paths/check` | The phone uses Download/TG Drive (or the app's own folder); there's no path to type. |

`python3` can list the service endpoints the app never calls. The whole list above is expected;
anything new in it is a gap:

```sh
cd tgdrive
grep -ohE '@(app|router)\.(get|post|put|patch|delete)\("[^"]+"' tgdrive/*.py | sort -u   # server routes
grep -oE '"(\$\{a\(aid\)\}|/api)[^"]*"' android/app/src/main/java/app/tgdrive/data/Api.kt | sort -u   # app calls
```

(`/api/stream-events` is used by `AppState.startLive`, and thumbnails and streams are built as
URLs in `Api.kt`, so those don't show in the grep either.)

**Small desktop features not ported yet (not declined, low priority):** slideshow shuffle (the
desktop viewer has a toggle; `TgIcons.shuffle` exists but is unused).

**Possible Android-only extras (not asked for; ask before building):** picture-in-picture video,
a home-screen widget, a notification when new files arrive.

## 3. Map of the code

| Path | What |
| --- | --- |
| `app/src/main/java/app/tgdrive/TGDriveApp.kt` | Application: logs and crash handler for both processes; `AppGraph` (OkHttp, `Api`, `AppState`, `EngineClient`); schedules the background sync; WorkManager configuration (main process only). |
| `engine/EngineService.kt` | The `:engine` process: starts Python (`tgdrive.mobile.start`), a foreground service while the app needs it, stops a minute after nothing holds it and **kills its process** (Python can't restart inside a process). Also accepts a bind from the background sync: no notification, CPU jobs held, stops when the sync lets go. |
| `engine/EngineClient.kt` | The app's side: start, hold ("ui", "keep", "player" …), state (a file plus a broadcast), and a watchdog that notices a dead service. It uses `ActivityManager.runningAppProcesses`, not `/proc`, which some phones hide across processes. A routine kill counts as *Stopped*; only a crash, or dying while starting, counts as *Failed*. |
| `engine/BackgroundSync.kt` | WorkManager periodic sync + `SyncWorker` (binds the service, `index/resync` for each account, waits until idle, 8 min cap). Settings in the `sync` SharedPreferences. |
| `engine/BatteryLimits.kt` | Background restriction, standby bucket, battery optimisation, Samsung detection and deep links. |
| `engine/UploadService.kt` | Uploads (picked files, whole folders through SAF, *Share → TG Drive*). |
| `engine/StartupReport.kt` | The text report (phone, service state, exit reasons, start steps, log tail). |
| `data/Api.kt`, `data/Models.kt` | HTTP API and models. **Response bodies are read on Dispatchers.IO** (reading them on Main threw NetworkOnMainThreadException and broke every list). `FlexBoolean` accepts 0/1 for every Boolean (SQLite has no booleans). |
| `data/AppState.kt` | Shared state: phases (Welcome, Starting, NeedsApiKey, NeedsLogin, Ready, Locked, Failed), live events (SSE), messages, `failed()`. It loads data only once the app is visible (`bootstrapWhenVisible`), so a background sync waking the process costs nothing. New-file events are bundled: lists refresh at most every 15 s. |
| `diag/AppLog.kt`, `diag/ProblemReport.kt`, `diag/ReportUi.kt` | Log files, crash reports, the problem-report zip and its UI (see §6). |
| `ui/…` | Compose UI: `main` (scaffold, drawer, top bar), `browse`, `viewer`, `photos`, `pages` (Transfers, Storage, Duplicates, Index, Activity), `settings`, `onboarding` (welcome, API key, sign-in, lock, splash, error), `actions` (every menu, sheet and dialog), `search`, `components`, `theme`. |
| `player/` | Media3 background player (`PlayerService`, `PlayerController`). |
| `app/src/main/cpp` | FTS5 built as a SQLite loadable extension (Android's Python SQLite lacks FTS5). |
| `app/src/androidTest` | Emulator tests (§5). |
| `contract/` | JVM harness: compiles the app's real `Api.kt`, `Models.kt` and `Format.kt` and runs ~130 calls against the real service (§5). |
| `../tgdrive/mobile.py` | The service's Android entry points: `start`, `stop`, `activity`, `events_since`, `set_background`. |
| `../tgdrive/pace.py` | CPU pacing: `quiet_for` (the first 20 s after a start on phones), `force` (background sync: heavy jobs paused). |

## 4. How it behaves (decisions worth knowing)

- **Start:** Python start, then importing the service (~4 s on the first start after an install
  or update, when Android unpacks the native libraries), then opening the accounts (well under a
  second). For the first 20 s after a start the meaning index, subjects, duplicate finder, index
  prefetch and search vocabulary wait (`pace.quiet_for`), so the first screens load first. Every
  step is logged with timings: `engine-start.log`, plus "accounts opened in", "service up in" and
  "status answered in" lines.
- **Background sync** (Settings → This phone): on by default, every 30 min–12 h (default 1 h),
  network required, never on low battery, optional Wi-Fi-only and charging-only. It binds the
  service instead of starting a foreground service; Android 12+ forbids starting a foreground
  service from the background. There's no notification, and the heavy jobs stay paused
  (`background` option → `pace.force("paused")`). The sync ends as soon as every account's
  indexer is idle again. If the app opens mid-sync, `set_background(false)` resumes normal work.
  "Stay connected all the time" (the old *Keep running*) is the always-on alternative.
- **Battery limits:** if Android restricts the app, or the sync hasn't run for 3× its interval
  (at least 6 h), This phone says so in red with a button to the right settings. On Samsung phones
  it always adds a hint about Sleeping / Deep sleeping apps.
- **Errors:** every failure goes through `AppState.failed(what, e)` or `Throwable.explain(where)`.
  The reason shows on screen, the stack goes to the log, and error snackbars have **Details**
  (full text, Copy, Send report).

## 5. Building and testing

There's no Android SDK in cloud sessions, and Google's Maven (dl.google.com) is blocked there, so
**the Android app is only compiled by CI**. Be careful with Kotlin you can't compile: read every
change back. Two traps that cost CI runs:
- In test classes with a property called `app`, a fully qualified `app.tgdrive.X` resolves
  `app` to that property and fails to compile. Import the class instead.
- Assignments are fine inside `when` branches only where the `when` is a statement.

**What can be run locally (in about a minute):**

```sh
# Service tests with the Android package set (numpy 1.26 like Chaquopy's; no numpy.bitwise_count)
python3.12 -m venv /tmp/avenv && /tmp/avenv/bin/pip install -r tgdrive/requirements.txt numpy==1.26.4 pytest   # once
cd tgdrive && /tmp/avenv/bin/python -m pytest -q tests          # 74 passed, 4 skipped (desktop browser tests need Playwright)

# Contract harness: the app's real Api.kt/Models.kt against the real service
cd tgdrive/android/contract && gradle -q --no-daemon installDist && PY=/tmp/avenv/bin/python ./run.sh
# "131 passed". The last check (Telegram rejects a made-up key) needs internet access to Telegram,
# which cloud sessions don't have; it passes in CI.
```

Maven Central sometimes answers 429 in cloud sessions; `contract/settings.gradle.kts` uses the
`repo1.maven.org` mirror. Kill leftover services with
`ps aux | grep "python boot.py" | grep -v grep | awk '{print $2}' | xargs -r kill`. Don't use
`pkill -f`: it matches your own shell.

**CI** (`.github/workflows/tgdrive-android.yml`, about 40 minutes; each push cancels the previous
run of the same branch):
1. *Service tests (Android package set)*: pytest plus the contract harness plus the Telegram check.
2. *Build APK*: the release APK (arm64-v8a + x86_64), signed (§7), with its certificate checked.
   It's published as a GitHub release `tgdrive-android-v<version>-<run>`, a pre-release off `main`.
3. *Emulator tests and screenshots* (`.github/scripts/tgdrive-android-emulator.sh`, API 34
   x86_64). It builds `staging` (the release build, R8-minified, made debuggable) and runs:
   - `EngineTest`: the service on Android (FTS5, OpenSSL, numpy, search, ranges, organising).
   - `ScreenshotTour`: every screen, screenshots only.
   - `Journeys`: 34 end-to-end journeys, each checked against the service. Folders, search,
     star, tags, note, rename, move, viewer, details, download, selection, type tabs, photos,
     the Tools pages, dark theme, share-to-upload, audio playback and mini player, a video that
     can't play, the PDF viewer, passcode lock/unlock/remove, the accounts screen, landscape,
     large text, background sync from Settings, error details with a problem report, and the
     report from the account menu. Any error the app shows fails the run.
   - `BackgroundSyncTest`: a sync with the app closed starts the service by binding, finishes,
     and the service stops afterwards.
   - `SignInFlow`: a fresh install, the real sign-in screens against Telegram with a made-up key
     (phone code and QR). Telegram must answer, and the app must show it.

   The screenshots, logs, a `*-FAIL.png`/`*-FAIL.xml` (window dump) per failed journey and the
   test outputs are force-pushed to the branch **`tgdrive-android-screens`**. That's the quickest
   way to see results:
   `git clone -q --depth 1 -b tgdrive-android-screens https://github.com/infinite4evr/vibes.git /tmp/screens`,
   then read `journeys.txt`, `background-sync.txt`, `signin.txt`, `app-demo.log`,
   `service-demo.log` and `shots/*.png`.
   The run status can be read without auth:
   `curl -s "https://api.github.com/repos/infinite4evr/vibes/actions/runs?branch=<branch>&per_page=3"`.
   Build errors are in the job log (GitHub MCP `get_job_logs`); the *Build errors* step prints
   the first error of each file.

**UI-test lessons (UiAutomator + Compose):**
- Views are replaced while live data (the indexing counter, progress) redraws. Tap by position
  (`Journeys.click`/`tapAt`), not with `UiObject2.click()`.
- Scroll slowly (`SLOW`, 1200 px/s) so lists don't fling on after a row is found.
- The accessibility tree lags behind scrolled rows. The type tabs are a `LazyRow` for this reason.
- Check results against the service (`g.api`) or app state, not only the screen.
- The test APK shares the app's copy of Kotlin, coroutines and OkHttp. `proguard-staging.pro`
  keeps them, plus the public members of the app classes the tests use. Add a class there when a
  test starts using it.
- The demo's videos and most songs are random bytes. `Morning raga (sample recording).wav` (in
  `tests/demo_server.py`) is a real WAV for playback tests, and the PDF is real.

## 6. Diagnostics (how the owner sends problems)

- The app writes `files/logs/app.log` and `files/logs/engine.log` (2 MB × 3, tokens removed).
  "Detailed debug logging" (Settings → About & diagnostics, shared with the service) adds every
  request, screen and action. Uncaught crashes go to `files/logs/crash-<process>-<time>.txt`, and
  the next start offers to send them.
- **Send report** is in Settings → About & diagnostics, the account menu (*Report a problem*),
  every error screen, and error **Details**. It builds one zip: `report.txt` (phone, service
  state, background limits and last sync, how the service's process ended, start steps, log
  tail), `app/` (app log and crashes), `engine/` (engine log and `engine-start.log`), and
  `service/` (`tgdrive.log`, `tgdrive-debug.log`, the service's crash reports). No passwords,
  keys, tokens or messages are included.
- When the owner uploads one, read `report.txt` first, then `engine/engine-start.log` (timings),
  `app/app.log` (phases, "status answered in"), then `service/tgdrive.log`.

## 7. Signing and releases (why updates wouldn't install)

Until September 2026 every CI build was signed with a throwaway debug key, because the signing
secret didn't exist. Android refuses an update signed with a different key, so every build needed
an uninstall. Now:
- CI signs with the key in the repository secrets `TGDRIVE_KEYSTORE_BASE64` (a PKCS12 keystore,
  alias `tgdrive`, base64) and `TGDRIVE_KEYSTORE_PASSWORD`. Setup is in `signing/README.md`.
  **The owner has to add these once.** Until then CI warns and signs with a throwaway key.
- The key is never committed; a private key in git was rejected as a credential leak. Don't
  generate one in a session either. The owner makes it on their machine and keeps a backup.
- After the first build with the secret, put the certificate's SHA-256 (printed by the *Check the
  signing key* step) in `signing/expected-certificate.sha256`. From then on CI refuses to publish
  an APK signed with any other key.
- `versionCode` is the workflow's run number, so it always increases. `versionName` is in
  `app/build.gradle.kts`.
- The first APK signed with the permanent key needs one last uninstall and reinstall. After that,
  updates install in place.

## 8. Status and open items (September 2026)

Done and verified by CI before the last batch: every screen and action in §5, sign-in against
Telegram, background sync scheduling in release builds (an R8 rule for WorkManager's Room
database), the Duplicates page, problem reports, and dialogs on small screens.

The **last batch** (the final push of this session) contains the following. The next session
should start by checking its CI run (§5):
- signing (§7) and the certificate check
- the battery-limits warnings (§4)
- the stale "failed" state fix (routine kills are *Stopped*; the sync ignores failures from
  before it started)
- bundled, silent list refreshes and the "New files · Show" pill
- the top bar following only the transfer badge
- the quiet start deferring prefetch and vocabulary
- the new journeys (share-upload, audio, video error, PDF, passcode, accounts, landscape, large
  text) and QR sign-in
- the real WAV in the sample data

Open items:
1. **Signing secret**: the owner adds it (§7). Then fill in `expected-certificate.sha256`.
2. **Slow start on the owner's phone** (Samsung SM-M336BU, Android 16): waiting for a problem
   report after a slow start, to see which step is slow. Everything measurable on the emulator is
   fast.
3. **Folder upload through the system folder picker** isn't automated: the picker is another
   app, different on each Android version. Test it by hand on a phone after changes to
   `UploadService`.
4. **Accessibility:** the accessibility tree lagging behind scrolled rows (see §5) may also affect
   TalkBack. Worth a check with TalkBack on a real phone.
5. The Samsung battery deep link (`com.samsung.android.lool`) differs between One UI versions.
   It falls back to the app's settings page.

## 9. Working with the owner

- Stop after significant work: list what was done and what's pending, and ask whether to continue.
- Build time is expensive: **push only when a whole batch of work is done**, not after each change.
- Commits: clear messages, ending with the session's attribution lines. Never mention model
  names in commits or code.
- Don't open a pull request unless asked.
