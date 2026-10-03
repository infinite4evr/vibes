package app.lumaclean.data

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import androidx.core.content.FileProvider
import app.lumaclean.core.Progress
import app.lumaclean.core.formatBytes
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException

data class OpResult(
    val done: Int,
    val failed: Int,
    val bytes: Long,
    val binIds: List<String> = emptyList(),
    val newPaths: List<String> = emptyList(),
)

class FileOps(
    private val context: Context,
    private val index: FileIndexRepository,
    private val bin: RecycleBin,
) {
    private val authority = "${context.packageName}.files"

    fun sizeOf(file: File): Long {
        if (!file.isDirectory) return file.length()
        index.current.value?.sizeOf(file.absolutePath)?.let { return it }
        return file.walkTopDown().filter { it.isFile }.sumOf { it.length() }
    }

    /**
     * Deletes [paths]. With [toBin] they go to the recycle bin (restorable); otherwise they
     * are removed for good. Folders are removed with everything inside.
     */
    suspend fun remove(paths: Collection<String>, toBin: Boolean, progress: Progress = Progress.None): OpResult {
        val ctx = currentCoroutineContext()
        var done = 0
        var failed = 0
        var bytes = 0L
        val binned = ArrayList<BinItem>()
        val removed = ArrayList<String>()
        // Recycling journals the whole batch in one write before anything moves, and settles it in one
        // write after (also on cancellation): two writes, however many files.
        val planned = if (toBin) bin.reserve(paths.map { it to sizeOf(File(it)) }) else emptyMap()
        val moved = HashSet<String>()
        try { paths.forEachIndexed { i, path ->
            ctx.ensureActive()
            val f = File(path)
            progress.report(i / paths.size.toFloat(), f.name)
            if (!f.exists()) {
                removed += path
                return@forEachIndexed
            }
            val item = planned[path]
            val size = item?.size ?: sizeOf(f)
            val ok = if (toBin) {
                item != null && bin.moveReserved(item).also { if (it) { binned += item; moved += item.id } }
            } else {
                if (f.isDirectory) f.deleteRecursively() else f.delete()
            }
            if (ok) {
                done++
                bytes += size
                removed += path
            } else failed++
        }
        } finally {
            if (toBin) bin.settle(planned.values.filter { it.id !in moved }.map { it.id })
            // Keep the visible index correct even on cancellation.
            index.removePaths(removed)
            notifyMedia(removed)
        }
        return OpResult(done, failed, bytes, binned.map { it.id })
    }

    /** Partial copies left in [dir] by a copy the app was killed during (named only by this class). */
    private fun removeStaleParts(dir: File) {
        val hourAgo = System.currentTimeMillis() - 60 * 60 * 1000
        dir.listFiles()?.forEach { f ->
            if (STAGING.matches(f.name) && f.lastModified() < hourAgo) f.deleteRecursively()
        }
    }

    fun restore(ids: Collection<String>): Int {
        val restored = bin.restore(ids)
        index.invalidate()
        notifyMedia(restored)
        return restored.size
    }

    fun rename(path: String, newName: String): String {
        val name = newName.trim()
        require(name.isNotEmpty() && '/' !in name) { "That name isn't allowed" }
        val src = File(path)
        val dest = File(src.parentFile, name)
        if (dest.exists()) throw IOException("\"$name\" already exists here")
        if (!src.renameTo(dest)) throw IOException("Couldn't rename ${src.name}")
        index.invalidate()
        notifyMedia(listOf(path, dest.absolutePath))
        return dest.absolutePath
    }

    fun createFolder(parent: String, name: String): String {
        val clean = name.trim()
        require(clean.isNotEmpty() && '/' !in clean) { "That name isn't allowed" }
        val dir = File(parent, clean)
        if (dir.exists()) throw IOException("\"$clean\" already exists here")
        if (!dir.mkdirs()) throw IOException("Couldn't create the folder")
        index.invalidate()
        return dir.absolutePath
    }

    /** Copies or moves [paths] into [destDir]; name clashes get " (1)" appended, never overwritten. */
    suspend fun transfer(paths: Collection<String>, destDir: String, move: Boolean, progress: Progress = Progress.None): OpResult {
        val ctx = currentCoroutineContext()
        val dest = File(destDir)
        val sources = paths.map(::File).filter { it.exists() }
        for (s in sources) {
            if (s.isDirectory && (destDir == s.absolutePath || destDir.startsWith(s.absolutePath + "/"))) {
                throw IOException("Can't put a folder inside itself")
            }
        }
        removeStaleParts(dest)
        val totalBytes = sources.sumOf { sizeOf(it) }.coerceAtLeast(1)
        var copied = 0L
        var done = 0
        var failed = 0
        val created = ArrayList<String>()
        val touched = ArrayList<String>()
        val verb = if (move) "Moving" else "Copying"

        fun copyFile(src: File, target: File) {
            val expected = src.length()
            val modified = src.lastModified()
            val tmp = File(target.parentFile, ".${target.name}.${java.util.UUID.randomUUID()}.part")
            try {
                FileInputStream(src).use { input ->
                    FileOutputStream(tmp).use { output ->
                        val buf = ByteArray(256 * 1024)
                        while (true) {
                            ctx.ensureActive()
                            val n = input.read(buf)
                            if (n < 0) break
                            output.write(buf, 0, n)
                            copied += n
                            progress.report(copied / totalBytes.toFloat(), "$verb ${src.name} · ${copied.formatBytes()}")
                        }
                        output.fd.sync()
                    }
                }
                ctx.ensureActive()
                if (tmp.length() != expected || src.length() != expected || src.lastModified() != modified)
                    throw IOException("Source changed while copying ${src.name}; original kept")
                tmp.setLastModified(modified)
                java.nio.file.Files.move(tmp.toPath(), target.toPath()) // fails if a new destination appeared
            } finally { tmp.delete() }
        }

        suspend fun copyTree(src: File, target: File) {
            ctx.ensureActive()
            if (src.isDirectory) {
                if (!target.exists() && !target.mkdirs()) throw IOException("Couldn't create ${target.name}")
                val children = src.listFiles() ?: throw IOException("Cannot read ${src.name}; original kept")
                children.forEach { copyTree(it, File(target, it.name)) }
            } else copyFile(src, target)
        }

        for (src in sources) {
            ctx.ensureActive()
            val target = uniqueFile(dest, src.name)
            val staging = File(dest, ".${src.name}.${java.util.UUID.randomUUID()}.part")
            val ok = runCatching {
                if (move && src.renameTo(target)) {
                    copied += sizeOf(target)
                    true
                } else {
                    copyTree(src, staging)
                    ctx.ensureActive()
                    java.nio.file.Files.move(staging.toPath(), target.toPath())
                    if (move) src.deleteRecursively() else true
                }
            }.getOrElse { e ->
                if (e is kotlinx.coroutines.CancellationException) {
                    staging.deleteRecursively()
                    throw e
                }
                staging.deleteRecursively()
                false
            }
            if (ok) {
                done++
                created += target.absolutePath
                if (move) touched += src.absolutePath
            } else failed++
        }
        index.invalidate()
        notifyMedia(created + touched)
        return OpResult(done, failed, copied, newPaths = created)
    }

    fun notifyMedia(paths: List<String>) {
        if (paths.isEmpty()) return
        runCatching { MediaScannerConnection.scanFile(context, paths.toTypedArray(), null, null) }
    }

    fun uriFor(path: String): Uri = FileProvider.getUriForFile(context, authority, File(path))

    fun openIntent(path: String): Intent {
        val uri = uriFor(path)
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, FileTypes.mime(path.substringAfterLast('/')))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return Intent.createChooser(view, "Open with")
    }

    fun shareIntent(paths: List<String>): Intent {
        val uris = ArrayList(paths.map(::uriFor))
        val mime = paths.map { FileTypes.mime(it.substringAfterLast('/')) }.distinct().let { if (it.size == 1) it[0] else "*/*" }
        val send = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris[0])
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
        }
        send.type = mime
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        send.clipData = ClipData.newRawUri("", uris[0]).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
        return Intent.createChooser(send, "Share")
    }
}

/** ".name.<uuid>.part": the temporary name a file or folder copy has until it is complete. */
private val STAGING = Regex("""^\..+\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.part$""")
