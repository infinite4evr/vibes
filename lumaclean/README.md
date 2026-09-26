# LumaClean

> **Linux:** Start with [`BUILD_COMMANDS.md`](BUILD_COMMANDS.md). For the normal build you only need `chmod +x build-apk.sh` once, then `./build-apk.sh`.


## One-command Linux APK build

1. Install Android Studio and use **Tools → SDK Manager** to install **Android SDK Platform 37**.
2. In a terminal inside this project, run:

```bash
chmod +x build-apk.sh
./build-apk.sh
```

The first build downloads Gradle and Android dependencies automatically. When it finishes, the installable debug APK is copied to the project root as **`LumaClean.apk`**. Later builds reuse the downloaded Gradle files.

If Android Studio is installed in a normal Linux location, the script automatically detects its JDK/SDK. You do not need to install Gradle separately.

A modern Android cleaner + storage manager inspired by the useful parts of CCleaner/Avast Cleanup, Files by Google, Norton Cleaner, Samsung Device Care, and SD Maid — implemented around current Android privacy/security rules instead of pretending to have root privileges.

## Implemented in this starter project

- Animated Material 3 storage dashboard
- Quick junk scan with conservative safe/review classification
- Own-app cache cleanup
- Deep shared-storage scan when the user explicitly grants **All files access**
- Temporary file, thumbnail, old APK, old log, zero-byte and empty-folder review
- Exact duplicate finder using file size pre-grouping + SHA-256
- Duplicate cleanup that retains the newest copy
- Large-file scan via MediaStore
- Media storage breakdown for images, video, audio and screenshots
- Similar-photo grouping using a lightweight perceptual dHash over recent images
- Photo optimizer using the system photo picker; creates smaller JPEG copies and keeps originals
- Installed-app manager
- Per-app cache/data/app size through `StorageStatsManager` after Usage Access
- Last-used dates via `UsageStatsManager`
- Open each app's Android storage/settings screen for individual cache management
- Guided per-app cache-cleaning fallback for devices where Android does not expose bulk automated clearing
- 30+ day unused-app hints from UsageStats
- Android's system `ACTION_CLEAR_APP_CACHE` consent flow for clearing app caches in bulk
- Uninstall handoff for user apps
- SD-card destination selection using Storage Access Framework
- Recursive move/copy engine with folder merge, duplicate skip, conflict rename and copy verification
- Dedicated WhatsApp shared-media migration
- General shared-storage migration to SD card
- Daily battery-friendly scan using WorkManager; it notifies instead of silently deleting personal files
- Local-only operation; no analytics SDK or cloud upload code

## Important Android limitations

Normal third-party Android apps cannot silently delete every other app's private cache, access `/data/data/<package>`, move private WhatsApp databases/session data, or force-stop arbitrary apps. LumaClean therefore uses Android's supported system consent/settings flows.

`MANAGE_EXTERNAL_STORAGE` and `QUERY_ALL_PACKAGES` are sensitive Google Play permissions. If this is published, the store listing and Play Console declarations must make file management/maintenance and app management genuine, prominent core functionality. If Play approval is not desired, remove those permissions and rely on MediaStore + Storage Access Framework.

## Build

Use Android Studio **Quail 4 (2026.1.4) or newer**, JDK 17, Android SDK 37, and sync Gradle.

This source targets Android 16 (API 36), satisfying the Google Play target requirement effective August 31, 2026, while compiling with API 37 for current Compose libraries.

For Linux, the included `build-apk.sh` bootstraps the required Gradle version automatically, so a separate Gradle installation is not required.

## Researched optional extensions

Current cleaner products also offer features such as duplicate/incomplete contact cleanup, cloud transfers/backups, location/condition-based battery profiles, noisy-notification insights, browser-data shortcuts, custom cleaning rules and root/Shizuku power features. They are intentionally not enabled by default here because several require additional sensitive permissions, external OAuth credentials, Accessibility review, or elevated privileges.

## Suggested next production modules

- Similar-photo grouping with perceptual hashes and user review
- Blurry/dark photo scoring on thumbnails
- Image/video compression with original backup option
- Screenshot/meme review cards
- Downloads aging rules
- Storage treemap analyzer
- Orphan-folder finder for uninstalled apps
- Export/import cleanup rules
- Optional Shizuku/root companion build for enthusiasts (not the Play-default build)
- Automated UI/instrumentation tests and benchmark profile

## Safety defaults

User media and files marked “Review” are never preselected. Scheduled scans never delete personal files automatically. SD moves verify destination length before source deletion and hash-check conflicts up to 128 MB.
