# Staging only (the release build, debuggable, for the emulator tests): shrinking and optimisation
# exactly as in release, but names kept, so the test APK can reach the app's classes.
-dontobfuscate
-keepclassmembers class app.tgdrive.AppGraph { public *; }
-keepclassmembers class app.tgdrive.engine.EngineClient { public *; }
-keepclassmembers class app.tgdrive.data.Api { public *; }
# The test APK shares the app's copy of these libraries (it doesn't carry its own), so keep them
# whole here; the app's own code is still shrunk and optimised as in release.
-keep class kotlin.** { *; }
-keep class kotlinx.coroutines.** { *; }
-keep class okhttp3.** { *; }
-keep class okio.** { *; }
-keep class kotlinx.serialization.json.** { *; }
-keepclassmembers class app.tgdrive.engine.BackgroundSync { public *; }
-keepclassmembers class app.tgdrive.engine.BackgroundSync$Last { public *; }
-keepclassmembers class app.tgdrive.data.AppState { public *; }
-keepclassmembers class app.tgdrive.player.PlayerController { public *; }
-keepclassmembers class app.tgdrive.player.PlayerController$Companion { public *; }
-keepclassmembers class app.tgdrive.util.Format { public *; }
-keepclassmembers class app.tgdrive.engine.BatteryLimits { public *; }
-keepclassmembers class app.tgdrive.diag.** { public *; }
-keep class app.tgdrive.data.Phase { *; }
-keep class app.tgdrive.data.Phase$* { *; }
-keepclassmembers class app.tgdrive.engine.EngineState { public *; }

# Public entry points exercised directly by the reliability instrumentation.
-keep class app.tgdrive.storage.** { *; }
-keep class app.tgdrive.engine.UploadJournal** { *; }
-keep class app.tgdrive.data.StartupCache** { *; }
-keep class app.tgdrive.data.BrowseModel** { *; }
# Models the reliability instrumentation constructs directly (R8 would otherwise drop or merge
# their default-argument constructors, which only the test APK calls).
-keep class app.tgdrive.data.Account { *; }
-keep class app.tgdrive.data.AppStatus { *; }
-keep class app.tgdrive.data.IndexStatus { *; }
