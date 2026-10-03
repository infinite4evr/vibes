package app.tgdrive.diag

import android.content.Context
import kotlin.system.exitProcess
import android.content.Intent
import android.os.Build
import android.os.Process
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.LinkedBlockingQueue

/**
 * TG Drive's log on the phone, like the desktop's tgdrive.log: one file per process
 * (logs/app.log for the interface, logs/engine.log for the service's Android side; the Python
 * service keeps its own tgdrive.log next to them). Errors and important steps are always written;
 * with "Detailed debug logging" on (Settings → About & diagnostics, shared with the desktop) every
 * request, screen and action is written too. Files rotate at 2 MB (three kept). Secrets in URLs
 * (?t=…) are removed. Everything also goes to logcat.
 */
object AppLog {
    private const val MAX_BYTES = 2L * 1024 * 1024
    private val time = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSS")
    private val secret = Regex("([?&](?:t|token)=)[^&\\s]+")
    private val queue = LinkedBlockingQueue<String>()
    @Volatile private var file: File? = null
    @Volatile private var started = false

    /** Detailed debug logging: requests, screens and actions, not only problems. */
    @Volatile var verbose = false

    fun dir(context: Context): File = app.tgdrive.storage.DataLocation.logs(context)

    /** Start logging for this process into logs/<name>.log (a background thread writes). */
    @Synchronized
    fun init(context: Context, name: String) {
        if (started) return
        started = true
        file = File(dir(context), "$name.log")
        Thread({
            while (true) {
                val first = queue.take()
                val batch = StringBuilder(first)
                while (true) batch.append(queue.poll() ?: break)
                write(batch.toString())
            }
        }, "tgdrive-log").apply { isDaemon = true; start() }
        i("log", "---- TG Drive ${versionOf(context)} · Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) · " +
            "${Build.MANUFACTURER} ${Build.MODEL} · process $name (${Process.myPid()})")
    }

    fun d(tag: String, msg: String) { if (verbose) log("D", tag, msg, null) }
    fun i(tag: String, msg: String) = log("I", tag, msg, null)
    fun w(tag: String, msg: String, t: Throwable? = null) = log("W", tag, msg, t)
    fun e(tag: String, msg: String, t: Throwable? = null) = log("E", tag, msg, t)

    /** Remove secrets (the per-launch tokens in stream URLs) from what is logged. */
    fun clean(s: String): String = secret.replace(s, "$1…")

    private fun log(level: String, tag: String, msg: String, t: Throwable?) {
        val text = clean(msg)
        when (level) {
            "E" -> android.util.Log.e("TGDrive/$tag", text, t)
            "W" -> android.util.Log.w("TGDrive/$tag", text, t)
            "I" -> android.util.Log.i("TGDrive/$tag", text)
            else -> android.util.Log.d("TGDrive/$tag", text)
        }
        val line = StringBuilder()
            .append(LocalDateTime.now().format(time)).append(' ').append(level).append(' ')
            .append(tag).append(" [").append(Thread.currentThread().name).append("]: ").append(text).append('\n')
        if (t != null) line.append(clean(stack(t))).append('\n')
        if (started) queue.offer(line.toString())
    }

    /** Write at once (a crash is about to end the process: the writer thread may not get to it). */
    fun flushNow(extra: String? = null) {
        val pending = StringBuilder()
        while (true) pending.append(queue.poll() ?: break)
        if (extra != null) pending.append(extra)
        if (pending.isNotEmpty()) write(pending.toString())
    }

    @Synchronized
    private fun write(text: String) {
        val f = file ?: return
        try {
            if (f.length() > MAX_BYTES) {
                File(f.path + ".2").delete()
                File(f.path + ".1").renameTo(File(f.path + ".2"))
                f.renameTo(File(f.path + ".1"))
            }
            f.appendText(text)
        } catch (_: Exception) {
        }
    }

    /** The end of this phone's app logs (the interface and the service's Android side), newest last. */
    fun tail(context: Context, lines: Int = 400): String {
        flushNow()
        val out = ArrayList<String>()
        for (name in listOf("engine.log", "app.log")) {
            val f = File(dir(context), name)
            if (!f.isFile) continue
            val text = runCatching {
                java.io.RandomAccessFile(f, "r").use { raf ->
                    val start = (raf.length() - 256 * 1024).coerceAtLeast(0)
                    raf.seek(start)
                    val buf = ByteArray((raf.length() - start).toInt())
                    raf.readFully(buf)
                    String(buf)
                }
            }.getOrDefault("")
            out += "==== $name"
            out += text.lines().takeLast(lines / 2)
        }
        return out.joinToString("\n")
    }

    /** Clear the app logs and seen crash reports (the current files are emptied, not removed). */
    @Synchronized
    fun clear(context: Context) {
        dir(context).listFiles().orEmpty().forEach { f ->
            when {
                f.name.endsWith(".log") -> runCatching { f.writeText("") }
                f.name.contains(".log.") || f.name.endsWith(".seen.txt") -> f.delete()
            }
        }
    }

    fun stack(t: Throwable): String = StringWriter().also { t.printStackTrace(PrintWriter(it)) }.toString().trimEnd()

    private fun versionOf(context: Context): String = runCatching {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName
    }.getOrNull() ?: "?"

    /**
     * Crashes (anything uncaught in this process): written to its own report file and the log
     * before the process ends, so the next start can offer to send it.
     */
    fun installCrashHandler(context: Context, name: String) {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, e ->
            val file = runCatching {
                val at = LocalDateTime.now()
                val report = buildString {
                    appendLine("TG Drive ${versionOf(context)} crashed in its $name process on thread ${thread.name} at $at")
                    appendLine("Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) · ${Build.MANUFACTURER} ${Build.MODEL}")
                    appendLine()
                    append(clean(stack(e)))
                }
                val f = File(dir(context), "crash-$name-${at.format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss-SSS"))}.txt")
                f.writeText(report)
                flushNow("${at.format(time)} E crash [${thread.name}]: ${clean(stack(e))}\n")
                f
            }.getOrNull()
            // The interface: show the crash screen (its own process) instead of the app vanishing, or
            // closing again at every launch while something keeps crashing.
            if (name == "app") {
                val shown = runCatching {
                    context.startActivity(Intent(context, CrashActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                        .putExtra(CrashActivity.EXTRA_REPORT, file?.path))
                }.isSuccess
                if (shown) {
                    Process.killProcess(Process.myPid())
                    exitProcess(10)
                }
            }
            previous?.uncaughtException(thread, e)
        }
    }

    /** Crash reports of the app not yet shown to the person (newest first). */
    fun unseenCrashes(context: Context): List<File> =
        dir(context).listFiles { f -> f.name.startsWith("crash-") && f.name.endsWith(".txt") && !f.name.endsWith(".seen.txt") }.orEmpty()
            .sortedByDescending { it.lastModified() }

    /** Shown (and sent or dismissed): kept for the report bundle, not offered again. */
    fun markSeen(files: List<File>) = files.forEach { it.renameTo(File(it.path.removeSuffix(".txt") + ".seen.txt")) }
}
