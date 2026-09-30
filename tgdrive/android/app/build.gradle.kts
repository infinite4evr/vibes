import java.net.URI
import java.security.MessageDigest
import java.util.zip.ZipInputStream

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("com.chaquo.python")
}

// CI builds only what the emulator needs with -Pabis=x86_64; phones are arm64-v8a.
// (Python 3.12+ on Android is 64-bit only.)
val abis = (project.findProperty("abis") as String? ?: "arm64-v8a,x86_64").split(",").map { it.trim() }

android {
    namespace = "app.tgdrive"
    compileSdk = 37

    defaultConfig {
        applicationId = "app.tgdrive"
        minSdk = 26
        targetSdk = 36
        // CI passes -PversionCode=<run number> so each release installs as an update
        versionCode = (project.findProperty("versionCode") as String?)?.toInt() ?: 1
        versionName = "2.4.0"
        ndk { abiFilters += abis }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        externalNativeBuild {
            cmake { arguments += listOf("-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON") }
        }
    }

    externalNativeBuild {
        cmake { path = file("src/main/cpp/CMakeLists.txt") }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Signed with the debug key; CI restores a stable one from a secret (see README)
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        checkReleaseBuilds = false
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    testOptions {
        animationsDisabled = true
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            options("--find-links", file("pywheels").absolutePath)
            install("-r", "python-requirements.txt")
        }
    }
    sourceSets {
        getByName("main") { srcDir(layout.buildDirectory.dir("generated/tgdrive-python")) }
    }
}

// ------------------------------------------------------------------ TG Drive's service
// The Python package is the desktop app's own (../../tgdrive), copied in at build time, plus the
// made-up account used by "Try it with sample data" and the emulator tests.
val syncTgdrivePython by tasks.registering(Sync::class) {
    val root = rootDir.parentFile
    from(root.resolve("tgdrive")) {
        into("tgdrive")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    from(root.resolve("run.py"))
    from(root.resolve("tests")) {
        into("tests")
        include("__init__.py", "fake.py", "demo_server.py")
    }
    into(layout.buildDirectory.dir("generated/tgdrive-python"))
}
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(syncTgdrivePython)
}

/** The meaning-search model (wordllama's l2_supercat: tokenizer and 256-d token embeddings), taken
 *  from the pinned wordllama wheel on PyPI and checked against known hashes. */
abstract class FetchModelTask : DefaultTask() {
    @get:Input abstract val url: Property<String>
    @get:Input abstract val wheelSha256: Property<String>
    @get:Input abstract val files: MapProperty<String, String>   // path in wheel -> sha256
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction
    fun fetch() {
        val out = outputDir.get().asFile.resolve("model")
        out.deleteRecursively()
        out.mkdirs()
        val bytes = URI(url.get()).toURL().openStream().use { it.readBytes() }
        check(sha256(bytes) == wheelSha256.get()) { "wordllama wheel hash mismatch" }
        val wanted = files.get()
        ZipInputStream(bytes.inputStream()).use { zip ->
            while (true) {
                val e = zip.nextEntry ?: break
                val hash = wanted[e.name] ?: continue
                val data = zip.readBytes()
                check(sha256(data) == hash) { "${e.name}: hash mismatch" }
                out.resolve(e.name.substringAfterLast('/')).writeBytes(data)
            }
        }
        check(out.list()!!.size == wanted.size) { "model files missing from the wheel" }
    }

    private fun sha256(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }
}

val fetchModel by tasks.registering(FetchModelTask::class) {
    url.set("https://files.pythonhosted.org/packages/bc/3d/4917a64f871b1c7404ff62653cac905279b6c422986720e98ff58c654342/wordllama-0.4.0.post1-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl")
    wheelSha256.set("c78466f0600550742b37eb9f8212cac1e548632f41bfc1f6c828b5726332b49e")
    files.set(mapOf(
        "wordllama/tokenizers/l2_supercat_tokenizer_config.json" to "93248f2a9ec36c7b35f700a033d5f36228aae48db61aee31007fa49062cdeb68",
        "wordllama/weights/l2_supercat_256.safetensors" to "64b47a2dc493cb8e85944076601189739852d7b64e0e1eedcb1937a251cd9fd5",
    ))
    outputDir.set(layout.buildDirectory.dir("generated/model-assets"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(fetchModel, FetchModelTask::outputDir)
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-process:2.11.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    implementation("com.squareup.okhttp3:okhttp:5.5.0")
    implementation("io.coil-kt.coil3:coil-compose:3.6.3")
    implementation("io.coil-kt.coil3:coil-network-okhttp:3.6.3")

    implementation("androidx.media3:media3-exoplayer:1.8.0")
    implementation("androidx.media3:media3-session:1.8.0")
    implementation("androidx.media3:media3-ui:1.8.0")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("androidx.documentfile:documentfile:1.0.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:rules:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}
