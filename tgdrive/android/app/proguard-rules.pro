# TG Drive for Android. Libraries (Chaquopy, kotlinx.serialization, OkHttp, Media3, Coil) ship
# their own rules; the app itself uses no reflection.
-dontwarn org.jetbrains.annotations.**
-dontwarn javax.annotation.**
# Chaquopy's Python code reaches these by name through the Java bridge.
-keep class com.chaquo.python.** { *; }
# Background sync (WorkManager): its Room database and the workers are created by reflection.
-keep class * extends androidx.room.RoomDatabase { <init>(...); }
-keep class * extends androidx.work.ListenableWorker { <init>(android.content.Context, androidx.work.WorkerParameters); }
