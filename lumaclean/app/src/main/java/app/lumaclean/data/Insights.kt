package app.lumaclean.data

import app.lumaclean.core.DAY_MS
import app.lumaclean.core.PermissionSnapshot
import app.lumaclean.core.formatBytes
import java.io.File

data class ChatBucket(val label: String, val path: String, val bytes: Long, val count: Int)

data class ChatApp(val name: String, val root: String, val buckets: List<ChatBucket>) {
    val bytes: Long get() = buckets.sumOf { it.bytes }
}

object ChatMedia {
    private val roots = listOf(
        "WhatsApp" to listOf("Android/media/com.whatsapp/WhatsApp/Media", "WhatsApp/Media"),
        "WhatsApp Business" to listOf("Android/media/com.whatsapp.w4b/WhatsApp Business/Media", "WhatsApp Business/Media"),
        "Telegram" to listOf("Android/media/org.telegram.messenger/Telegram", "Telegram"),
        "Signal" to listOf("Android/media/org.thoughtcrime.securesms", "Signal"),
    )

    fun analyze(index: FileIndex): List<ChatApp> = roots.mapNotNull { (name, candidates) ->
        val root = candidates.map { "${index.root}/$it" }.firstOrNull { (index.sizeOf(it) ?: 0L) > 0 } ?: return@mapNotNull null
        val buckets = File(root).listFiles()?.filter { it.isDirectory }?.mapNotNull { dir ->
            val bytes = index.sizeOf(dir.absolutePath) ?: 0L
            if (bytes <= 0) null
            else ChatBucket(prettyName(name, dir.name), dir.absolutePath, bytes, index.dirCounts[dir.absolutePath] ?: 0)
        }.orEmpty().sortedByDescending { it.bytes }
        if (buckets.isEmpty()) null else ChatApp(name, root, buckets)
    }

    private fun prettyName(app: String, folder: String): String = when {
        folder == ".Statuses" -> "Statuses you viewed"
        folder.startsWith(".") -> folder.removePrefix(".").replaceFirstChar { it.uppercase() }
        else -> folder.removePrefix("$app ").removePrefix("WhatsApp ").removePrefix("Telegram ")
    }
}

enum class HealthAction { CLEAN, STORAGE, UNUSED_APPS, BATTERY, RAM, PERMISSIONS, RECYCLE_BIN, DUPLICATES }

data class HealthIssue(val title: String, val detail: String, val severity: Int, val action: HealthAction, val actionLabel: String)

data class Health(val score: Int, val issues: List<HealthIssue>) {
    val label: String
        get() = when {
            score >= 90 -> "Excellent"
            score >= 75 -> "Good"
            score >= 55 -> "Fair"
            else -> "Needs attention"
        }
}

object HealthEngine {
    fun compute(
        storage: VolumeInfo?,
        memory: MemoryInfo?,
        battery: BatteryInfo?,
        junk: JunkReport?,
        apps: List<AppInfo>?,
        perms: PermissionSnapshot,
        binBytes: Long,
    ): Health {
        var score = 100
        val issues = ArrayList<HealthIssue>()

        if (!perms.allFiles) {
            issues += HealthIssue("Allow file access", "Needed to find junk, duplicates and big files", 1, HealthAction.PERMISSIONS, "Allow")
        }
        storage?.let {
            val f = it.usedFraction
            val penalty = when {
                f > 0.95f -> 30
                f > 0.90f -> 20
                f > 0.80f -> 10
                else -> 0
            }
            if (penalty > 0) {
                score -= penalty
                issues += HealthIssue(
                    "Storage ${(f * 100).toInt()}% full",
                    "${it.free.formatBytes()} left. Phones slow down when storage runs low.",
                    if (penalty >= 20) 3 else 2, HealthAction.STORAGE, "Review",
                )
            }
        }
        junk?.let {
            val safe = it.safeBytes
            val penalty = when {
                safe > 2_000_000_000 -> 15
                safe > 500_000_000 -> 8
                safe > 100_000_000 -> 3
                else -> 0
            }
            score -= penalty
            if (it.totalBytes > 50_000_000) {
                issues += HealthIssue(
                    "${it.totalBytes.formatBytes()} of junk found",
                    "${safe.formatBytes()} of it is safe to remove right now",
                    if (penalty >= 8) 2 else 1, HealthAction.CLEAN, "Clean",
                )
            }
        }
        memory?.let {
            if (it.low || it.available < it.total * 0.12) {
                score -= 8
                issues += HealthIssue("Memory is tight", "${it.available.formatBytes()} of RAM free", 2, HealthAction.RAM, "Free up")
            }
        }
        battery?.let {
            if (!it.health.good) {
                score -= 15
                issues += HealthIssue("Battery health: ${it.health.label}", "Android reports a battery problem", 3, HealthAction.BATTERY, "Details")
            } else if (it.tempC >= 45f) {
                score -= 5
                issues += HealthIssue("Battery is hot (${it.tempC.toInt()}°C)", "Let the phone cool down, especially while charging", 2, HealthAction.BATTERY, "Details")
            }
        }
        apps?.let { list ->
            val cutoff = System.currentTimeMillis() - 60 * DAY_MS
            val unused = list.filter { !it.system && it.lastUsed in 1 until cutoff }
            if (unused.size >= 5) {
                score -= if (unused.size >= 15) 6 else 3
                issues += HealthIssue(
                    "${unused.size} apps unused for 2+ months",
                    "Together they take ${unused.sumOf { it.totalBytes }.formatBytes()}",
                    1, HealthAction.UNUSED_APPS, "Review",
                )
            }
        }
        if (binBytes > 1_000_000_000) {
            score -= 3
            issues += HealthIssue("Recycle bin holds ${binBytes.formatBytes()}", "Empty it to get that space back", 1, HealthAction.RECYCLE_BIN, "Open")
        }
        if (!perms.usage) {
            issues += HealthIssue("Allow usage access", "Shows app sizes, unused apps and data usage", 0, HealthAction.PERMISSIONS, "Allow")
        }
        return Health(score.coerceIn(0, 100), issues.sortedByDescending { it.severity })
    }
}
