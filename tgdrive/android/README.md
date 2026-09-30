# TG Drive for Android

The TG Drive desktop app on a phone: the same service (Telegram, index, smart search, streaming,
transfers, folders that sync through your Telegram channel) running on the phone itself, with a
native interface built after the desktop design. No server, no computer needed.

Download the APK from the latest `tgdrive-android-v…` release (built by CI). Android 8.0 or newer,
64-bit ARM or x86.

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
  the background player, or *Settings → This phone → Keep running*), then stops after a minute.
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

Not on Android: the WebDAV drive, folder sync with a folder on disk, split view and the desktop
integration settings (tray, title bar, file-manager menus).

## Build

CI builds everything (`.github/workflows/tgdrive-android.yml`): the release APK, the service tests
in Android mode, and an emulator run (`EngineTest` starts the real service and checks search,
streaming and the FTS5 extension; `ScreenshotTour` walks through every screen on the sample data
and keeps the screenshots as an artifact).

Locally, with JDK 17 and the Android SDK (platform 36, NDK and CMake from the SDK manager):

```bash
cd tgdrive/android
./gradlew :app:assembleDebug                 # all ABIs
./gradlew :app:assembleDebug -Pabis=arm64-v8a  # faster, one ABI
```

CI signs releases with a stable key restored from the `TGDRIVE_DEBUG_KEYSTORE_BASE64` secret (the
same arrangement as LumaClean), so each new APK installs as an update over the last one. A local
build uses your own debug key.

## Layout

| Path | What |
|---|---|
| `app/build.gradle.kts` | Android, Chaquopy (Python 3.13, pinned `python-requirements.txt`), the model download, copying `../tgdrive` into the APK |
| `app/src/main/java/app/tgdrive/engine` | the service process, the client that starts/holds it, uploads |
| `app/src/main/java/app/tgdrive/data` | the HTTP API, models, shared app state and live events |
| `app/src/main/java/app/tgdrive/ui` | the interface: theme (desktop design tokens and icons), browse, viewer, menus, pages, settings |
| `app/src/main/java/app/tgdrive/player` | Media3 background player |
| `app/src/main/cpp` | FTS5 as a SQLite extension |
| `app/src/androidTest` | emulator tests |
