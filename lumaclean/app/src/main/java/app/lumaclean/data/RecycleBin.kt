package app.lumaclean.data

import android.content.Context
import android.os.Environment
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.random.Random

data class BinItem(
    val id: String,
    val originalPath: String,
    val binPath: String,
    val size: Long,
    val deletedAt: Long,
    val isDir: Boolean,
) {
    val name: String get() = originalPath.substringAfterLast('/')
}

/**
 * Deleted files are renamed into a hidden folder on the same volume (instant, no copying)
 * and can be restored until the bin is emptied or they expire.
 */
class RecycleBin(context: Context, private val dirName: String) {
    private val json = JsonFile(context, "recycle_bin.json")
    private val _items = MutableStateFlow(load())
    val items: StateFlow<List<BinItem>> = _items.asStateFlow()

    val totalBytes: Long get() = _items.value.sumOf { it.size }

    private fun binDirFor(path: String): File {
        val primary = Environment.getExternalStorageDirectory().absolutePath
        val volumeRoot = if (path.startsWith("$primary/")) primary
        else path.split('/').take(3).joinToString("/") // /storage/XXXX-XXXX
        return File(volumeRoot, dirName).apply {
            mkdirs()
            runCatching { File(this, ".nomedia").createNewFile() }
        }
    }

    /** Moves one path into the bin. Returns null when it can't (then nothing changed). */
    @Synchronized
    fun moveIn(path: String, size: Long): BinItem? {
        val src = File(path)
        if (!src.exists()) return null
        val id = "${System.currentTimeMillis()}-${Random.nextInt(1_000_000)}"
        val dest = File(binDirFor(path), id)
        val item = BinItem(id, path, dest.absolutePath, size, System.currentTimeMillis(), src.isDirectory)
        // Write the recovery record BEFORE moving bytes. A kill or cancellation cannot orphan a file.
        update(listOf(item) + _items.value)
        if (!src.renameTo(dest)) {
            update(_items.value.filterNot { it.id == id })
            return null
        }
        return item
    }

    @Synchronized
    fun record(added: List<BinItem>) {
        if (added.isEmpty()) return
        update((added + _items.value).distinctBy { it.id })
    }

    /** Puts items back where they were; a clashing name gets " (1)" appended. */
    @Synchronized
    fun restore(ids: Collection<String>): List<String> {
        val set = ids.toSet()
        val restored = ArrayList<String>()
        val keep = _items.value.filter { item ->
            if (item.id !in set || !available(item)) return@filter true
            val original = File(item.originalPath)
            original.parentFile?.mkdirs()
            val target = uniqueFile(original.parentFile ?: return@filter true, original.name)
            val ok = File(item.binPath).renameTo(target)
            if (ok) restored += target.absolutePath
            !ok
        }
        update(keep)
        return restored
    }

    @Synchronized
    fun deleteForever(ids: Collection<String>): Long {
        val set = ids.toSet()
        var freed = 0L
        val keep = _items.value.filter { item ->
            if (item.id !in set || !available(item)) return@filter true
            val f = File(item.binPath)
            val ok = f.exists() && f.deleteRecursively()
            if (ok) freed += item.size
            !ok
        }
        update(keep)
        return freed
    }

    fun purgeOlderThan(days: Int): Long {
        val cutoff = System.currentTimeMillis() - days * 24L * 60 * 60 * 1000
        return deleteForever(_items.value.filter { it.deletedAt < cutoff }.map { it.id })
    }

    /** A missing/unmounted volume must never be mistaken for an emptied recycle bin. */
    fun available(item: BinItem): Boolean = File(item.binPath).exists()

    /** Keeps missing records for recovery when an SD card or storage permission returns. */
    @Synchronized
    fun reconcile() {
        // Deliberately preserve records. Existence alone cannot distinguish disconnected storage,
        // revoked permission, and a genuinely missing file. Restore/delete require available bytes.
        _items.value = load()
    }

    private fun update(list: List<BinItem>) {
        val a = JSONArray()
        list.forEach {
            a.put(
                JSONObject().put("id", it.id).put("o", it.originalPath).put("b", it.binPath)
                    .put("s", it.size).put("t", it.deletedAt).put("d", it.isDir),
            )
        }
        json.write(a)
        _items.value = list
    }

    private fun load(): List<BinItem> {
        val a = json.read()
        return (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let {
                BinItem(it.optString("id"), it.optString("o"), it.optString("b"), it.optLong("s"), it.optLong("t"), it.optBoolean("d"))
            }
        }
    }
}

fun uniqueFile(dir: File, name: String): File {
    var f = File(dir, name)
    if (!f.exists()) return f
    val dot = name.lastIndexOf('.')
    val base = if (dot > 0) name.substring(0, dot) else name
    val ext = if (dot > 0) name.substring(dot) else ""
    var i = 1
    while (f.exists()) {
        f = File(dir, "$base ($i)$ext")
        i++
    }
    return f
}
