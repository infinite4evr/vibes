package com.example.lumaclean.data

import android.app.AppOpsManager
import android.app.usage.StorageStatsManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Process
import android.os.storage.StorageManager
import com.example.lumaclean.model.InstalledAppInfo

class AppRepository(private val context: Context) {
    fun hasUsageAccess(): Boolean {
        val appOps = context.getSystemService(AppOpsManager::class.java)
        val mode = appOps.checkOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            Process.myUid(),
            context.packageName
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun loadApps(): List<InstalledAppInfo> {
        val pm = context.packageManager
        val apps = pm.getInstalledApplications(0)
        val usage = usageMap()
        val storage = context.getSystemService(StorageStatsManager::class.java)

        return apps.mapNotNull { ai ->
            runCatching {
                val pkg = ai.packageName
                val pkgInfo = pm.getPackageInfo(pkg, 0)
                val stats = if (hasUsageAccess()) {
                    runCatching {
                        storage.queryStatsForUid(ai.storageUuid ?: StorageManager.UUID_DEFAULT, ai.uid)
                    }.getOrNull()
                } else null
                InstalledAppInfo(
                    packageName = pkg,
                    label = pm.getApplicationLabel(ai).toString(),
                    versionName = pkgInfo.versionName ?: "",
                    cacheBytes = stats?.cacheBytes ?: 0L,
                    dataBytes = stats?.dataBytes ?: 0L,
                    appBytes = stats?.appBytes ?: 0L,
                    lastUsed = usage[pkg] ?: 0L,
                    systemApp = ai.flags and ApplicationInfo.FLAG_SYSTEM != 0
                )
            }.getOrNull()
        }.sortedWith(compareByDescending<InstalledAppInfo> { it.cacheBytes }.thenBy { it.label.lowercase() })
    }

    private fun usageMap(): Map<String, Long> {
        if (!hasUsageAccess()) return emptyMap()
        val usageManager = context.getSystemService(UsageStatsManager::class.java)
        val end = System.currentTimeMillis()
        val start = end - 90L * 24 * 60 * 60 * 1000
        return usageManager.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, start, end)
            .groupBy { it.packageName }
            .mapValues { (_, stats) -> stats.maxOfOrNull { it.lastTimeUsed } ?: 0L }
    }
}
