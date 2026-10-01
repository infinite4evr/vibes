package app.tgdrive

import android.app.ActivityManager
import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import app.tgdrive.engine.EngineState
import com.chaquo.python.Kwarg
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * A big library, as a heavy user has it: 100 000 files in 1 700 chats (tests/bigdb.py, the same
 * generator the service's scale tests use), built on the phone itself. TG Drive must open to its main
 * screen quickly and stay responsive: the sidebar with every chat, All files scrolled through several
 * pages, Photos, a search, Storage, the chats list. Android must not report it as not responding.
 *
 * Runs last in CI, on a cleared app (it replaces TG Drive's data with the big library).
 */
@RunWith(AndroidJUnit4::class)
class BigLibraryTest : UiDriver() {
    private val timings = StringBuilder()

    private fun timed(what: String, block: () -> Unit) {
        val t0 = System.currentTimeMillis()
        block()
        val ms = System.currentTimeMillis() - t0
        timings.append("$what: $ms ms\n")
        Log.i(TAG, "$what: $ms ms")
    }

    private fun notResponding(): String? {
        val am = app.getSystemService(ActivityManager::class.java)
        return am.processesInErrorState?.firstOrNull { it.processName.startsWith(app.packageName) }
            ?.let { "${it.processName}: ${it.shortMsg}" }
    }

    /** Frame statistics and memory, while TG Drive still runs (the test runner ends its processes after). */
    private fun keepMeasurements() {
        dir.mkdirs()
        for ((file, cmd) in listOf("big-library-frames.txt" to "dumpsys gfxinfo ${app.packageName}",
                "big-library-memory-app.txt" to "dumpsys meminfo ${app.packageName}",
                "big-library-memory-engine.txt" to "dumpsys meminfo ${app.packageName}:engine")) {
            runCatching { File(dir, file).writeText(device.executeShellCommand(cmd)) }
                .onFailure { Log.w(TAG, "couldn't keep $file", it) }
        }
    }

    /** The library, written where TG Drive keeps its data: 100 000 files, signed-in account 424242. */
    private fun buildLibrary(files: Int) {
        val data = File(app.filesDir, "tgdrive").apply { deleteRecursively(); mkdirs() }
        val account = File(data, "accounts/424242").apply { mkdirs() }
        File(account, "session.session").writeBytes(ByteArray(0))
        File(data, "settings.json").writeText("""{"api_id": 1234567, "api_hash": "0123456789abcdef0123456789abcdef"}""")
        System.loadLibrary("tgfts5")
        if (!Python.isStarted()) Python.start(AndroidPlatform(app))
        val py = Python.getInstance()
        val env = py.getModule("os").get("environ")!!
        env.callAttr("__setitem__", "TGDRIVE_DATA", data.path)
        env.callAttr("__setitem__", "HOME", data.path)
        env.callAttr("__setitem__", "TGDRIVE_PACKAGED", "1")
        py.getModule("tgdrive.mobile").callAttr("enable_fts5", "libtgfts5.so")
        val path = py.getModule("pathlib").callAttr("Path", File(account, "index.db").path)
        py.getModule("tests.bigdb").callAttr("build", path, files, Kwarg("quiet", true)).callAttr("close")
    }

    @Test
    fun aHundredThousandFilesOpenFastAndStayResponsive() {
        app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
        app.getSharedPreferences("engine", 0).edit().putBoolean("demo", false).commit()
        runBlocking {
            g.engine.stop()
            withTimeoutOrNull(40_000) { g.engine.state.first { it.phase == EngineState.Phase.Stopped || it.phase == EngineState.Phase.Failed } }
        }
        Thread.sleep(2000)
        timed("building 100 000 files") { buildLibrary(100_000) }

        ActivityScenario.launch(MainActivity::class.java).use {
            runCatching { device.executeShellCommand("dumpsys gfxinfo ${app.packageName} reset") }
            try {
                browse()
            } finally {
                keepMeasurements()
                Log.i(TAG, "timings:\n$timings")
                File(dir, "big-library-timings.txt").apply { parentFile?.mkdirs() }.writeText(timings.toString())
            }
            notResponding()?.let { fail("Android reported TG Drive as not responding: $it") }
        }
    }

    /** What a heavy user does first: the main screen, the sidebar, the big pages, a search. */
    private fun browse() {
        var ready = false
        timed("service ready") {
            ready = runBlocking { withTimeoutOrNull(240_000) { g.engine.state.first { it.ready } } } != null
        }
        if (!ready) fail("the service didn't start on the big library: ${g.engine.state.value.error}")
        // The main screen must show (not a blank or black window).
        timed("main screen after the service was ready") {
            if (find(By.text("Search everything…"), 30_000) == null) {
                shot("50-big-main-screen-FAIL", 200)
                fail("the main screen didn't show within 30 s of the service being ready")
            }
        }
        shot("50-big-home", 1500)

        timed("sidebar with every chat") {
            tapDesc("Menu")
            need(By.desc("Close navigation menu"), "the sidebar", 10_000)
            // Open the biggest chat group and scroll through it.
            for (group in listOf("CHANNELS", "GROUPS")) {
                device.findObject(By.textStartsWith(group))?.let { tapAt(it) }
            }
            repeat(4) { swipeUp(0.6f) }
            shot("51-big-sidebar", 800)
            device.pressBack()
        }

        timed("All files, five pages") {
            page("All files")
            need(By.desc("File options"), "files in All files", 30_000)
            repeat(5) { swipeUp(0.6f); Thread.sleep(300) }
            need(By.desc("File options"), "files after scrolling", 15_000)
            shot("52-big-all-files", 800)
        }

        timed("Photos") {
            page("Photos")
            need(By.textContains("20"), "the photo timeline", 30_000)
            repeat(3) { swipeUp(0.6f); Thread.sleep(300) }
            shot("53-big-photos", 1500)
        }

        timed("search") {
            search("polity")
            need(By.desc("File options"), "search results", 30_000)
            shot("54-big-search", 800)
        }

        timed("Storage") {
            page("Storage")
            need(By.textContains("Total size"), "the storage numbers", 90_000)
            shot("55-big-storage", 800)
        }

        timed("Chats and indexing") {
            page("Chats and indexing")
            Thread.sleep(3000)
            repeat(3) { swipeUp(0.6f) }
            shot("56-big-chats", 800)
        }

        // The service's own answers while its background jobs (subjects, meaning index, duplicates)
        // work through the big library: pages must still answer quickly (pace.foreground).
        val aid = g.state.aid.value
        val slowest = (1..8).maxOf {
            val t0 = System.currentTimeMillis()
            runBlocking {
                g.api.status()
                g.api.files(aid, mapOf("limit" to "90", "copies" to "hide"))
            }
            Thread.sleep(700)
            System.currentTimeMillis() - t0 - 700
        }
        timings.append("slowest status + first page of files (of 8): $slowest ms\n")
        if (slowest > 5000) fail("the service took $slowest ms to answer while its background jobs ran")
    }

    private companion object {
        const val TAG = "BigLibrary"
    }
}
