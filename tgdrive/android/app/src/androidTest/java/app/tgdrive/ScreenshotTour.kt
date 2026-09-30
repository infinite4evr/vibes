package app.tgdrive

import android.graphics.Bitmap
import android.os.Environment
import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Walks through the app on the sample account and saves a screenshot of each screen (CI keeps
 * them, so every change to the interface can be looked at). A step that can't find what it
 * looks for is logged and skipped, so one moved button doesn't hide every other screenshot.
 */
@RunWith(AndroidJUnit4::class)
class ScreenshotTour {
    private val inst = InstrumentationRegistry.getInstrumentation()
    private val device = UiDevice.getInstance(inst)
    private val dir = File(inst.targetContext.getExternalFilesDir(Environment.DIRECTORY_PICTURES), "tour")
    private val missed = ArrayList<String>()

    private fun shot(name: String, settle: Long = 1500) {
        Thread.sleep(settle)
        device.waitForIdle()
        val bmp: Bitmap = inst.uiAutomation.takeScreenshot() ?: return
        dir.mkdirs()
        File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun find(sel: BySelector, timeout: Long = 6000): UiObject2? = device.wait(Until.findObject(sel), timeout)

    /** Tap something by its text or description; scrolls the drawer or page to find it. */
    private fun tap(text: String, desc: Boolean = false, scroll: Boolean = false, long: Boolean = false): Boolean {
        val sel = if (desc) By.desc(text) else By.text(text)
        var o = find(sel, if (scroll) 1500 else 6000)
        var tries = 0
        while (o == null && scroll && tries < 8) {
            // The drawer's list when it is open (narrower than the screen), else the page.
            val lists = device.findObjects(By.scrollable(true))
            (lists.firstOrNull { it.visibleBounds.right < device.displayWidth - 8 } ?: lists.maxByOrNull { it.visibleBounds.height() })
                ?.scroll(Direction.DOWN, 0.7f)
            o = find(sel, 800)
            tries++
        }
        if (o == null) { missed += text; Log.w("ScreenshotTour", "not found: $text"); return false }
        // The screen can redraw between finding and tapping (StaleObjectException): find it again.
        repeat(4) {
            try {
                val target = o ?: find(sel, 3000) ?: run { missed += text; return false }
                if (long) target.longClick() else target.click()
                return true
            } catch (e: androidx.test.uiautomator.StaleObjectException) {
                o = null
                Thread.sleep(300)
            }
        }
        missed += text
        return false
    }

    private fun back() { device.pressBack(); Thread.sleep(600) }

    private fun menu() = tap("Menu", desc = true)

    private fun sidebar(label: String): Boolean {
        if (!menu()) return false
        Thread.sleep(500)
        if (tapQuietly(label)) return true
        // Tools start folded: open the group, then look again.
        if (label in TOOLS && tapQuietly("TOOLS")) { Thread.sleep(300); if (tapQuietly(label)) return true }
        missed += label
        back()
        return false
    }

    private fun tapQuietly(text: String): Boolean {
        val before = missed.size
        val ok = tap(text, scroll = true)
        while (missed.size > before) missed.removeAt(missed.lastIndex)
        return ok
    }

    @Test
    fun tour() {
        val app = ApplicationProvider.getApplicationContext<TGDriveApp>()
        app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
        app.getSharedPreferences("engine", 0).edit().putBoolean("demo", true).commit()
        ActivityScenario.launch(MainActivity::class.java).use {
            runBlocking { withTimeout(240_000) { app.graph.engine.state.first { it.ready || it.phase == EngineState.Phase.Failed } } }
            find(By.text("My Drive"), 30_000)
            shot("01-home", 4000)

            if (menu()) { shot("02-sidebar"); back() }

            if (sidebar("All files")) {
                shot("03-all-files", 3000)
                if (tap("View", desc = true)) { shot("04-view-options"); back() }
                if (tap("Filters")) { shot("05-filters"); back() }
                if (tap("File options", desc = true)) { shot("06-file-menu"); back() }
                if (tap("More", desc = true)) {
                    shot("07-list-menu")
                    if (tap("Select all")) { shot("08-selection"); tap("Clear selection", desc = true) }
                }
            }

            if (tap("Search everything…")) {
                shot("09-search-suggestions")
                find(By.focused(true), 3000)?.text = "polity"
                device.pressEnter()
                shot("10-search-results", 3000)
                back()
            }

            if (sidebar("Photos")) {
                shot("11-photos", 3000)
                // Open the first picture (the grid has no text to find it by).
                device.click(device.displayWidth / 8, device.displayHeight * 3 / 10)
                shot("12-viewer", 3000)
                back()
            }

            if (sidebar("Starred")) {
                shot("13-starred", 2500)
                if (tap("File options", desc = true)) {
                    if (tap("Details")) { shot("14-details", 2500); back() } else back()
                }
            }

            for ((label, name) in listOf("Transfers" to "15-transfers", "Storage" to "16-storage", "Duplicates" to "17-duplicates",
                "Chats and indexing" to "18-index", "Activity" to "19-activity")) {
                if (sidebar(label)) shot(name, 2500)
            }

            if (sidebar("Settings")) {
                shot("20-settings")
                if (tap("Appearance")) { shot("21-settings-appearance"); back() }
                if (tap("This phone", scroll = true)) { shot("22-settings-phone"); back() }
            }

            if (sidebar("My Drive")) {
                if (tap("New")) { shot("23-new-menu"); back() }
                if (tap("Account", desc = true)) { shot("24-account-menu"); back() }
            }
            Log.i("ScreenshotTour", "done; not found: $missed")
        }
    }

    private companion object {
        val TOOLS = setOf("Transfers", "Storage", "Duplicates", "Chats and indexing", "Activity", "Settings")
    }
}
