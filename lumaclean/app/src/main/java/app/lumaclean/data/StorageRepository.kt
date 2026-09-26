package app.lumaclean.data

import android.app.usage.StorageStatsManager
import android.content.Context
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.os.storage.StorageManager
import android.os.storage.StorageVolume

data class VolumeInfo(
    val name: String,
    val path: String?,
    val total: Long,
    val free: Long,
    val primary: Boolean,
) {
    val used: Long get() = (total - free).coerceAtLeast(0)
    val usedFraction: Float get() = if (total <= 0) 0f else used.toFloat() / total
}

class StorageRepository(private val context: Context) {

    fun primary(): VolumeInfo {
        val stats = context.getSystemService(StorageStatsManager::class.java)
        // StorageStatsManager counts the whole flash chip, including the system partition, like Settings does
        val (total, free) = runCatching {
            stats.getTotalBytes(StorageManager.UUID_DEFAULT) to stats.getFreeBytes(StorageManager.UUID_DEFAULT)
        }.getOrElse {
            val fs = StatFs(Environment.getDataDirectory().absolutePath)
            fs.totalBytes to fs.availableBytes
        }
        return VolumeInfo("Internal storage", Environment.getExternalStorageDirectory().absolutePath, total, free, true)
    }

    fun volumes(): List<VolumeInfo> = listOf(primary()) + removable()

    fun removable(): List<VolumeInfo> {
        val sm = context.getSystemService(StorageManager::class.java) ?: return emptyList()
        return sm.storageVolumes
            .filter { it.isRemovable && it.state == Environment.MEDIA_MOUNTED }
            .mapNotNull { vol ->
                val path = volumePath(vol) ?: return@mapNotNull null
                runCatching {
                    val fs = StatFs(path)
                    VolumeInfo(vol.getDescription(context) ?: "SD card", path, fs.totalBytes, fs.availableBytes, false)
                }.getOrNull()
            }
    }

    private fun volumePath(vol: StorageVolume): String? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) vol.directory?.absolutePath
        else runCatching { vol.javaClass.getMethod("getPath").invoke(vol) as? String }.getOrNull()

    fun freeBytes(path: String = Environment.getExternalStorageDirectory().absolutePath): Long =
        runCatching { StatFs(path).availableBytes }.getOrDefault(0L)

    /** Pretty name for a path, e.g. "Internal storage › Download". */
    fun displayPath(path: String): String {
        val root = Environment.getExternalStorageDirectory().absolutePath
        if (path == root) return "Internal storage"
        if (path.startsWith("$root/")) return "Internal storage › " + path.removePrefix("$root/").replace("/", " › ")
        removable().firstOrNull { it.path != null && path.startsWith(it.path) }?.let { v ->
            val rest = path.removePrefix(v.path!!).trim('/')
            return if (rest.isEmpty()) v.name else v.name + " › " + rest.replace("/", " › ")
        }
        return path
    }
}
