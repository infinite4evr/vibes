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
import app.tgdrive.R
import app.tgdrive.graph
import app.tgdrive.util.Format
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
    private val queue = Channel<Job>(Channel.UNLIMITED)
    private var pending = 0

    private data class Job(val aid: Long, val uris: List<Uri>, val tree: Uri?, val folderId: String?, val chatId: Long?, val caption: String)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        scope.launch { for (job in queue) run(job) }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ServiceCompat.startForeground(this, NOTIFY_ID, notification(getString(R.string.upload_preparing), null),
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
        if (intent == null) return START_NOT_STICKY
        val uris = buildList {
            intent.clipData?.let { cd -> for (i in 0 until cd.itemCount) cd.getItemAt(i).uri?.let(::add) }
            if (isEmpty()) intent.data?.let(::add)
        }
        val tree = intent.getStringExtra(EXTRA_TREE)?.let(Uri::parse)
        pending++
        queue.trySend(Job(intent.getLongExtra(EXTRA_AID, 0), if (tree != null) emptyList() else uris, tree,
            intent.getStringExtra(EXTRA_FOLDER), intent.getLongExtra(EXTRA_CHAT, 0).takeIf { it != 0L },
            intent.getStringExtra(EXTRA_CAPTION).orEmpty()))
        return START_NOT_STICKY
    }

    private suspend fun run(job: Job) {
        val g = graph
        withContext(Dispatchers.Main) { g.engine.hold("upload", true) }
        try {
            withTimeoutOrNull(60_000) { g.engine.state.first { it.ready } } ?: error("TG Drive's service isn't running.")
            val files = if (job.tree != null) walkTree(job.tree) else job.uris.map { it to "" }
            var sent = 0
            var failed = 0
            for ((i, pair) in files.withIndex()) {
                val (uri, rel) = pair
                val (name, size) = describe(uri)
                update(getString(R.string.upload_sending, name), if (files.size > 1) (i * 100 / files.size) else null)
                try {
                    val body = UriBody(this, uri, size, contentResolver.getType(uri)?.toMediaTypeOrNull())
                    g.api.upload(job.aid, name, body, job.folderId, rel = if (rel.isEmpty()) "" else "$rel/$name",
                        caption = job.caption, chatId = job.chatId)
                    sent++
                } catch (e: Exception) {
                    failed++
                    g.state.message("Couldn't upload “$name”: ${e.message}", error = true)
                }
            }
            val msg = when {
                failed == 0 -> resources.getQuantityString(R.plurals.upload_queued, sent, sent)
                else -> getString(R.string.upload_some_failed, sent, failed)
            }
            g.state.message(msg, error = failed > 0)
            g.state.changed("upload")
            withContext(Dispatchers.Main) { g.state.loadTransfers() }
        } catch (e: Exception) {
            g.state.message(e.message ?: "Upload failed.", error = true)
        } finally {
            pending--
            if (pending <= 0) {
                withContext(Dispatchers.Main) {
                    g.engine.hold("upload", false)
                    ServiceCompat.stopForeground(this@UploadService, ServiceCompat.STOP_FOREGROUND_REMOVE)
                    stopSelf()
                }
            }
        }
    }

    /** Every file under a picked folder, with its path relative to (and including) that folder. */
    private fun walkTree(tree: Uri): List<Pair<Uri, String>> {
        val root = DocumentFile.fromTreeUri(this, tree) ?: return emptyList()
        val out = ArrayList<Pair<Uri, String>>()
        fun walk(dir: DocumentFile, rel: String) {
            for (f in dir.listFiles()) {
                val n = f.name ?: continue
                if (n.startsWith(".")) continue
                if (f.isDirectory) walk(f, "$rel/$n") else out += f.uri to rel
            }
        }
        walk(root, root.name ?: "Folder")
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
        .setContentIntent(EngineService.openApp(this, null))
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

    companion object {
        private const val NOTIFY_ID = 7
        const val EXTRA_AID = "aid"
        const val EXTRA_FOLDER = "folder"
        const val EXTRA_CHAT = "chat"
        const val EXTRA_CAPTION = "caption"
        const val EXTRA_TREE = "tree"

        fun start(context: Context, aid: Long, uris: List<Uri>, folderId: String?, chatId: Long? = null, caption: String = "") {
            if (uris.isEmpty()) return
            val clip = ClipData.newRawUri("files", uris.first()).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
            val i = Intent(context, UploadService::class.java).apply {
                clipData = clip
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                putExtra(EXTRA_AID, aid)
                putExtra(EXTRA_FOLDER, folderId)
                putExtra(EXTRA_CAPTION, caption)
                if (chatId != null) putExtra(EXTRA_CHAT, chatId)
            }
            ContextCompat.startForegroundService(context, i)
        }

        fun startTree(context: Context, aid: Long, tree: Uri, folderId: String?) {
            val i = Intent(context, UploadService::class.java).apply {
                putExtra(EXTRA_TREE, tree.toString())
                putExtra(EXTRA_AID, aid)
                putExtra(EXTRA_FOLDER, folderId)
            }
            ContextCompat.startForegroundService(context, i)
        }
    }
}

@Suppress("unused")
private fun sizeLabel(n: Long) = Format.size(n)
