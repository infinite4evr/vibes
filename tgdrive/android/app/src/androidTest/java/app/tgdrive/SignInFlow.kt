package app.tgdrive

import android.graphics.Bitmap
import android.os.Environment
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * A first start on a fresh install, through the real screens: Welcome → Sign in → the Telegram
 * app key → the phone number → Send code. With a made-up key Telegram must answer, and the app
 * must show that answer (the buttons must never just do nothing). Needs a fresh install (the CI
 * script clears the app's data first) and internet access.
 */
@RunWith(AndroidJUnit4::class)
class SignInFlow {
    private val inst = InstrumentationRegistry.getInstrumentation()
    private val device = UiDevice.getInstance(inst)
    private val dir = File(inst.targetContext.getExternalFilesDir(Environment.DIRECTORY_PICTURES), "tour")

    private fun shot(name: String) {
        Thread.sleep(800)
        val bmp: Bitmap = inst.uiAutomation.takeScreenshot() ?: return
        dir.mkdirs()
        File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun waitText(text: String, ms: Long = 20_000): UiObject2? = device.wait(Until.findObject(By.textContains(text)), ms)

    private fun fields(): List<UiObject2> = device.findObjects(By.clazz("android.widget.EditText"))

    /** Close the keyboard if it is open (Back with no keyboard would leave the screen). */
    private fun hideKeyboard() {
        Thread.sleep(500)
        val ime = runCatching { device.executeShellCommand("dumpsys input_method") }.getOrDefault("")
        if (ime.contains("mInputShown=true")) { device.pressBack(); Thread.sleep(600) }
    }

    /** A button that may be below the fold on a small screen: scroll the page until it shows. */
    private fun scrollTo(text: String): UiObject2? {
        repeat(8) {
            device.findObject(By.text(text))?.let { return it }
            device.findObjects(By.scrollable(true)).maxByOrNull { it.visibleBounds.height() }
                ?.let { runCatching { it.scroll(androidx.test.uiautomator.Direction.DOWN, 0.6f) } }
            Thread.sleep(400)
        }
        return device.findObject(By.text(text))
    }

    @Test
    fun signInWithAMadeUpKeyShowsTelegramsAnswer() {
        ActivityScenario.launch(MainActivity::class.java).use {
            val start = waitText("Sign in with Telegram", 30_000)
            shot("30-welcome")
            assertNotNull("the welcome screen didn't show", start)
            start!!.click()

            // The app key (my.telegram.org). The service starts first: up to a couple of minutes on a fresh install.
            val keyScreen = waitText("Connect TG Drive to Telegram", 180_000)
            shot("31-api-key")
            assertNotNull("the app key screen didn't show", keyScreen)
            device.wait(Until.hasObject(By.clazz("android.widget.EditText")), 10_000)
            val keyFields = fields()
            assertTrue("expected the API ID and hash fields, found ${keyFields.size}", keyFields.size >= 2)
            keyFields[0].text = "1234567"
            keyFields[1].text = "0123456789abcdef0123456789abcdef"
            hideKeyboard()
            val cont = scrollTo("Continue")
            assertNotNull(cont)
            shot("32-api-key-filled")
            cont!!.click()

            // The sign-in screen must follow.
            val signIn = waitText("Sign in to Telegram", 30_000)
            shot("33-sign-in")
            assertNotNull("Continue on the app key screen didn't lead to signing in", signIn)
            device.wait(Until.hasObject(By.clazz("android.widget.EditText")), 10_000)
            fields().first().text = "+15550100000"
            hideKeyboard()
            val send = scrollTo("Send code")
            assertNotNull(send)
            send!!.click()
            shot("34-sending")

            // Telegram answers: the made-up key is rejected, and the app says so.
            val answer = waitText("rejected the API ID", 90_000) ?: waitText("Can't reach Telegram", 1_000)
            shot("35-telegram-answer")
            assertNotNull("Send code showed no answer from Telegram", answer)
            assertTrue("Telegram couldn't be reached from the emulator: ${answer!!.text}", answer.text.contains("rejected the API ID"))
        }
    }
}
