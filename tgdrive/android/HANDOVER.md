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
| `engine/UploadService.kt` | Uploads (picked files, whole folders through SAF, *Share → TG Drive*). Only `content://` links from other apps are accepted: a share naming a file path or TG Drive's own FileProvider (`<package>.files`) is refused, since it would make TG Drive upload its private data (a Telegram session). |
| `engine/StartupReport.kt` | The text report (phone, service state, exit reasons, start steps, log tail). |
| `data/Api.kt`, `data/Models.kt` | HTTP API and models. **Response bodies are read on Dispatchers.IO** (reading them on Main threw NetworkOnMainThreadException and broke every list). `FlexBoolean` accepts 0/1 for every Boolean (SQLite has no booleans). |
| `data/AppState.kt` | Shared state: phases (Welcome, Starting, NeedsApiKey, NeedsLogin, Ready, Locked, Failed), live events (SSE), messages, `failed()`. It loads data only once the app is visible (`bootstrapWhenVisible`), so a background sync waking the process costs nothing. New-file events are bundled: lists refresh at most every 15 s. |
| `diag/AppLog.kt`, `diag/ProblemReport.kt`, `diag/ReportUi.kt` | Log files, crash reports, the problem-report zip and its UI (see §6). The crash handler is installed in `TGDriveApp.attachBaseContext`, before any library starts. |
| `diag/GitHubIssue.kt` | "Create GitHub issue": a pre-filled issue link on `infinite4evr/vibes` with the error, stack, phone, service state, the service's latest crash report and log tails (tokens removed), kept under 7 600 characters. |
| `diag/CrashActivity.kt` | The crash screen, in its own process `:crash` with plain Android views. Any crash in the interface's process lands here instead of the app vanishing, with Create GitHub issue, Send report, Copy, Open again, and (after 2+ crashes in 10 min) Reset settings. The reset clears only the `app` and `player` prefs and `engine-state.json`, never the service's data. |
| `ui/…` | Compose UI: `main` (scaffold, drawer, top bar), `browse`, `viewer`, `photos`, `pages` (Transfers, Storage, Duplicates, Index, Activity), `settings`, `onboarding` (welcome, API key, sign-in, lock, splash, error), `actions` (every menu, sheet and dialog), `search`, `components`, `theme`. |
| `player/` | Media3 background player (`PlayerService`, `PlayerController`). |
| `app/src/main/cpp` | FTS5 built as a SQLite loadable extension (Android's Python SQLite lacks FTS5). |
| `MainActivity.kt` | The single activity. Intents: share targets, and `EXTRA_OPEN_SCREEN` ("transfers", "storage", "settings/phone" …, mapped by `ui/main/MainScreen.kt` `screenNamed`), which the notifications use (the upload notification opens Transfers) and the tests use to reach a page directly. |
| `app/src/androidTest` | Emulator tests (§5). `UiDriver.kt` is the shared base class: taps by position, slow scrolls, the sidebar, search, `open(screen)`, screenshots. |
| `contract/` | JVM harness: compiles the app's real `Api.kt`, `Models.kt` and `Format.kt` and runs ~130 calls against the real service (§5). |
| `../tgdrive/mobile.py` | The service's Android entry points: `start`, `stop`, `activity`, `events_since`, `set_background`. |
| `../tgdrive/pace.py` | CPU pacing: `quiet_for` (the first 20 s after a start on phones), `force` (background sync: heavy jobs paused), `foreground()` (called by the API middleware on every request from the app: background jobs step aside for 0.6 s, so pages answer quickly while the index works). |

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
  The reason shows on screen, the stack goes to the log, and error snackbars have **Details**:
  the full text, **Create GitHub issue** (the main button), Send report, Copy. Failed pages and
  lists offer "Report this", which opens the same dialog. Error screens, the crash notice,
  Settings → About and the account menu have the GitHub button too.
- **Crashes:** a crash in the interface's process opens the crash screen (`CrashActivity`), so the
  app never just closes, or closes again at every launch. The service's own crashes are shown by
  the app (Failed screen).
- **Answers are read and closed on Dispatchers.IO** (`Api.rawOnce`, `Call.await`). A request cancelled
  just as its answer arrived (a screen closing, the lock screen giving way) used to close the
  response on the main thread. Closing an unread body reads the socket, so Android ended the app
  with `NetworkOnMainThreadException`. Found by the journeys (the app died after unlocking);
  `EngineTest.requestsCancelledAsTheirAnswerArrivesDontCrash` covers it. It may explain some of the
  owner's "sometimes the app crashes".
- **Background sync while locked:** a locked TG Drive shows no accounts, so the sync used to report
  "Not signed in". It now says it waits for the passcode.
- **Foreground services can be refused** (Android 12+ from the background; Android 15+ after
  data-sync's 6 h/day limit, reset when the app is opened). `EngineService.goForeground` and
  `UploadService` catch that and carry on without the notification. Upload starts return false
  and the screen says so; before this they would crash the app.
- **Big libraries** (the owner has ~100 000 files): every endpoint is fast on an idle service, but
  background CPU jobs (subjects, meaning index, duplicates, prefetch) held Python's GIL, and a page
  took seconds (Storage 1.8 s instead of 2 ms on a computer, 10× that on a phone). Now each request
  calls `pace.foreground()` and the jobs' `rest()`/`arest()` wait while requests keep coming (at most
  10 s in a row, so they still progress). On phones `sys.setswitchinterval(0.002)` makes Python hand
  the GIL to the request thread sooner. `BigLibraryTest` checks it on the emulator (§5).
- **Opening a downloaded file** always goes through the FileProvider (the whole external storage is
  a root, links are granted per file). A `file://` fallback used to crash on Android 7+.
- **Pause and resume of a download** (`transfers.py`): pausing cancels the download task, but a
  map save (`.part.map`) already running in a worker thread goes on, and the cancelled task saves
  once more. Both used the same temp file, and the download could end in "No such file or
  directory". Saves and closing the `.part` now take one lock per file (`_map_lock`). A task that
  was paused or replaced never writes its error over the transfer's status. The regression test
  `test_download_resumed_while_its_last_save_still_runs` forces the overlap (it failed 3 of 3
  runs before the fix).
- **File types no longer indexed** (Settings → Indexing): turning a type off only stops indexing it.
  "Remove types no longer indexed" shows how many of those files are still in the index and removes
  them, in batches of 2 000 on the writer thread (`maintenance.remove_unindexed_types`; tasks
  `unindexed_types` / `remove_unindexed_types` of `POST /api/a/{aid}/maintenance/{task}`, on desktop
  and Android). Nothing changes in Telegram, and placements (folders, stars, tags, notes) are kept.
  Turning a type on resets the progress of every Telegram filter that finds it
  (`AccountManager._on_settings` → `Database.rescan_filters`; photos sent as files come with the
  *document* filter) and marks the chats pending, so its files come back, into their folders. That
  also covers what was posted while the type was off, which used to be missed until a full re-index.
- **Busy index:** SQLite "database is locked/busy" (a long background write, mostly on slow phones)
  answers 503 `{"busy": true}` instead of a crash message. The app retries reads up to 3 times;
  writes say "TG Drive is busy saving its index. Try again in a moment."

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
cd tgdrive && /tmp/avenv/bin/python -m pytest -q tests          # 78 passed, 4 skipped (desktop browser tests need Playwright)

# Contract harness: the app's real Api.kt/Models.kt against the real service
cd tgdrive/android/contract && gradle -q --no-daemon installDist && PY=/tmp/avenv/bin/python ./run.sh
# "131 passed". The last check (Telegram rejects a made-up key) needs internet access to Telegram,
# which cloud sessions don't have; it passes in CI.
```

Maven Central sometimes answers 429 in cloud sessions; `contract/settings.gradle.kts` uses the
`repo1.maven.org` mirror. Kill leftover services with
`ps aux | grep "python boot.py" | grep -v grep | awk '{print $2}' | xargs -r kill`. Don't use
`pkill -f`: it matches your own shell.

**CI** (`.github/workflows/tgdrive-android.yml`, called by `ci.yml`; about 90 minutes; each push cancels
the previous run of the same branch). On `main` all three jobs run; on other branches it runs only when
the branch changed the Android app or the Python service, and the emulator job only when it changed
the Android app (`tgdrive/android/**`):
1. *Service tests (Android package set)*: pytest plus the contract harness plus the Telegram check.
2. *Build APK*: the release APK (arm64-v8a + x86_64), signed (§7), with its certificate checked.
   It's published as a GitHub release `tgdrive-android-v<version>-<run>`, a pre-release off `main`.
3. *Emulator tests and screenshots* (`.github/scripts/tgdrive-android-emulator.sh`, API 34
   x86_64). It builds `staging` (the release build, R8-minified, made debuggable) and runs:
   - `EngineTest`: the service on Android (FTS5, OpenSSL, numpy, search, ranges, organising).
   - `ScreenshotTour`: every screen, screenshots only.
   - `Journeys`: 37 end-to-end journeys, each checked against the service. Folders, search,
     star, tags, note, rename, move, viewer, details, download, selection, type tabs, photos,
     the Tools pages, the sidebar, dark theme, share-to-upload (a real Downloads file through the
     media store) and the refusal of a share naming TG Drive's own files, audio playback and mini player, a video that
     can't play, the PDF viewer, passcode lock/unlock/remove, the accounts screen, landscape,
     large text, background sync from Settings, the service's process killed mid-use (it must come
     back by itself, with no error shown), error details with a problem report, and the
     report from the account menu, and a GitHub issue from an error's details. Any error the app
     shows fails the run.
   - `BackgroundSyncTest`: a sync with the app closed starts the service by binding, finishes,
     and the service stops afterwards. And the app opened during a sync: the main screen shows,
     and the service keeps running for it when the sync lets go.
   - `CrashScreenTest`: the crash screen with a planted report (error, buttons, the GitHub link,
     Open again). After it, the script crashes the interface's process for real (`am crash <pid>`
     of `app.tgdrive`; `am crash app.tgdrive` hit the `:engine` process instead) and fails if the
     crash screen doesn't come up.
   - `SignInFlow`: a fresh install, the real sign-in screens against Telegram with a made-up key
     (phone code and QR). Telegram must answer, and the app must show it.
   - `BigLibraryTest`: replaces the app's data with a 100 000-file, 1 700-chat index built on the
     emulator by `tests/bigdb.py` (packaged in the APK's `tests/` for this only), with a signed-out
     account (no live indexing). The main screen must show within 30 s of the service being ready,
     then the sidebar, All files (5 pages), Photos, a search, Storage and the chats list; Android
     must not report it as not responding. `big-library-timings.txt`, `big-library-frames.txt`
     (gfxinfo) and `big-library-memory-*.txt` are kept.

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
- All UI tests extend `UiDriver`; add helpers there, not in one test.
- Views are replaced while live data (the indexing counter, progress) redraws. Tap by position
  (`UiDriver.click`/`tapAt`), not with `UiObject2.click()`. `find` clears UiAutomator's
  accessibility cache first (stale nodes caused false "not found").
- Reach pages with `open("storage")` / `page("Storage")` (the open-screen intent), and use the
  sidebar only where the sidebar itself is under test.
- Scroll slowly (`SLOW`, 1200 px/s) so lists don't fling on after a row is found. `scrollTo` uses
  plain swipes plus fresh lookups (`swipeUp`); `UiObject2.scrollUntil` reads the cached tree and
  scrolled past a row that was on screen.
- Open files with `openFile(name) { opened }`: it taps the label below the top bar (the results
  page shows the query in the top bar, and a tap there reopened the search) and taps again if the
  first tap didn't take. Search submits with the app's own magnifier (`By.desc("Search").pkg(…)`);
  the keyboard's Search key has the same description.
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
- **GitHub issues:** the owner mostly reports with the **Create GitHub issue** button, so bug
  reports arrive as issues on `infinite4evr/vibes` (label `android`, `bug` if the labels exist).
  The body has "What happened", "Details" (the stack), "Phone and app", "The service's latest
  crash report" and log tails. Read them with the GitHub tools. The zip may be attached too.
- When the owner uploads one, read `report.txt` first, then `engine/engine-start.log` (timings),
  `app/app.log` (phases, "status answered in"), then `service/tgdrive.log`.

## 7. Signing and releases (why updates wouldn't install)

Until September 2026 every CI build was signed with a throwaway debug key, because the signing
secret didn't exist. Android refuses an update signed with a different key, so every build needed
an uninstall. Now:
- CI signs with the key in the repository secrets `TGDRIVE_KEYSTORE_BASE64` (a PKCS12 keystore,
  alias `tgdrive`, base64) and `TGDRIVE_KEYSTORE_PASSWORD`. Setup is in `signing/README.md`.
  They are set (October 2026). If they become unusable, the *Signing key* step says why and the build
  falls back to a throwaway key; the certificate check then refuses to publish it.
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

Verified: **everything green on commit `4a9262d`**. That covers the three workflows (TG Drive Android,
TG Drive desktop, CI) and, on the emulator with the minified `staging` build:
- `EngineTest` (7, including the cancelled-requests crash regression), `ScreenshotTour`,
  `CrashScreenTest` plus a real crash of the interface's process (the crash screen came up),
  `SignInFlow` against Telegram.
- `Journeys`: all 37.
- `BackgroundSyncTest`: both tests.
- `BigLibraryTest` (100 000 files, 1 700 chats): the service is ready in 0.8 s and the main screen
  shows 2.0 s later. Status plus a page of files takes at most 143 ms while the background jobs run.
  Memory at 100 000 files: about 146 MB for the app and 250 MB for the service (PSS). The emulator
  draws in software, so its frame statistics can't be compared with a phone's.

**The owner's black screen at ~100 000 files** could not be reproduced on the emulator: with a
100 000-file index the app opens in about 2 s. The real difference is a signed-in account whose
indexer and background jobs run while the app opens. Those jobs held Python's GIL, and on a phone
the first requests could take tens of seconds (a desktop measurement: 1.8 s for Storage instead of
2 ms). That is fixed (`pace.foreground`, §4). If it still happens, ask for **Send report** right after
it happens: `app.log` shows "status answered in … ms" and each phase, and `engine-start.log` shows
the start steps.

Also fixed in the last batch:
- A crash: cancelled requests had their responses closed on the main thread (§4).
- A download race on pause and resume (§4).
- A test-order cascade: a run that died in the passcode journey left the passcode set, which locked
  every later test out. `TestHygiene.removeLeftoverPasscode` now runs first.
- Found by reading the screenshots: the list toolbar pushed *View* and *More* off narrow screens
  and with large text (sort, copies and filters now scroll sideways). The crash screen's buttons
  were below a 40-line report (now above it). The *Chats and indexing* page was titled "Index
  manager", the desktop's name; the sidebar and the owner call it *Chats and indexing*.

Open items:
1. **Signing: done (October 2026).** The secrets are set, release `tgdrive-android-v2.4.0-43` was the
   first APK signed with the permanent key, and `signing/expected-certificate.sha256` holds its
   certificate, so CI refuses any other key. The owner uninstalls once and installs build 43 (or later);
   every build after that updates in place.
2. **Black screen at ~100 000 files** on the owner's phone: see above, needs the owner's
   confirmation or a report.
3. **Slow start on the owner's phone** (Samsung SM-M336BU, Android 16): waiting for a problem
   report after a slow start, to see which step is slow. Everything measurable on the emulator is
   fast.
4. **Folder upload through the system folder picker** isn't automated: the picker is another
   app, different on each Android version. Test it by hand on a phone after changes to
   `UploadService`.
5. **Accessibility:** the accessibility tree lagging behind scrolled rows (see §5) may also affect
   TalkBack. Worth a check with TalkBack on a real phone.
6. The Samsung battery deep link (`com.samsung.android.lool`) differs between One UI versions.
   It falls back to the app's settings page.
7. A sync whose process is killed shows "Syncing now…" in Settings until its time budget has
   passed (up to 10 min, `BackgroundSync.last`). Harmless; WorkManager reruns it.
8. Offered to the owner, not asked for yet: a "Remove file types no longer indexed" button (after
   narrowing *Indexing types*, the old types stay in the index until a full re-index).

## 9. Working with the owner

- Stop after significant work: list what was done and what's pending, and ask whether to continue.
- Build time is expensive: **push only when a whole batch of work is done**, not after each change.
- Commits: clear messages, ending with the session's attribution lines. Never mention model
  names in commits or code.
- Don't open a pull request unless asked.
