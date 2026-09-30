plugins {
    kotlin("jvm") version "2.4.10"
    kotlin("plugin.serialization") version "2.4.10"
    application
}


// The app's files, copied in unchanged.
val appSrc = rootDir.resolve("../app/src/main/java/app/tgdrive")
val shared by tasks.registering(Sync::class) {
    from(appSrc.resolve("data")) { include("Api.kt", "Models.kt"); into("app/tgdrive/data") }
    from(appSrc.resolve("util")) { include("Format.kt"); into("app/tgdrive/util") }
    into(layout.buildDirectory.dir("shared"))
}

kotlin {
    sourceSets["main"].kotlin.srcDirs("src", layout.buildDirectory.dir("shared"))
}
tasks.named("compileKotlin") { dependsOn(shared) }

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    implementation("com.squareup.okhttp3:okhttp:5.5.0")
}

application { mainClass.set("app.tgdrive.contract.MainKt") }
