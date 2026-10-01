package app.tgdrive.engine

import android.app.ActivityManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings

/**
 * What Android (and the phone's maker) lets TG Drive do in the background. The background sync
 * only runs if Android allows background work: a "Restricted" battery setting, the restricted
 * standby bucket, or Samsung's "sleeping apps" stop it quietly. Settings → This phone shows this
 * and opens the right screen to change it.
 */
object BatteryLimits {
    data class Status(
        /** Settings → Apps → TG Drive → Battery → "Restricted" (API 28+): no background work at all. */
        val backgroundRestricted: Boolean,
        /** Android's "restricted" standby bucket (API 30+; unused apps, or Samsung's deep sleep): jobs about once a day. */
        val restrictedBucket: Boolean,
        /** Battery optimisation on (the default): fine for the background sync, which runs in Doze's windows. */
        val optimized: Boolean,
        val samsung: Boolean,
        val bucket: Int?,
    ) {
        /** The background sync won't run as set (or at all). */
        val blocksSync: Boolean get() = backgroundRestricted || restrictedBucket

        fun describe(): String = buildList {
            add(if (backgroundRestricted) "background restricted" else "background allowed")
            bucket?.let { add("standby bucket ${bucketName(it)}") }
            add(if (optimized) "battery optimised" else "battery unrestricted")
        }.joinToString(" · ")
    }

    fun status(c: Context): Status {
        val am = c.getSystemService(ActivityManager::class.java)
        val restricted = Build.VERSION.SDK_INT >= 28 && runCatching { am.isBackgroundRestricted }.getOrDefault(false)
        val bucket = if (Build.VERSION.SDK_INT >= 28)
            runCatching { c.getSystemService(UsageStatsManager::class.java)?.appStandbyBucket }.getOrNull() else null
        val pm = c.getSystemService(PowerManager::class.java)
        val optimized = runCatching { !pm.isIgnoringBatteryOptimizations(c.packageName) }.getOrDefault(true)
        return Status(
            backgroundRestricted = restricted,
            restrictedBucket = Build.VERSION.SDK_INT >= 30 && bucket == BUCKET_RESTRICTED,
            optimized = optimized,
            samsung = Build.MANUFACTURER.equals("samsung", ignoreCase = true),
            bucket = bucket,
        )
    }

    /** The app's own page in Android's settings (Battery → Unrestricted / Optimised / Restricted is there). */
    fun openAppSettings(c: Context) {
        val i = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${c.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { c.startActivity(i) }
    }

    /** Samsung's battery page (Background usage limits: sleeping / never sleeping apps), else the app's page. */
    fun openSamsungBattery(c: Context) {
        val tries = listOf(
            Intent().setClassName("com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity"),
            Intent().setClassName("com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"),
        )
        for (i in tries) {
            if (runCatching { c.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess) return
        }
        openAppSettings(c)
    }

    private const val BUCKET_RESTRICTED = 45   // UsageStatsManager.STANDBY_BUCKET_RESTRICTED (API 30)

    private fun bucketName(b: Int) = when (b) {
        5 -> "exempted"; 10 -> "active"; 20 -> "working set"; 30 -> "frequent"; 40 -> "rare"; 45 -> "restricted"; 50 -> "never"
        else -> b.toString()
    }
}
