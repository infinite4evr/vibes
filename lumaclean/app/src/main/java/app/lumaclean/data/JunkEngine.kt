package app.lumaclean.data

import android.app.usage.StorageStatsManager
import android.content.Context
import android.os.Build
import android.os.Process
import app.lumaclean.core.DAY_MS
import app.lumaclean.core.Perms
import app.lumaclean.core.Progress
import app.lumaclean.core.formatDate
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File

enum class JunkKind(val label: String, val description: String) {
    APP_CACHE("LumaClean cache", "Temporary files this app made"),
    THUMBNAILS("Thumbnail caches", "Preview images apps rebuild when needed"),
    TEMP("Temporary files", "Leftover .tmp files and unfinished downloads"),
    LOGS("Old log files", "Diagnostic logs older than a week"),
    APKS("Installer files", "APKs for apps you already have or have used"),
    LEFTOVERS("Leftovers of removed apps", "Media folders of apps no longer installed"),
    EMPTY_FOLDERS("Empty folders", "Folders with nothing inside"),
    EMPTY_FILES("Empty files", "Files with no content, older than a week"),
    DELETED_MEDIA("Gallery trash", "Photos and videos already in the system trash"),
    OLD_DOWNLOADS("Old downloads", "Downloads you haven't touched in a while"),
}

data class JunkItem(
    val path: String,
    val size: Long,
    val modified: Long,
    val isDir: Boolean,
    val safe: Boolean,
    val note: String? = null,
) {
    val name: String get() = path.substringAfterLast('/')
}

data class JunkGroup(val kind: JunkKind, val items: List<JunkItem>) {
    val bytes: Long get() = items.sumOf { it.size }
}

data class JunkReport(
    val groups: List<JunkGroup>,
    /** Cache held by other apps, which only Android's own "clear caches" screen can remove. */
    val otherAppsCache: Long?,
    val scannedFiles: Int,
    val finishedAt: Long,
    val limited: Boolean,
) {
    val totalBytes: Long get() = groups.sumOf { it.bytes }
    val safeBytes: Long get() = groups.sumOf { g -> g.items.filter { it.safe }.sumOf { it.size } }
    val defaultSelection: Set<String> get() = groups.flatMap { g -> g.items.filter { it.safe }.map { it.path } }.toSet()

    fun without(paths: Set<String>): JunkReport =
        copy(groups = groups.map { g -> g.copy(items = g.items.filterNot { it.path in paths }) }.filter { it.items.isNotEmpty() })
}

class JunkEngine(
    private val context: Context,
    private val index: FileIndexRepository,
    private val exclusions: ExclusionStore,
    private val settings: SettingsRepository,
    private val storage: StorageRepository,
) {
    private val standardFolders = setOf(
        "DCIM", "Pictures", "Download", "Downloads", "Music", "Movies", "Documents", "Alarms", "Notifications",
        "Podcasts", "Ringtones", "Audiobooks", "Recordings", "Android", "Screenshots",
    )
    private val keepFiles = setOf(".keep", ".gitkeep", ".nomedia", ".ds_store")
    private val rotatedLog = Regex(".*\\.log\\.\\d+$")

    suspend fun scan(progress: Progress): JunkReport {
        val ctx = currentCoroutineContext()
        val out = LinkedHashMap<JunkKind, MutableList<JunkItem>>()
        fun add(kind: JunkKind, item: JunkItem) {
            if (!exclusions.isExcluded(item.path)) out.getOrPut(kind) { mutableListOf() } += item
        }

        // our own cache is always safe to clear, with or without file access
        listOfNotNull(context.cacheDir, context.externalCacheDir).forEach { dir ->
            dir.listFiles()?.forEach { f ->
                val size = if (f.isDirectory) f.walkTopDown().filter { it.isFile }.sumOf { it.length() } else f.length()
                if (size > 0) add(JunkKind.APP_CACHE, JunkItem(f.absolutePath, size, f.lastModified(), f.isDirectory, true))
            }
        }

        var scanned = 0
        var limited = true
        if (Perms.hasAllFiles(context)) {
            limited = false
            val idx = index.get(progress.slice(0f, 0.75f), maxAgeMs = 60_000)
            scanned = idx.files.size
            val now = System.currentTimeMillis()
            val installed = installedPackages()
            val oldDownloadCutoff = now - settings.current.oldDownloadDays * DAY_MS
            val download = "${idx.root}/Download/"
            val apkCandidates = ArrayList<FileEntry>()

            idx.files.forEachIndexed { i, f ->
                if (i % 2000 == 0) {
                    ctx.ensureActive()
                    progress.report(0.75f + 0.15f * i / idx.files.size.coerceAtLeast(1), "Looking for junk…")
                }
                val lower = f.path.lowercase()
                val name = f.name.lowercase()
                val age = now - f.modified
                when {
                    "/.thumbnails/" in lower || "/.thumbcache/" in lower ->
                        add(JunkKind.THUMBNAILS, JunkItem(f.path, f.size, f.modified, false, true))
                    name.startsWith(".trashed-") ->
                        add(JunkKind.DELETED_MEDIA, JunkItem(f.path, f.size, f.modified, false, false, "Will be deleted by the gallery later anyway"))
                    name.endsWith(".tmp") || name.endsWith(".temp") || name.startsWith("~$") ||
                        ((name.endsWith(".crdownload") || name.endsWith(".part") || name.endsWith(".partial")) && age > DAY_MS) ->
                        add(JunkKind.TEMP, JunkItem(f.path, f.size, f.modified, false, age > DAY_MS))
                    (name.endsWith(".log") || rotatedLog.matches(name)) && age > 7 * DAY_MS ->
                        add(JunkKind.LOGS, JunkItem(f.path, f.size, f.modified, false, true))
                    f.category == FileCategory.APKS -> { apkCandidates += f }
                    f.size == 0L && age > 7 * DAY_MS && !name.startsWith(".nomedia") && name !in keepFiles ->
                        add(JunkKind.EMPTY_FILES, JunkItem(f.path, 0, f.modified, false, false))
                    f.path.startsWith(download) && f.modified < oldDownloadCutoff ->
                        add(JunkKind.OLD_DOWNLOADS, JunkItem(f.path, f.size, f.modified, false, false, "Last changed ${f.modified.formatDate()}"))
                }
            }

            progress.report(0.9f, "Checking installer files…", force = true)
            val pm = context.packageManager
            apkCandidates.forEach { f ->
                ctx.ensureActive()
                @Suppress("DEPRECATION")
                val info = if (f.name.endsWith(".apk", true)) runCatching { pm.getPackageArchiveInfo(f.path, 0) }.getOrNull() else null
                val pkg = info?.packageName
                val installedVersion = pkg?.let { installed[it] }
                val archiveVersion = info?.let { if (Build.VERSION.SDK_INT >= 28) it.longVersionCode else @Suppress("DEPRECATION") it.versionCode.toLong() }
                val (safe, note) = when {
                    installedVersion != null && archiveVersion != null && archiveVersion <= installedVersion -> true to "Already installed"
                    installedVersion != null -> false to "Newer than the installed app"
                    else -> false to "Not installed"
                }
                add(JunkKind.APKS, JunkItem(f.path, f.size, f.modified, false, safe, note))
            }

            // Android/media/<package> folders of apps that are gone
            File(idx.root, "Android/media").listFiles()?.forEach { dir ->
                if (dir.isDirectory && dir.name.contains('.') && dir.name !in installed) {
                    val size = idx.sizeOf(dir.absolutePath) ?: 0L
                    add(JunkKind.LEFTOVERS, JunkItem(dir.absolutePath, size, dir.lastModified(), true, false, dir.name))
                }
            }

            idx.emptyDirs.forEach { dir ->
                val top = dir.removePrefix(idx.root + "/").substringBefore('/')
                val isStandardRoot = !dir.removePrefix(idx.root + "/").contains('/') && top in standardFolders
                if (!isStandardRoot && !dir.startsWith(idx.root + "/Android/") && !dir.contains("/.")) {
                    add(JunkKind.EMPTY_FOLDERS, JunkItem(dir, 0, File(dir).lastModified(), true, true))
                }
            }
        }

        progress.report(0.97f, "Measuring app caches…", force = true)
        val otherCache = if (Perms.hasUsage(context)) otherAppsCache() else null

        val groups = JunkKind.entries.mapNotNull { kind ->
            out[kind]?.takeIf { it.isNotEmpty() }?.let { items -> JunkGroup(kind, items.sortedByDescending { it.size }) }
        }
        return JunkReport(groups, otherCache, scanned, System.currentTimeMillis(), limited)
    }

    fun otherAppsCache(): Long {
        val stats = context.getSystemService(StorageStatsManager::class.java)
        val pm = context.packageManager
        var total = 0L
        @Suppress("DEPRECATION")
        pm.getInstalledApplications(0).forEach { ai ->
            if (ai.packageName == context.packageName) return@forEach
            runCatching {
                total += stats.queryStatsForPackage(ai.storageUuid, ai.packageName, Process.myUserHandle()).cacheBytes
            }
        }
        return total
    }

    private fun installedPackages(): Map<String, Long> {
        @Suppress("DEPRECATION")
        return context.packageManager.getInstalledPackages(0).associate { p ->
            p.packageName to (if (Build.VERSION.SDK_INT >= 28) p.longVersionCode else @Suppress("DEPRECATION") p.versionCode.toLong())
        }
    }

    /** Deletes junk for good and returns the space actually freed (measured, not estimated). */
    suspend fun clean(items: List<JunkItem>, progress: Progress, files: FileOps): Pair<OpResult, Long> {
        val before = storage.freeBytes()
        val result = files.remove(items.map { it.path }, toBin = false, progress = progress)
        progress.report(1f, "Finishing up…", force = true)
        val after = storage.freeBytes()
        val measured = (after - before).coerceAtLeast(0)
        // the file system may report freed space lazily; fall back to what we removed
        val freed = if (measured > 0) measured else result.bytes
        return result to freed
    }
}
