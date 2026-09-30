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
-keepclassmembers class app.tgdrive.engine.BackgroundSync { public *; }
-keepclassmembers class app.tgdrive.engine.BackgroundSync$Last { public *; }
-keepclassmembers class app.tgdrive.data.AppState { public *; }
-keepclassmembers class app.tgdrive.player.PlayerController { public *; }
-keepclassmembers class app.tgdrive.player.PlayerController$Companion { public *; }
-keepclassmembers class app.tgdrive.util.Format { public *; }
-keepclassmembers class app.tgdrive.engine.BatteryLimits { public *; }
-keepclassmembers class app.tgdrive.diag.** { public *; }
