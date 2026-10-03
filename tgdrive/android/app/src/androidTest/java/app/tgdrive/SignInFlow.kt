package app.tgdrive

import app.tgdrive.storage.DataLocation
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * A first start on a fresh install, through the real screens: Welcome → Sign in → the Telegram
 * app key → the phone number → Send code, then QR sign-in. With a made-up key Telegram must answer,
 * and the app must show that answer (the buttons must never just do nothing). Needs a fresh install
 * (the CI script clears the app's data first) and internet access.
 */
@RunWith(AndroidJUnit4::class)
class SignInFlow : UiDriver() {

    private fun waitText(text: String, ms: Long = 20_000): UiObject2? = find(By.textContains(text), ms)

    private fun fields(): List<UiObject2> = device.findObjects(By.clazz("android.widget.EditText"))

    /** Close the keyboard if it is open (Back with no keyboard would leave the screen). */
    private fun hideKeyboard() {
        Thread.sleep(500)
        val ime = runCatching { device.executeShellCommand("dumpsys input_method") }.getOrDefault("")
        if (ime.contains("mInputShown=true")) { device.pressBack(); Thread.sleep(600) }
    }

    @Test
    fun signInWithAMadeUpKeyShowsTelegramsAnswer() {
        // pm clear deliberately retains the portable profile; this journey needs its own fresh one.
        DataLocation.select(app, java.io.File(android.os.Environment.getExternalStorageDirectory(), "TGDrive-Test-signin-${java.util.UUID.randomUUID()}"))
        ActivityScenario.launch(MainActivity::class.java).use {
            need(By.textContains("Sign in with Telegram"), "the welcome screen", 30_000)
            shot("30-welcome", 800)
            click(By.textContains("Sign in with Telegram"), "Sign in with Telegram")

            // The app key (my.telegram.org). The service starts first: up to a couple of minutes on a fresh install.
            need(By.textContains("Connect TG Drive to Telegram"), "the app key screen", 180_000)
            shot("31-api-key", 800)
            device.wait(Until.hasObject(By.clazz("android.widget.EditText")), 10_000)
            val keyFields = fields()
            assertTrue("expected the API ID and hash fields, found ${keyFields.size}", keyFields.size >= 2)
            keyFields[0].text = "1234567"
            keyFields[1].text = "0123456789abcdef0123456789abcdef"
            hideKeyboard()
            scrollTo(By.text("Continue"), "Continue")
            shot("32-api-key-filled", 500)
            click(By.text("Continue"), "Continue")

            // The sign-in screen must follow.
            need(By.textContains("Sign in to Telegram"), "the sign-in screen after Continue", 30_000)
            shot("33-sign-in", 800)
            device.wait(Until.hasObject(By.clazz("android.widget.EditText")), 10_000)
            fields().first().text = "+15550100000"
            hideKeyboard()
            scrollTo(By.text("Send code"), "Send code")
            click(By.text("Send code"), "Send code")
            shot("34-sending", 800)

            // Telegram answers: the made-up key is rejected, and the app says so.
            val answer = waitText("rejected the API ID", 90_000) ?: waitText("Can't reach Telegram", 1_000)
            shot("35-telegram-answer", 500)
            assertTrue("Send code showed no answer from Telegram", answer != null)
            assertTrue("Telegram couldn't be reached from the emulator: ${answer!!.text}", answer.text.contains("rejected the API ID"))

            // QR sign-in: Telegram answers it too (the same made-up key is rejected), with a way to try again.
            click(By.text("QR code"), "the QR code option")
            // "Get a new code" only shows once the QR step has Telegram's answer.
            need(By.text("Get a new code"), "QR sign-in's answer from Telegram (and a way to try again)", 90_000)
            shot("36-qr-answer", 500)
            val why = need(By.textContains("Telegram rejected"), "why QR sign-in failed", 3_000)
            assertTrue("QR sign-in didn't say what to check: ${why.text}", why.text.contains("my.telegram.org"))
        }
    }
}
