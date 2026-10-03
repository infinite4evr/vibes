package app.tgdrive.diag

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.util.TypedValue
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import app.tgdrive.MainActivity
import kotlinx.coroutines.runBlocking
import java.io.File

/**
 * What you see instead of TG Drive vanishing: any crash in the app's process ends up here (see
 * [AppLog.installCrashHandler]), with the error, a GitHub issue or problem report about it, and a
 * way back in. It runs in its own process (":crash") with plain Android views, nothing of the
 * app's state, interface toolkit or service, so it works even when those are what broke. When
 * the crashes repeat, it offers to reset the app's own settings; accounts, the index and
 * downloads are never touched.
 */
class CrashActivity : Activity() {

    private lateinit var report: String
    private var recent = 1

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // This screen already explains the failed launch: "Open again" goes straight to the app.
        app.tgdrive.storage.DataLocation.launchFinished(this)
        val file = intent.getStringExtra(EXTRA_REPORT)?.let { File(it) }?.takeIf { it.isFile }
            ?: AppLog.unseenCrashes(this).firstOrNull()
        report = runCatching { file?.readText() }.getOrNull()?.takeIf { it.isNotBlank() }
            ?: "TG Drive stopped, but no crash report was saved."
        // Shown: not offered again by the notice at the next start (the file stays for problem reports).
        if (file != null && !file.name.endsWith(".seen.txt")) AppLog.markSeen(listOf(file))
        val since = System.currentTimeMillis() - REPEAT_WINDOW
        recent = AppLog.dir(this).listFiles { f -> f.name.startsWith("crash-app-") && f.lastModified() > since }?.size ?: 1
        setContentView(build())
    }

    /** The exception line of the report ("java.lang.IllegalStateException: …"), for the issue's title. */
    private fun cause(): String = report.lineSequence().drop(2).firstOrNull { it.isNotBlank() && !it.startsWith("Android ") }?.trim()
        ?: "TG Drive stopped"

    private fun build(): View {
        val dp = { v: Int -> TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt() }
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(40), dp(24), dp(32))
        }
        fun text(s: String, size: Float, color: Int, bold: Boolean = false, top: Int = 0) = TextView(this).apply {
            text = s
            setTextColor(color)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
            if (bold) setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(top), 0, 0)
            col.addView(this)
        }
        text("TG Drive stopped", 24f, INK, bold = true)
        text("Something went wrong and TG Drive had to close. Your files, folders and sign-ins are safe: they live in " +
            "Telegram and in TG Drive's own storage on this phone.", 15f, INK2, top = 10)
        if (recent >= 2) text("This has happened $recent times in the last few minutes.", 15f, DANGER, bold = true, top = 10)
        text("Reporting it gets it fixed: “Create GitHub issue” opens a new issue with this error and the end of TG Drive's " +
            "logs (you see it before sending). “Send report” makes a file with all the logs.", 14f, INK2, top = 10)

        fun button(label: String, primary: Boolean, onClick: () -> Unit) = Button(this).apply {
            text = label
            isAllCaps = false
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setTextColor(if (primary) Color.WHITE else ACCENT)
            backgroundTintList = ColorStateList.valueOf(if (primary) ACCENT else PANEL)
            setOnClickListener { onClick() }
            col.addView(this, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(52)).apply { topMargin = dp(10) })
        }
        button("Create GitHub issue", primary = true) {
            GitHubIssue.openAsync(this, GitHubIssue.titleFor("Android crash", cause()), "TG Drive stopped (a crash).", report)
        }
        button("Send report", primary = false) { sendReport() }
        button("Copy the details", primary = false) {
            getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("TG Drive crash", report))
            Toast.makeText(this, "Copied", Toast.LENGTH_SHORT).show()
        }
        button("Open TG Drive again", primary = recent < 2) { reopen() }
        if (recent >= 2) button("Reset TG Drive's settings and open", primary = true) { confirmReset() }

        // The error itself below the buttons: they must show without scrolling.
        TextView(this).apply {
            text = report.lineSequence().take(40).joinToString("\n")
            typeface = Typeface.MONOSPACE
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setTextColor(INK2)
            setTextIsSelectable(true)
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = GradientDrawable().apply { setColor(PANEL); cornerRadius = dp(10).toFloat() }
            col.addView(this, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply { topMargin = dp(16) })
        }

        return ScrollView(this).apply {
            setBackgroundColor(CANVAS)
            isFillViewport = true
            addView(col)
        }
    }

    private fun sendReport() {
        Toast.makeText(this, "Making the report…", Toast.LENGTH_SHORT).show()
        Thread({
            runCatching { runBlocking { ProblemReport.share(this@CrashActivity, null, report.take(3000)) } }
                .onFailure { e -> runOnUiThread { Toast.makeText(this, "Couldn't make the report: ${e.message}", Toast.LENGTH_LONG).show() } }
        }, "tgdrive-report").start()
    }

    private fun reopen() {
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        finish()
    }

    private fun confirmReset() {
        AlertDialog.Builder(this)
            .setTitle("Reset TG Drive's settings?")
            .setMessage("Clears the app's own settings on this phone (the last screen, list and player settings, the state of " +
                "its service). Your Telegram accounts, TG Drive's index, folders, tags and downloads are kept.")
            .setPositiveButton("Reset and open") { _, _ -> reset(); reopen() }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** The app's own settings only: never the service's data (accounts, index, folders) or downloads. */
    private fun reset() {
        runCatching {
            getSharedPreferences("app", MODE_PRIVATE).edit().clear().putBoolean("welcomed", true).commit()
            getSharedPreferences("player", MODE_PRIVATE).edit().clear().commit()
            app.tgdrive.storage.PortablePreferences.save(this)
            File(filesDir, "engine-state.json").delete()
            AppLog.i("crash", "the app's settings were reset from the crash screen")
        }
    }

    companion object {
        const val EXTRA_REPORT = "report"
        /** Crashes this close together count as "keeps crashing". */
        private const val REPEAT_WINDOW = 10 * 60_000L
        private val INK = Color.rgb(0x1C, 0x23, 0x31)
        private val INK2 = Color.rgb(0x4A, 0x55, 0x68)
        private val DANGER = Color.rgb(0xC6, 0x28, 0x28)
        private val ACCENT = Color.rgb(0x2B, 0x6C, 0xD4)
        private val PANEL = Color.rgb(0xEE, 0xF1, 0xF6)
        private val CANVAS = Color.rgb(0xFA, 0xFB, 0xFD)
    }
}
