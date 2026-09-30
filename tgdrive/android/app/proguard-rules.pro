# TG Drive for Android. Libraries (Chaquopy, kotlinx.serialization, OkHttp, Media3, Coil) ship
# their own rules; the app itself uses no reflection.
-dontwarn org.jetbrains.annotations.**
-dontwarn javax.annotation.**
# Chaquopy's Python code reaches these by name through the Java bridge.
-keep class com.chaquo.python.** { *; }
