package app.tgdrive.engine

import android.app.Service
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.provider.OpenableColumns
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.documentfile.provider.DocumentFile
import app.tgdrive.diag.AppLog
import app.tgdrive.R
import app.tgdrive.graph
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.currentCoroutineContext
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File

/**
 * Hands files from this phone to TG Drive's service (PUT /upload), which then uploads them to
 * Telegram in the background with pause, resume and retry like any other transfer.
 *
 * Files come from the system file picker, a folder picked with the system picker (sent with
 * their folders, like the desktop's folder upload) or another app's Share menu. Reading them runs
 * in this foreground service, so leaving the app doesn't stop a big file half-way.
 */
class UploadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val queue = Channel<String>(Channel.UNLIMITED)
    private lateinit var journal: UploadJournal
    private val enqueuing = java.util.concurrent.atomic.AtomicInteger(0)
    private val scheduled = java.util.Collections.synchronizedSet(HashSet<String>())
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        journal = UploadJournal(this)
        scope.launch { for (id in queue) { try { runEntry(id) } finally { scheduled.remove(id) } } }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        try {
            ServiceCompat.startForeground(this, NOTIFY_ID, notification(getString(R.string.upload_preparing), null),
                if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
        } catch (e: Exception) { AppLog.w("upload", "couldn't show foreground notification", e) }
        enqueuing.incrementAndGet()
        scope.launch {
            try {
                val uris = buildList {
                    intent?.clipData?.let { cd -> for (i in 0 until cd.itemCount) cd.getItemAt(i).uri?.let(::add) }
                    if (isEmpty()) intent?.data?.let(::add)
                }
                val tree = intent?.getStringExtra(EXTRA_TREE)?.let(Uri::parse)
                val all = if (tree != null) walkTree(tree) else uris.map { it to "" }
                val persisted = contentResolver.persistedUriPermissions.filter { it.isReadPermission }.map { it.uri }.toSet()
                // Only what other apps and Android's pickers hand over: never a file path, or TG Drive's own files
                // (a share naming them would make TG Drive read its private data, e.g. a Telegram session).
                val refused = all.count { (uri, _) -> !uploadable(uri) }
                if (refused > 0) {
                    AppLog.w("upload", "refused $refused shared item(s) that aren't another app's files")
                    graph.state.message("Skipped $refused of the shared items: TG Drive only uploads files other apps share.", error = true)
                }
                for ((uri, rel) in all) {
                    if (!uploadable(uri)) continue
                    val name = runCatching { describe(uri).first }.getOrDefault("Shared file")
                    val grant = (tree ?: uri).takeIf { it in persisted }?.toString().orEmpty()
                    journal.put(UploadJournal.Entry(java.util.UUID.randomUUID().toString(), intent?.getLongExtra(EXTRA_AID,0) ?: 0,
                        uri.toString(), name, intent?.getStringExtra(EXTRA_FOLDER), rel,
                        intent?.getLongExtra(EXTRA_CHAT,0)?.takeIf { it != 0L }, intent?.getStringExtra(EXTRA_CAPTION).orEmpty(),
                        demo=graph.engine.demo, grant=grant))
                }
                val retry = intent?.action == ACTION_RETRY
                for (e in journal.list()) if (e.demo == graph.engine.demo && (retry || e.error.isEmpty()) && scheduled.add(e.id)) queue.send(e.id)
            } catch (e: Exception) { graph.state.failed("Preparing upload queue", e) }
            finally { if (enqueuing.decrementAndGet() == 0 && scheduled.isEmpty()) stopSelfResult(startId) }
        }
        return START_NOT_STICKY
    }

    private suspend fun runEntry(id: String) {
        var entry = journal.list().firstOrNull { it.id == id } ?: return
        val g = graph
        withContext(Dispatchers.Main) { g.engine.hold("upload", true) }
        try {
            val dir = File(app.tgdrive.storage.DataLocation.state(this), "upload-staging").apply { mkdirs() }
            val staged = File(dir, "$id.bin")
            val uri = Uri.parse(entry.uri)
            // A file kept readable by a persisted permission is read again after a restart: no copy. One
            // shared with only a temporary permission is copied first (within the staging limit), so a
            // restart doesn't lose it; one too big for that is sent straight away.
            if (entry.grant.isEmpty() && (entry.staged.isEmpty() || !staged.exists())) {
                val limit = (g.state.setting("upload_staging_limit_mb")?.toLongOrNull() ?: 4096L) * 1024 * 1024
                if (stage(uri, dir, staged, limit)) {
                    entry = entry.copy(staged = staged.absolutePath, error = "")
                    journal.put(entry)
                }
            }
            withTimeoutOrNull(60_000) { g.engine.state.first { it.ready } } ?: error("TG Drive's service isn't running.")
            check(g.engine.state.value.demo == entry.demo) { "Switch back to the account mode where this upload was queued." }
            sending.value = Sending(entry.name, 1, scheduled.size)
            update("Sending ${entry.name}", null)
            val body = if (staged.exists()) staged.asRequestBody("application/octet-stream".toMediaTypeOrNull())
                else UriBody(this, uri, runCatching { describe(uri).second }.getOrDefault(-1L), contentResolver.getType(uri)?.toMediaTypeOrNull())
            g.api.upload(entry.aid, entry.name, body, entry.folder,
                rel=if (entry.rel.isEmpty()) "" else "${entry.rel}/${entry.name}", caption=entry.caption,
                chatId=entry.chat, uploadId=entry.id)
            // The engine durably acknowledged this id. Replaying it cannot enqueue a second upload.
            journal.discard(this, entry)
            staged.delete()
            g.state.changed("upload")
        } catch (e: kotlinx.coroutines.CancellationException) { throw e
        } catch (e: Exception) {
            journal.put(entry.copy(error=e.message ?: "Upload interrupted"))
            g.state.message("${entry.name}: pending in Offline & recovery", error=false)
            AppLog.w("upload", "handoff pending: ${entry.id}", e)
        } finally {
            sending.value = null
            withContext(kotlinx.coroutines.NonCancellable + Dispatchers.Main) {
                g.engine.hold("upload", false)
                if (scheduled.size <= 1 && enqueuing.get() == 0) {
                    ServiceCompat.stopForeground(this@UploadService, ServiceCompat.STOP_FOREGROUND_REMOVE)
                    stopSelf()
                }
            }
        }
    }

    /** Copies [uri] to [staged]; false (nothing kept) when it is bigger than [limit] allows. */
    private suspend fun stage(uri: Uri, dir: File, staged: File, limit: Long): Boolean {
        val tmp = File(dir, "${staged.nameWithoutExtension}.part")
        val other = dir.listFiles().orEmpty().filter { it != tmp && it != staged }.sumOf { it.length() }
        val size = runCatching { describe(uri).second }.getOrDefault(-1L)
        if (size >= 0 && other + size > limit) return false
        try {
            contentResolver.openInputStream(uri)?.use { input ->
                java.io.FileOutputStream(tmp).use { output ->
                    val buf = ByteArray(256 * 1024)
                    var count = 0L
                    while (true) {
                        currentCoroutineContext().ensureActive()
                        val n = input.read(buf); if (n < 0) break
                        count += n
                        if (other + count > limit) return false
                        check(dir.usableSpace > n + 256L * 1024 * 1024) { "Not enough free space to prepare this upload." }
                        output.write(buf, 0, n)
                    }
                    output.fd.sync()
                }
            } ?: error("File permission expired. Select this file again; remove this pending entry in Recovery.")
            check(tmp.renameTo(staged)) { "Could not save upload staging file" }
            return true
        } finally { tmp.delete() }
    }

    private suspend fun walkTree(tree: Uri): List<Pair<Uri, String>> {
        val root = DocumentFile.fromTreeUri(this, tree) ?: return emptyList()
        val out = ArrayList<Pair<Uri,String>>()
        suspend fun walk(dir: DocumentFile, rel: String) {
            currentCoroutineContext().ensureActive()
            for (f in dir.listFiles()) {
                val name = f.name ?: continue
                if (name.startsWith(".")) continue
                if (f.isDirectory) walk(f,"$rel/$name") else out += f.uri to rel
            }
        }
        walk(root,root.name ?: "Folder")
        return out
    }

    private fun describe(uri: Uri): Pair<String, Long> {
        var name = uri.lastPathSegment?.substringAfterLast('/') ?: "file"
        var size = -1L
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getString(0)?.let { name = it }
                if (!c.isNull(1)) size = c.getLong(1)
            }
        }
        return name to size
    }

    private fun update(text: String, progress: Int?) {
        try {
            NotificationManagerCompat.from(this).notify(NOTIFY_ID, notification(text, progress))
        } catch (_: SecurityException) {
        }
    }

    private fun notification(text: String, progress: Int?) = NotificationCompat.Builder(this, EngineService.CHANNEL_ENGINE)
        .setSmallIcon(R.drawable.ic_stat_tgdrive)
        .setContentTitle(getString(R.string.upload_title))
        .setContentText(text)
        .setOngoing(true)
        .setSilent(true)
        .setContentIntent(EngineService.openScreen(this, "transfers"))
        .apply { if (progress != null) setProgress(100, progress, false) else setProgress(0, 0, true) }
        .build()

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    /** Streams a content:// file straight into the request, without a temporary copy. */
    private class UriBody(private val context: Context, private val uri: Uri, private val size: Long,
                          private val type: MediaType?) : RequestBody() {
        override fun contentType() = type
        override fun contentLength() = size
        override fun isOneShot() = true
        override fun writeTo(sink: BufferedSink) {
            context.contentResolver.openInputStream(uri)?.use { sink.writeAll(it.source()) }
                ?: throw java.io.IOException("can't read ${uri.lastPathSegment}")
        }
    }

    private fun uploadable(uri: Uri): Boolean = uri.scheme == "content" && uri.authority != "$packageName.files"

    companion object {
        private const val NOTIFY_ID = 7
        const val ACTION_RETRY = "app.tgdrive.upload.RETRY"
        fun retry(context: Context): Boolean = requestStart(context, Intent(context, UploadService::class.java).setAction(ACTION_RETRY))
        /** The file being handed to TG Drive's service right now (shown on the Transfers page). */
        val sending = kotlinx.coroutines.flow.MutableStateFlow<Sending?>(null)

        const val EXTRA_AID = "aid"
        const val EXTRA_FOLDER = "folder"
        const val EXTRA_CHAT = "chat"
        const val EXTRA_CAPTION = "caption"
        const val EXTRA_TREE = "tree"

        /** Upload [uris]; false if Android didn't let the upload start (the caller says so). */
        fun start(context: Context, aid: Long, uris: List<Uri>, folderId: String?, chatId: Long? = null, caption: String = ""): Boolean {
            if (uris.isEmpty()) return true
            uris.forEach { uri -> runCatching { context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) } }
            val clip = ClipData.newRawUri("files", uris.first()).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
            val i = Intent(context, UploadService::class.java).apply {
                clipData = clip
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                putExtra(EXTRA_AID, aid)
                putExtra(EXTRA_FOLDER, folderId)
                putExtra(EXTRA_CAPTION, caption)
                if (chatId != null) putExtra(EXTRA_CHAT, chatId)
            }
            return requestStart(context, i)
        }

        /** Start the upload service; false if Android refused (the caller says so). */
        private fun requestStart(context: Context, i: Intent): Boolean = try {
            ContextCompat.startForegroundService(context, i)
            true
        } catch (e: Exception) {
            AppLog.w("upload", "couldn't start the upload service", e)
            false
        }

        fun startTree(context: Context, aid: Long, tree: Uri, folderId: String?): Boolean {
            runCatching { context.contentResolver.takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            val i = Intent(context, UploadService::class.java).apply {
                putExtra(EXTRA_TREE, tree.toString())
                putExtra(EXTRA_AID, aid)
                putExtra(EXTRA_FOLDER, folderId)
            }
            return requestStart(context, i)
        }
    }
}

data class Sending(val name: String, val index: Int, val total: Int)
