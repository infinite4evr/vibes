package app.tgdrive

import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import app.tgdrive.data.FileItem
import app.tgdrive.data.Phase
import app.tgdrive.diag.GitHubIssue
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.player.PlayerController
import app.tgdrive.util.Format
import app.tgdrive.data.UiMessage
import app.tgdrive.data.str
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertTrue
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
class Journeys : UiDriver() {
    private val failures = ArrayList<String>()
    private val errors = java.util.Collections.synchronizedList(ArrayList<UiMessage>())
    private var n = 0

    // ------------------------------------------------------------------ helpers

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

    private val aid get() = g.state.aid.value

    private suspend fun file(q: String, name: String): FileItem? =
        g.api.files(aid, mapOf("q" to q, "limit" to "50", "copies" to "hide")).items.firstOrNull { it.name == name || it.displayName == name }

    /** [uri] shared to TG Drive from another app (the share sheet's ACTION_SEND). */
    private fun share(uri: android.net.Uri) {
        app.startActivity(android.content.Intent(android.content.Intent.ACTION_SEND)
            .setClass(app, MainActivity::class.java).setType("text/plain")
            .putExtra(android.content.Intent.EXTRA_STREAM, uri)
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK or android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION))
    }

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
            runBlocking { removeLeftoverPasscode(g) }
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
                openFile(renamed, "the viewer of “$renamed”") { find(By.desc("Details"), 300) != null }
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
                page("Transfers")
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
                page("All files")
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
                page("All files")
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
                page("Photos")
                Thread.sleep(3000)
                // The first picture (the grid has no text): just below the first month's title.
                val month = runCatching { find(By.textContains("20"), 5000)?.visibleBounds }.getOrNull()
                device.click(device.displayWidth / 4, (month?.bottom ?: device.displayHeight / 3) + device.displayWidth / 5)
                need(By.desc("Details"), "a photo in the viewer", 15_000)
                device.swipe(device.displayWidth * 4 / 5, device.displayHeight / 2, device.displayWidth / 5, device.displayHeight / 2, 15)
                shot("e2e-photo-next", 2000)
                back()
            }

            // Each Tools page opens with its title and content (an error screen fails the step).
            for ((name, title) in listOf("Storage" to "Storage", "Duplicates" to "Duplicates", "Chats and indexing" to "Chats and indexing",
                    "Activity" to "Activity", "Transfers" to "Transfers")) {
                step("page-" + name.lowercase().replace(' ', '-')) {
                    page(name)
                    need(By.text(title), "the $title page", 15_000)
                    Thread.sleep(2500)
                    if (find(By.text("Couldn't load this"), 500) != null) throw AssertionError("the $title page couldn't load")
                }
            }

            // The sidebar itself (the other journeys open pages by their links): a page from it, and back.
            step("sidebar") {
                home()
                sidebar("Photos")
                need(By.textContains("items"), "Photos, opened from the sidebar", 20_000)
                sidebar("My Drive")
                need(By.text("My Drive"), "My Drive, opened from the sidebar", 10_000)
            }

            step("dark-theme") {
                try {
                    open("settings/appearance")
                    tap("Dark")
                    eventually("the theme is saved") { g.state.settings.value.str("theme") == "dark" }
                    home()
                    shot("e2e-dark-home", 1500)
                    open("settings/appearance")
                    tap("Match the system")
                    eventually("the theme is back") { g.state.settings.value.str("theme") == "system" }
                } finally {
                    // Never leave the next journeys in dark mode.
                    if (g.state.settings.value.str("theme") != "system")
                        runBlocking { withContext(Dispatchers.Main) { g.state.setSetting("theme", "system") } }
                }
            }

            // A file shared from another app (the share sheet → TG Drive) is uploaded to Telegram. The file is
            // put in Downloads through Android's media store, so the share carries a real other-app URI.
            step("share-upload") {
                home()
                val name = "e2e shared note ${System.currentTimeMillis() % 100_000}.txt"
                val resolver = app.contentResolver
                val uri = resolver.insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    android.content.ContentValues().apply {
                        put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, name)
                        put(android.provider.MediaStore.MediaColumns.MIME_TYPE, "text/plain")
                    }) ?: throw AssertionError("couldn't make a file in Downloads")
                try {
                    resolver.openOutputStream(uri)!!.use { it.write("Shared from another app by the end-to-end run.\n".toByteArray()) }
                    share(uri)
                    eventually("the shared file is in TG Drive", 120_000) { file(name.substringBeforeLast('.'), name) != null }
                    search(name.substringBeforeLast('.'))
                    need(label(name.take(16)), "the uploaded file in search", 15_000)
                } finally {
                    runCatching { resolver.delete(uri, null, null) }
                }
            }

            // A share naming TG Drive's own files (its private data, e.g. a Telegram session) is refused.
            step("share-own-files-refused") {
                home()
                val name = "e2e private ${System.currentTimeMillis() % 100_000}.txt"
                val f = File(app.cacheDir, name).apply { writeText("TG Drive's own file: never uploaded.\n") }
                val refused = CompletableDeferred<String>()
                val watch = CoroutineScope(Dispatchers.Default).launch(start = CoroutineStart.UNDISPATCHED) {
                    g.state.messages.first { it.text.contains("Skipped") }.let { refused.complete(it.text) }
                }
                try {
                    share(androidx.core.content.FileProvider.getUriForFile(app, "${app.packageName}.files", f))
                    val text = runBlocking { withTimeoutOrNull(60_000) { refused.await() } }
                        ?: throw AssertionError("sharing TG Drive's own file wasn't refused")
                    assertTrue("unclear refusal: $text", text.contains("only uploads files other apps share"))
                    Thread.sleep(3000)
                    assertTrue("TG Drive uploaded its own file", runBlocking { file(name.substringBeforeLast('.'), name) } == null)
                    // The refusal is the expected answer here, not an error of the run.
                    errors.removeAll { it.text.startsWith("Skipped") }
                    find(By.desc("Dismiss"), 3000)?.let { tapAt(it) }
                } finally {
                    watch.cancel()
                    f.delete()
                }
            }

            // A song that really plays: in the background player, with the mini player to stop it.
            step("audio-player") {
                search("Morning raga")
                val player = PlayerController.get(app)
                openFile("Morning raga", "the sample recording") { player.playing || find(By.desc("Stop"), 200) != null }
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
                openFile(name.take(18), "the video") { find(By.desc("Details"), 300) != null }
                need(By.textContains("this video"), "the video error message", 30_000)
                need(By.desc("Details"), "the viewer, still open")
                shot("e2e-video-error", 300)
                back()
            }

            step("pdf-viewer") {
                search("Fundamental Rights")
                openFile("Fundamental Rights", "the sample PDF") { find(By.desc("Details"), 300) != null }
                need(By.textContains("1 / "), "the PDF's page counter", 30_000)
                shot("e2e-pdf", 1200)
                back()
            }

            // App passcode: set it, lock, unlock with it, remove it (and never leave it set).
            step("passcode-lock") {
                val code = JOURNEY_PASSCODE
                try {
                    open("settings/security")
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
                    open("settings/security")
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
                    page("Photos")
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
                open("settings/phone")
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

            // Android ends the service's process whenever it likes (memory, battery): with the app on
            // screen it must start again by itself, and the app carry on without an error.
            step("service-killed-recovers") {
                home()
                val before = g.engine.state.value
                if (!before.ready || before.pid <= 0) throw AssertionError("the service isn't running (${before.phase})")
                android.os.Process.killProcess(before.pid)
                eventually("the service is back in a new process", 120_000) {
                    val s = g.engine.state.value
                    s.ready && s.pid != before.pid
                }
                eventually("the app is ready again", 60_000) { g.state.phase.value == Phase.Ready && !g.state.reconnecting.value }
                search("Fundamental Rights")
                need(label("Fundamental Rights"), "a search result after the restart", 20_000)
                shot("e2e-after-service-restart", 300)
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
    }
}
