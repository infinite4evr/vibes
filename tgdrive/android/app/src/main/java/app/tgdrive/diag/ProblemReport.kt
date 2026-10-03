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
 *   own/                 what TG Drive keeps in its own storage: the startup steps (startup.log), crash
 *                        reports, and app log lines the data folder couldn't take
 *   app/                 the interface's log in the data folder (logs/app.log, crash report copies)
 *   engine/              the service's Android log and its start steps
 *   service/             the Python service's logs (tgdrive.log, and tgdrive-debug.log when detailed
 *                        logging is on) and its crash reports
 *
 * Free-form text is omitted by default. The optional detailed version can include file names,
 * chat names and search terms; common secret patterns are scrubbed, but users must review it
 * before sharing because arbitrary third-party error text cannot be exhaustively classified.
 */
object ProblemReport {
    private const val MAX_FILE = 6L * 1024 * 1024   // the end of each log, at most

    suspend fun build(context: Context, engine: EngineClient?, error: String? = null, includeNames: Boolean = false): File = withContext(Dispatchers.IO) {
        AppLog.flushNow()
        val dir = File(context.cacheDir, "reports").apply { mkdirs() }
        dir.listFiles()?.forEach { if (System.currentTimeMillis() - it.lastModified() > 86_400_000) it.delete() }
        val stamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"))
        val zip = File(dir, "tgdrive-report-$stamp-${java.util.UUID.randomUUID()}.zip")
        ZipOutputStream(zip.outputStream().buffered()).use { out ->
            fun text(name: String, body: String) {
                out.putNextEntry(ZipEntry(name)); out.write((if (name == "report.txt" && !includeNames) body else ReportPrivacy.clean(body, includeNames)).toByteArray()); out.closeEntry()
            }
            fun file(name: String, f: File) {
                if (!f.isFile) return
                val body = RandomAccessFile(f,"r").use { raf ->
                    raf.seek((raf.length()-MAX_FILE).coerceAtLeast(0))
                    val bytes=ByteArray((raf.length()-raf.filePointer).toInt()); raf.readFully(bytes)
                    String(bytes, Charsets.UTF_8)
                }
                text(name, body)
            }
            text("report.txt", if (includeNames) StartupReport.build(context, engine, error) else
                "TG Drive ${app.tgdrive.BuildConfig.VERSION_NAME}\nAndroid ${android.os.Build.VERSION.SDK_INT}\n" +
                "Service: ${engine?.state?.value?.phase}\nPersonal text omitted. Log timestamps, severity and code locations retained.\n")
            // TG Drive's own storage first (always readable): the startup steps, crash reports, and any app log
            // that couldn't be written to the data folder.
            AppLog.crashDir(context).listFiles().orEmpty().filter { it.isFile }.sortedBy { it.name }.forEach { file("own/${it.name}", it) }
            val logs = AppLog.dir(context)
            logs.listFiles().orEmpty().sortedBy { it.name }.forEach { f ->
                when {
                    f.name.startsWith("app.log") || f.name.startsWith("crash-app") -> file("app/${f.name}", f)
                    f.name.startsWith("engine.log") || f.name.startsWith("crash-engine") -> file("engine/${f.name}", f)
                    else -> file("app/${f.name}", f)
                }
            }
            file("engine/${EngineService.START_LOG}", File(app.tgdrive.storage.DataLocation.logs(context), EngineService.START_LOG))
            val service = app.tgdrive.storage.DataLocation.root(context)?.let { File(it,"service") } ?: File(context.filesDir,"tgdrive")
            File(service, "logs").listFiles().orEmpty().sortedBy { it.name }.forEach { file("service/${it.name}", it) }
            File(service, "crashes").listFiles().orEmpty().filter { it.name.endsWith(".txt") }
                .sortedByDescending { it.lastModified() }.take(30).forEach { file("service/crashes/${it.name}", it) }
        }
        AppLog.i("report", "problem report made: ${zip.name} (${zip.length() / 1024} KB)")
        zip
    }

    /** Make the report and open the share sheet with it. */
    suspend fun share(context: Context, engine: EngineClient?, error: String? = null) {
        ReportPreview.show(context, engine, error)
    }

    fun shareFile(context: Context, zip: File) {
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
