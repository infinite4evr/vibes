package app.tgdrive

import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Walks through the app on the sample account, through the real sidebar, and saves a screenshot of
 * each screen (CI keeps them, so every change to the interface can be looked at). A screen that
 * can't be reached is logged and skipped, so one moved button doesn't hide every other screenshot;
 * the run fails only if most of it couldn't be reached. Journeys checks what the screens do.
 */
@RunWith(AndroidJUnit4::class)
class ScreenshotTour : UiDriver() {
    private val missed = ArrayList<String>()

    /** One part of the tour: skipped (and noted) if it can't be done. */
    private fun part(name: String, block: () -> Unit) {
        try {
            block()
        } catch (e: Throwable) {
            missed += "$name (${e.message ?: e.javaClass.simpleName})"
            Log.w(TAG, "skipped $name", e)
            runCatching { home() }
        }
    }

    @Test
    fun tour() {
        app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
        app.getSharedPreferences("engine", 0).edit().putBoolean("demo", true).commit()
        ActivityScenario.launch(MainActivity::class.java).use {
            runBlocking { withTimeout(240_000) { g.engine.state.first { it.ready || it.phase == EngineState.Phase.Failed } } }
            need(By.text("My Drive"), "My Drive", 30_000)
            shot("01-home", 4000)

            part("sidebar") { tapDesc("Menu"); need(By.desc("Close navigation menu"), "the sidebar"); shot("02-sidebar"); back() }

            part("all files") {
                sidebar("All files")
                need(By.desc("File options"), "files", 15_000)
                shot("03-all-files", 2500)
                tapDesc("View"); shot("04-view-options"); back()
                tap("Filters"); shot("05-filters"); back()
                tapDesc("File options"); shot("06-file-menu"); back()
                tapDesc("More"); shot("07-list-menu")
                tap("Select all"); shot("08-selection"); tapDesc("Clear selection")
            }

            part("search") {
                home()
                tap("Search everything…")
                shot("09-search-suggestions")
                back()
                search("polity")
                shot("10-search-results", 2500)
            }

            part("photos") {
                sidebar("Photos")
                shot("11-photos", 3000)
                val month = runCatching { find(By.textContains("20"), 5000)?.visibleBounds }.getOrNull()
                device.click(device.displayWidth / 4, (month?.bottom ?: device.displayHeight / 3) + device.displayWidth / 5)
                need(By.desc("Details"), "a photo", 15_000)
                shot("12-viewer", 2500)
                back()
            }

            part("starred and details") {
                sidebar("Starred")
                shot("13-starred", 2500)
                tapDesc("File options")
                tap("Details")
                shot("14-details", 2500)
                back()
            }

            for ((label, name) in listOf("Transfers" to "15-transfers", "Storage" to "16-storage", "Duplicates" to "17-duplicates",
                    "Chats and indexing" to "18-index", "Activity" to "19-activity")) {
                part(label) { sidebar(label); shot(name, 2500) }
            }

            part("settings") {
                sidebar("Settings")
                shot("20-settings")
                tap("Appearance"); shot("21-settings-appearance"); back()
                scrollTo(By.text("This phone"), "This phone"); tap("This phone"); shot("22-settings-phone"); back()
            }

            part("new and account menus") {
                sidebar("My Drive")
                tap("New"); shot("23-new-menu"); back()
                tapDesc("Account"); shot("24-account-menu"); back()
            }
            Log.i(TAG, "done; skipped: $missed")
            assertTrue("most of the tour couldn't be done: $missed", missed.size <= 3)
        }
    }

    private companion object {
        const val TAG = "ScreenshotTour"
    }
}
