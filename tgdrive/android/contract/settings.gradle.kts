// A desktop (JVM) build of the Android app's data layer (Api.kt, Models.kt, Format.kt, compiled
// unchanged), run against TG Drive's real service: every call the app makes, decoded with the
// app's own models. Not part of the Android build.
rootProject.name = "tgdrive-contract"

pluginManagement {
    repositories {
        maven("https://repo1.maven.org/maven2")
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories { maven("https://repo1.maven.org/maven2") }
}
