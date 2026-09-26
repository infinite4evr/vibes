package app.lumaclean.data

import android.app.usage.NetworkStats
import android.app.usage.NetworkStatsManager
import android.app.usage.StorageStatsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.PermissionInfo
import android.graphics.Bitmap
import android.net.ConnectivityManager
import android.os.Build
import android.os.Environment
import android.os.Process
import android.provider.MediaStore
import android.util.LruCache
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.core.content.FileProvider
import androidx.core.graphics.drawable.toBitmap
import app.lumaclean.core.DAY_MS
import app.lumaclean.core.Perms
import app.lumaclean.core.Progress
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.OutputStream
import java.util.Calendar
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

data class AppInfo(
    val packageName: String,
    val label: String,
    val versionName: String,
    val versionCode: Long,
    val system: Boolean,
    val updatedSystem: Boolean,
    val enabled: Boolean,
    val installer: String,
    val firstInstall: Long,
    val lastUpdate: Long,
    val targetSdk: Int,
    val minSdk: Int,
    val uid: Int,
    val appBytes: Long,
    val dataBytes: Long,
    val cacheBytes: Long,
    val lastUsed: Long,
    val apkPath: String,
    val splitCount: Int,
    val launchable: Boolean,
    val hasSizes: Boolean,
) {
    val totalBytes: Long get() = appBytes + dataBytes
    val canUninstall: Boolean get() = !system || updatedSystem
}

data class AppPermission(val name: String, val label: String, val granted: Boolean, val sensitive: Boolean)

data class AppUsage(
    val packageName: String,
    val label: String,
    val foregroundMs: Long,
    val lastUsed: Long,
    val wifiBytes: Long,
    val mobileBytes: Long,
)

data class UsageReport(
    val days: Int,
    val apps: List<AppUsage>,
    val dailyScreenMs: List<Pair<Long, Long>>,
    val totalScreenMs: Long,
    val totalWifi: Long,
    val totalMobile: Long,
    val mobileAvailable: Boolean,
)

class AppsRepository(private val context: Context) {
    private val pm: PackageManager = context.packageManager
    private val icons = LruCache<String, ImageBitmap>(300)

    suspend fun load(progress: Progress): List<AppInfo> {
        val ctx = currentCoroutineContext()
        @Suppress("DEPRECATION")
        val apps = pm.getInstalledApplications(0)
        val usage = if (Perms.hasUsage(context)) lastUsedMap() else emptyMap()
        val sizes = Perms.hasUsage(context)
        return apps.mapIndexedNotNull { i, ai ->
            ctx.ensureActive()
            progress.report(i / apps.size.toFloat(), "Reading ${i + 1} of ${apps.size} apps")
            runCatching { build(ai, usage[ai.packageName] ?: 0L, sizes) }.getOrNull()
        }.sortedByDescending { it.totalBytes }
    }

    fun loadOne(packageName: String): AppInfo? = runCatching {
        @Suppress("DEPRECATION")
        val ai = pm.getApplicationInfo(packageName, 0)
        val usage = if (Perms.hasUsage(context)) lastUsedMap()[packageName] ?: 0L else 0L
        build(ai, usage, Perms.hasUsage(context))
    }.getOrNull()

    fun isInstalled(packageName: String): Boolean =
        runCatching { @Suppress("DEPRECATION") pm.getPackageInfo(packageName, 0); true }.getOrDefault(false)

    private fun build(ai: ApplicationInfo, lastUsed: Long, withSizes: Boolean): AppInfo {
        @Suppress("DEPRECATION")
        val pi: PackageInfo = pm.getPackageInfo(ai.packageName, 0)
        val stats = if (withSizes) runCatching {
            context.getSystemService(StorageStatsManager::class.java)
                .queryStatsForPackage(ai.storageUuid, ai.packageName, Process.myUserHandle())
        }.getOrNull() else null
        val fallbackApk = runCatching { File(ai.sourceDir).length() }.getOrDefault(0L)
        return AppInfo(
            packageName = ai.packageName,
            label = pm.getApplicationLabel(ai).toString(),
            versionName = pi.versionName ?: "",
            versionCode = if (Build.VERSION.SDK_INT >= 28) pi.longVersionCode else @Suppress("DEPRECATION") pi.versionCode.toLong(),
            system = ai.flags and ApplicationInfo.FLAG_SYSTEM != 0,
            updatedSystem = ai.flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP != 0,
            enabled = ai.enabled,
            installer = installerLabel(ai.packageName),
            firstInstall = pi.firstInstallTime,
            lastUpdate = pi.lastUpdateTime,
            targetSdk = ai.targetSdkVersion,
            minSdk = if (Build.VERSION.SDK_INT >= 24) ai.minSdkVersion else 0,
            uid = ai.uid,
            appBytes = stats?.appBytes ?: fallbackApk,
            dataBytes = stats?.dataBytes ?: 0L,
            cacheBytes = stats?.cacheBytes ?: 0L,
            lastUsed = lastUsed,
            apkPath = ai.sourceDir ?: "",
            splitCount = ai.splitSourceDirs?.size ?: 0,
            launchable = pm.getLaunchIntentForPackage(ai.packageName) != null,
            hasSizes = stats != null,
        )
    }

    private fun installerLabel(pkg: String): String {
        val installer = runCatching {
            if (Build.VERSION.SDK_INT >= 30) pm.getInstallSourceInfo(pkg).installingPackageName
            else @Suppress("DEPRECATION") pm.getInstallerPackageName(pkg)
        }.getOrNull()
        return when (installer) {
            null -> "Preinstalled"
            "com.android.vending" -> "Google Play"
            "com.sec.android.app.samsungapps" -> "Galaxy Store"
            "com.amazon.venezia" -> "Amazon Appstore"
            "com.huawei.appmarket" -> "AppGallery"
            "com.xiaomi.market", "com.xiaomi.mipicks" -> "Xiaomi GetApps"
            "org.fdroid.fdroid" -> "F-Droid"
            "com.aurora.store" -> "Aurora Store"
            "com.android.packageinstaller", "com.google.android.packageinstaller",
            "com.samsung.android.packageinstaller", "com.miui.packageinstaller" -> "Installed from a file"
            "com.android.shell" -> "Installed over USB"
            else -> runCatching {
                @Suppress("DEPRECATION")
                pm.getApplicationLabel(pm.getApplicationInfo(installer, 0)).toString()
            }.getOrDefault(installer)
        }
    }

    fun icon(packageName: String, sizePx: Int): ImageBitmap? {
        icons.get(packageName)?.let { return it }
        val bmp = runCatching {
            pm.getApplicationIcon(packageName).toBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888).asImageBitmap()
        }.getOrNull() ?: return null
        icons.put(packageName, bmp)
        return bmp
    }

    fun permissions(packageName: String): List<AppPermission> {
        val pi = runCatching {
            @Suppress("DEPRECATION")
            pm.getPackageInfo(packageName, PackageManager.GET_PERMISSIONS)
        }.getOrNull() ?: return emptyList()
        val names = pi.requestedPermissions ?: return emptyList()
        val flags = pi.requestedPermissionsFlags
        return names.mapIndexed { i, name ->
            val info = runCatching { pm.getPermissionInfo(name, 0) }.getOrNull()
            val base = info?.let {
                if (Build.VERSION.SDK_INT >= 28) it.protection else @Suppress("DEPRECATION") (it.protectionLevel and PermissionInfo.PROTECTION_MASK_BASE)
            }
            val label = info?.loadLabel(pm)?.toString()?.takeIf { it.isNotBlank() && it != name }
                ?.replaceFirstChar { it.uppercase() }
                ?: name.substringAfterLast('.').lowercase().replace('_', ' ').replaceFirstChar { it.uppercase() }
            AppPermission(
                name = name,
                label = label,
                granted = flags != null && i < flags.size && flags[i] and PackageInfo.REQUESTED_PERMISSION_GRANTED != 0,
                sensitive = base == PermissionInfo.PROTECTION_DANGEROUS,
            )
        }.distinctBy { it.name }.sortedWith(compareByDescending<AppPermission> { it.sensitive }.thenByDescending { it.granted }.thenBy { it.label })
    }

    fun launchIntent(packageName: String): Intent? = pm.getLaunchIntentForPackage(packageName)

    /**
     * Saves the app's installer to Download/LumaClean. Apps split into several APKs are
     * bundled as one .apks file, which installers like SAI accept.
     */
    fun backupApk(app: AppInfo): String {
        val base = "${app.label.replace(Regex("[^A-Za-z0-9 ._-]"), "")}_${app.versionName}".trim()
        val splits = runCatching {
            @Suppress("DEPRECATION")
            pm.getApplicationInfo(app.packageName, 0).splitSourceDirs?.toList()
        }.getOrNull().orEmpty()
        val name = if (splits.isEmpty()) "$base.apk" else "$base.apks"
        writeToDownloads(name, if (splits.isEmpty()) "application/vnd.android.package-archive" else "application/zip") { out ->
            if (splits.isEmpty()) FileInputStream(app.apkPath).use { it.copyTo(out) }
            else ZipOutputStream(out).use { zip ->
                (listOf(app.apkPath) + splits).forEach { path ->
                    zip.putNextEntry(ZipEntry(File(path).name))
                    FileInputStream(path).use { it.copyTo(zip) }
                    zip.closeEntry()
                }
            }
        }
        return "Download/LumaClean/$name"
    }

    fun shareApkIntent(app: AppInfo): Intent {
        val dir = File(context.cacheDir, "share").apply { mkdirs() }
        val file = File(dir, "${app.label.replace(Regex("[^A-Za-z0-9._-]"), "_")}.apk")
        FileInputStream(app.apkPath).use { input -> FileOutputStream(file).use { input.copyTo(it) } }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        val send = Intent(Intent.ACTION_SEND)
            .setType("application/vnd.android.package-archive")
            .putExtra(Intent.EXTRA_STREAM, uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return Intent.createChooser(send, "Share ${app.label}")
    }

    private fun writeToDownloads(name: String, mime: String, write: (OutputStream) -> Unit) {
        if (Build.VERSION.SDK_INT >= 29) {
            val resolver = context.contentResolver
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.MIME_TYPE, mime)
                put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/LumaClean")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: error("Couldn't create the file in Downloads")
            try {
                resolver.openOutputStream(uri)?.use(write) ?: error("Couldn't write to Downloads")
                values.clear()
                values.put(MediaStore.Downloads.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
            } catch (t: Throwable) {
                resolver.delete(uri, null, null)
                throw t
            }
        } else {
            @Suppress("DEPRECATION")
            val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "LumaClean")
            dir.mkdirs()
            FileOutputStream(uniqueFile(dir, name)).use(write)
        }
    }

    private fun lastUsedMap(): Map<String, Long> {
        val usm = context.getSystemService(UsageStatsManager::class.java) ?: return emptyMap()
        val end = System.currentTimeMillis()
        return runCatching {
            usm.queryUsageStats(UsageStatsManager.INTERVAL_BEST, end - 365 * DAY_MS, end)
                .groupBy { it.packageName }
                .mapValues { (_, list) -> list.maxOf { it.lastTimeUsed } }
        }.getOrDefault(emptyMap())
    }

    /** Screen time from foreground events (the method Digital Wellbeing uses) plus per-app data. */
    suspend fun usage(days: Int, progress: Progress): UsageReport {
        val ctx = currentCoroutineContext()
        val usm = context.getSystemService(UsageStatsManager::class.java)
        val cal = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
            add(Calendar.DAY_OF_YEAR, -(days - 1))
        }
        val start = cal.timeInMillis
        val end = System.currentTimeMillis()
        val dayStarts = (0 until days).map { start + it * DAY_MS }

        progress.report(null, "Reading screen time…", force = true)
        val foreground = HashMap<String, Long>()
        val lastUsed = HashMap<String, Long>()
        val daily = LongArray(days)
        val open = HashMap<String, Long>()
        fun addSpan(pkg: String, from: Long, to: Long) {
            if (to <= from) return
            foreground[pkg] = (foreground[pkg] ?: 0L) + (to - from)
            var s = from
            while (s < to) {
                val d = ((s - start) / DAY_MS).toInt().coerceIn(0, days - 1)
                val dayEnd = start + (d + 1) * DAY_MS
                val e = minOf(to, dayEnd)
                daily[d] += e - s
                s = e
            }
        }
        val events = usm.queryEvents(start, end)
        val e = UsageEvents.Event()
        var n = 0
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            if (++n % 5000 == 0) ctx.ensureActive()
            val pkg = e.packageName ?: continue
            @Suppress("DEPRECATION")
            when (e.eventType) {
                UsageEvents.Event.MOVE_TO_FOREGROUND -> open[pkg] = e.timeStamp
                UsageEvents.Event.MOVE_TO_BACKGROUND -> {
                    open.remove(pkg)?.let { addSpan(pkg, it, e.timeStamp) }
                    lastUsed[pkg] = e.timeStamp
                }
            }
        }
        open.forEach { (pkg, from) -> addSpan(pkg, from, end); lastUsed[pkg] = end }
        // launchers and our own app aren't interesting screen time
        val home = homePackages()
        home.forEach { foreground.remove(it) }

        progress.report(null, "Reading data usage…", force = true)
        val wifi = dataByUid(ConnectivityManager.TYPE_WIFI, start, end)
        val mobile = dataByUid(ConnectivityManager.TYPE_MOBILE, start, end)
        val uidToPkg = HashMap<Int, String>()
        (wifi.keys + mobile.keys).forEach { uid ->
            uidToPkg[uid] = when (uid) {
                1000 -> "android"
                -4 -> "(removed apps)"
                -5 -> "(hotspot)"
                else -> pm.getPackagesForUid(uid)?.firstOrNull() ?: "uid:$uid"
            }
        }
        val pkgWifi = HashMap<String, Long>()
        val pkgMobile = HashMap<String, Long>()
        wifi.forEach { (uid, b) -> uidToPkg[uid]?.let { pkgWifi[it] = (pkgWifi[it] ?: 0) + b } }
        mobile.forEach { (uid, b) -> uidToPkg[uid]?.let { pkgMobile[it] = (pkgMobile[it] ?: 0) + b } }

        val all = foreground.keys + pkgWifi.keys + pkgMobile.keys
        val apps = all.map { pkg ->
            AppUsage(
                packageName = pkg,
                label = labelFor(pkg),
                foregroundMs = foreground[pkg] ?: 0L,
                lastUsed = lastUsed[pkg] ?: 0L,
                wifiBytes = pkgWifi[pkg] ?: 0L,
                mobileBytes = pkgMobile[pkg] ?: 0L,
            )
        }
        return UsageReport(
            days = days,
            apps = apps,
            dailyScreenMs = dayStarts.mapIndexed { i, d -> d to daily[i] },
            totalScreenMs = foreground.values.sum(),
            totalWifi = deviceTotal(ConnectivityManager.TYPE_WIFI, start, end) ?: pkgWifi.values.sum(),
            totalMobile = deviceTotal(ConnectivityManager.TYPE_MOBILE, start, end) ?: pkgMobile.values.sum(),
            mobileAvailable = mobile.isNotEmpty() || deviceTotal(ConnectivityManager.TYPE_MOBILE, start, end) != null,
        )
    }

    private fun labelFor(pkg: String): String = when {
        pkg == "android" -> "Android system"
        pkg.startsWith("(") -> pkg.trim('(', ')').replaceFirstChar { it.uppercase() }
        pkg.startsWith("uid:") -> "System service"
        else -> runCatching {
            @Suppress("DEPRECATION")
            pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
        }.getOrDefault(pkg)
    }

    private fun homePackages(): Set<String> {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        @Suppress("DEPRECATION")
        return pm.queryIntentActivities(intent, 0).map { it.activityInfo.packageName }.toSet() + context.packageName
    }

    private fun dataByUid(type: Int, start: Long, end: Long): Map<Int, Long> {
        val nsm = context.getSystemService(NetworkStatsManager::class.java) ?: return emptyMap()
        return runCatching {
            val out = HashMap<Int, Long>()
            nsm.querySummary(type, null, start, end).useStats { stats ->
                val bucket = NetworkStats.Bucket()
                while (stats.hasNextBucket()) {
                    stats.getNextBucket(bucket)
                    out[bucket.uid] = (out[bucket.uid] ?: 0L) + bucket.rxBytes + bucket.txBytes
                }
            }
            out.filterValues { it > 0 }
        }.getOrDefault(emptyMap())
    }

    fun deviceTotal(type: Int, start: Long, end: Long): Long? {
        val nsm = context.getSystemService(NetworkStatsManager::class.java) ?: return null
        return runCatching {
            val b = nsm.querySummaryForDevice(type, null, start, end)
            b.rxBytes + b.txBytes
        }.getOrNull()
    }
}

private inline fun <R> NetworkStats.useStats(block: (NetworkStats) -> R): R =
    try { block(this) } finally { close() }
