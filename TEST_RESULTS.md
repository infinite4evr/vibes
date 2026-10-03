# Validation and regression coverage

Results recorded for the updated source on 2026-10-03. Android compilation is not an emulator/device test result.

## Executed here

| Check | Result |
| --- | --- |
| TG Drive service/integration suite, excluding browser tests | 96 passed, 5 skipped |
| TG Drive Playwright browser journeys | 36 passed |
| PC Command Center suite, including terminal confirmation UI journeys | 272 passed, 3 skipped |
| TG Drive Android Kotlin, debug application + instrumentation sources | Compiled successfully |
| TG Drive Android Kotlin, staging application + instrumentation sources | Compiled successfully |
| LumaClean Android Kotlin, debug application + instrumentation sources | Compiled successfully |
| Python parsing, web JavaScript parsing, workflow YAML and CI shell syntax | Passed |
| ZIP CRC, relative paths and byte comparison against changed source | Passed |

The browser and service suites use a sample Telegram transport and real temporary SQLite/filesystem state. They verify UI-to-service behavior without accessing a real Telegram account. The Android build retains the supplied dependency versions. A final incremental Kotlin build reported conflicting overloads with no duplicate source declarations; recompiling with `-Pkotlin.incremental=false` succeeded. The service run emits one upstream Starlette/httpx deprecation warning. Optional dependency/platform checks account for the skips; they are not represented as passes.

A first sandbox-restricted PC run could not exercise its local network fixtures. The complete run with those fixtures enabled passed, as recorded above. Browser tests initially exposed a paused-index Recovery bug, now fixed; the folder-pin test was also isolated from a preceding deliberate offline exclusion.

## Added coverage mapped to changes

| Area | Automated cases |
| --- | --- |
| Offline pin completion, opening, restart, deletion and cache protection | `tgdrive/tests/test_offline_recovery.py`: `test_pin_download_restart_cache_cleanup_open_unpin`; browser `test_offline_pin_open_and_remove_via_ui`; Android `RecoveryJourneys.pinFromMenuThenRemoveCopyKeepsOriginal` |
| Offline capacity and automatic download budget | Service `test_storage_budget_rejects_before_partial_pin`, `test_folder_daily_budget_missing_file_and_manual_recovery`; browser `test_offline_budgets_persist_across_reload` |
| Folder subscriptions, unsubscribe, explicit exclusions | Service `test_unpin_in_subscribed_folder_stays_removed_until_explicit_repin`; browser `test_folder_pin_and_stop_automatic_downloads` |
| Recovery actions and idempotent upload handoff | Service `test_upload_receipt_prevents_duplicate_handoff_and_recovery_resumes`; browser `test_recovery_resumes_indexing_through_ui`; Android `RecoveryJourneys.interruptedStagedUploadCanBeRetriedFromRecovery` |
| Independent thumbnail budget | Service `test_thumbnail_budget_does_not_touch_pins` |
| Offline action discoverability | Browser `test_file_menu_offline_action_and_recovery_empty_state` |
| First data-folder selection, default detection, reinstall credentials and sessions | `tgdrive/tests/test_data_location.py`: first selection/reinstall and existing-default cases; Android `PortableStorageTest.folderCopyReinstallAndTypedSettingsRestore` |
| Data-folder copy, reuse, failures, process locks and safe paths | Remaining `test_data_location.py` cases cover retained originals, no merging into another profile, failed copies, another live process, nested/unrelated folders, Android sibling paths, Windows separators and untouched downloaded databases |
| Phone preference types and staged upload paths after relocation | `PortableStorageTest.folderCopyReinstallAndTypedSettingsRestore` |
| Rejected uninstallable/nonempty Android directories | `PortableStorageTest.folderSelectionRejectsUninstallableAndUnrelatedFolders` |
| Data-folder settings UI | Browser `test_data_folder_selection_is_scheduled_from_settings`; Android `RecoveryJourneys.selectedDataFolderAndChangeActionAreVisible` |
| Account switching and stale cache writes | `ReliabilityTest.delayedAccountCannotReplaceNewAccountOrCache` |
| Pagination reload cancellation | `ReliabilityTest.reloadDuringPaginationCanLoadMoreAgain` |
| Overall startup deadline | `ReliabilityTest.stalledStatusHasOverallDeadline` |
| Lock privacy and unambiguous startup cache keys | `ReliabilityTest.lockedBootstrapCannotRecreateSavedScreen`, `cacheKeysSeparateLiteralDelimiters` |
| Durable/concurrent upload journal | `ReliabilityTest.journalSurvivesReopeningAndConcurrentWriters` |
| Accurate background sync result | `ReliabilityTest.syncNeverMarksPausedErrorOrUnknownAsUpToDate` |
| Private default report and explicit opt-in | `ReliabilityTest.reportZipOmitsNamesByDefaultAndHonoursOptIn`; `RecoveryJourneys.privacyPreviewDefaultsOffAndCancelDoesNotShare`; existing sharing journey updated for the preview |
| Silent/early startup failures | `.github/scripts/tgdrive-startup-smoke.sh`: actual cold launcher and deliberately corrupted preferences; existing `CrashScreenTest` and real-process-crash CI check retained |
| Recycle cancellation persistence and missing storage | LumaClean `FileSafetyTest.cancelledBatchCanRestoreMovedFiles`, `disconnectedStorageKeepsRestoreRecord` |
| Partial/cancelled copy safety and changing source | LumaClean `FileSafetyTest.cancelledCopyLeavesNoPartialDestination`, `changingSourceFailsWithoutPublishingCopy` |
| Cleanup explanation, cancel and confirmed deletion | LumaClean `CleanupPreviewTest`, using a real scanned fixture and the Compose cleanup screen |
| Action prerequisites, effects, rollback, missing commands and cancel | `pc-command-center/tests/test_action_preview_e2e.py`: four cases, including real Textual confirmation dialogs |
| Publish dependency gates and empty/crashed instrumentation | `tgdrive/tests/test_release_gate.py`: truth table across job outcomes and positive-completion matching; LumaClean publish ordering |

The suite adds **14 TG Drive Android instrumentation cases** and **5 LumaClean cases**, as well as the launcher shell smoke checks. The Python/browser cases are a mix of E2E journeys and focused integration tests; the distinction is intentional so races, copy failures and process locks can be tested deterministically.

## Not executed here

- Android emulator/instrumentation or tests on a physical phone: this environment has no usable KVM device. The sources compile and the workflows run the tests before publishing when required. Their runtime outcome is still pending.
- The new launcher smoke checks and malformed-preferences UI case: included in the staging emulator workflow, not run locally.
- A complete release APK/NDK packaging build or installation on the user's device. The supplied ZIP contains source changes, not a signed APK.
- Native desktop Qt and GTK window interaction on Windows/macOS/Linux. Service/browser behavior and the Textual confirmation flow were exercised; native GUI and OS-specific storage/permission behavior still need platform checks.
- The exact reported phone crash: no device crash/exit log was available. Do not interpret successful compilation as proof that the user's crash is resolved.

## Running the checks

From `tgdrive/`, in the project's Python environment:

```bash
python -m pytest tests --ignore=tests/test_e2e.py -q
python -m playwright install chromium
python -m pytest tests/test_e2e.py -q
```

If Chromium is already installed, `TGDRIVE_TEST_CHROMIUM=/absolute/path/to/chromium` selects it.

From `pc-command-center/`:

```bash
python -m pytest tests -q
```

With the Android SDK, JDK 17, Gradle 9.6.0 and the project build prerequisites, from `tgdrive/android/`:

```bash
gradle --no-daemon :app:compileStagingKotlin :app:compileStagingAndroidTestKotlin -PtestBuildType=staging -Pabis=x86_64 -Pkotlin.incremental=false
gradle --no-daemon :app:assembleStaging :app:assembleStagingAndroidTest -PtestBuildType=staging -Pabis=x86_64
# Boot a disposable emulator, then:
bash ../../.github/scripts/tgdrive-android-emulator.sh
```

From `lumaclean/`:

```bash
gradle --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest
# Boot a disposable emulator, then:
bash ../.github/scripts/lumaclean-emulator.sh
```

The emulator scripts use sample data, deliberately alter preferences and simulate failures; run them on disposable test emulators. Select `full`/`emulator` in the TG Drive workflow to enforce its device journeys. No workflow, remote release or deployment was triggered while preparing this update.
