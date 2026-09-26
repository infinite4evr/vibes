package app.lumaclean.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** A JSON array persisted in the app's private files; small lists only. */
internal class JsonFile(context: Context, name: String) {
    private val file = File(context.filesDir, name)

    @Synchronized
    fun read(): JSONArray = runCatching { JSONArray(file.readText()) }.getOrDefault(JSONArray())

    @Synchronized
    fun write(array: JSONArray) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(array.toString())
        if (!tmp.renameTo(file)) {
            file.writeText(array.toString())
            tmp.delete()
        }
    }
}

data class HistoryEntry(val time: Long, val title: String, val items: Int, val bytes: Long)

class HistoryStore(context: Context) {
    private val json = JsonFile(context, "history.json")
    private val _entries = MutableStateFlow(load())
    val entries: StateFlow<List<HistoryEntry>> = _entries.asStateFlow()

    fun add(title: String, items: Int, bytes: Long) {
        if (items <= 0 && bytes <= 0) return
        val next = (listOf(HistoryEntry(System.currentTimeMillis(), title, items, bytes)) + _entries.value).take(300)
        _entries.value = next
        save(next)
    }

    fun clear() {
        _entries.value = emptyList()
        save(emptyList())
    }

    private fun load(): List<HistoryEntry> {
        val a = json.read()
        return (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let { HistoryEntry(it.optLong("t"), it.optString("title"), it.optInt("n"), it.optLong("b")) }
        }
    }

    private fun save(list: List<HistoryEntry>) {
        val a = JSONArray()
        list.forEach { a.put(JSONObject().put("t", it.time).put("title", it.title).put("n", it.items).put("b", it.bytes)) }
        json.write(a)
    }
}

/** Folders and files the user never wants cleaned. */
class ExclusionStore(context: Context) {
    private val json = JsonFile(context, "never_clean.json")
    private val _paths = MutableStateFlow(load())
    val paths: StateFlow<List<String>> = _paths.asStateFlow()

    fun add(path: String) {
        val clean = path.trimEnd('/')
        if (clean.isEmpty() || clean in _paths.value) return
        update((_paths.value + clean).sorted())
    }

    fun remove(path: String) = update(_paths.value - path)

    fun isExcluded(path: String): Boolean {
        val list = _paths.value
        if (list.isEmpty()) return false
        return list.any { path == it || path.startsWith("$it/") }
    }

    private fun update(list: List<String>) {
        _paths.value = list
        json.write(JSONArray(list))
    }

    private fun load(): List<String> {
        val a = json.read()
        return (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }
    }
}

data class BatteryPoint(val time: Long, val level: Int, val tempC: Float, val charging: Boolean)

/** A rolling seven-day log of battery level and temperature, written by the monitor worker. */
class BatteryLogStore(context: Context) {
    private val json = JsonFile(context, "battery_log.json")
    private val _points = MutableStateFlow(load())
    val points: StateFlow<List<BatteryPoint>> = _points.asStateFlow()

    @Synchronized
    fun add(point: BatteryPoint) {
        val cutoff = point.time - 7L * 24 * 60 * 60 * 1000
        val last = _points.value.lastOrNull()
        // two logs within five minutes add nothing to the chart
        if (last != null && point.time - last.time < 5 * 60_000 && last.level == point.level) return
        val next = (_points.value + point).filter { it.time >= cutoff }
        _points.value = next
        val a = JSONArray()
        next.forEach {
            a.put(JSONObject().put("t", it.time).put("l", it.level).put("c", it.tempC.toDouble()).put("ch", it.charging))
        }
        json.write(a)
    }

    private fun load(): List<BatteryPoint> {
        val a = json.read()
        return (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let {
                BatteryPoint(it.optLong("t"), it.optInt("l"), it.optDouble("c").toFloat(), it.optBoolean("ch"))
            }
        }.sortedBy { it.time }
    }
}
