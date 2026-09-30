# Staging only (the release build, debuggable, for the emulator tests): shrinking and optimisation
# exactly as in release, but names kept, so the test APK can reach the app's classes.
-dontobfuscate
-keepclassmembers class app.tgdrive.AppGraph { public *; }
-keepclassmembers class app.tgdrive.engine.EngineClient { public *; }
-keepclassmembers class app.tgdrive.data.Api { public *; }
