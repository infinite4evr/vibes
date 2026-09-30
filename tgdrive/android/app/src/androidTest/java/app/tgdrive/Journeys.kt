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
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import app.tgdrive.data.FileItem
import app.tgdrive.data.UiMessage
import app.tgdrive.data.str
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * What people do in TG Drive, through the real screens on the sample account, each result checked
 * against the service: make, rename, move and delete a folder; search; star, tag, rename, note,
 * move, open, download a file; select; the pages under Tools; the theme; and an error with its
 * details and problem report. Any error the app shows along the way fails the run.
 *
 * Every journey runs even when an earlier one fails (the run lists all failures at the end), and
 * each leaves a screenshot (e2e-*.png, next to the tour's).
 */
@RunWith(AndroidJUnit4::class)
class Journeys {
    private val inst = InstrumentationRegistry.getInstrumentation()
    private val device = UiDevice.getInstance(inst)
    private val app = ApplicationProvider.getApplicationContext<TGDriveApp>()
    private val g get() = app.graph
    private val dir = File(inst.targetContext.getExternalFilesDir(Environment.DIRECTORY_PICTURES), "tour")
    private val failures = ArrayList<String>()
    private val errors = java.util.Collections.synchronizedList(ArrayList<UiMessage>())
    private var n = 0

    // ------------------------------------------------------------------ helpers
    private fun shot(name: String, settle: Long = 1200) {
        Thread.sleep(settle)
        device.waitForIdle()
        val bmp: Bitmap = inst.uiAutomation.takeScreenshot() ?: return
        dir.mkdirs()
        File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun find(sel: BySelector, ms: Long = 8000): UiObject2? = device.wait(Until.findObject(sel), ms)

    private fun need(sel: BySelector, what: String, ms: Long = 8000): UiObject2 = find(sel, ms) ?: throw AssertionError("not on screen: $what")

    private fun click(sel: BySelector, what: String, long: Boolean = false, ms: Long = 8000) {
        repeat(3) { attempt ->
            val o = need(sel, what, ms)
            try {
                if (long) o.longClick() else o.click()
                Thread.sleep(500)
                return
            } catch (e: StaleObjectException) {
                if (attempt == 2) throw e
            }
        }
    }

    private fun tap(text: String) = click(By.text(text), "“$text”")

    /** A dialog's button whose text is also its title ("Rename"): the lowest one on screen. */
    private fun tapButton(text: String) {
        need(By.text(text), "“$text”")
        val o = device.findObjects(By.text(text)).maxByOrNull { it.visibleBounds.centerY() } ?: throw AssertionError("no “$text”")
        o.click()
        Thread.sleep(500)
    }

    /** The share sheet opened (the system's chooser, in front of TG Drive). */
    private fun shareSheetOpened(): Boolean {
        val until = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < until) {
            if (device.currentPackageName != app.packageName) return true
            if (device.hasObject(By.textContains("problem report"))) return true
            Thread.sleep(300)
        }
        return false
    }
    private fun tapDesc(desc: String) = click(By.desc(desc), "button “$desc”")

    /** An action in a bottom sheet, which may be below the sheet's fold: swipe the sheet up until it shows. */
    private fun sheetTap(text: String) {
        repeat(5) {
            val o = find(By.text(text), 1200)
            if (o != null) { o.click(); Thread.sleep(500); return }
            device.swipe(device.displayWidth / 2, device.displayHeight * 85 / 100, device.displayWidth / 2, device.displayHeight * 45 / 100, 25)
        }
        tap(text)
    }

    /** Type into the dialog's text field (the focused one, else the last on screen). */
    private fun type(text: String) {
        val field = find(By.clazz("android.widget.EditText").focused(true), 4000)
            ?: device.findObjects(By.clazz("android.widget.EditText")).lastOrNull()
            ?: throw AssertionError("no text field to type “$text” into")
        field.text = text
        Thread.sleep(300)
    }

    private fun back() { device.pressBack(); Thread.sleep(600) }

    private fun sidebar(label: String) {
        tapDesc("Menu")
        Thread.sleep(500)
        var o = find(By.text(label), 1500)
        if (o == null && label in TOOLS) { find(By.text("TOOLS"), 1000)?.click(); Thread.sleep(400); o = find(By.text(label), 1500) }
        var tries = 0
        while (o == null && tries < 6) {
            val lists = device.findObjects(By.scrollable(true))
            (lists.firstOrNull { it.visibleBounds.right < device.displayWidth - 8 } ?: lists.firstOrNull())?.scroll(Direction.DOWN, 0.7f)
            o = find(By.text(label), 800)
            tries++
        }
        (o ?: throw AssertionError("sidebar has no “$label”")).click()
        Thread.sleep(1200)
    }

    /** The menu of the file row showing [name] (the “File options” button on the same line). */
    private fun fileMenu(name: String) {
        val row = need(By.textContains(name), "file “$name”", 15_000)
        val y = row.visibleBounds.centerY()
        val button = device.findObjects(By.desc("File options")).minByOrNull { Math.abs(it.visibleBounds.centerY() - y) }
            ?: throw AssertionError("no File options button next to “$name”")
        button.click()
        need(By.text("Details"), "the file menu")
    }

    private fun folderMenu(name: String) {
        val row = need(By.text(name), "folder “$name”", 15_000)
        val y = row.visibleBounds.centerY()
        val button = device.findObjects(By.desc("Folder options")).minByOrNull { Math.abs(it.visibleBounds.centerY() - y) }
        if (button != null && Math.abs(button.visibleBounds.centerY() - y) < 200) button.click() else row.longClick()
        need(By.text("Delete folder"), "the folder menu")
    }

    private fun search(q: String) {
        home()
        tap("Search everything…")
        val field = need(By.focused(true), "the search field")
        field.text = q
        device.pressEnter()
        Thread.sleep(2000)
    }

    /** Back to My Drive with nothing open. */
    private fun home() {
        repeat(6) {
            if (find(By.text("Search everything…"), 600) != null && find(By.desc("Menu"), 300) != null) {
                if (find(By.text("My Drive"), 300) != null) return
            }
            device.pressBack()
            Thread.sleep(400)
            if (device.currentPackageName != app.packageName) {
                ActivityScenario.launch(MainActivity::class.java)
                Thread.sleep(2000)
            }
        }
        runCatching { sidebar("My Drive") }
    }

    /** Wait until [check] holds, asking the service again every half second. */
    private fun eventually(what: String, ms: Long = 15_000, check: suspend () -> Boolean) = runBlocking {
        val until = System.currentTimeMillis() + ms
        var last: Throwable? = null
        while (System.currentTimeMillis() < until) {
            try { if (check()) return@runBlocking } catch (e: Exception) { last = e }
            Thread.sleep(500)
        }
        throw AssertionError("never happened: $what" + (last?.let { " (last error: ${it.message})" } ?: ""))
    }

    private val aid get() = g.state.aid.value

    private suspend fun file(q: String, name: String): FileItem? =
        g.api.files(aid, mapOf("q" to q, "limit" to "50")).items.firstOrNull { it.name == name || it.displayName == name }

    private suspend fun folderId(name: String): String? { g.state.loadFolders(); return g.state.folders.value.folders.firstOrNull { it.name == name }?.id }

    private fun step(name: String, block: () -> Unit) {
        n++
        val tag = "e2e-%02d-%s".format(n, name)
        val before = errors.size
        try {
            block()
            if (find(By.text("Send report"), 300) != null && find(By.text("What went wrong"), 100) == null)
                throw AssertionError("an error screen is showing")
            shot(tag)
            val shown = errors.drop(before).filterNot { it.text.startsWith(PLANTED) }
            if (shown.isNotEmpty()) throw AssertionError("the app showed an error: " + shown.joinToString { it.text + (it.detail?.let { d -> " — " + d.take(600) } ?: "") })
            Log.i(TAG, "ok    $name")
        } catch (e: Throwable) {
            Log.e(TAG, "FAIL  $name", e)
            failures += "$name: ${e.message ?: e.javaClass.simpleName}"
            runCatching { shot("$tag-FAIL", 300) }
            runCatching { home() }
        }
    }

    // ------------------------------------------------------------------ the journeys
    @Test
    fun whatPeopleDo() {
        app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
        app.getSharedPreferences("engine", 0).edit().putBoolean("demo", true).commit()
        val watcher = CoroutineScope(Dispatchers.Default)
        watcher.launch { g.state.messages.collect { if (it.error) errors += it } }
        ActivityScenario.launch(MainActivity::class.java).use {
            runBlocking { withTimeout(240_000) { g.engine.state.first { it.ready || it.phase == EngineState.Phase.Failed } } }
            need(By.text("My Drive"), "My Drive", 60_000)
            Thread.sleep(2500)
            val folder = "E2E box"
            val folder2 = "E2E box 2"
            val renamed = "syllabus e2e.txt"

            step("new-folder") {
                tap("New")
                sheetTap("New folder")
                need(By.text("Create"), "the new folder dialog")
                type(folder)
                tap("Create")
                eventually("the folder is made") { folderId(folder) != null }
                need(By.text(folder), "the new folder in My Drive")
            }

            step("rename-folder") {
                folderMenu(folder)
                sheetTap("Rename")
                need(By.text("Rename folder"), "the rename dialog")
                type(folder2)
                tapButton("Rename")
                eventually("the folder is renamed") { folderId(folder2) != null && folderId(folder) == null }
                need(By.text(folder2), "the renamed folder")
            }

            step("search") {
                search("syllabus")
                need(By.textContains("syllabus.txt"), "syllabus.txt in the results", 15_000)
            }

            step("star") {
                fileMenu("syllabus.txt")
                tap("Star")
                eventually("syllabus.txt is starred") { file("syllabus", "syllabus.txt")?.starred == true }
            }

            step("tags") {
                fileMenu("syllabus.txt")
                tap("Tags")
                need(By.textContains("Tags for"), "the tags dialog")
                type("e2etag,")
                need(By.text("#e2etag"), "the new tag chip")
                tap("Save")
                eventually("syllabus.txt has the tag") { file("syllabus", "syllabus.txt")?.tags?.contains("e2etag") == true }
            }

            step("note") {
                fileMenu("syllabus.txt")
                sheetTap("Note…")
                need(By.text("Save"), "the note dialog", 10_000)
                type("written by the e2e run")
                tap("Save")
                eventually("the note is saved") {
                    val f = file("syllabus", "syllabus.txt") ?: return@eventually false
                    g.api.detail(aid, f.ref).extras.note == "written by the e2e run"
                }
            }

            step("rename-file") {
                fileMenu("syllabus.txt")
                sheetTap("Rename…")
                need(By.text("Rename"), "the rename dialog")
                type(renamed)
                tapButton("Rename")
                eventually("the file is renamed") { file("syllabus", renamed) != null }
            }

            step("move-file") {
                search("syllabus")
                fileMenu(renamed)
                tap("Move")
                click(By.text(folder2), "the folder in the picker")
                tap("Move here")
                val id = runBlocking { folderId(folder2) } ?: throw AssertionError("the folder is gone")
                eventually("the file is in the folder") { file("syllabus", renamed)?.folderId == id }
            }

            step("open-folder") {
                home()
                tap(folder2)
                need(By.textContains(renamed), "the moved file inside the folder", 15_000)
            }

            step("viewer") {
                tap(renamed)
                Thread.sleep(2500)
                need(By.desc("Details"), "the viewer")
                shot("e2e-viewer-text", 1500)
                tapDesc("Details")
                need(By.textContains("written by the e2e run"), "the note on the details page", 15_000)
                back()
                back()
            }

            step("download") {
                if (find(By.textContains(renamed), 2000) == null) { home(); tap(folder2) }
                fileMenu(renamed)
                tap("Download")
                sidebar("Transfers")
                need(By.textContains("syllabus"), "the download in Transfers", 20_000)
                eventually("the download finishes", 60_000) {
                    g.api.transfers(aid).transfers.any { it.name.contains("syllabus") && it.status == "done" }
                }
            }

            step("selection") {
                home()
                tap(folder2)
                click(By.textContains(renamed), "the file", long = true)
                need(By.desc("Clear selection"), "the selection bar")
                shot("e2e-selection-bar", 600)
                tapDesc("Star")   // unstar: all selected are starred
                eventually("the file is unstarred") { file("syllabus", renamed)?.starred == false }
            }

            step("delete-folder") {
                home()
                folderMenu(folder2)
                sheetTap("Delete folder")
                need(By.textContains("Delete “$folder2”?"), "the delete question")
                tapButton("Delete folder")
                eventually("the folder is deleted") { folderId(folder2) == null }
                eventually("the file is back in no folder") { file("syllabus", renamed)?.folderId == null }
            }

            step("all-files-and-filters") {
                sidebar("All files")
                need(By.desc("File options"), "files in All files", 15_000)
                tapDesc("Filters")
                shot("e2e-filters", 800)
                back()
                tapDesc("View")
                shot("e2e-view-options", 800)
                back()
            }

            step("photos") {
                sidebar("Photos")
                Thread.sleep(3000)
                device.click(device.displayWidth / 8, device.displayHeight * 3 / 10)
                need(By.desc("Details"), "a photo in the viewer", 15_000)
                device.swipe(device.displayWidth * 4 / 5, device.displayHeight / 2, device.displayWidth / 5, device.displayHeight / 2, 15)
                shot("e2e-photo-next", 2000)
                back()
            }

            for (page in listOf("Storage", "Duplicates", "Chats and indexing", "Activity", "Transfers")) {
                step("page-" + page.lowercase().replace(' ', '-')) {
                    sidebar(page)
                    Thread.sleep(2500)
                }
            }

            step("dark-theme") {
                sidebar("Settings")
                tap("Appearance")
                tap("Dark")
                eventually("the theme is saved") { g.state.settings.value.str("theme") == "dark" }
                home()
                shot("e2e-dark-home", 1500)
                sidebar("Settings")
                tap("Appearance")
                tap("Match the system")
                eventually("the theme is back") { g.state.settings.value.str("theme") == "system" }
            }

            step("error-details-and-report") {
                home()
                runBlocking { withContext(Dispatchers.Main) {
                    g.state.failed(PLANTED, IllegalStateException("$PLANTED (planted by the test)"))
                } }
                tap("Details")
                need(By.text("What went wrong"), "the error details")
                need(By.textContains("IllegalStateException"), "the error's stack in the details")
                shot("e2e-error-details", 500)
                tap("Send report")
                // The share sheet (another app's window) with the report.
                val chooser = shareSheetOpened()
                shot("e2e-report-share", 1500)
                if (!chooser) throw AssertionError("the share sheet for the report didn't open")
                val zips = File(app.cacheDir, "reports").listFiles().orEmpty().filter { it.name.endsWith(".zip") }
                val zip = zips.maxByOrNull { it.lastModified() } ?: throw AssertionError("no report file was made")
                val names = java.util.zip.ZipFile(zip).use { z -> z.entries().toList().map { it.name } }
                for (entry in listOf("report.txt", "app/app.log", "engine/engine.log", "service/tgdrive.log"))
                    if (entry !in names) throw AssertionError("the report has no $entry (has: $names)")
                back()
                if (find(By.text("What went wrong"), 1000) != null) tap("Close")
            }

            step("report-from-account-menu") {
                home()
                tapDesc("Account")
                sheetTap("Report a problem")
                val chooser = shareSheetOpened()
                shot("e2e-report-account-menu", 1000)
                if (!chooser) throw AssertionError("the share sheet for the report didn't open")
                back()
            }
        }
        watcher.cancel()
        Log.i(TAG, "done: ${n - failures.size} of $n passed")
        if (failures.isNotEmpty()) fail("${failures.size} of $n journeys failed:\n" + failures.joinToString("\n"))
    }

    private companion object {
        const val TAG = "Journeys"
        const val PLANTED = "E2E planted error"
        val TOOLS = setOf("Transfers", "Storage", "Duplicates", "Chats and indexing", "Activity", "Settings")
    }
}
