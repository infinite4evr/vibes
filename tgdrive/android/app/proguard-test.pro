# The instrumented tests' own APK when it is minified along with the staging app.
-dontobfuscate
-dontwarn **
-keep class app.tgdrive.EngineTest { *; }
-keep class app.tgdrive.ScreenshotTour { *; }
-keep class org.junit.** { *; }
-keep class androidx.test.** { *; }
-keep class app.tgdrive.SignInFlow { *; }

-keep class app.tgdrive.ReliabilityTest { *; }
-keep class app.tgdrive.RecoveryJourneys { *; }
-keep class app.tgdrive.PortableStorageTest { *; }
-keep class app.tgdrive.DataFolderSetup { *; }
