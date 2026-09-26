package app.lumaclean.data

import android.os.Environment
import android.webkit.MimeTypeMap
import app.lumaclean.core.Progress
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File
import java.util.ArrayDeque

enum class FileCategory(val label: String) {
    IMAGES("Images"),
    VIDEOS("Videos"),
    AUDIO("Audio"),
    DOCUMENTS("Documents"),
    APKS("Installers"),
    ARCHIVES("Archives"),
    OTHER("Other"),
}

object FileTypes {
    private val categories: Map<String, FileCategory> = buildMap {
        listOf("jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "dng", "raw", "avif", "svg", "tif", "tiff")
            .forEach { put(it, FileCategory.IMAGES) }
        listOf("mp4", "mkv", "mov", "avi", "webm", "3gp", "m4v", "flv", "wmv", "ts", "mpeg", "mpg")
            .forEach { put(it, FileCategory.VIDEOS) }
        listOf("mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "amr", "wma", "mid", "midi", "m4b", "3ga")
            .forEach { put(it, FileCategory.AUDIO) }
        listOf(
            "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "rtf", "odt", "ods", "odp", "csv",
            "epub", "md", "html", "htm", "json", "xml", "pages", "numbers", "key", "vcf",
        ).forEach { put(it, FileCategory.DOCUMENTS) }
        listOf("apk", "apks", "xapk", "apkm").forEach { put(it, FileCategory.APKS) }
        listOf("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst").forEach { put(it, FileCategory.ARCHIVES) }
    }

    fun extension(name: String): String {
        val dot = name.lastIndexOf('.')
        return if (dot <= 0 || dot == name.lastIndex) "" else name.substring(dot + 1).lowercase()
    }

    fun category(name: String): FileCategory = categories[extension(name)] ?: FileCategory.OTHER

    fun mime(name: String): String {
        val ext = extension(name)
        if (ext == "apk") return "application/vnd.android.package-archive"
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "*/*"
    }

    fun isVisualMedia(name: String) = category(name).let { it == FileCategory.IMAGES || it == FileCategory.VIDEOS }
}

class FileEntry(val path: String, val size: Long, val modified: Long, val category: FileCategory) {
    val name: String get() = path.substring(path.lastIndexOf('/') + 1)
    val parent: String get() = path.substring(0, path.lastIndexOf('/').coerceAtLeast(0))
    val isHidden: Boolean get() = path.contains("/.")
}

/** One walk of shared storage, reused by every file feature until something changes. */
class FileIndex(
    val root: String,
    val files: List<FileEntry>,
    val dirSizes: Map<String, Long>,
    val dirCounts: Map<String, Int>,
    val allDirs: List<String>,
    val builtAt: Long,
    val truncated: Boolean,
) {
    val totalBytes: Long = files.sumOf { it.size }

    val categoryBytes: Map<FileCategory, Long> by lazy {
        val m = HashMap<FileCategory, Long>()
        files.forEach { m[it.category] = (m[it.category] ?: 0L) + it.size }
        m
    }

    val categoryCounts: Map<FileCategory, Int> by lazy {
        val m = HashMap<FileCategory, Int>()
        files.forEach { m[it.category] = (m[it.category] ?: 0) + 1 }
        m
    }

    fun sizeOf(path: String): Long? = dirSizes[path]

    /** Folders with no files anywhere below them, reported at the top-most empty level only. */
    val emptyDirs: List<String> by lazy {
        val empty = allDirs.filter { (dirCounts[it] ?: 0) == 0 && it != root }.toHashSet()
        empty.filter { dir -> dir.substring(0, dir.lastIndexOf('/')) !in empty }
    }

    /** The index minus deleted or moved paths (files, or folders with everything under them). */
    fun without(removed: Collection<String>): FileIndex {
        if (removed.isEmpty()) return this
        val gone = removed.toHashSet()
        fun isGone(path: String): Boolean {
            var p = path
            while (p.length > root.length) {
                if (p in gone) return true
                val cut = p.lastIndexOf('/')
                if (cut <= 0) break
                p = p.substring(0, cut)
            }
            return false
        }
        val sizes = HashMap(dirSizes)
        val counts = HashMap(dirCounts)
        val kept = ArrayList<FileEntry>(files.size)
        for (f in files) {
            if (isGone(f.path)) {
                var p = f.parent
                while (p.length >= root.length) {
                    sizes[p]?.let { sizes[p] = it - f.size }
                    counts[p]?.let { counts[p] = it - 1 }
                    if (p == root) break
                    p = p.substring(0, p.lastIndexOf('/'))
                }
            } else kept += f
        }
        val dirs = allDirs.filterNot { isGone(it) }
        return FileIndex(root, kept, sizes.filterKeys { !isGone(it) }, counts.filterKeys { !isGone(it) }, dirs, builtAt, truncated)
    }
}

class FileIndexRepository {
    private val mutex = Mutex()
    private val _current = MutableStateFlow<FileIndex?>(null)
    val current: StateFlow<FileIndex?> = _current.asStateFlow()

    @Volatile
    private var stale = false

    val root: String get() = Environment.getExternalStorageDirectory().absolutePath

    /** Our own recycle bin folder; kept out of the index so it never shows up as junk or files. */
    val binDirName = ".LumaClean-Bin"

    suspend fun get(progress: Progress = Progress.None, maxAgeMs: Long = 10 * 60_000L): FileIndex = mutex.withLock {
        val cached = _current.value
        if (cached != null && !stale && System.currentTimeMillis() - cached.builtAt < maxAgeMs) return cached
        val built = build(progress)
        stale = false
        _current.value = built
        built
    }

    /** Next [get] rebuilds; the current index stays visible meanwhile. */
    fun invalidate() {
        stale = true
    }

    fun removePaths(paths: Collection<String>) {
        _current.value?.let { _current.value = it.without(paths) }
    }

    private suspend fun build(progress: Progress): FileIndex {
        val rootDir = Environment.getExternalStorageDirectory()
        val root = rootDir.absolutePath
        val skip = setOf("$root/Android/data", "$root/Android/obb", "$root/$binDirName")
        val files = ArrayList<FileEntry>(32_768)
        val dirs = ArrayList<String>(4096)
        val stack = ArrayDeque<File>()
        stack.push(rootDir)
        var bytes = 0L
        var truncated = false
        val limit = 600_000
        val ctx = currentCoroutineContext()

        while (stack.isNotEmpty()) {
            val dir = stack.pop()
            dirs += dir.absolutePath
            val children = dir.listFiles() ?: continue
            for (child in children) {
                val path = child.absolutePath
                if (child.isDirectory) {
                    if (path !in skip) stack.push(child)
                } else {
                    val size = child.length()
                    files += FileEntry(path, size, child.lastModified(), FileTypes.category(child.name))
                    bytes += size
                }
            }
            if (files.size >= limit) {
                truncated = true
                break
            }
            if (dirs.size % 64 == 0) {
                ctx.ensureActive()
                progress.report(null, "Scanning storage · ${files.size.formatCount()} files · ${bytes.formatBytes()}")
            }
        }
        progress.report(null, "Summing folder sizes…", force = true)

        val sizes = HashMap<String, Long>(dirs.size * 2)
        val counts = HashMap<String, Int>(dirs.size * 2)
        dirs.forEach { sizes[it] = 0L; counts[it] = 0 }
        for (f in files) {
            var p = f.parent
            while (true) {
                sizes[p] = (sizes[p] ?: 0L) + f.size
                counts[p] = (counts[p] ?: 0) + 1
                if (p.length <= root.length) break
                val cut = p.lastIndexOf('/')
                if (cut <= 0) break
                p = p.substring(0, cut)
            }
        }
        return FileIndex(root, files, sizes, counts, dirs, System.currentTimeMillis(), truncated)
    }
}
