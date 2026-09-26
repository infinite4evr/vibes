package app.lumaclean.data

import app.lumaclean.core.Progress
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File
import java.io.FileInputStream
import java.io.RandomAccessFile
import java.security.MessageDigest

data class DupFile(val path: String, val size: Long, val modified: Long) {
    val name: String get() = path.substringAfterLast('/')
}

data class DupGroup(val key: String, val size: Long, val files: List<DupFile>) {
    val reclaimable: Long get() = size * (files.size - 1)
    val category: FileCategory get() = FileTypes.category(files.first().name)
}

enum class KeepRule(val label: String) {
    OLDEST("Keep oldest"),
    NEWEST("Keep newest"),
    SHORTEST_PATH("Keep in main folder"),
}

class DuplicateEngine(
    private val index: FileIndexRepository,
    private val exclusions: ExclusionStore,
) {
    /**
     * Same size → same first and last 64 KB → same full SHA-256. Only the last, expensive
     * step reads whole files, and only for the few candidates that survive the first two.
     */
    suspend fun scan(progress: Progress, minSize: Long = 4 * 1024): List<DupGroup> {
        val ctx = currentCoroutineContext()
        val idx = index.get(progress.slice(0f, 0.4f), maxAgeMs = 60_000)
        val bySize = HashMap<Long, MutableList<FileEntry>>()
        idx.files.forEach { f ->
            if (f.size >= minSize && !f.isHidden && !exclusions.isExcluded(f.path)) {
                bySize.getOrPut(f.size) { mutableListOf() } += f
            }
        }
        val sameSize = bySize.values.filter { it.size > 1 }
        val candidates = sameSize.sumOf { it.size }

        var checked = 0
        val partial = ArrayList<List<FileEntry>>()
        for (group in sameSize) {
            val byHead = HashMap<String, MutableList<FileEntry>>()
            for (f in group) {
                ctx.ensureActive()
                checked++
                progress.report(0.4f + 0.3f * checked / candidates.coerceAtLeast(1), "Comparing ${checked.formatCount()} of ${candidates.formatCount()} files")
                edgeHash(f)?.let { byHead.getOrPut(it) { mutableListOf() } += f }
            }
            byHead.values.filter { it.size > 1 }.forEach { partial += it }
        }

        val fullBytes = partial.sumOf { g -> if (g[0].size > EDGE * 2) g[0].size * g.size else 0L }.coerceAtLeast(1)
        var read = 0L
        val groups = ArrayList<DupGroup>()
        for (group in partial) {
            val size = group[0].size
            if (size <= EDGE * 2) {
                // the edge hash already covered every byte
                groups += makeGroup("e${size}_${group[0].path.hashCode()}", size, group)
                continue
            }
            val byFull = HashMap<String, MutableList<FileEntry>>()
            for (f in group) {
                ctx.ensureActive()
                progress.report(0.7f + 0.3f * read / fullBytes, "Verifying · ${read.formatBytes()} of ${fullBytes.formatBytes()}")
                fullHash(f)?.let { byFull.getOrPut(it) { mutableListOf() } += f }
                read += size
            }
            byFull.forEach { (hash, files) -> if (files.size > 1) groups += makeGroup(hash, size, files) }
        }
        return groups.sortedByDescending { it.reclaimable }
    }

    private fun makeGroup(key: String, size: Long, files: List<FileEntry>) =
        DupGroup(key, size, files.map { DupFile(it.path, it.size, it.modified) }.sortedBy { it.modified })

    private fun edgeHash(f: FileEntry): String? = runCatching {
        val md = MessageDigest.getInstance("MD5")
        RandomAccessFile(File(f.path), "r").use { raf ->
            val len = raf.length()
            val buf = ByteArray(EDGE.toInt())
            val head = raf.read(buf).coerceAtLeast(0)
            md.update(buf, 0, head)
            if (len > EDGE * 2) {
                raf.seek(len - EDGE)
                val tail = raf.read(buf).coerceAtLeast(0)
                md.update(buf, 0, tail)
            }
        }
        md.digest().toHex()
    }.getOrNull()

    private suspend fun fullHash(f: FileEntry): String? {
        val ctx = currentCoroutineContext()
        return runCatching {
            val md = MessageDigest.getInstance("SHA-256")
            FileInputStream(f.path).use { input ->
                val buf = ByteArray(512 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    md.update(buf, 0, n)
                    ctx.ensureActive()
                }
            }
            md.digest().toHex()
        }.getOrNull()
    }

    companion object {
        private const val EDGE = 64L * 1024

        /** The files to delete so that exactly one copy per group stays. */
        fun selectionFor(groups: List<DupGroup>, rule: KeepRule): Set<String> =
            groups.flatMap { g -> g.files.filter { it != keeper(g, rule) }.map { it.path } }.toSet()

        fun keeper(group: DupGroup, rule: KeepRule): DupFile = when (rule) {
            KeepRule.OLDEST -> group.files.minBy { it.modified }
            KeepRule.NEWEST -> group.files.maxBy { it.modified }
            KeepRule.SHORTEST_PATH -> group.files.minWith(compareBy<DupFile>({ it.path.count { c -> c == '/' } }, { it.path.length }))
        }
    }
}

private fun ByteArray.toHex(): String {
    val chars = "0123456789abcdef"
    val sb = StringBuilder(size * 2)
    for (b in this) {
        val v = b.toInt() and 0xff
        sb.append(chars[v shr 4]).append(chars[v and 0xf])
    }
    return sb.toString()
}
