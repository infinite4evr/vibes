# LumaClean — Linux build commands

## Fast path

### 1. Extract the ZIP

From the directory where you downloaded it:

```bash
unzip LumaClean-Final-Linux.zip
cd LumaClean
```

### 2. Make the scripts executable

```bash
chmod +x build-apk.sh install-apk.sh
```

### 3. Build the APK

```bash
./build-apk.sh
```

When the build succeeds, the APK is copied to:

```text
LumaClean.apk
```

That is the APK you can copy to your phone and install.

---

## One-time prerequisites

The build script needs:

- Android SDK with Android SDK Platform 37
- Java 17 or newer
- `curl` or `wget`
- `unzip`

The easiest setup is Android Studio. Open Android Studio once and install **Android SDK Platform 37** from **Tools → SDK Manager**.

If you are using Ubuntu, Debian, Linux Mint, Pop!_OS or another apt-based distribution, these terminal commands install the small command-line prerequisites and JDK 17:

```bash
sudo apt update
sudo apt install -y openjdk-17-jdk curl unzip
```

Check Java:

```bash
java -version
```

If Android Studio has already installed its own JDK, `build-apk.sh` can usually detect it and you may not need the OpenJDK package above.

### Android SDK location

The script checks common Linux locations automatically, especially:

```text
$HOME/Android/Sdk
$HOME/Android/sdk
/opt/android-sdk
/usr/local/lib/android/sdk
/usr/lib/android-sdk
```

If your SDK lives somewhere else, set it before building:

```bash
export ANDROID_SDK_ROOT="/path/to/your/Android/Sdk"
export ANDROID_HOME="$ANDROID_SDK_ROOT"
./build-apk.sh
```

---

## Rebuild after changing code

Just run:

```bash
./build-apk.sh
```

The downloaded Gradle files are reused on later builds.

---

## Install the APK over USB (optional)

Enable **Developer options → USB debugging** on the Android phone, connect it by USB, then run:

```bash
adb devices
```

Accept the USB-debugging prompt on the phone if one appears.

Then either run:

```bash
./install-apk.sh
```

or manually:

```bash
adb install -r LumaClean.apk
```

---

## If `adb` is missing

On Ubuntu/Debian-based systems:

```bash
sudo apt update
sudo apt install -y adb
```

Android Studio also includes Android SDK Platform Tools, which provides `adb`.

---

## Clean Gradle build manually (optional)

Normally you do not need these commands because `build-apk.sh` handles the build.

If a Gradle wrapper is present:

```bash
./gradlew clean
./gradlew :app:assembleDebug
```

The raw Gradle output APK is then located at:

```text
app/build/outputs/apk/debug/app-debug.apk
```

The provided `build-apk.sh` additionally copies it to the project root as:

```text
LumaClean.apk
```

## AGP 9 / Kotlin note
This package uses Android Gradle Plugin 9's built-in Kotlin support. Do not add `org.jetbrains.kotlin.android`, `android.builtInKotlin=false`, or `android.newDsl=false`; those compatibility settings are not needed in this fixed package.

## CI builds and releases

`.github/workflows/lumaclean-apk.yml` builds the debug APK on every push that
touches `lumaclean/` (or when run by hand from the Actions tab) and publishes it
as a GitHub Release tagged `lumaclean-v<versionName>-<run number>`. Builds from
branches other than `main` are marked pre-release. The run number is used as
`versionCode`, so each release installs as an update.

To keep the same signing key across releases (so the phone updates in place
instead of needing an uninstall), add your debug keystore as a repository
secret named `LUMACLEAN_DEBUG_KEYSTORE_BASE64`:

```bash
base64 -w0 ~/.android/debug.keystore
```
