# TG Drive, LumaClean and PC Command Center update

## Updating

1. Keep a backup of your current app data.
2. **Install the updated Android app over the old one before uninstalling.** First select the persistent folder and let migration finish. An older installation's private data cannot be recovered after Android has already removed it during uninstall.
3. SQLite additions are created automatically. No manual database migration is required.

## Persistent TG Drive data folders

| Platform | Default |
| --- | --- |
| Android | Internal shared storage / `TG Drive` (normally `/storage/emulated/0/TG Drive`) |
| Windows | `%LOCALAPPDATA%\TG Drive` |
| macOS | `~/Library/Application Support/TG Drive` |
| Linux | `$XDG_DATA_HOME/tgdrive`, or `~/.local/share/tgdrive` |

On a new installation, choose the default or another dedicated folder. An existing default profile is detected automatically once storage permission is available. After reinstalling, select your previous custom folder to recover that profile. Android must grant storage access again after reinstalling; the app cannot restore an Android permission itself.

The desktop folder contains settings/API credentials, Telegram sessions, account indexes, transfer queues, offline copies, service caches/logs, the Qt web profile and window settings. Android keeps service state in `service/`, phone preferences in `android/preferences.json`, durable phone state and upload staging in `android/state/`, logs in `android/logs/`, and cached images/model files in `android/`. `service/` and `android/` carry a `.nomedia` file so gallery and music apps don't list thumbnails, offline copies or caches.

Phone preferences preserve their types, including account IDs, and restore the selected account, appearance, player and background-sync preferences. The small pointer to the selected folder, operating-system permissions, WorkManager scheduling, temporary launch tokens and installed Python/native runtime remain app-private and are recreated. Files originally picked from another app are not copied until upload staging; after reinstalling, an unstaged upload may require picking its source again.

Keep this folder private: it contains Telegram sessions and API credentials. The app lock is an interface lock; it does not encrypt the shared folder. Do not put the folder in Android/data or Android/obb, or in a temporary directory. The Android selector rejects app-specific storage and storage roots. Downloads keep going to the usual place (`Download/TG Drive` on the phone, `~/Downloads/TG Drive` on desktop) or to the folder chosen in Settings → Downloads; external sync/source folders retain their own paths. The selected folder holds TG Drive's own data.

Change the folder later in **Settings → Data & maintenance** on desktop, or **Settings → Data & maintenance → Data folder** on Android. Desktop copies at the next full restart, after the service releases its databases. A copy that fails (a full disk, a removed drive) is cleaned out of the destination and TG Drive keeps starting from the original folder; it says why once. If the selected folder itself is missing at startup (an unplugged drive), TG Drive asks for it instead of starting with an empty profile. Android closes the service and UI before changing the folder. Copying to an empty folder retains the original. Selecting an existing TG Drive profile opens that profile without merging accounts from another profile. Nested destinations and unrelated nonempty directories are rejected.

Absolute paths owned by the profile are updated after a move, including offline files, transfers, sync pairs and staged phone uploads. Only known TG Drive database tables are changed; downloaded databases and browser files are never scanned or rewritten. Interrupted/failed copies leave the original selected. If a partial destination remains after a failure, use a new empty folder or inspect/remove the partial copy before retrying; do not delete the original.

`--data` and `TGDRIVE_DATA` remain explicit desktop overrides. Remove those overrides to use the stored GUI selection on later launches. The native desktop window stores its web preferences in the selected folder; an independently opened system browser retains its own browser profile.

Android storage references: [shared storage](https://developer.android.com/training/data-storage/shared), [all-files access](https://developer.android.com/training/data-storage/manage-all-files).

## Issues fixed

1. **Cancelled LumaClean recycle batches could orphan already-moved files.** Each item is journaled before its move, with atomic persistence and cancellation-safe index refresh.
2. **Missing/removable storage could make recycle records disappear.** Reconcile, restore, permanent-delete and expiry paths retain inaccessible entries so reconnecting storage permits recovery.
3. **Partial LumaClean copies could look complete or expose partially copied folders.** Chunked cancellation checks, temporary destinations, file synchronization, source-change checks and staged folder publication protect the original and remove incomplete destinations.
4. **Android release publishing could run before required validation finished.** Publishing depends on successful build/service jobs and successful requested emulator tests; failure, cancellation and unrequested skips are distinguished.
5. **An empty/crashed instrumentation run could escape failure detection.** CI now requires a positive completed-test count, and APK installation failures stop the run.
6. **Android bootstrap requests could outlast the intended startup deadline.** Startup now has an overall deadline, bounded status requests, cancellation and retry handling.
7. **Delayed responses could replace the newly selected account's content.** Account generations/load IDs reject stale state and cache writes.
8. **Reloading during pagination could leave Load more stuck.** Reload cancels old pagination jobs, clears the flag and discards stale page/stat responses.
9. **Locked startup could recreate a cleared screen cache.** Cache reads/writes respect lock state and invalidation generations; disk updates are atomic.
10. **Startup cache query keys could collide around delimiter characters.** Query components are encoded independently.
11. **Background sync could call paused, failed or unknown indexing successful.** Only a completed idle state counts as success; bounded waits and failure/cancellation reporting replace false success.
12. **Phone uploads waiting for service handoff were memory-only.** A durable journal, interrupted-upload recovery and idempotent handoff prevent lost queue entries and repeated handoffs. Files picked with a lasting permission are read again after a restart; only files shared with a temporary permission are copied to staging first (within the staging limit; bigger ones are sent directly). The permission is released once the file is handed over.
13. **Demo/live upload handoffs could cross modes after a restart.** Journal entries carry their mode and retry checks the running service's mode.
14. **Generic transfer deletion could remove a pinned offline copy.** Offline paths are protected; removal goes through the explicit offline-copy action.
15. **Paused indexing did not always appear in Recovery.** Recovery now checks the actual pause flag as well as phase/error state.
16. **Diagnostic text could expose names/search terms without a preview.** Android reports omit free-form personal text by default and require an explicit preview/share action; detailed text is opt-in.
17. **Migration could leave stale local paths or alter unrelated databases.** Path rebasing is restricted to app-owned records, supports Windows separators, and updates phone catalogs/journals and Android sibling download paths.
18. **Native settings could disappear on reinstall or folder selection.** Portable typed phone preferences and a data-folder-local desktop settings file preserve them, with migration of existing desktop settings.

### Android icon-then-close report

The launcher icon still opens the main screen directly (existing home-screen icons keep working). If a launch dies before its main screen appears, the next launch opens a small startup screen in a separate process instead, with recent app reports, logs and Android process-exit history, and a way to open TG Drive again or choose another data folder. Heavy app-graph initialization is lazy; early preference/setup failures show a readable fallback with a folder-selection action. Service startup still has its retry/error screen and bounded bootstrap.

**The exact crash on your phone has not been reproduced or identified without its crash/exit log.** These changes address silent startup handling and known startup failure paths. A native/library/device-specific failure still needs the new Startup details output or logcat to identify its cause. The added emulator smoke test covers both a normal cold launch and intentionally corrupted portable preferences.

**Follow-up (the icon stays, no new logs, after a cleaner app).** Starting TG Drive no longer depends on the shared data folder answering, and no failure goes unrecorded:

- Every start is recorded step by step in TG Drive's own app storage (`startup.log`), written at once, before the data folder is touched. Cleaner apps can't reach it.
- A watchdog checks the main thread until the first screen shows. If it's busy for 5 s, its stack is recorded. If it's stuck for 15 s, the startup screen opens and says where it was stuck, instead of the icon staying on screen.
- A start that ended before its main screen, however it ended, is explained at the next launch: Android's exit reason and the last step. Before, only crashes and freezes reported by Android counted, and anything else was retried blindly.
- The startup screen, the crash screen and "Create GitHub issue" never wait on the data folder. Crash reports go to TG Drive's own storage first, and the startup screen says when the folder isn't answering.
- Files cleaner apps delete come back on their own: the app log and its folder, the service log (it used to keep writing into the deleted file), the thumbnail cache (every thumbnail used to fail until a restart), the `.nomedia` markers and the startup cache folder.
- A damaged `preferences.json` is set aside as `preferences.json.damaged`. TG Drive opens with the phone's own settings and says so, instead of stopping at an error screen at every launch.
- The emulator smoke test now covers a cleaned-out data folder, a damaged preferences file and a launch that hangs.

## Features added

- **Offline files and folders:** pin from file/folder actions, view completion and byte counts, open complete local copies, retry missing/failed copies and remove only the local copy. Folder subscriptions include descendants and pick up new indexed files. Removing an individual copy excludes it from automatic re-pinning until explicitly pinned again. Stopping a folder subscription keeps existing copies.
- **Offline & recovery page on desktop and Android:** actionable transfer, indexing, folder-sync and offline failures. Android additionally exposes durable pending-upload retry/removal and a saved offline catalog when the service is unavailable.
- **Storage/data controls:** offline reservation limit, daily automatic-download budget, thumbnail cache target, existing streaming cache limit presented alongside them, and Android upload-staging limit. Manual retries may exceed the daily automatic budget; offline capacity still applies. Budgets are per account where labeled. Lower limits do not delete pinned data. Thumbnail cleanup protects the current response, so one active image can temporarily exceed its target; enforcement occurs when thumbnails are written/fetched.
- **Privacy preview for Android reports:** personal text omitted by default, names/search terms opt-in, review before sharing and cancel without sending. Detailed error logs can contain arbitrary third-party text, so review the opt-in report.
- **LumaClean cleanup explanations:** per-item reason, path and size in the confirmation, a scrollable preview and clear irreversible-action wording. Recycle entries show when their storage is unavailable.
- **PC Command Center action previews:** prerequisites, expected effects and rollback guidance in terminal and GTK confirmations. Missing required executables/directories disable confirmation. Optional tools and internal Python actions remain usable. Actions without a defined rollback say so; this is guidance, not an automatic undo engine.
- **Persistent TG Drive data-folder selection and restore**, including credentials, sessions and native preferences, on Android and desktop.
- **Android startup recovery screen and process-exit diagnostics**, plus CI cold-launch/failure checks.

Search inside documents and file revision history were **not added**. Existing filename/metadata search remains as supplied.

## Tests and coverage

See `TEST_RESULTS.md` for executed results and limitations. New automated cases cover the changes through browser/UI journeys, HTTP-to-database/transfer integration, filesystem lifecycle checks and Android instrumentation. These use temporary data and a deterministic fake Telegram transport unless an existing test explicitly exercises Telegram sign-in. They do not use your Telegram credentials.
