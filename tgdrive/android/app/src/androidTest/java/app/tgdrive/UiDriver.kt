package app.tgdrive

import android.graphics.Bitmap
import android.os.Environment
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import kotlinx.coroutines.runBlocking
import java.io.File

/**
 * Driving TG Drive's real screens from tests (UiAutomator), the way that works reliably with Compose:
 * tap by position (live counters redraw views every second, so a found view can be replaced before
 * it is tapped), scroll slowly (no fling past what was found), wait for the drawer to be open, and
 * check that a search was really submitted. Journeys and BigLibraryTest build on it.
 */
abstract class UiDriver {
    protected val inst = InstrumentationRegistry.getInstrumentation()
    protected val device: UiDevice = UiDevice.getInstance(inst)
    protected val app: TGDriveApp = ApplicationProvider.getApplicationContext()
    protected val g get() = app.graph
    protected val dir = File(inst.targetContext.getExternalFilesDir(Environment.DIRECTORY_PICTURES), "tour")

    protected fun shot(name: String, settle: Long = 1200) {
        Thread.sleep(settle)
        device.waitForIdle()
        val bmp: Bitmap = inst.uiAutomation.takeScreenshot() ?: return
        dir.mkdirs()
        File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    /**
     * The accessibility tree UiAutomator reads can lag behind Compose after scrolls and live updates
     * (a view on screen isn't found). Android 14 can drop that cache (UiAutomation.clearCache); older
     * versions just don't have it.
     */
    protected fun freshTree() {
        runCatching { android.app.UiAutomation::class.java.getMethod("clearCache").invoke(inst.uiAutomation) }
    }

    protected fun find(sel: BySelector, ms: Long = 8000): UiObject2? {
        freshTree()
        return device.wait(Until.findObject(sel), ms) ?: run { freshTree(); device.findObject(sel) }
    }

    /** Open one of TG Drive's screens by name ("all", "photos", "settings/security" …; MainScreen's screenNamed). */
    protected fun open(screen: String) {
        app.startActivity(android.content.Intent(app, MainActivity::class.java)
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK or android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(MainActivity.EXTRA_OPEN_SCREEN, screen))
        Thread.sleep(1500)
    }

    /** A page of the sidebar, opened by its link (the sidebar itself has its own journey and the tour). */
    protected fun page(label: String) = open(PAGES[label] ?: error("no link for “$label”"))

    protected fun need(sel: BySelector, what: String, ms: Long = 8000): UiObject2 = find(sel, ms) ?: throw AssertionError("not on screen: $what")

    /** A file's name on screen (a label, never the search box that may hold the same words). */
    protected fun label(text: String): BySelector = By.clazz("android.widget.TextView").textContains(text)

    /**
     * Tap what [sel] finds, by its position: live parts of the screen (the indexing counter, progress)
     * redraw every second, and a found view can be replaced before it is tapped.
     */
    protected fun click(sel: BySelector, what: String, long: Boolean = false, ms: Long = 8000) {
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

    protected fun tap(text: String) = click(By.text(text), "“$text”")

    /** Tap a view already found, by its position (see [click]). */
    protected fun tapAt(o: UiObject2, long: Boolean = false) {
        val b = try { o.visibleBounds } catch (_: StaleObjectException) { throw AssertionError("the view changed before it could be tapped") }
        if (long) device.swipe(b.centerX(), b.centerY(), b.centerX(), b.centerY(), 160) else device.click(b.centerX(), b.centerY())
        Thread.sleep(500)
    }

    /** Something further down a page: scroll the page until it shows. */
    protected fun scrollTo(sel: BySelector, what: String): UiObject2 {
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
    protected fun tapButton(text: String) {
        need(By.text(text), "“$text”")
        val o = device.findObjects(By.text(text)).maxByOrNull { it.visibleBounds.centerY() } ?: throw AssertionError("no “$text”")
        tapAt(o)
    }

    protected fun tapDesc(desc: String) = click(By.desc(desc), "button “$desc”")

    /** An action in a bottom sheet, which may be below the sheet's fold: swipe the sheet up until it shows. */
    protected fun sheetTap(text: String) {
        repeat(5) {
            val o = find(By.text(text), 1200)
            if (o != null) { tapAt(o); return }
            device.swipe(device.displayWidth / 2, device.displayHeight * 85 / 100, device.displayWidth / 2, device.displayHeight * 45 / 100, 25)
        }
        tap(text)
    }

    /** Type into the dialog's text field (the focused one, else the last on screen). */
    protected fun type(text: String) {
        val field = find(By.clazz("android.widget.EditText").focused(true), 4000)
            ?: device.findObjects(By.clazz("android.widget.EditText")).lastOrNull()
            ?: throw AssertionError("no text field to type “$text” into")
        field.text = text
        Thread.sleep(300)
    }

    protected fun back() { device.pressBack(); Thread.sleep(600) }

    protected fun sidebar(label: String) {
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

    protected fun search(q: String) {
        home()
        tap("Search everything…")
        repeat(3) { attempt ->
            val field = find(By.clazz("android.widget.EditText"), 5000) ?: throw AssertionError("no search box")
            try { field.text = q } catch (_: StaleObjectException) { }
            if (find(By.clazz("android.widget.EditText").text(q), 1500) != null) {
                // The magnifier submits (the keyboard's Search key too, but a test can't press that reliably).
                tapDesc("Search")
                // Submitted when the results page (no text box) has replaced the search box.
                if (device.wait(Until.gone(By.clazz("android.widget.EditText")), 6000)) {
                    Thread.sleep(1500)
                    return
                }
            }
            if (attempt < 2) Thread.sleep(500)
        }
        throw AssertionError("the search for “$q” wasn't submitted")
    }

    /** Back to My Drive with nothing open. */
    protected fun home() {
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
    protected fun eventually(what: String, ms: Long = 15_000, check: suspend () -> Boolean) = runBlocking {
        val until = System.currentTimeMillis() + ms
        var last: Throwable? = null
        while (System.currentTimeMillis() < until) {
            try { if (check()) return@runBlocking } catch (e: Exception) { last = e }
            Thread.sleep(500)
        }
        throw AssertionError("never happened: $what" + (last?.let { " (last error: ${it.message})" } ?: ""))
    }

    protected companion object {
        val PAGES = mapOf("My Drive" to "drive", "All files" to "all", "Starred" to "starred", "Recent" to "recent",
            "Photos" to "photos", "Transfers" to "transfers", "Storage" to "storage", "Duplicates" to "duplicates",
            "Chats and indexing" to "index", "Activity" to "activity", "Settings" to "settings")
        const val SLOW = 1200   // px/s: a scroll that doesn't fling
        val TOOLS = setOf("Transfers", "Storage", "Duplicates", "Chats and indexing", "Activity", "Settings")
    }
}
