package app.tgdrive.ui.actions

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.webkit.MimeTypeMap
import androidx.core.content.FileProvider
import app.tgdrive.diag.AppLog
import java.io.File

/** Android's side of opening, sharing and copying things. */
object Platform {
    fun openUrl(ctx: Context, url: String): Boolean = try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (_: ActivityNotFoundException) {
        false
    }

    fun mimeOf(name: String, fallback: String? = null): String {
        val ext = name.substringAfterLast('.', "").lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: fallback ?: "application/octet-stream"
    }

    fun uriFor(ctx: Context, path: String): Uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.files", File(path))

    /** Open a downloaded file with the app Android picks for it. */
    fun openFile(ctx: Context, path: String, mime: String?): Boolean {
        val f = File(path)
        if (!f.exists()) return false
        // Never a file:// link: Android 7+ refuses those with a crash (FileUriExposedException).
        val uri = try { uriFor(ctx, path) } catch (e: IllegalArgumentException) {
            AppLog.w("platform", "no content link for a file outside TG Drive's shared folders", e)
            return false
        }
        val i = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime ?: mimeOf(f.name))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            ctx.startActivity(Intent.createChooser(i, "Open with").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }

    /** Hand a stream to another app (VLC, MX Player …): the media token only plays streams. */
    fun openStream(ctx: Context, url: String, mime: String?, title: String): Boolean {
        val i = Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse(url), mime ?: "video/*")
            .putExtra("title", title)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            ctx.startActivity(Intent.createChooser(i, "Play with").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }

    fun shareFiles(ctx: Context, paths: List<String>) {
        val uris = ArrayList(paths.map { uriFor(ctx, it) })
        val i = if (uris.size == 1) Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris[0]).setType(mimeOf(paths[0]))
        else Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris).setType("*/*")
        i.clipData = ClipData.newRawUri("files", uris[0]).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        ctx.startActivity(Intent.createChooser(i, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun shareText(ctx: Context, text: String) {
        val i = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
        ctx.startActivity(Intent.createChooser(i, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun copy(ctx: Context, label: String, text: String) {
        val cm = ctx.getSystemService(ClipboardManager::class.java)
        cm.setPrimaryClip(ClipData.newPlainText(label, text))
    }

    /** Make a finished download show up in Files, Gallery and music apps. */
    fun scan(ctx: Context, path: String) {
        MediaScannerConnection.scanFile(ctx, arrayOf(path), null, null)
    }
}
