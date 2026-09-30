plugins {
    id("com.android.application") version "9.4.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.10" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.4.10" apply false
    // Python in the app: MIT-licensed, maintained by the author of Python's own Android support (PEP 738)
    id("com.chaquo.python") version "17.0.0" apply false
}
