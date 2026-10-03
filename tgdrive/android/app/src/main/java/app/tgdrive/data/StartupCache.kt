package app.tgdrive.data

import android.content.Context
import app.tgdrive.diag.AppLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import java.io.File

/**
 * What the main screen showed last time (status, folders, chats, tags and the first page of the
 * last few lists), kept on this phone so the app opens straight onto it, like Gmail does, while
 * TG Drive's service starts in the background (that takes seconds: a Python process and Telegram).
 * Once the service answers, everything is loaded again and replaces this.
 *
 * Never kept while an app passcode is set: the files must not show before it is entered.
 */
class StartupCache(context: Context, private val scope: CoroutineScope) {

    @Serializable
    data class Page(val items: List<FileItem> = emptyList(), val next: String? = null)

    @Serializable
    data class Snapshot(
        val demo: Boolean = false,
        val aid: Long = 0,
        val status: AppStatus = AppStatus(),
        val account: AccountStatus? = null,
        val folders: FoldersResponse = FoldersResponse(),
        val chats: List<Chat> = emptyList(),
        val filters: List<DialogFilter> = emptyList(),
        val tags: List<Tag> = emptyList(),
        val subjects: List<Subject> = emptyList(),
        /** First pages of the last lists opened, oldest first ([key] → page). */
        val pages: Map<String, Page> = emptyMap(),
    )

    private val file = File(app.tgdrive.storage.DataLocation.state(context), "startup-cache.json")
    private var saveJob: Job? = null
    private val diskLock = Any()
    @Volatile private var generation = 0L

    /** The snapshot as it stands (read from disk by [load], then kept current by [update]). */
    var snapshot: Snapshot? = null
        private set

    suspend fun load(): Snapshot? {
        val revision = generation
        val s = withContext(Dispatchers.IO) { synchronized(diskLock) {
            if (!file.exists()) return@synchronized null
            try {
                JsonCodec.decodeFromString(Snapshot.serializer(), file.readText())
            } catch (e: Exception) {
                AppLog.w("startup-cache", "couldn't read the saved screen", e)
                file.delete()
                null
            }
        } }
        // A clear or a newer snapshot must never be undone by an earlier disk read.
        if (revision != generation || snapshot != null) return null
        if (s?.status?.let { it.locked || it.lockSet } == true) { clear(); return null }
        snapshot = s
        return s
    }

    /** Change the snapshot (only once there is one: [start] begins it); saved a moment later. */
    fun update(change: (Snapshot) -> Snapshot) {
        val s = snapshot ?: return
        snapshot = change(s)
        save()
    }

    /** A fresh snapshot for [status]'s account; the old one is kept when it is for the same account and mode. */
    fun start(status: AppStatus, aid: Long, demo: Boolean) {
        if (status.lockSet || status.locked || !status.apiConfigured || status.accounts.none { it.id == aid }) { clear(); return }
        generation++
        val st = status.copy(mediaToken = "")
        val old = snapshot
        snapshot = if (old != null && old.aid == aid && old.demo == demo) old.copy(status = st) else Snapshot(demo, aid, st)
        save()
    }

    fun clear() {
        snapshot = null
        val revision = ++generation
        saveJob?.cancel()
        saveJob = null
        scope.launch(Dispatchers.IO) { synchronized(diskLock) {
            if (revision == generation) { file.delete(); File(file.parentFile, "${file.name}.tmp").delete() }
        } }
    }

    fun page(key: String): Page? = snapshot?.pages?.get(key)

    fun putPage(key: String, items: List<FileItem>, next: String?) = update { s ->
        val pages = LinkedHashMap(s.pages)
        pages.remove(key)
        pages[key] = Page(items, next)
        while (pages.size > MAX_PAGES) pages.remove(pages.keys.first())
        s.copy(pages = pages)
    }

    /** Written at most every couple of seconds, off the main thread, atomically. */
    private fun save() {
        if (saveJob?.isActive == true) return
        saveJob = scope.launch {
            delay(SAVE_AFTER_MS)
            val s = snapshot ?: return@launch
            val revision = generation
            withContext(Dispatchers.IO) {
                try {
                    val text = JsonCodec.encodeToString(Snapshot.serializer(), s)
                    synchronized(diskLock) {
                        if (revision == generation) {
                            val tmp = File(file.parentFile, "${file.name}.tmp")
                            tmp.writeText(text)
                            check(tmp.renameTo(file)) { "Could not commit startup cache" }
                        }
                    }
                } catch (e: Exception) {
                    AppLog.w("startup-cache", "couldn't save the screen", e)
                }
            }
        }
    }

    companion object {
        private const val MAX_PAGES = 4
        private const val SAVE_AFTER_MS = 2000L

        /** The key of a list's first page: the account and its parameters, in a fixed order. */
        fun key(aid: Long, params: Map<String, String>): String =
            "$aid?" + params.filterKeys { it != "record" && it != "limit" }.toSortedMap().entries.joinToString("&") { "${java.net.URLEncoder.encode(it.key, "UTF-8")}=${java.net.URLEncoder.encode(it.value, "UTF-8")}" }
    }
}
