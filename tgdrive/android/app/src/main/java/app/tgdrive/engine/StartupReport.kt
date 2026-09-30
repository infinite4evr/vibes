package app.tgdrive.engine

import android.content.Context
import android.os.Build
import android.system.Os
import android.system.OsConstants
import app.tgdrive.BuildConfig
import java.io.File
import java.io.RandomAccessFile

/**
 * What to send when TG Drive's service doesn't start: the phone, how the start went step by step,
 * how Android ended the service's process, and the end of the service's own log. Secrets (the
 * per-launch tokens) are left out.
 */
object StartupReport {
    fun build(context: Context, engine: EngineClient, error: String?): String = buildString {
        val s = engine.state.value
        appendLine("TG Drive ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE}${if (BuildConfig.DEBUG) ", debug" else ""})")
        appendLine("Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) · ${Build.MANUFACTURER} ${Build.MODEL} · " +
            "ABIs ${Build.SUPPORTED_ABIS.joinToString()} · page size ${runCatching { Os.sysconf(OsConstants._SC_PAGESIZE) }.getOrDefault(-1)}")
        appendLine("Service: ${s.phase} · stage “${s.stage}” · pid ${s.pid} · port ${s.port} · demo ${s.demo}" +
            (if (s.version.isNotBlank()) " · ${s.version} · crypto ${s.crypto} · fts5 ${s.fts5} · numpy ${s.numpy}" else ""))
        if (!error.isNullOrBlank()) { appendLine(); appendLine("Error:"); appendLine(error) }
        appendLine()
        appendLine("How the service's process ended (newest first):")
        appendLine(engine.exitHistory())
        appendLine()
        appendLine("Start steps:")
        appendLine(tail(File(context.filesDir, EngineService.START_LOG), 60).ifBlank { "(none)" })
        appendLine()
        appendLine("Service log (end):")
        appendLine(tail(File(context.filesDir, "tgdrive/logs/tgdrive.log"), 80).ifBlank { "(none)" })
    }

    /** The last `lines` lines of a file, reading only its end. */
    fun tail(f: File, lines: Int, maxBytes: Long = 48 * 1024): String {
        if (!f.exists()) return ""
        return runCatching {
            RandomAccessFile(f, "r").use { raf ->
                val len = raf.length()
                val start = (len - maxBytes).coerceAtLeast(0)
                raf.seek(start)
                val bytes = ByteArray((len - start).toInt())
                raf.readFully(bytes)
                bytes.decodeToString().lines().let { if (start > 0) it.drop(1) else it }.takeLast(lines).joinToString("\n")
            }
        }.getOrDefault("")
    }
}
