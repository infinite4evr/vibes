# The instrumented tests' own APK when it is minified along with the staging app.
-dontobfuscate
-dontwarn **
-keep class app.tgdrive.EngineTest { *; }
-keep class app.tgdrive.ScreenshotTour { *; }
-keep class org.junit.** { *; }
-keep class androidx.test.** { *; }
-keep class app.tgdrive.SignInFlow { *; }
