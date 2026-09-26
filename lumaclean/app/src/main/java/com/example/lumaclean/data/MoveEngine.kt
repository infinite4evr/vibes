package com.example.lumaclean.data

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import com.example.lumaclean.model.MigrationProgress
import com.example.lumaclean.model.MigrationResult
import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest

class MoveEngine(private val context: Context) {
    suspend fun migrate(
        source: File,
        destinationTree: Uri,
        deleteSource: Boolean,
        onProgress: (MigrationProgress) -> Unit
    ): MigrationResult {
        val destination = DocumentFile.fromTreeUri(context, destinationTree)
            ?: error("The selected SD-card folder is no longer accessible")
        require(destination.canWrite()) { "The selected destination is not writable" }
        require(source.exists()) { "Source does not exist: ${source.absolutePath}" }

        val files = if (source.isFile) listOf(source) else source.walkTopDown()
            .onEnter { dir ->
                val normalized = dir.absolutePath.replace('\\', '/').lowercase()
                !normalized.contains("/android/data") &&
                    !normalized.contains("/android/obb") &&
                    !normalized.contains("/android/sandbox")
            }
            .filter { it.isFile }
            .toList()
        var copied = 0
        var skipped = 0
        var renamed = 0
        var failed = 0
        var bytes = 0L

        files.forEachIndexed { index, file ->
            val relativeParent = source.toPath().let { base ->
                val parent = file.parentFile?.toPath() ?: base
                runCatching { base.relativize(parent).toString() }.getOrDefault("")
            }
            val targetDir = ensureDirectories(destination, relativeParent)
            val existing = targetDir.findFile(file.name)
            var targetName = file.name

            if (existing != null && existing.isFile) {
                if (equivalent(file, existing)) {
                    skipped++
                    if (deleteSource) runCatching { file.delete() }
                    onProgress(MigrationProgress(file.name, index + 1, files.size, bytes))
                    return@forEachIndexed
                }
                targetName = uniqueName(targetDir, file.name)
                renamed++
            }

            val target = targetDir.createFile(mimeFor(file), targetName)
            if (target == null) {
                failed++
                return@forEachIndexed
            }

            val ok = runCatching {
                context.contentResolver.openOutputStream(target.uri, "w")!!.use { output ->
                    FileInputStream(file).use { input -> input.copyTo(output, 1024 * 1024) }
                }
                target.length() == file.length()
            }.getOrDefault(false)

            if (ok) {
                copied++
                bytes += file.length()
                if (deleteSource) runCatching { file.delete() }
            } else {
                failed++
                runCatching { target.delete() }
            }

            onProgress(MigrationProgress(file.name, index + 1, files.size, bytes))
        }

        if (deleteSource && source.isDirectory) {
            source.walkBottomUp().filter { it.isDirectory }.forEach { dir -> runCatching { dir.delete() } }
        }
        return MigrationResult(copied, skipped, renamed, failed, bytes)
    }

    private fun ensureDirectories(root: DocumentFile, relative: String): DocumentFile {
        var current = root
        relative.replace('\\', '/').split('/').filter { it.isNotBlank() }.forEach { part ->
            current = current.findFile(part)?.takeIf { it.isDirectory }
                ?: current.createDirectory(part)
                ?: error("Could not create destination folder: $part")
        }
        return current
    }

    private fun equivalent(source: File, target: DocumentFile): Boolean {
        if (source.length() != target.length()) return false
        if (source.length() > 128L * 1024 * 1024) return true
        val a = sha256(FileInputStream(source))
        val b = context.contentResolver.openInputStream(target.uri)?.use { sha256(it) } ?: return false
        return a.contentEquals(b)
    }

    private fun sha256(input: java.io.InputStream): ByteArray {
        val md = MessageDigest.getInstance("SHA-256")
        input.use { stream ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val n = stream.read(buffer)
                if (n <= 0) break
                md.update(buffer, 0, n)
            }
        }
        return md.digest()
    }

    private fun uniqueName(dir: DocumentFile, original: String): String {
        val dot = original.lastIndexOf('.')
        val base = if (dot > 0) original.substring(0, dot) else original
        val ext = if (dot > 0) original.substring(dot) else ""
        var i = 1
        while (dir.findFile("$base ($i)$ext") != null) i++
        return "$base ($i)$ext"
    }

    private fun mimeFor(file: File): String = when (file.extension.lowercase()) {
        "jpg", "jpeg" -> "image/jpeg"
        "png" -> "image/png"
        "webp" -> "image/webp"
        "mp4" -> "video/mp4"
        "mkv" -> "video/x-matroska"
        "mp3" -> "audio/mpeg"
        "pdf" -> "application/pdf"
        "apk" -> "application/vnd.android.package-archive"
        else -> "application/octet-stream"
    }
}
