package app.tgdrive.ui.browse

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.tgdrive.data.AppState
import app.tgdrive.data.ApiException
import app.tgdrive.data.FileItem
import app.tgdrive.data.FileRef
import app.tgdrive.data.FileStats
import app.tgdrive.data.Folder
import app.tgdrive.data.str
import app.tgdrive.ui.nav.View
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

val SORTS = listOf(
    "relevance:desc" to "Best match", "date:desc" to "Newest first", "date:asc" to "Oldest first",
    "name:asc" to "Name, A to Z", "name:desc" to "Name, Z to A", "size:desc" to "Largest first",
    "size:asc" to "Smallest first", "chat:asc" to "By chat", "duration:desc" to "Longest first",
    "type:asc" to "By type", "ext:asc" to "By extension",
)

/**
 * One file list (a folder, a chat, a search …): its parameters, the pages loaded so far, the
 * counts per type and the selection. The same rules as the desktop's files.js (viewParams,
 * listParams, keyset paging).
 */
@Stable
class BrowseModel(val state: AppState, val view: View, private val scope: CoroutineScope) {
    var kind by mutableStateOf("")
    var sort by mutableStateOf(if (view is View.Search) "relevance" else "date")
    var order by mutableStateOf("desc")
    private var userSorted = false
    /** Filter-panel parameters (the desktop's S.adv): exts, size_min, date_from, chat_kinds … */
    var adv by mutableStateOf<Map<String, String>>(emptyMap())

    val items = mutableStateListOf<FileItem>()
    var next by mutableStateOf<String?>(null)
    var loading by mutableStateOf(false)
    var loadingMore by mutableStateOf(false)
    var loaded by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var moreError by mutableStateOf<String?>(null)
    var stats by mutableStateOf<FileStats?>(null)
    var corrected by mutableStateOf<String?>(null)
    var words by mutableStateOf<List<String>>(emptyList())
    var tookMs by mutableStateOf<Long?>(null)
    var effectiveSort by mutableStateOf(sort)

    /** Selected files by key (long-press or tap while selecting). */
    val selected = mutableStateMapOf<String, FileItem>()
    val selecting: Boolean get() = selected.isNotEmpty()

    private var job: Job? = null
    private var statsJob: Job? = null
    private var gen = 0

    val aid: Long get() = state.aid.value

    val isTextSearch: Boolean get() = viewParams()?.containsKey("q") == true
    val smartFolder: Folder? get() = (view as? View.Drive)?.folderId?.let { id -> state.folders.value.folders.firstOrNull { it.id == id } }?.takeIf { it.smart }

    fun viewParams(): Map<String, String>? {
        val p = LinkedHashMap<String, String>()
        when (val v = view) {
            is View.Drive -> {
                val fo = v.folderId?.let { id -> state.folders.value.folders.firstOrNull { it.id == id } }
                val rules = if (fo?.smart == true) fo.rules as? JsonObject else null
                when {
                    rules != null -> {
                        (rules["params"] as? JsonObject)?.forEach { (k, value) -> (value as? JsonPrimitive)?.contentOrNull?.let { p[k] = it } }
                        rules.str("q")?.takeIf { it.isNotBlank() }?.let { p["q"] = it }
                    }
                    v.folderId != null -> p["folder_id"] = v.folderId
                    else -> {
                        val ch = state.folders.value.drive.channelId ?: return null
                        p["chat_ids"] = ch.toString()
                        p["filed"] = "0"
                    }
                }
            }
            View.All -> {}
            View.Starred -> p["starred"] = "1"
            View.Recent -> p["recent"] = "1"
            View.Continue -> p["in_progress"] = "1"
            is View.Chat -> { p["chat_ids"] = v.chatId.toString(); v.topicId?.let { p["topic_id"] = it.toString() } }
            is View.TgFolder -> p["dialog_filter"] = v.filterId.toString()
            is View.TagView -> p["tag"] = v.tag
            is View.SubjectView -> p["subject"] = v.subject
            is View.Album -> { p["chat_ids"] = v.chatId.toString(); p["grouped_id"] = v.groupedId.toString() }
            is View.Saved -> {
                val s = state.folders.value.saved.firstOrNull { it.id == v.savedId } ?: return null
                s.params.forEach { (k, value) -> (value as? JsonPrimitive)?.contentOrNull?.let { p[k] = it } }
                if (s.q.isNotBlank()) p["q"] = s.q
            }
            is View.Search -> {
                if (v.q.isNotBlank()) p["q"] = v.q
                v.scope?.let { p.putAll(it.params) }
            }
        }
        return p
    }

    fun params(extra: Map<String, String> = emptyMap(), withKind: Boolean = true): Map<String, String>? {
        val base = viewParams() ?: return null
        val p = LinkedHashMap(base)
        p.putAll(adv)
        p["sort"] = when {
            view == View.Recent && sort == "date" && !userSorted -> "recent"
            view == View.Continue && sort == "date" && !userSorted -> "played"
            sort == "relevance" && !p.containsKey("q") -> "date"
            else -> sort
        }
        p["order"] = order
        if (withKind && kind.isNotEmpty()) p["kinds"] = kind
        if (view !is View.Album) p["copies"] = if (state.setting("hide_duplicates") == "false") "show" else "hide"
        p.putAll(extra)
        return p
    }

    fun setSort(value: String) {
        val (s, o) = value.split(":")
        sort = s
        order = o
        userSorted = true
        reload()
    }

    fun setKindFilter(k: String) {
        if (kind == k) return
        kind = k
        reload(keepStats = true)
    }

    fun setFilters(p: Map<String, String>) {
        adv = p.filterValues { it.isNotBlank() }
        reload()
    }

    fun reload(keepStats: Boolean = false) {
        job?.cancel()
        val my = ++gen
        next = null
        error = null
        moreError = null
        loading = true
        val p = params(mapOf("limit" to PAGE.toString()))
        if (p == null) {
            items.clear(); loading = false; loaded = true
            return
        }
        job = scope.launch {
            try {
                val page = state.api.files(aid, p)
                if (my != gen) return@launch
                items.clear()
                items.addAll(page.items)
                next = page.next
                corrected = page.corrected
                words = page.words
                tookMs = page.tookMs
                effectiveSort = page.sort ?: sort
                loaded = true
            } catch (e: ApiException) {
                if (my != gen) return@launch
                if (e.locked) state.onLocked()
                if (e.status != 408 || !e.message.orEmpty().contains("Superseded")) error = e.message
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                if (my == gen) error = e.message ?: "TG Drive isn't responding."
            } finally {
                if (my == gen) loading = false
            }
        }
        if (!keepStats || stats == null) loadStats()
    }

    fun loadMore() {
        val cursor = next ?: return
        if (loadingMore || loading) return
        val my = gen
        loadingMore = true
        moreError = null
        val p = params(mapOf("limit" to PAGE.toString(), "cursor" to cursor)) ?: return
        scope.launch {
            try {
                val page = state.api.files(aid, p)
                if (my != gen) return@launch
                val have = items.mapTo(HashSet()) { it.key }
                items.addAll(page.items.filter { it.key !in have })
                next = page.next
            } catch (e: Exception) {
                if (my == gen) moreError = e.message ?: "Couldn't load more files."
            } finally {
                if (my == gen) loadingMore = false
            }
        }
    }

    private fun loadStats() {
        statsJob?.cancel()
        val p = params(withKind = false) ?: return
        statsJob = scope.launch {
            try {
                stats = state.api.stats(aid, p - "sort" - "order")
            } catch (_: Exception) {
            }
        }
    }

    /** Apply a change to files in place (star, tags, rename …) without reloading. */
    fun update(refs: Collection<FileRef>, change: (FileItem) -> FileItem) {
        val keys = refs.mapTo(HashSet()) { "${it.chatId}:${it.msgId}" }
        for (i in items.indices) if (items[i].key in keys) items[i] = change(items[i])
        for (k in selected.keys.toList()) if (k in keys) selected[k] = change(selected[k]!!)
    }

    fun remove(refs: Collection<FileRef>) {
        val keys = refs.mapTo(HashSet()) { "${it.chatId}:${it.msgId}" }
        items.removeAll { it.key in keys }
        keys.forEach { selected.remove(it) }
    }

    fun toggle(f: FileItem) {
        if (selected.containsKey(f.key)) selected.remove(f.key) else selected[f.key] = f
    }

    fun selectAll() {
        items.forEach { selected[it.key] = it }
    }

    fun clearSelection() = selected.clear()

    companion object {
        const val PAGE = 90
    }
}

/** Human title of a view (header and back stack). */
fun viewTitle(state: AppState, v: View): String = when (v) {
    is View.Drive -> v.folderId?.let { id -> state.folders.value.folders.firstOrNull { it.id == id }?.name } ?: "My Drive"
    View.All -> "All files"
    View.Starred -> "Starred"
    View.Recent -> "Recent"
    View.Continue -> "Continue watching"
    is View.Chat -> state.chats.value.firstOrNull { it.id == v.chatId }?.title ?: "Chat"
    is View.TgFolder -> state.dialogFilters.value.firstOrNull { it.id == v.filterId }?.title ?: "Telegram folder"
    is View.Saved -> state.folders.value.saved.firstOrNull { it.id == v.savedId }?.name ?: "Saved search"
    is View.TagView -> "#${v.tag}"
    is View.SubjectView -> state.subjects.value.firstOrNull { it.id == v.subject }?.let { "${it.emoji ?: ""} ${it.name}".trim() } ?: v.subject
    is View.Album -> "Album"
    is View.Search -> if (v.q.isBlank()) "Search" else "“${v.q}”"
}
