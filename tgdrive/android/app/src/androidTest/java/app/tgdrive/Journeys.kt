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
import app.tgdrive.diag.GitHubIssue
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.player.PlayerController
import app.tgdrive.util.Format
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

    /** A file's name on screen (a label, never the search box that may hold the same words). */
    private fun label(text: String): BySelector = By.clazz("android.widget.TextView").textContains(text)

    /**
     * Tap what [sel] finds, by its position: live parts of the screen (the indexing counter, progress)
     * redraw every second, and a found view can be replaced before it is tapped.
     */
    private fun click(sel: BySelector, what: String, long: Boolean = false, ms: Long = 8000) {
        repeat(6) {
            val o = need(sel, what, ms)
            val b = try { o.visibleBounds } catch (_: StaleObjectException) { null }
            if (b != null) {
                if (long) device.swipe(b.centerX(), b.centerY(), b.centerX(), b.centerY(), 160)
                else device.click(b.centerX(), b.centerY())
                Thread.sleep(500)
                return
            }
            Thread.sleep(300)
        }
        throw AssertionError("couldn't tap $what (it kept changing)")
    }

    private fun tap(text: String) = click(By.text(text), "“$text”")

    /** Tap a view already found, by its position (see [click]). */
    private fun tapAt(o: UiObject2, long: Boolean = false) {
        val b = try { o.visibleBounds } catch (_: StaleObjectException) { throw AssertionError("the view changed before it could be tapped") }
        if (long) device.swipe(b.centerX(), b.centerY(), b.centerX(), b.centerY(), 160) else device.click(b.centerX(), b.centerY())
        Thread.sleep(500)
    }

    /** Something further down a page: scroll the page until it shows. */
    private fun scrollTo(sel: BySelector, what: String): UiObject2 {
        find(sel, 1500)?.let { return it }
        repeat(3) {
            runCatching {
                device.findObjects(By.scrollable(true)).maxByOrNull { it.visibleBounds.height() }
                    ?.scrollUntil(Direction.DOWN, Until.findObject(sel))
            }.getOrNull()?.let { return it }
            find(sel, 800)?.let { return it }
        }
        return need(sel, what, 1000)
    }

    /** A dialog's button whose text is also its title ("Rename"): the lowest one on screen. */
    private fun tapButton(text: String) {
        need(By.text(text), "“$text”")
        val o = device.findObjects(By.text(text)).maxByOrNull { it.visibleBounds.centerY() } ?: throw AssertionError("no “$text”")
        tapAt(o)
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
            if (o != null) { tapAt(o); return }
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
        // A page opened from another shows Back instead of Menu: go back to where the menu is
        // (home() also brings TG Drive back if Back left it).
        if (find(By.desc("Menu"), 1500) == null) home()
        tapDesc("Menu")
        // Wait for the drawer to be fully open (its scrim), or the page behind it gets scrolled instead.
        need(By.desc("Close navigation menu"), "the open sidebar", 6000)
        Thread.sleep(700)
        fun drawerList(): UiObject2? = runCatching {
            device.findObjects(By.scrollable(true)).firstOrNull { it.visibleBounds.right < device.displayWidth - 8 }
        }.getOrNull()
        // The drawer keeps where it was scrolled to: back to its top (My Drive is its first row).
        var up = 0
        while (find(By.text("My Drive"), 600) == null && up++ < 8) {
            runCatching { drawerList()?.scroll(Direction.UP, 0.8f) }
            device.waitForIdle()
            Thread.sleep(400)
        }
        fun scrollFind(sel: BySelector): UiObject2? {
            var o = find(sel, 1500)
            var tries = 0
            while (o == null && tries < 10) {
                // Slowly, so the list doesn't fling on after a row was found (it would be gone when tapped).
                runCatching { drawerList()?.scroll(Direction.DOWN, 0.45f, SLOW) }
                device.waitForIdle()
                Thread.sleep(500)
                o = find(sel, 1500)
                tries++
            }
            return o
        }
        var o = scrollFind(By.text(label))
        // Tools start folded: open the group, then look again.
        if (o == null && label in TOOLS) {
            runCatching { scrollFind(By.text("TOOLS"))?.let { tapAt(it) } }
            Thread.sleep(1500)   // the group opens with an animation
            o = scrollFind(By.text(label))
        }
        if (o == null) throw AssertionError("sidebar has no “$label”")
        click(By.text(label), "“$label” in the sidebar")
        Thread.sleep(1200)
    }

    /** The menu of the file showing [name]; searches for it first when it isn't on screen. */
    private fun fileMenu(name: String) {
        if (find(label(name), 2000) == null || find(By.desc("Menu"), 200) != null && find(By.desc("Back"), 200) == null)
            search(name.substringBefore('.'))
        val row = need(label(name), "file “$name”", 15_000)
        val y = row.visibleBounds.centerY()
        // A row has it on the same line; a card at the top of its picture, above the name.
        val button = device.findObjects(By.desc("File options")).filter { it.visibleBounds.centerY() <= y + 40 }
            .maxByOrNull { it.visibleBounds.centerY() }
            ?: throw AssertionError("no File options button for “$name”")
        tapAt(button)
        need(By.text("Details"), "the file menu")
    }

    private fun folderMenu(name: String) {
        val row = need(By.text(name), "folder “$name”", 15_000)
        val y = row.visibleBounds.centerY()
        val button = device.findObjects(By.desc("Folder options")).minByOrNull { Math.abs(it.visibleBounds.centerY() - y) }
        if (button != null && Math.abs(button.visibleBounds.centerY() - y) < 200) tapAt(button) else tapAt(row, long = true)
        need(By.text("Delete folder"), "the folder menu")
    }

    private fun search(q: String) {
        home()
        tap("Search everything…")
        // Type into the search box, and check it took the text (the screen may still be settling).
        repeat(4) {
            val field = find(By.clazz("android.widget.EditText"), 5000)
            if (field != null) {
                try { field.text = q } catch (_: StaleObjectException) { }
                if (find(By.clazz("android.widget.EditText").text(q), 1500) != null) {
                    // Submitted when the search box gives way to the results page.
                    repeat(3) {
                        device.pressEnter()
                        if (device.wait(Until.gone(By.clazz("android.widget.EditText").text(q)), 4000)) {
                            Thread.sleep(1500)
                            return
                        }
                    }
                    throw AssertionError("the search for “$q” wasn't submitted")
                }
            }
            Thread.sleep(500)
        }
        throw AssertionError("couldn't type “$q” into the search box")
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
        g.api.files(aid, mapOf("q" to q, "limit" to "50", "copies" to "hide")).items.firstOrNull { it.name == name || it.displayName == name }

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
            // What the screen offered (texts, descriptions, bounds), to see why something wasn't found.
            runCatching { dir.mkdirs(); device.dumpWindowHierarchy(File(dir, "$tag-FAIL.xml")) }
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
                need(label("syllabus.txt"), "syllabus.txt in the results", 15_000)
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
                click(By.textContains(renamed), "“$renamed”", ms = 15_000)
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

            // Every type with files gets a tab (not only Photos and Videos), and a tab shows only that type.
            step("type-tabs") {
                sidebar("All files")
                need(By.desc("File options"), "files in All files", 15_000)
                val docs = runBlocking { g.api.stats(aid, mapOf("copies" to "hide")).kindCounts["document"] } ?: 0L
                if (docs <= 0L) throw AssertionError("the sample has no documents to show")
                val header = "${Format.num(docs)} files"
                // The row scrolls; tap along it (after a swipe) until the list says it shows the documents.
                val y = need(By.text("All"), "the type tabs").visibleBounds.centerY()   // the tab (not the "All files" title)
                fun sweep(): Boolean {
                    // Every 14 px from the row's visible end (the next tab only peeks in by ~20 px).
                    for (x in (device.displayWidth - 16 downTo 24) step 14) {
                        device.click(x, y)
                        Thread.sleep(900)
                        if (find(By.textContains(header), 700) != null) return true
                    }
                    return false
                }
                var found = sweep()
                if (!found) {
                    device.swipe(device.displayWidth * 4 / 5, y, device.displayWidth / 5, y, 20)
                    Thread.sleep(1200)
                    found = sweep()
                }
                if (!found) throw AssertionError("no tab shows the $docs documents")
                val first = runBlocking { g.api.files(aid, mapOf("kinds" to "document", "copies" to "hide")).items.firstOrNull()?.displayName }
                need(By.textContains(first ?: "?"), "a document in the Documents tab", 10_000)
                shot("e2e-documents-tab", 500)
            }

            step("photos") {
                sidebar("Photos")
                Thread.sleep(3000)
                // The first picture (the grid has no text): just below the first month's title.
                val month = runCatching { find(By.textContains("20"), 5000)?.visibleBounds }.getOrNull()
                device.click(device.displayWidth / 4, (month?.bottom ?: device.displayHeight / 3) + device.displayWidth / 5)
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

            // A file shared from another app (the share sheet → TG Drive) is uploaded to Telegram.
            step("share-upload") {
                home()
                val f = File(app.cacheDir, "e2e shared note.txt").apply { writeText("Shared from another app by the end-to-end run.\n") }
                val uri = androidx.core.content.FileProvider.getUriForFile(app, "${app.packageName}.files", f)
                val send = android.content.Intent(android.content.Intent.ACTION_SEND)
                    .setClass(app, MainActivity::class.java).setType("text/plain")
                    .putExtra(android.content.Intent.EXTRA_STREAM, uri)
                    .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK or android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
                app.startActivity(send)
                eventually("the shared file is in TG Drive", 120_000) { file("shared", "e2e shared note.txt") != null }
                search("e2e shared note")
                need(label("e2e shared note"), "the uploaded file in search", 15_000)
            }

            // A song that really plays: in the background player, with the mini player to stop it.
            step("audio-player") {
                search("Morning raga")
                click(label("Morning raga"), "the sample recording", ms = 15_000)
                val player = PlayerController.get(app)
                eventually("the recording plays", 30_000) { player.playing && player.position > 1500 }
                need(By.desc("Stop"), "the mini player")
                shot("e2e-mini-player", 300)
                tapDesc("Stop")
                eventually("the player stops", 10_000) { !player.playing }
            }

            // The sample videos are made-up bytes: the viewer must say it can't play, not hang or crash.
            step("video-that-cannot-play") {
                val name = runBlocking {
                    g.api.files(aid, mapOf("kinds" to "video", "copies" to "hide", "limit" to "5")).items.firstOrNull()?.displayName
                } ?: throw AssertionError("the sample has no videos")
                search(name.substringBeforeLast('.').take(24))
                click(label(name.take(18)), "the video", ms = 15_000)
                need(By.textContains("this video"), "the video error message", 30_000)
                need(By.desc("Details"), "the viewer, still open")
                shot("e2e-video-error", 300)
                back()
            }

            step("pdf-viewer") {
                search("Fundamental Rights")
                click(label("Fundamental Rights"), "the sample PDF", ms = 15_000)
                need(By.textContains("1 / "), "the PDF's page counter", 30_000)
                shot("e2e-pdf", 1200)
                back()
            }

            // App passcode: set it, lock, unlock with it, remove it (and never leave it set).
            step("passcode-lock") {
                val code = "2468"
                try {
                    sidebar("Settings")
                    scrollTo(By.text("Security"), "Security in Settings")
                    click(By.text("Security"), "Security")
                    click(By.text("Set"), "Set (passcode)")
                    need(By.text("Set a passcode"), "the passcode dialog")
                    val fields = device.findObjects(By.clazz("android.widget.EditText"))
                    if (fields.size < 2) throw AssertionError("expected 2 passcode fields, found ${fields.size}")
                    fields[0].text = code
                    fields[1].text = code
                    click(By.text("Save"), "Save")
                    eventually("the passcode is set") { g.api.status().lockSet }
                    click(By.text("Lock"), "Lock now")
                    need(By.textContains("Enter your passcode"), "the lock screen", 15_000)
                    shot("e2e-locked", 300)
                    (find(By.clazz("android.widget.EditText"), 5000) ?: throw AssertionError("no passcode field")).text = code
                    click(By.text("Unlock"), "Unlock")
                    eventually("TG Drive unlocks", 20_000) { !g.api.status().locked }
                    sidebar("Settings")
                    scrollTo(By.text("Security"), "Security in Settings")
                    click(By.text("Security"), "Security")
                    click(By.text("Change"), "Change (passcode)")
                    val again = device.findObjects(By.clazz("android.widget.EditText"))
                    if (again.isEmpty()) throw AssertionError("no current-passcode field")
                    again[0].text = code
                    click(By.text("Remove the passcode"), "Remove the passcode")
                    eventually("the passcode is removed") { !g.api.status().lockSet }
                } finally {
                    runBlocking {
                        runCatching { if (g.api.status().locked) g.api.unlock(code) }
                        runCatching { if (g.api.status().lockSet) g.api.setLock(null, code) }
                    }
                }
                home()
            }

            step("accounts") {
                home()
                tapDesc("Account")
                sheetTap("Manage accounts")
                need(By.text("Accounts"), "the accounts screen")
                shot("e2e-accounts", 600)
                home()
            }

            // Turned sideways, and with Android's largest text: the main screens still work.
            step("landscape") {
                home()
                try {
                    device.setOrientationLeft()
                    Thread.sleep(2500)
                    need(By.text("Search everything…"), "the search bar in landscape", 15_000)
                    shot("e2e-landscape-home", 800)
                    sidebar("Photos")
                    shot("e2e-landscape-photos", 2000)
                } finally {
                    // Always upright again: later journeys (and bottom sheets) assume portrait.
                    device.setOrientationNatural()
                    device.unfreezeRotation()
                    Thread.sleep(1500)
                }
                home()
            }

            step("large-text") {
                try {
                    device.executeShellCommand("settings put system font_scale 1.5")
                    Thread.sleep(2500)
                    home()
                    need(By.text("Search everything…"), "the search bar with large text", 15_000)
                    shot("e2e-large-text-home", 800)
                    tap("New")
                    need(By.text("New folder"), "the New menu with large text")
                    shot("e2e-large-text-new", 600)
                    back()
                } finally {
                    device.executeShellCommand("settings put system font_scale 1.0")
                    Thread.sleep(2000)
                }
                home()
            }

            step("background-sync") {
                sidebar("Settings")
                scrollTo(By.text("This phone"), "This phone in Settings")
                click(By.text("This phone"), "This phone in Settings")
                Thread.sleep(1000)
                need(By.text("BACKGROUND SYNC"), "the background sync settings")
                need(By.text("Sync in the background"), "the background sync switch")
                val before = BackgroundSync.last(app).at
                scrollTo(By.text("Sync now"), "Sync now")
                click(By.text("Sync now"), "Sync now")
                eventually("the sync finishes", 180_000) {
                    val l = BackgroundSync.last(app)
                    l.at != before && !l.running
                }
                val l = BackgroundSync.last(app)
                if (!l.ok) throw AssertionError("the sync failed: ${l.result}")
                need(By.textContains(l.result.take(12)), "the result under Last sync", 6000)
                shot("e2e-background-sync", 300)
                home()
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

            // An error's details open a GitHub issue about it (in the browser; copied when there is none).
            step("github-issue-from-error") {
                home()
                runBlocking { withContext(Dispatchers.Main) {
                    g.state.failed(PLANTED, IllegalStateException("$PLANTED for the GitHub issue"))
                } }
                tap("Details")
                need(By.text("What went wrong"), "the error details")
                val canBrowse = app.packageManager.resolveActivity(
                    android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse("https://github.com")), 0) != null
                tap("Create GitHub issue")
                val until = System.currentTimeMillis() + 15_000
                var left = false
                while (!left && System.currentTimeMillis() < until) { left = device.currentPackageName != app.packageName; Thread.sleep(300) }
                shot("e2e-github-issue", 2500)
                if (canBrowse && !left) throw AssertionError("Create GitHub issue didn't open GitHub")
                if (!canBrowse) {
                    val clip = runBlocking { withContext(Dispatchers.Main) {
                        app.getSystemService(android.content.ClipboardManager::class.java)?.primaryClip?.getItemAt(0)?.text?.toString()
                    } }
                    if (clip?.contains("github.com/${GitHubIssue.REPO}/issues/new") != true)
                        throw AssertionError("with no browser, the issue link wasn't copied")
                }
                // Back to TG Drive (a browser may need several Backs, or keep the screen).
                repeat(4) { if (device.currentPackageName != app.packageName) { device.pressBack(); Thread.sleep(600) } }
                if (device.currentPackageName != app.packageName) ActivityScenario.launch(MainActivity::class.java)
                Thread.sleep(1500)
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
        const val SLOW = 1200   // px/s: a scroll that doesn't fling
        val TOOLS = setOf("Transfers", "Storage", "Duplicates", "Chats and indexing", "Activity", "Settings")
    }
}
