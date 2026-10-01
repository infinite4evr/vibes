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

## If the *Signing key* step fails

It says why:
- "isn't the keystore file in base64": the secret holds something else (a path, the password, part
  of the text). Encode the `.p12` again and paste the whole output.
- "doesn't open with TGDRIVE_KEYSTORE_PASSWORD": the password secret doesn't match the keystore.
- A key that isn't called `tgdrive` is fine: CI uses the keystore's first key and says so.

## The certificate check

CI prints the release APK's certificate fingerprint (SHA-256). Once the secret is set, put the
fingerprint in `expected-certificate.sha256` in this folder: one line, lowercase hex, no colons.
From then on CI refuses to publish a release signed with any other key.
