package app.tgdrive.ui.actions

import android.content.Context
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.tgdrive.data.AppState
import app.tgdrive.diag.AppLog
import app.tgdrive.data.FileItem
import app.tgdrive.data.Folder
import app.tgdrive.data.long
import app.tgdrive.data.str
import app.tgdrive.ui.browse.BrowseModel
import app.tgdrive.util.Format
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.jsonPrimitive

/** Dialogs and sheets over the main screen. */
sealed interface Overlay {
    data class FileMenu(val file: FileItem) : Overlay
    data class SelectionMenu(val files: List<FileItem>) : Overlay
    data class Move(val files: List<FileItem>, val copy: Boolean = false) : Overlay
    data class Tags(val files: List<FileItem>) : Overlay
    data class Rename(val file: FileItem) : Overlay
    data class BulkRename(val files: List<FileItem>) : Overlay
    data class Note(val file: FileItem, val note: String) : Overlay
    data class Delete(val files: List<FileItem>) : Overlay
    data class Send(val files: List<FileItem>) : Overlay
    data class SetSubject(val files: List<FileItem>) : Overlay
    data class FolderEdit(val folder: Folder?, val parentId: String?, val smart: Boolean = false) : Overlay
    data class FolderMenu(val folder: Folder) : Overlay
    data class FolderDelete(val folder: Folder) : Overlay
    data class FolderDownload(val folder: Folder) : Overlay
    data object NewMenu : Overlay
    data object AccountMenu : Overlay
    data class Sort(val model: BrowseModel) : Overlay
    data class Filters(val model: BrowseModel) : Overlay
    data class ViewOptions(val model: BrowseModel) : Overlay
    data class SaveSearch(val q: String, val params: Map<String, String>) : Overlay
    data class ListMenu(val model: BrowseModel) : Overlay
    data class Forget(val files: List<FileItem>) : Overlay
    data class FolderMove(val folder: Folder) : Overlay
    data class FolderRename(val folder: Folder) : Overlay
    data class ChatMenu(val chatId: Long) : Overlay
}

/**
 * What can be done to files and folders, as in the desktop's actions.js: each action tells what
 * happened, offers Undo where TG Drive can undo it, and updates the list on screen in place.
 */
@Stable
class Actions(val state: AppState, private val scope: CoroutineScope, private val ctx: Context) {
    var overlay by mutableStateOf<Overlay?>(null)
    /** The list on screen, updated in place after an action. */
    var model: BrowseModel? = null

    private val aid get() = state.aid.value
    private fun refs(files: Collection<FileItem>) = files.map { it.ref }

    fun open(o: Overlay) { overlay = o }
    fun close() { overlay = null }

    private fun act(done: String? = null, undo: Boolean = false, block: suspend () -> String?) {
        // Which action (for the log): the caller's name, e.g. "star" or "moveFolder".
        val name = Throwable().stackTrace.getOrNull(1)?.methodName?.substringBefore('$') ?: "action"
        AppLog.d("action", name)
        scope.launch {
            try {
                val msg = block() ?: done
                if (msg != null) {
                    if (undo) state.message(msg, action = "Undo", onAction = { undoLast() }) else state.message(msg)
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                state.failed(name, e)
            }
        }
    }

    fun undoLast() = act {
        val r = state.api.undo(aid)
        state.loadFolders()
        state.changed("undo")
        r.str("undone")?.let { "Undone: $it" } ?: "Nothing to undo."
    }

    // ------------------------------------------------------------------ files
    fun star(files: List<FileItem>, on: Boolean) = act(undo = true) {
        state.api.meta(aid, refs(files), starred = on)
        model?.update(refs(files)) { it.copy(starred = on) }
        state.loadFolders()
        if (on) "Starred ${label(files)}" else "Removed the star from ${label(files)}"
    }

    fun setTags(files: List<FileItem>, add: List<String>, remove: List<String>) = act(undo = true) {
        state.api.meta(aid, refs(files), tagsAdd = add.ifEmpty { null }, tagsRemove = remove.ifEmpty { null })
        model?.update(refs(files)) { f -> f.copy(tags = (f.tags + add).distinct() - remove.toSet()) }
        state.loadTags()
        "Tags saved"
    }

    fun saveNote(file: FileItem, note: String) = act {
        state.api.meta(aid, listOf(file.ref), note = note)
        model?.update(listOf(file.ref)) { it.copy(note = kotlinx.serialization.json.JsonPrimitive(note.isNotBlank())) }
        if (note.isBlank()) "Note removed" else "Note saved"
    }

    fun rename(file: FileItem, name: String) = act(undo = true) {
        state.api.rename(aid, file.ref, name)
        model?.update(listOf(file.ref)) { it.copy(name = name.ifBlank { it.originalName ?: it.name }, renamed = name.isNotBlank()) }
        if (name.isBlank()) "Back to the original name" else "Renamed to “$name”"
    }

    fun bulkRename(files: List<FileItem>, pattern: String, start: Int) = act(undo = true) {
        val r = state.api.bulkRename(aid, refs(files), pattern, start)
        state.changed("rename")
        "Renamed ${Format.plural(r.long("renamed"), "file")}"
    }

    fun move(files: List<FileItem>, folder: Folder?) = act(undo = true) {
        state.api.place(aid, refs(files), folder?.id)
        val here = (model?.view as? app.tgdrive.ui.nav.View.Drive)
        if (here != null && here.folderId != folder?.id) model?.remove(refs(files))
        else model?.update(refs(files)) { it.copy(folderId = folder?.id) }
        state.loadFolders()
        if (folder == null) "Moved ${label(files)} out of folders" else "Moved ${label(files)} to ${folder.name}"
    }

    fun copyToDrive(files: List<FileItem>, folder: Folder?) = act(undo = true) {
        val r = state.api.copyToDrive(aid, refs(files), folder?.id)
        state.loadFolders()
        state.changed("copy")
        val failed = (r["failed"] as? JsonArray)?.map { it.jsonPrimitive.content }.orEmpty()
        val copied = (r["copied"] as? JsonArray)?.size ?: 0
        when {
            failed.isEmpty() -> "Saved ${Format.plural(copied, "copy", "copies")} to ${folder?.name ?: state.folders.value.driveTitle}"
            copied == 0 -> throw IllegalStateException(failed.first())
            else -> "Saved $copied; ${failed.size} couldn't be copied: ${failed.first()}"
        }
    }

    fun deleteFromTelegram(files: List<FileItem>) = act {
        val r = state.api.deleteFiles(aid, refs(files))
        model?.remove(refs(files))
        state.loadFolders()
        val failed = (r["failed"] as? JsonArray)?.map { it.jsonPrimitive.content }.orEmpty()
        val n = r.long("deleted")
        if (failed.isEmpty()) "Deleted ${Format.plural(n, "file")} from Telegram"
        else "Deleted $n; couldn't delete in ${failed.joinToString()}"
    }

    fun forget(files: List<FileItem>) = act {
        state.api.forgetFiles(aid, refs(files))
        model?.remove(refs(files))
        "Removed ${label(files)} from TG Drive's index (Telegram is unchanged)"
    }

    fun pinOffline(files: List<FileItem>) = act {
        state.api.json("POST", "/api/a/$aid/offline", buildJsonObject {
            put("items", buildJsonArray { files.forEach { f -> add(buildJsonArray { add(JsonPrimitive(f.chatId)); add(JsonPrimitive(f.msgId)) }) } })
        })
        "Offline copies queued. See Offline & recovery."
    }
    fun pinFolderOffline(f: Folder) = act {
        state.api.json("POST", "/api/a/$aid/offline", buildJsonObject { put("folder_id", JsonPrimitive(f.id)) })
        "Folder pinned. New indexed files will download within your daily budget."
    }

    fun download(files: List<FileItem>, zip: Boolean = false) = act {
        state.api.download(aid, refs(files), zip = zip, keepStructure = zip, name = if (zip) "TG Drive files" else null)
        state.loadTransfers()
        if (zip) "Making a zip of ${label(files)}" else "Downloading ${label(files)}"
    }

    fun send(files: List<FileItem>, chatId: Long, forward: Boolean) = act {
        state.api.send(aid, refs(files), chatId, if (forward) "forward" else "copy")
        val title = state.chats.value.firstOrNull { it.id == chatId }?.title ?: "the chat"
        "Sent ${label(files)} to $title"
    }

    fun markWatched(files: List<FileItem>, done: Boolean) = act {
        for (f in files) state.api.savePlayback(aid, f.ref, if (done) (f.duration ?: 0.0) else 0.0, f.duration, done)
        model?.update(refs(files)) { it.copy(watched = done) }
        if (done) "Marked as watched" else "Marked as not watched"
    }

    fun setSubject(files: List<FileItem>, subject: String?) = act {
        state.api.setSubject(aid, refs(files), subject)
        model?.update(refs(files)) { it.copy(subject = subject) }
        state.loadSubjects()
        if (subject == null) "Subject cleared" else "Subject set"
    }

    fun copyLink(f: FileItem) {
        val link = f.link ?: return state.message("This file has no public link.", error = true)
        Platform.copy(ctx, "Telegram link", link)
        state.message("Link copied")
    }

    // ------------------------------------------------------------------ folders
    fun deleteFolder(f: Folder) = act(undo = true) {
        val r = state.api.deleteFolder(aid, f.id)
        state.loadFolders()
        state.changed("folders")
        val n = r.long("unfiled")
        "Deleted “${f.name}”" + if (n > 0) " (its ${Format.plural(n, "file")} are still in Telegram)" else ""
    }

    fun downloadFolder(f: Folder, zip: Boolean) = act {
        state.api.downloadFolder(aid, f.id, zip)
        state.loadTransfers()
        if (zip) "Making a zip of “${f.name}”" else "Downloading “${f.name}”"
    }

    fun applyRules(f: Folder) = act {
        val r = state.api.applyRules(aid, f.id)
        state.loadFolders()
        state.changed("rules")
        "Filed ${Format.plural(r.long("filed"), "file")} into “${f.name}”"
    }

    fun createFolder(name: String, parentId: String?, rules: JsonObject? = null, onCreated: ((String) -> Unit)? = null) = act(undo = true) {
        val f = state.api.createFolder(aid, name, parentId, rules = rules)
        state.loadFolders()
        onCreated?.invoke(f.id)
        when {
            rules == null -> "Created “$name”"
            rules.str("mode") == "smart" -> "Created smart folder “$name”"
            else -> "Created “$name”; matching files are being filed"
        }
    }

    fun renameFolder(f: Folder, name: String) = updateFolder(f, buildJsonObject { put("name", name) }, "Renamed to “$name”")

    fun moveFolder(f: Folder, parent: Folder?) = updateFolder(f, buildJsonObject { put("parent_id", parent?.id) },
        if (parent == null) "Moved “${f.name}” to My Drive" else "Moved “${f.name}” into “${parent.name}”")

    fun updateFolder(f: Folder, changes: JsonObject, done: String) = act(undo = true) {
        state.api.updateFolder(aid, f.id, changes)
        state.loadFolders()
        done
    }

    /** Save or remove a folder's rule; an auto-filing rule files what already matches right away. */
    fun saveRule(f: Folder, rules: JsonObject?) = act(undo = true) {
        state.api.updateFolder(aid, f.id, buildJsonObject { put("rules", rules ?: JsonNull) })
        val msg = when {
            rules == null -> "Rule removed. The folder is an ordinary folder again."
            rules.str("mode") == "auto" -> {
                val n = state.api.applyRules(aid, f.id).long("filed")
                if (n > 0) "Rule saved. Filed ${Format.plural(n, "file")} into “${f.name}”." else "Rule saved. New matching files will be filed here."
            }
            else -> "Smart folder updated"
        }
        state.loadFolders()
        state.changed("rules")
        msg
    }

    fun saveSearch(name: String, q: String, params: Map<String, String>, onSaved: (String) -> Unit) = act {
        val s = state.api.saveSearch(aid, name, q, JsonObject(params.mapValues { JsonPrimitive(it.value) }))
        state.loadFolders()
        onSaved(s.id)
        "Saved “$name”"
    }

    fun deleteSaved(id: String) = act {
        state.api.deleteSearch(aid, id)
        state.loadFolders()
        "Saved search deleted"
    }

    // ------------------------------------------------------------------ chats
    fun pinChat(chatId: Long, pinned: Boolean) = act {
        state.api.pinChat(aid, chatId, pinned)
        state.loadChats()
        if (pinned) "Pinned to the sidebar" else "Unpinned"
    }

    fun rescanChat(chatId: Long) = act {
        state.api.rescanChat(aid, chatId)
        state.loadChats()
        "Re-indexing the chat from the start"
    }

    fun excludeChat(chatId: Long, excluded: Boolean) = act {
        state.api.excludeChat(aid, chatId, excluded)
        state.loadChats()
        state.changed("chats")
        if (excluded) "Excluded. Its files left TG Drive's index." else "Included again; it's being indexed"
    }

    // ------------------------------------------------------------------ outside the app
    fun openUrl(url: String) {
        if (!Platform.openUrl(ctx, url)) state.message("No app can open that link.", error = true)
    }

    fun openInTelegram(f: FileItem) = act {
        val d = state.api.detail(aid, f.ref)
        val url = d.extras.tgLink ?: d.file.link ?: throw IllegalStateException("Telegram has no link for messages in basic groups.")
        openUrl(url)
        null
    }

    fun copyLinks(files: List<FileItem>) {
        val links = files.mapNotNull { it.link }
        if (links.isEmpty()) return state.message("Private chats and basic groups have no t.me links.", error = true)
        Platform.copy(ctx, "Telegram links", links.joinToString("\n"))
        val missing = files.size - links.size
        state.message("Copied ${Format.plural(links.size, "link")}" + if (missing > 0) ". $missing in private chats have none." else "")
    }

    /**
     * Hand a file to another app: videos and audio stream straight to the player you choose; anything
     * else is downloaded first (if it isn't already) and opens when it's ready.
     */
    fun openWithApp(f: FileItem) = act {
        if (f.streamable) {
            if (!Platform.openStream(ctx, state.api.externalStreamUrl(aid, f), f.mime, f.displayName)) throw IllegalStateException("No app can play this.")
            return@act null
        }
        val local = state.api.detail(aid, f.ref).extras.localPath
        if (local != null && java.io.File(local).exists()) {
            if (!Platform.openFile(ctx, local, f.mime)) throw IllegalStateException("No app on this phone opens .${f.ext ?: "these"} files.")
            return@act null
        }
        val id = (state.api.download(aid, listOf(f.ref))["ids"] as? JsonArray)?.firstOrNull()?.jsonPrimitive?.content?.toLongOrNull()
            ?: throw IllegalStateException("Couldn't start the download.")
        state.loadTransfers()
        state.message("Downloading “${f.displayName}”. It opens when it's ready.")
        scope.launch { openWhenDone(id, f) }
        null
    }

    private suspend fun openWhenDone(id: Long, f: FileItem) {
        repeat(60 * 60) {
            kotlinx.coroutines.delay(1000)
            val t = runCatching { state.api.transfers(aid).transfers.firstOrNull { it.id == id } }.getOrNull() ?: return@repeat
            when (t.status) {
                "done" -> { t.path?.let { Platform.openFile(ctx, it, f.mime) }; return }
                "error", "cancelled" -> { state.message(t.error ?: "The download didn't finish.", error = true); return }
            }
        }
    }

    private fun label(files: Collection<FileItem>) =
        if (files.size == 1) "“${files.first().displayName}”" else Format.plural(files.size, "file")

}
