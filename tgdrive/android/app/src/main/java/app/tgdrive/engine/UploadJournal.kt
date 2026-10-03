package app.tgdrive.engine

import android.content.Context
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Durable phone-to-engine handoff, separate from the engine's Telegram transfer queue. */
class UploadJournal(context: Context) {
    private val file = AtomicFile(File(app.tgdrive.storage.DataLocation.state(context), "pending-uploads.json"))
    data class Entry(val id: String, val aid: Long, val uri: String, val name: String,
                     val folder: String?, val rel: String, val chat: Long?, val caption: String,
                     val staged: String = "", val error: String = "", val demo: Boolean = false,
                     /** A content URI whose persisted read permission covers this file (the file or its picked
                      *  folder): such a file is read again after a restart instead of being copied first. */
                     val grant: String = "")
    companion object { private val lock = Any() }
    fun list(): List<Entry> = synchronized(lock) {
        val text = try { file.openRead().bufferedReader().use { it.readText() } } catch (_: java.io.FileNotFoundException) { return@synchronized emptyList() }
        val arr = JSONArray(text)
        (0 until arr.length()).map { i -> arr.getJSONObject(i).let { o ->
            Entry(o.getString("id"), o.getLong("aid"), o.getString("uri"), o.getString("name"),
                o.optString("folder").takeIf { it.isNotEmpty() }, o.optString("rel"),
                o.optLong("chat").takeIf { it != 0L }, o.optString("caption"), o.optString("staged"), o.optString("error"), o.optBoolean("demo"), o.optString("grant"))
        } }
    }
    fun put(e: Entry) = synchronized(lock) { write(list().filterNot { it.id == e.id } + e) }
    fun remove(id: String) = synchronized(lock) { write(list().filterNot { it.id == id }) }

    /** Forget [e] for good: its staged copy, and the file permission once no other entry needs it. */
    fun discard(context: Context, e: Entry) {
        val stillUsed = synchronized(lock) {
            write(list().filterNot { it.id == e.id })
            list().any { it.grant == e.grant }
        }
        if (e.staged.isNotEmpty()) File(e.staged).delete()
        if (e.grant.isNotEmpty() && !stillUsed) runCatching {
            context.contentResolver.releasePersistableUriPermission(android.net.Uri.parse(e.grant),
                android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }
    private fun write(entries: List<Entry>) {
        val arr = JSONArray()
        entries.forEach { e -> arr.put(JSONObject().put("id",e.id).put("aid",e.aid).put("uri",e.uri)
            .put("name",e.name).put("folder",e.folder.orEmpty()).put("rel",e.rel).put("chat",e.chat ?: 0L)
            .put("demo",e.demo).put("caption",e.caption).put("staged",e.staged).put("error",e.error).put("grant",e.grant)) }
        val out = file.startWrite()
        try { out.write(arr.toString().toByteArray()); file.finishWrite(out) }
        catch (e: Throwable) { file.failWrite(out); throw e }
    }
}
