package com.example.lumaclean.data

import android.os.Build
import android.os.Environment
import com.example.lumaclean.model.DuplicateFile
import com.example.lumaclean.model.DuplicateGroup
import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest
import java.util.ArrayDeque

class DuplicateScanner {
    fun scan(maxEntries: Int = 100_000): List<DuplicateGroup> {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
            return emptyList()
        }

        val root = Environment.getExternalStorageDirectory()
        val bySize = HashMap<Long, MutableList<File>>()
        val queue = ArrayDeque<File>()
        queue.add(root)
        var visited = 0

        while (queue.isNotEmpty() && visited < maxEntries) {
            val dir = queue.removeFirst()
            val children = runCatching { dir.listFiles()?.toList().orEmpty() }.getOrDefault(emptyList())
            for (f in children) {
                visited++
                if (visited >= maxEntries) break
                val p = f.absolutePath.lowercase()
                if (p.contains("/android/data") || p.contains("/android/obb")) continue
                if (f.isDirectory) queue.add(f)
                else if (f.length() > 0L) bySize.getOrPut(f.length()) { mutableListOf() }.add(f)
            }
        }

        val groups = mutableListOf<DuplicateGroup>()
        bySize.values.asSequence()
            .filter { it.size > 1 }
            .forEach { sameSize ->
                val byHash = HashMap<String, MutableList<File>>()
                sameSize.forEach { f ->
                    hash(f)?.let { digest -> byHash.getOrPut(digest) { mutableListOf() }.add(f) }
                }
                byHash.filterValues { it.size > 1 }.forEach { (digest, files) ->
                    val items = files.sortedByDescending { it.lastModified() }.map {
                        DuplicateFile(it.absolutePath, it.name, it.length(), it.lastModified())
                    }
                    groups += DuplicateGroup(digest, items)
                }
            }
        return groups.sortedByDescending { it.reclaimableBytes }
    }

    fun deleteExtras(groups: Collection<DuplicateGroup>): Pair<Int, Long> {
        var deleted = 0
        var bytes = 0L
        groups.forEach { group ->
            group.files.drop(1).forEach { item ->
                val file = File(item.path)
                if (runCatching { file.delete() }.getOrDefault(false)) {
                    deleted++
                    bytes += item.sizeBytes
                }
            }
        }
        return deleted to bytes
    }

    private fun hash(file: File): String? = runCatching {
        val md = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val n = input.read(buffer)
                if (n <= 0) break
                md.update(buffer, 0, n)
            }
        }
        md.digest().joinToString("") { "%02x".format(it) }
    }.getOrNull()
}
