package app.tgdrive

import android.content.Intent
import android.graphics.Bitmap
import android.os.Environment
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import app.tgdrive.diag.AppLog
import app.tgdrive.diag.CrashActivity
import app.tgdrive.diag.GitHubIssue
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * The crash screen (what shows instead of the app vanishing): the error, a GitHub issue about it,
 * the problem report, and a way back into TG Drive. (CI also crashes the running app for real and
 * checks that this screen comes up: .github/scripts/tgdrive-android-emulator.sh.)
 */
@RunWith(AndroidJUnit4::class)
class CrashScreenTest {
    private val inst = InstrumentationRegistry.getInstrumentation()
    private val device = UiDevice.getInstance(inst)
    private val app = ApplicationProvider.getApplicationContext<TGDriveApp>()
    private val dir = File(inst.targetContext.getExternalFilesDir(Environment.DIRECTORY_PICTURES), "tour")

    private fun shot(name: String) {
        Thread.sleep(800)
        val bmp: Bitmap = inst.uiAutomation.takeScreenshot() ?: return
        dir.mkdirs()
        File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test
    fun crashScreenOffersAnIssueAReportAndAWayBack() {
        val planted = "planted by the crash screen test"
        val report = File(AppLog.dir(app), "crash-app-${System.currentTimeMillis()}.txt").apply {
            writeText("TG Drive test crashed in its app process on thread main\nAndroid test\n\n" +
                "java.lang.IllegalStateException: $planted\n\tat app.tgdrive.Test.run(Test.kt:1)\n")
        }
        app.startActivity(Intent(app, CrashActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            .putExtra(CrashActivity.EXTRA_REPORT, report.path))
        assertNotNull("the crash screen didn't show", device.wait(Until.findObject(By.text("TG Drive stopped")), 15_000))
        assertNotNull("the crash screen doesn't show the error", device.findObject(By.textContains(planted)))
        for (b in listOf("Create GitHub issue", "Send report", "Open TG Drive again"))
            assertNotNull("no “$b” on the crash screen", device.findObject(By.text(b)))
        shot("41-crash-screen")

        // The issue link it opens: TG Drive's repository, the error in it, short enough for a browser.
        val url = GitHubIssue.link(GitHubIssue.titleFor("Android crash", "IllegalStateException: $planted"),
            GitHubIssue.body(app, "TG Drive stopped (a crash).", report.readTextOrNull() ?: planted))
        assertTrue("wrong issue link: ${url.take(120)}", url.startsWith("https://github.com/${GitHubIssue.REPO}/issues/new?"))
        assertTrue("the issue link is too long for a browser (${url.length})", url.length <= 7_600)
        assertTrue("the issue doesn't carry the error", android.net.Uri.decode(url).contains(planted))

        // And back into the app.
        device.findObject(By.text("Open TG Drive again")).click()
        assertTrue("TG Drive didn't open again", device.wait(Until.gone(By.text("TG Drive stopped")), 15_000))
        assertTrue("TG Drive isn't in front", device.wait(Until.hasObject(By.pkg(app.packageName)), 15_000))
        shot("42-after-crash-screen")
    }

    private fun File.readTextOrNull(): String? = runCatching { readText() }.getOrNull()
        ?: runCatching { File(path.removeSuffix(".txt") + ".seen.txt").readText() }.getOrNull()
}
