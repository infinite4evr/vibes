package app.tgdrive.diag

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.widget.Toast
import app.tgdrive.BuildConfig
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.engine.BatteryLimits
import app.tgdrive.engine.EngineService
import app.tgdrive.engine.EngineState
import app.tgdrive.engine.StartupReport
import java.io.File

/**
 * "Create GitHub issue": opens a new issue on TG Drive's repository in the browser (or the GitHub
 * app), already filled in with what went wrong: the error and its stack, the phone and app, the
 * service's state, its latest crash report and the end of the logs. You see it before sending and
 * can edit it. Tokens are removed from everything (AppLog.clean); file and chat names can appear
 * in log lines. The full logs don't fit in a link: the issue says how to attach the problem report.
 */
object GitHubIssue {
    const val REPO = "infinite4evr/vibes"
    /** Browsers and GitHub accept links up to about 8 000 characters; stay under it. */
    private const val MAX_URL = 7_600

    /** Opens the new issue: prepared on a background thread (it reads the logs), then the browser. */
    fun openAsync(context: Context, title: String, what: String?, detail: String?) {
        val app = context.applicationContext
        Thread({
            val url = runCatching { link(title, body(app, what, detail)) }.getOrElse {
                AppLog.w("report", "couldn't prepare the GitHub issue", it)
                link(title, (what ?: "") + "\n\n" + (detail ?: "").take(3000))
            }
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                try {
                    app.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                } catch (e: ActivityNotFoundException) {
                    val cm = app.getSystemService(ClipboardManager::class.java)
                    cm?.setPrimaryClip(ClipData.newPlainText("TG Drive issue", url))
                    Toast.makeText(app, "No browser to open GitHub: the issue link was copied instead.", Toast.LENGTH_LONG).show()
                }
            }
        }, "tgdrive-issue").start()
    }

    /** A title from an error: its first line, short. */
    fun titleFor(prefix: String, error: String?): String {
        val first = error?.lineSequence()?.firstOrNull { it.isNotBlank() }?.trim().orEmpty()
        return (if (first.isEmpty()) prefix else "$prefix: $first").take(110)
    }

    /** The issue link; the body is shortened (logs first, then the details) until the link fits. */
    fun link(title: String, body: String): String {
        val base = "https://github.com/$REPO/issues/new?labels=${Uri.encode("android,bug")}&title=${Uri.encode(title)}&body="
        var text = body
        while (true) {
            val url = base + Uri.encode(text)
            if (url.length <= MAX_URL || text.length < 200) return url
            text = shorten(text)
        }
    }

    /**
     * One step shorter: the logs lose their oldest line (the longest log first); once the logs are down
     * to a few lines, the error's details and crash report lose their deepest line (the top of a stack,
     * the exception itself, is kept); as a last resort the end is cut.
     */
    private fun shorten(text: String): String {
        val lines = text.lines().toMutableList()
        data class Block(val heading: String, val start: Int, val end: Int) { val size get() = end - start }
        val blocks = ArrayList<Block>()
        var heading = ""
        var i = 0
        while (i < lines.size) {
            val l = lines[i]
            if (l.startsWith("### ")) heading = l
            if (l.startsWith("```text")) {
                var end = i + 1
                while (end < lines.size && !lines[end].startsWith("```")) end++
                blocks += Block(heading, i + 1, end)
                i = end + 1
            } else i++
        }
        val logs = blocks.filter { "log" in it.heading.lowercase() || "start steps" in it.heading.lowercase() }
        logs.filter { it.size > 3 }.maxByOrNull { it.size }?.let { lines.removeAt(it.start); return lines.joinToString("\n") }
        (blocks - logs.toSet()).filter { it.size > 6 }.maxByOrNull { it.size }?.let { lines.removeAt(it.end - 1); return lines.joinToString("\n") }
        return text.take((text.length * 0.85).toInt()) + "\n…"
    }

    fun body(context: Context, what: String?, detail: String?): String = buildString {
        appendLine("### What happened")
        appendLine(what?.trim()?.takeIf { it.isNotEmpty() }?.let { AppLog.clean(it) } ?: "_Describe what you were doing when it went wrong._")
        appendLine()
        if (!detail.isNullOrBlank()) {
            appendLine("### Details")
            appendLine("```text")
            appendLine(AppLog.clean(detail).trim().take(4000))
            appendLine("```")
            appendLine()
        }
        appendLine("### Phone and app")
        val s = runCatching { EngineState.read(context) }.getOrNull()
        appendLine("- TG Drive ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE}) · Android ${Build.VERSION.RELEASE} " +
            "(API ${Build.VERSION.SDK_INT}) · ${Build.MANUFACTURER} ${Build.MODEL}")
        if (s != null) appendLine("- Service: ${s.phase} · “${s.stage}” · ${s.version.ifBlank { "?" }} · sample data ${s.demo}" +
            (s.error?.let { " · error: ${it.lineSequence().first().take(200)}" } ?: ""))
        runCatching {
            appendLine("- Background: ${BatteryLimits.status(context).describe()} · sync " +
                (if (BackgroundSync.enabled(context)) "every ${BackgroundSync.minutes(context)} min" else "off") +
                " · last: ${BackgroundSync.last(context).let { if (it.at == 0L) "never" else it.result }}")
        }
        appendLine()
        latestServiceCrash(context)?.let { crash ->
            appendLine("### The service's latest crash report")
            appendLine("```text")
            appendLine(AppLog.clean(crash).trim())
            appendLine("```")
            appendLine()
        }
        val appLog = tailOf(File(AppLog.dir(context), "app.log"), 60)
        if (appLog.isNotBlank()) {
            appendLine("### App log (end)")
            appendLine("```text")
            appendLine(AppLog.clean(appLog))
            appendLine("```")
            appendLine()
        }
        val serviceLog = tailOf(File(app.tgdrive.storage.DataLocation.root(context)?.resolve("service") ?: File(context.filesDir,"tgdrive"), "logs/tgdrive.log"), 40)
        if (serviceLog.isNotBlank()) {
            appendLine("### Service log (end)")
            appendLine("```text")
            appendLine(AppLog.clean(serviceLog))
            appendLine("```")
            appendLine()
        }
        val start = tailOf(File(app.tgdrive.storage.DataLocation.logs(context), EngineService.START_LOG), 15)
        if (start.isNotBlank()) {
            appendLine("### Service start steps")
            appendLine("```text")
            appendLine(AppLog.clean(start))
            appendLine("```")
            appendLine()
        }
        appendLine("_The complete logs are in the problem report: TG Drive → Settings → About & diagnostics → **Send report**. " +
            "Attach that .zip here if you can._")
    }

    /** The newest crash report the service saved in the last day (the traceback of a server error), shortened. */
    private fun latestServiceCrash(context: Context): String? {
        val dir = File(app.tgdrive.storage.DataLocation.root(context)?.resolve("service") ?: File(context.filesDir,"tgdrive"), "crashes")
        val f = dir.listFiles { x -> x.name.endsWith(".txt") }.orEmpty().maxByOrNull { it.lastModified() } ?: return null
        if (System.currentTimeMillis() - f.lastModified() > 86_400_000) return null
        return runCatching { f.readText().take(2500) }.getOrNull()
    }

    private fun tailOf(f: File, lines: Int): String = StartupReport.tail(f, lines)
}
