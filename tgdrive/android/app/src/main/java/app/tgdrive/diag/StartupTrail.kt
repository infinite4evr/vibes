package app.tgdrive.diag

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.os.Debug
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import app.tgdrive.engine.StartupReport
import app.tgdrive.storage.DataLocation
import app.tgdrive.storage.DataLocationActivity
import java.io.File
import java.io.RandomAccessFile
import java.time.Instant
import java.util.concurrent.atomic.AtomicBoolean

/**
 * How each start of TG Drive's interface went, step by step: `files/logs/startup.log`, in the app's own
 * storage. Unlike the app log (queued, kept in the data folder) every line is written at once, in storage
 * no other app can clean, so it survives what the app log may not: a hang, a native crash, a kill, a data
 * folder that stopped answering or was emptied by a cleaner app. The startup screen, problem reports and
 * GitHub issues show it.
 *
 * While the main thread works through a start ([begin] … [done]), a watchdog checks that it still answers.
 * Busy for 5 s: what it is doing (its stack) is written here. Stuck for 15 s while the person is looking at
 * it: TG Drive opens its startup screen (its own process) with that, and ends the stuck process, instead of
 * leaving the launcher icon on screen with nothing said.
 */
object StartupTrail {
    private const val MAX_BYTES = 192L * 1024
    private const val BUSY_MS = 5_000L
    private const val STUCK_MS = 15_000L
    /** A start that is still "in progress" this long after its last step, but answering, is not watched any more. */
    private const val GIVE_UP_MS = 120_000L
    /** The startup screen's extra: the step the main thread was stuck in. */
    const val EXTRA_STUCK = "stuck"

    /** What the main thread is starting now (null: nothing to watch). */
    @Volatile private var step: String? = null
    @Volatile private var stepSince = 0L
    private var watching = false
    private val lock = Any()

    fun file(c: Context): File = File(DataLocation.privateLogs(c), "startup.log")

    /** Write [text] to the trail at once, and to the app log. */
    fun mark(c: Context, text: String) {
        AppLog.i("startup", text.lineSequence().first())
        note(c, text)
    }

    /** Write [text] to the trail only (the app log may be what is failing). */
    fun note(c: Context, text: String) {
        synchronized(lock) {
            runCatching {
                val f = file(c)
                if (f.length() > MAX_BYTES) trim(f)
                f.appendText("${Instant.now()} [${Process.myPid()}] $text\n")
            }
        }
    }

    /** The main thread starts [what]: written down, and watched until [done]. */
    fun begin(c: Context, what: String) {
        mark(c, what)
        val ctx = c.applicationContext ?: c
        synchronized(lock) {
            step = what
            stepSince = SystemClock.uptimeMillis()
            if (watching) return
            watching = true
        }
        Thread({ watch(ctx) }, "tgdrive-startup-watch").apply { isDaemon = true }.start()
    }

    /** The start reached its screen (the main screen, or an error screen that explains): nothing more to watch. */
    fun done(c: Context, what: String) {
        synchronized(lock) { step = null }
        mark(c, what)
    }

    /** The last [lines] lines of the trail. */
    fun tail(c: Context, lines: Int = 80): String = StartupReport.tail(file(c), lines, 64L * 1024)

    /** The last step the process [pid] wrote down, if any. */
    fun lastStep(c: Context, pid: Int): String? = runCatching {
        tail(c, 400).lineSequence().filter { it.contains(" [$pid] ") }.lastOrNull()?.substringAfter(" [$pid] ")
    }.getOrNull()

    private fun watch(ctx: Context) {
        val main = Handler(Looper.getMainLooper())
        while (true) {
            val answered = AtomicBoolean(false)
            val sent = SystemClock.uptimeMillis()
            synchronized(lock) {
                if (step == null || sent - stepSince > GIVE_UP_MS) { step = null; watching = false; return }
            }
            main.postAtFrontOfQueue { answered.set(true) }
            var noted = 0L
            while (!answered.get()) {
                SystemClock.sleep(250)
                val blocked = SystemClock.uptimeMillis() - sent
                val what = step ?: "starting"
                if ((noted == 0L && blocked >= BUSY_MS) || (noted < STUCK_MS && blocked >= STUCK_MS)) {
                    noted = blocked
                    mark(ctx, "The main thread hasn't answered for ${blocked / 1000} s, while: $what\n${mainStack()}")
                }
                // A debugger holding the main thread at a breakpoint isn't a stuck start.
                if (blocked >= STUCK_MS && lookedAt() && !Debug.isDebuggerConnected()) { stuck(ctx, what, blocked); return }
            }
            SystemClock.sleep(500)
        }
    }

    /** Whether the person is looking at TG Drive (it is in front, or visible). */
    private fun lookedAt(): Boolean = runCatching {
        val info = ActivityManager.RunningAppProcessInfo()
        ActivityManager.getMyMemoryState(info)
        info.importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_VISIBLE
    }.getOrDefault(false)

    /** Stuck in front of the person: say so on the startup screen, and end this process (it can't recover). */
    private fun stuck(ctx: Context, what: String, blocked: Long) {
        mark(ctx, "Stuck: no answer from the main thread for ${blocked / 1000} s, while: $what. Opening the startup screen.")
        // The next launch opens the startup screen too, whatever happens to this one.
        DataLocation.launchStarted(ctx)
        runCatching {
            ctx.startActivity(Intent(ctx, DataLocationActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                .putExtra(EXTRA_STUCK, what))
        }.onFailure { note(ctx, "Couldn't open the startup screen: $it") }
        Process.killProcess(Process.myPid())
    }

    private fun mainStack(): String =
        Looper.getMainLooper().thread.stackTrace.take(40).joinToString("\n") { "\tat $it" }

    /** Keep the newer half (whole lines). */
    private fun trim(f: File) {
        val keep = RandomAccessFile(f, "r").use { raf ->
            val start = (raf.length() - MAX_BYTES / 2).coerceAtLeast(0)
            raf.seek(start)
            ByteArray((raf.length() - start).toInt()).also { raf.readFully(it) }
        }
        val tmp = File(f.path + ".tmp")
        tmp.writeText(String(keep, Charsets.UTF_8).substringAfter('\n'))
        if (!tmp.renameTo(f)) tmp.delete()
    }
}
