# TG Drive for Android

The TG Drive desktop app on a phone: the same service (Telegram, index, smart search, streaming,
transfers, folders that sync through your Telegram channel) running on the phone itself, with a
native interface built after the desktop design. No server, no computer needed.

Download the APK from the latest `tgdrive-android-v…` release (built by CI). Android 8.0 or newer,
64-bit ARM or x86.

Picking up development? Read **[HANDOVER.md](HANDOVER.md)**: scope decisions, code map, how to
build and verify, lessons learned, open items.

## How it works

```
┌──────────── app process ────────────┐      ┌──────────── :engine process ────────────┐
│ Jetpack Compose interface           │ HTTP │ EngineService (foreground, dataSync)    │
│  AppState ← live events (SSE)       │◀────▶│  Python 3.13 via Chaquopy               │
│  Media3 player, PdfRenderer, Coil   │ 127. │  tgdrive package (the desktop service)  │
│  UploadService (SAF → PUT /upload)  │ 0.0.1│  Telethon · SQLite + FTS5 · uvicorn     │
└─────────────────────────────────────┘      └─────────────────────────────────────────┘
```

- **The service is the desktop's own code** (`tgdrive/tgdrive`), run by Chaquopy in a separate
  process so a crash there can't take the interface down. Packages without an Android build have
  stand-ins in the package itself, used only where the real ones are missing: a Starlette adapter
  for FastAPI (`webapp.py`), a pure-Python tokenizer and safetensors reader (`tok.py`), a fuzzy
  matcher (`fuzzy.py`), transliteration (`translit.py`) and OpenSSL AES through ctypes for
  Telegram's encryption (`fastcrypto.py`). CI runs the service tests with exactly the Android
  package set (`service-android-mode` job).
- **SQLite full-text search**: Android's Python ships SQLite without FTS5, so the app builds FTS5
  as a loadable extension (`app/src/main/cpp/sqlite`, from the SQLite amalgamation of the same
  version) and registers it at start.
- **Only this app can talk to the service**: it listens on 127.0.0.1 with a secret that changes
  every start (`x-tgdrive-token`); streams handed to other players (VLC, MX Player) use a separate
  token that can only play streams.
- **Battery**: the service runs while the app is open and while something needs it (transfers,
  the background player), then stops after a minute. For the first 20 seconds after a start the
  CPU-heavy background jobs wait, so the first screens load first.
- **Background sync** (*Settings → This phone*): Android's job scheduler checks your chats for new
  files every 30 min–12 h (default 1 h) while the app is closed. It needs a network, never runs
  on low battery, and can be limited to Wi-Fi or charging. It binds the service without a
  notification, holds the heavy jobs until you open the app, and stops as soon as the chats are
  checked. If Android or Samsung's battery saver is holding it back, the page says so and opens
  the right settings. *Stay connected all the time* keeps the service running instead, at a
  higher battery cost.
- **The meaning model** (offline semantic search) is downloaded at build time, checked against a
  pinned SHA-256, and bundled; numpy comes from Chaquopy's repository. If numpy can't load on a
  device, search keeps working without the meaning tier.

## What's the same as the desktop

Browse (My Drive, All files, Starred, Recent, Continue watching, Photos, saved searches, Telegram
folders, subjects, tags, every chat), smart search with suggestions and operators, filters, sort,
grid/list, albums as stacks, folders with colours, emoji and smart/auto-filing rules, move, copy,
rename (also with patterns), tags, notes, subjects, star, undo, send to chat, delete/hide,
streaming video/audio/PDF/text with resume positions and playback speed, a background player with
a queue, downloads and uploads (files or whole folders, also *Share → TG Drive* from other apps),
Storage, Duplicates, Index manager, Activity, several accounts, sample data, proxy, app passcode,
maintenance, folder backups, settings backup, logs, crash reports and diagnostics. Settings are
the desktop's settings.

**Not on Android, by decision** (details in HANDOVER.md §2): folder sync with a folder on the
device, the "Drive on this computer" WebDAV mount (and an Android Files-app equivalent), desktop
integration (tray, autostart, title bar, file-manager menus), split and column views, keyboard
shortcuts, drag and drop, importing from old desktop versions, and the VLC/mpv launcher and `.m3u`
playlists. Android opens streams in any installed player instead, and plays queues in its own
background player.

## Problems and crashes

Wherever an error shows (its **Details**, error screens, the crash notice, *Settings → About &
diagnostics*, the account menu) there is **Create GitHub issue**. It opens a new issue on this
repository, filled in with the error, the phone, the service's state and the end of the logs; you
see it before sending. If the app crashes, it shows a crash screen with the same button instead
of closing (in its own process, so it works whatever broke). If the crashes repeat, the screen
also offers to reset the app's settings, keeping accounts and the index.

### Problem reports

*Settings → About & diagnostics → Send report* (also *Account menu → Report a problem*, error
screens and error **Details**) makes one `.zip` with the app's and the service's logs, crash
reports, startup timings and the phone's details. It has no passwords, keys, tokens or messages.
Turn on *Detailed debug logging* first, reproduce the problem, then send the zip.

## Build

CI builds everything (`.github/workflows/tgdrive-android.yml`): the service tests in Android mode
plus the contract harness (the app's real API code against the real service), the signed release
APK, and an emulator run of the minified build:
- `EngineTest`: the service on Android (search, streaming, the FTS5 extension).
- `ScreenshotTour`: every screen.
- `Journeys`: 37 end-to-end journeys, each checked against the service.
- `BackgroundSyncTest`: a sync with the app closed.
- `CrashScreenTest`, plus a real crash of the app's interface process: the crash screen must come up.
- `SignInFlow`: the real sign-in against Telegram.
- `BigLibraryTest`: a 100 000-file, 1 700-chat library built on the emulator. The main screen must
  show quickly and every big page must stay responsive (timings, frame statistics and memory are
  kept).

Screenshots and logs are pushed to the `tgdrive-android-screens` branch.

Locally, with JDK 17 and the Android SDK (platform 36, NDK and CMake from the SDK manager):

```bash
cd tgdrive/android
./gradlew :app:assembleDebug                 # all ABIs
./gradlew :app:assembleDebug -Pabis=arm64-v8a  # faster, one ABI
```

## Signing

Every release must be signed with the same key, or Android won't install it as an update. CI
signs with the key in the `TGDRIVE_KEYSTORE_BASE64` / `TGDRIVE_KEYSTORE_PASSWORD` repository
secrets and checks the certificate. **Setup and rules: [signing/README.md](signing/README.md).**
Without the secrets a build is signed with a throwaway key and warns about it. Local builds use
your own debug key.

## Layout

| Path | What |
|---|---|
| `app/build.gradle.kts` | Android, Chaquopy (Python 3.13, pinned `python-requirements.txt`), the model download, copying `../tgdrive` into the APK |
| `app/src/main/java/app/tgdrive/engine` | the service process, the client that starts/holds it, background sync, battery limits, uploads |
| `app/src/main/java/app/tgdrive/diag` | log files, crash reports, problem reports |
| `app/src/main/java/app/tgdrive/data` | the HTTP API, models, shared app state and live events |
| `app/src/main/java/app/tgdrive/ui` | the interface: theme (desktop design tokens and icons), browse, viewer, menus, pages, settings |
| `app/src/main/java/app/tgdrive/player` | Media3 background player |
| `app/src/main/cpp` | FTS5 as a SQLite extension |
| `app/src/androidTest` | emulator tests |
| `contract` | the app's API code run against the real service on a computer (CI and locally) |
| `signing` | how releases are signed (the key itself is in the repository secrets) |
