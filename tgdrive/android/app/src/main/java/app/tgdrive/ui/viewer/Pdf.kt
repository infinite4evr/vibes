package app.tgdrive.ui.viewer

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.os.Handler
import android.os.HandlerThread
import android.os.ParcelFileDescriptor
import android.os.ProxyFileDescriptorCallback
import android.os.storage.StorageManager
import android.system.ErrnoException
import android.system.OsConstants
import androidx.compose.runtime.mutableStateMapOf
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.graph
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayOutputStream
import java.io.Closeable

/**
 * A PDF read straight from TG Drive's stream: Android's PdfRenderer asks for bytes through a
 * proxy file descriptor, and each request fetches only the 256 KB pieces it needs (kept in a
 * small cache), so the first page of a 300 MB book shows after a few hundred KB, like the desktop's
 * pdf.js preview. Rendering runs on one thread (PdfRenderer isn't thread-safe).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RemotePdf private constructor(
    private val pfd: ParcelFileDescriptor,
    private val renderer: PdfRenderer,
    private val thread: HandlerThread,
) : Closeable {
    val pageCount: Int get() = renderer.pageCount

    /** Page size in PDF points (1/72 inch). */
    fun pageSize(index: Int): Pair<Int, Int> = synchronized(renderer) {
        renderer.openPage(index).use { it.width to it.height }
    }

    suspend fun render(index: Int, widthPx: Int): Bitmap = withContext(renderDispatcher) {
        synchronized(renderer) {
            renderer.openPage(index).use { page ->
                val w = widthPx.coerceIn(64, 2600)
                val h = (w.toFloat() * page.height / page.width).toInt().coerceIn(64, 4200)
                val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
                bmp.eraseColor(Color.WHITE)
                page.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                bmp
            }
        }
    }

    override fun close() {
        runCatching { synchronized(renderer) { renderer.close() } }
        runCatching { pfd.close() }
        thread.quitSafely()
    }

    private class RangeReader(private val http: OkHttpClient, private val url: String, private val size: Long) : ProxyFileDescriptorCallback() {
        private val cache = object : LinkedHashMap<Long, ByteArray>(16, .75f, true) {
            override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Long, ByteArray>?) = size > 64
        }

        override fun onGetSize(): Long = size

        override fun onRead(offset: Long, size: Int, data: ByteArray): Int {
            var done = 0
            try {
                while (done < size && offset + done < this.size) {
                    val pos = offset + done
                    val idx = pos / CHUNK
                    val chunk = cache[idx] ?: fetch(idx).also { cache[idx] = it }
                    val within = (pos - idx * CHUNK).toInt()
                    if (within >= chunk.size) break
                    val n = minOf(size - done, chunk.size - within)
                    System.arraycopy(chunk, within, data, done, n)
                    done += n
                }
            } catch (e: Exception) {
                throw ErrnoException("read", OsConstants.EIO)
            }
            return done
        }

        private fun fetch(idx: Long): ByteArray {
            val start = idx * CHUNK
            val end = minOf(size, start + CHUNK) - 1
            val req = Request.Builder().url(url).header("Range", "bytes=$start-$end").build()
            http.newCall(req).execute().use { r ->
                if (r.code != 206 && r.code != 200) throw java.io.IOException("HTTP ${r.code}")
                val bytes = r.body.bytes()
                return if (r.code == 200) bytes.copyOfRange(start.toInt().coerceAtMost(bytes.size), (end + 1).toInt().coerceAtMost(bytes.size)) else bytes
            }
        }

        override fun onRelease() {
            cache.clear()
        }
    }

    companion object {
        private const val CHUNK = 256L * 1024
        private val renderDispatcher = Dispatchers.IO.limitedParallelism(1)

        /** Open a PDF from a stream URL (blocking network: call off the main thread). */
        fun open(ctx: Context, http: OkHttpClient, url: String, size: Long): RemotePdf {
            val thread = HandlerThread("tgdrive-pdf").apply { start() }
            try {
                val sm = ctx.getSystemService(StorageManager::class.java)
                val pfd = sm.openProxyFileDescriptor(ParcelFileDescriptor.MODE_READ_ONLY, RangeReader(http, url, size), Handler(thread.looper))
                val renderer = try {
                    PdfRenderer(pfd)
                } catch (e: Exception) {
                    pfd.close(); throw e
                }
                return RemotePdf(pfd, renderer, thread)
            } catch (e: Exception) {
                thread.quitSafely()
                throw e
            }
        }
    }
}

/**
 * First pages on PDF cards (desktop 2.3): most PDFs on Telegram have no preview picture, so the
 * app draws page one of the PDFs you see, a few at a time, and hands the picture to TG Drive's
 * service, which keeps it for every device and window.
 */
class PdfThumbs private constructor(private val ctx: Context) {
    private val ready = mutableStateMapOf<String, Int>()
    private val queued = HashSet<String>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val permits = Semaphore(2)

    /** The docthumb URL for a PDF card; the first request for one checks whether it exists and draws it if not. */
    fun urlFor(state: AppState, aid: Long, f: FileItem): String? {
        if (!f.isPdf || f.size <= 0) return null
        val key = "$aid:${f.key}"
        val version = ready[key]
        if (version == null) {
            synchronized(queued) { if (!queued.add(key)) return null }
            scope.launch { ensure(state, aid, f, key) }
            return null
        }
        return if (version > 0) state.api.docThumbUrl(aid, f.chatId, f.msgId) + "?r=$version" else null
    }

    private suspend fun ensure(state: AppState, aid: Long, f: FileItem, key: String) {
        val api = state.api
        val http = ctx.graph.mediaHttp
        // Does the service have it already (or know it can't be drawn)?
        val status = runCatching {
            http.newCall(Request.Builder().url(api.docThumbUrl(aid, f.chatId, f.msgId)).build()).execute().use { it.code to it.header("X-Doc-Thumb") }
        }.getOrNull() ?: return run { synchronized(queued) { queued.remove(key) } }
        when {
            status.first == 200 -> { ready[key] = 1; return }
            status.second == "none" -> { ready[key] = 0; return }
        }
        permits.withPermit {
            try {
                RemotePdf.open(ctx, http, api.streamUrl(aid, f), f.size).use { pdf ->
                    val bmp = pdf.render(0, 360)
                    val out = ByteArrayOutputStream()
                    bmp.compress(Bitmap.CompressFormat.JPEG, 80, out)
                    bmp.recycle()
                    api.saveDocThumb(aid, f.ref, out.toByteArray())
                    ready[key] = 2
                }
            } catch (e: Exception) {
                runCatching { api.docThumbFailed(aid, f.ref) }
                ready[key] = 0
            }
        }
    }

    companion object {
        @Volatile private var instance: PdfThumbs? = null
        fun get(ctx: Context): PdfThumbs = instance ?: synchronized(this) { instance ?: PdfThumbs(ctx.applicationContext).also { instance = it } }
    }
}
