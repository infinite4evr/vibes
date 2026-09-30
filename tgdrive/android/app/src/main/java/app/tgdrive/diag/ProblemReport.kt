package app.tgdrive.diag

import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import app.tgdrive.engine.EngineClient
import app.tgdrive.engine.EngineService
import app.tgdrive.engine.StartupReport
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.RandomAccessFile
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * A problem report: one .zip with everything needed to find out what went wrong, made on the
 * phone and handed to the share sheet (to send by mail, Telegram, or upload anywhere):
 *
 *   report.txt           the phone, the service's state, how its process last ended, what went wrong
 *   app/                 the interface's log and crash reports (logs/app.log, crash-*.txt)
 *   engine/              the service's Android log and its start steps
 *   service/             the Python service's logs (tgdrive.log, and tgdrive-debug.log when detailed
 *                        logging is on) and its crash reports
 *
 * No passwords, API hashes, tokens or messages: the logs never contain them (tokens are removed
 * from URLs as they are written). File and chat names can appear in the logs.
 */
object ProblemReport {
    private const val MAX_FILE = 6L * 1024 * 1024   // the end of each log, at most

    suspend fun build(context: Context, engine: EngineClient, error: String? = null): File = withContext(Dispatchers.IO) {
        AppLog.flushNow()
        val dir = File(context.cacheDir, "reports").apply { mkdirs() }
        dir.listFiles()?.forEach { if (System.currentTimeMillis() - it.lastModified() > 86_400_000) it.delete() }
        val stamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"))
        val zip = File(dir, "tgdrive-report-$stamp.zip")
        ZipOutputStream(zip.outputStream().buffered()).use { out ->
            fun text(name: String, body: String) {
                out.putNextEntry(ZipEntry(name)); out.write(body.toByteArray()); out.closeEntry()
            }
            fun file(name: String, f: File) {
                if (!f.isFile) return
                out.putNextEntry(ZipEntry(name))
                RandomAccessFile(f, "r").use { raf ->
                    val start = (raf.length() - MAX_FILE).coerceAtLeast(0)
                    raf.seek(start)
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = raf.read(buf)
                        if (n <= 0) break
                        out.write(buf, 0, n)
                    }
                }
                out.closeEntry()
            }
            text("report.txt", StartupReport.build(context, engine, error))
            val logs = AppLog.dir(context)
            logs.listFiles().orEmpty().sortedBy { it.name }.forEach { f ->
                when {
                    f.name.startsWith("app.log") || f.name.startsWith("crash-app") -> file("app/${f.name}", f)
                    f.name.startsWith("engine.log") || f.name.startsWith("crash-engine") -> file("engine/${f.name}", f)
                    else -> file("app/${f.name}", f)
                }
            }
            file("engine/${EngineService.START_LOG}", File(context.filesDir, EngineService.START_LOG))
            val service = File(context.filesDir, "tgdrive")
            File(service, "logs").listFiles().orEmpty().sortedBy { it.name }.forEach { file("service/${it.name}", it) }
            File(service, "crashes").listFiles().orEmpty().filter { it.name.endsWith(".txt") }
                .sortedByDescending { it.lastModified() }.take(30).forEach { file("service/crashes/${it.name}", it) }
        }
        AppLog.i("report", "problem report made: ${zip.name} (${zip.length() / 1024} KB)")
        zip
    }

    /** Make the report and open the share sheet with it. */
    suspend fun share(context: Context, engine: EngineClient, error: String? = null) {
        val zip = build(context, engine, error)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", zip)
        val send = Intent(Intent.ACTION_SEND)
            .setType("application/zip")
            .putExtra(Intent.EXTRA_STREAM, uri)
            .putExtra(Intent.EXTRA_SUBJECT, "TG Drive problem report")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        send.clipData = ClipData.newRawUri(zip.name, uri)
        context.startActivity(Intent.createChooser(send, "Send the problem report").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
