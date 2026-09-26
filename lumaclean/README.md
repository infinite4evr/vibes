# LumaClean

An Android phone manager: cleaning, storage, apps, battery and device health in one app. Material 3, adapts to phones, foldables and tablets, and works fully offline (the app has no internet permission).

- **Get the APK:** every push that touches `lumaclean/` builds a release APK and publishes it on the repository's [Releases](../../releases) page. See [`BUILD_COMMANDS.md`](BUILD_COMMANDS.md) for local builds and signing.
- **Package:** `app.lumaclean` · minimum Android 8.0 (API 26) · targets Android 16 (API 36), compiled against API 37.

## Features

| Area | What it does |
|---|---|
| **Home** | Health score (storage, junk, memory, battery, unused apps) with the reasons and a fix for each, live storage / RAM / battery tiles, quick actions, last cleanup and recycle bin |
| **Smart Clean** | Finds this app's cache, thumbnail caches, temp and unfinished downloads, old logs, installer files (marked "already installed" when safe), leftovers of removed apps, empty folders and files, gallery trash and old downloads. Safe items are pre-selected, the rest are for review. One tap clears **every app's cache** through Android's own consent screen (Android 11+). Space freed is measured, not estimated. Long-press to add anything to the never-clean list |
| **Storage** | Breakdown by type (images, videos, audio, documents, installers, archives) plus apps and system, a file manager (open, share, copy, move, rename, new folder, delete) that sorts folders by size, large files, duplicates, old downloads, chat media, search, SD card |
| **Recycle bin** | Files deleted in LumaClean are moved (instantly, no copying) into a hidden bin and can be restored, with Undo right after deleting. Emptied automatically after 7–60 days |
| **Duplicates** | Exact copies only: size, then first/last 64 KB, then full SHA-256. Keep oldest / newest / the one in the main folder; one copy is always kept |
| **Photos** | Similar photos (bursts and near-copies, keeps the sharpest), screenshots, large videos, photo compression (three levels, keeps date/location/camera EXIF, fixes rotation, skips photos that wouldn't shrink ≥10%, copy or replace) |
| **Chat media** | WhatsApp, WhatsApp Business, Telegram and Signal folders split into images, videos, voice notes, documents, statuses… |
| **Apps** | Every app with size (app + data + cache), last used, installer (Play, Galaxy Store, file…); sort and filter; batch uninstall; unused apps (30–180 days); per-app details with storage, screen time, data use, all permissions (granted or not), SDK levels, and **save or share the APK** (split apps become `.apks`) |
| **Screen time & data** | Today / 7 / 30 days, daily bar chart, per-app screen time (from foreground events, like Digital Wellbeing), Wi-Fi and mobile data per app |
| **Memory** | Live RAM gauge and "Free up RAM" that ends cached background processes and reports what was actually freed |
| **Battery** | Level, health, temperature, voltage, current, power, estimated capacity, charge cycles (Android 14+), time to full, and 24 h / 7 day level and temperature charts recorded in the background |
| **Device & network** | Model, Android version and patch, chip, live per-core clock speeds, RAM, display, cameras, sensors (copy as a report); connection type, signal, band, link speed, IPs, DNS and data totals |
| **Background** | Weekly checkup notification when there's a lot to clean, storage-almost-full and battery-too-hot alerts, recycle bin expiry |
| **Everywhere** | Search for any tool, app or file; long-press multi-select with a bottom action bar; progress with Cancel for every scan; results kept when you switch screens; light/dark/system theme, Material You colours or four accents; home-screen shortcuts (Smart Clean, Free up RAM, Large files) |

## Code layout

```
app/src/main/java/app/lumaclean/
  LumaApp.kt          Application + AppContainer (repositories, background tasks, delete/restore helpers)
  MainActivity.kt     edge-to-edge activity, deep links from shortcuts and notifications
  core/               Task (cancellable background job with progress), Operations, permissions, formatting
  data/               FileIndex (one walk of storage shared by every file feature), JunkEngine,
                      DuplicateEngine, RecycleBin, FileOps, AppsRepository, SystemRepository,
                      MediaRepository, health score, settings and small JSON stores
  work/               weekly checkup + 15-minute monitor workers, notifications
  ui/                 theme, navigation, shared components, one file per screen group
```

## Permissions, and what Android doesn't allow

- **All files access** (`MANAGE_EXTERNAL_STORAGE`) powers cleaning, the file manager and media tools. **Usage access** powers app sizes, unused apps, screen time and data usage. Both are granted by the user in Settings; the app explains each one where it's needed.
- Without root, no app can clear other apps' caches one by one, read `Android/data` on Android 11+, see other apps' CPU use or really "cool the CPU". LumaClean uses Android's own consent screens instead of pretending.
- `MANAGE_EXTERNAL_STORAGE`, `QUERY_ALL_PACKAGES` and `PACKAGE_USAGE_STATS` need a declaration in the Play Console if this is ever published there; file and app management are the app's core purpose.

## Safety defaults

Nothing is deleted without a confirmation that says what goes. Personal files are never pre-selected. Deleted files go to the recycle bin unless you choose "delete for good". Scheduled checkups only notify; they never delete anything.
