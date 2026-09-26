package com.example.lumaclean.data

import android.content.Context
import android.os.Build
import android.os.Environment
import com.example.lumaclean.model.CleanCandidate
import com.example.lumaclean.model.JunkKind
import com.example.lumaclean.model.RiskLevel
import java.io.File
import java.util.ArrayDeque

class JunkScanner(private val context: Context) {
    private val now get() = System.currentTimeMillis()
    private val day = 24L * 60 * 60 * 1000

    fun scan(maxEntries: Int = 120_000): List<CleanCandidate> {
        val out = LinkedHashMap<String, CleanCandidate>()
        scanOwnCache(out)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
            return out.values.sortedByDescending { it.sizeBytes }
        }

        val root = Environment.getExternalStorageDirectory()
        val queue = ArrayDeque<File>()
        queue.add(root)
        var visited = 0

        while (queue.isNotEmpty() && visited < maxEntries) {
            val dir = queue.removeFirst()
            val children = runCatching { dir.listFiles()?.toList().orEmpty() }.getOrDefault(emptyList())
            if (children.isEmpty() && dir != root && isReviewableEmptyDir(dir)) {
                put(out, dir, JunkKind.EMPTY_FOLDER, RiskLevel.REVIEW, 0)
            }
            for (file in children) {
                visited++
                if (visited >= maxEntries) break
                if (shouldSkip(file)) continue
                if (file.isDirectory) {
                    queue.add(file)
                    continue
                }
                classify(file)?.let { (kind, risk) ->
                    put(out, file, kind, risk, file.length())
                }
            }
        }
        return out.values.sortedByDescending { it.sizeBytes }
    }

    fun delete(items: Collection<CleanCandidate>): Pair<Int, Long> {
        var count = 0
        var bytes = 0L
        items.forEach { item ->
            val file = File(item.path)
            val existed = file.exists()
            val ok = runCatching {
                if (item.isDirectory) file.deleteRecursively() else file.delete()
            }.getOrDefault(false)
            if (existed && ok) {
                count++
                bytes += item.sizeBytes
            }
        }
        return count to bytes
    }

    private fun scanOwnCache(out: MutableMap<String, CleanCandidate>) {
        listOfNotNull(context.cacheDir, context.externalCacheDir).forEach { cache ->
            cache.walkTopDown().filter { it.isFile }.forEach { file ->
                put(out, file, JunkKind.APP_CACHE, RiskLevel.SAFE, file.length())
            }
        }
    }

    private fun classify(file: File): Pair<JunkKind, RiskLevel>? {
        val n = file.name.lowercase()
        val p = file.absolutePath.lowercase()
        val age = now - file.lastModified()
        return when {
            "/.thumbnails/" in p || p.endsWith("/.thumbnails") -> JunkKind.THUMBNAIL to RiskLevel.SAFE
            n.endsWith(".tmp") || n.endsWith(".temp") || n.endsWith(".bak~") -> JunkKind.TEMP_FILE to RiskLevel.REVIEW
            n.endsWith(".apk") && age > 30 * day -> JunkKind.OLD_APK to RiskLevel.REVIEW
            n.endsWith(".log") && age > 14 * day && file.length() < 100L * 1024 * 1024 -> JunkKind.LOG_FILE to RiskLevel.REVIEW
            file.length() == 0L && age > 7 * day && !isProtectedZeroByte(file) -> JunkKind.ZERO_BYTE to RiskLevel.REVIEW
            else -> null
        }
    }

    private fun shouldSkip(file: File): Boolean {
        val p = file.absolutePath.replace('\\', '/').lowercase()
        if (p.contains("/android/data") || p.contains("/android/obb")) return true
        if (file.name == ".nomedia") return true
        return false
    }

    private fun isReviewableEmptyDir(file: File): Boolean {
        val p = file.absolutePath.replace('\\', '/').lowercase()
        return !p.contains("/android/") && now - file.lastModified() > 30 * day
    }

    private fun isProtectedZeroByte(file: File): Boolean {
        val n = file.name.lowercase()
        return n == ".nomedia" || n == ".keep" || n == ".gitkeep"
    }

    private fun put(
        out: MutableMap<String, CleanCandidate>,
        file: File,
        kind: JunkKind,
        risk: RiskLevel,
        size: Long
    ) {
        out[file.absolutePath] = CleanCandidate(
            path = file.absolutePath,
            name = file.name.ifBlank { file.absolutePath },
            sizeBytes = size,
            kind = kind,
            risk = risk,
            lastModified = file.lastModified(),
            isDirectory = file.isDirectory
        )
    }
}
