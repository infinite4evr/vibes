# TG Drive's signing key

Every release build of the Android app must be signed with the **same key**. Android only
installs an update over the installed app when the key matches. Otherwise it asks you to
uninstall first, which loses the app's index and sign-ins.

The key is **not** in the repository. CI reads it from two repository secrets:

| Secret | Value |
| --- | --- |
| `TGDRIVE_KEYSTORE_BASE64` | the keystore file (PKCS12, alias `tgdrive`), base64-encoded |
| `TGDRIVE_KEYSTORE_PASSWORD` | its password (also used as the key's password) |

## One-time setup

1. Make the key (on your computer; any JDK has `keytool`):

   ```sh
   keytool -genkeypair -storetype PKCS12 -keystore tgdrive-release.p12 -alias tgdrive \
     -keyalg RSA -keysize 3072 -validity 12000 -dname "CN=TG Drive"
   ```

2. Base64 it: `base64 -w0 tgdrive-release.p12` (Linux), `base64 -i tgdrive-release.p12` (macOS), or in
   Windows PowerShell `[Convert]::ToBase64String([IO.File]::ReadAllBytes("tgdrive-release.p12")) | Set-Clipboard`.
   CI also accepts wrapped lines, Windows line ends and `certutil -encode` output.
3. GitHub → this repository → Settings → Secrets and variables → Actions → New repository secret:
   add `TGDRIVE_KEYSTORE_BASE64` (the base64 text) and `TGDRIVE_KEYSTORE_PASSWORD`.
4. **Back up `tgdrive-release.p12` and its password** somewhere safe. If they're lost, the next
   build can't update the installed app.

The first APK built after this still needs one uninstall and reinstall, because older builds
were signed with throwaway keys. Every build after that installs as an update.

## If the *Signing key* step reports a problem

The build still finishes, signed with a throwaway key (so there's an APK to test), and the step
says what's wrong with the secrets without showing them:
- "looks like a file path" or "far too short for a keystore": `TGDRIVE_KEYSTORE_BASE64` must hold
  the **contents** of the `.p12` file, base64-encoded (3 000 to 5 000 characters), not its path or
  the password.
- "isn't base64 text" or "decodes to something that isn't a keystore": encode the `.p12` file again
  (step 2) and paste the whole output.
- "wrong password": `TGDRIVE_KEYSTORE_PASSWORD` doesn't match the keystore.
- A key that isn't called `tgdrive` is fine: CI uses the keystore's first key and says so.

## The certificate check

CI prints the release APK's certificate fingerprint (SHA-256). Once the secret is set, put the
fingerprint in `expected-certificate.sha256` in this folder: one line, lowercase hex, no colons.
From then on CI refuses to publish a release signed with any other key.
