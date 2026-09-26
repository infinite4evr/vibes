package app.lumaclean.work

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.lumaclean.LumaApp
import app.lumaclean.MainActivity
import app.lumaclean.R
import app.lumaclean.core.Perms
import app.lumaclean.core.Progress
import app.lumaclean.core.formatBytes
import app.lumaclean.data.AppSettings
import app.lumaclean.data.BatteryPoint
import java.util.concurrent.TimeUnit

object Notifier {
    const val CHANNEL_CHECKUP = "checkup"
    const val CHANNEL_ALERTS = "alerts"

    fun createChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_CHECKUP, "Weekly checkup", NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = "How much space a cleanup would free" },
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ALERTS, "Alerts", NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "Storage almost full, battery too hot" },
        )
    }

    @SuppressLint("MissingPermission")
    fun show(context: Context, id: Int, channel: String, title: String, text: String, route: String) {
        if (!Perms.hasNotifications(context)) return
        val intent = Intent(context, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_ROUTE, route)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pending = PendingIntent.getActivity(
            context, id, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val n = NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat_luma)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).notify(id, n)
    }
}

object Scheduler {
    private const val CHECKUP = "weekly-checkup"
    private const val MONITOR = "monitor"

    fun apply(context: Context, s: AppSettings) {
        val wm = WorkManager.getInstance(context)
        // the checkup also empties expired recycle-bin items, so it always runs
        val checkup = PeriodicWorkRequestBuilder<CheckupWorker>(7, TimeUnit.DAYS)
            .setConstraints(Constraints.Builder().setRequiresBatteryNotLow(true).build())
            .setInitialDelay(1, TimeUnit.DAYS)
            .build()
        wm.enqueueUniquePeriodicWork(CHECKUP, ExistingPeriodicWorkPolicy.KEEP, checkup)

        // battery history needs samples; alerts ride along
        val monitor = PeriodicWorkRequestBuilder<MonitorWorker>(15, TimeUnit.MINUTES).build()
        wm.enqueueUniquePeriodicWork(MONITOR, ExistingPeriodicWorkPolicy.KEEP, monitor)
    }
}

class CheckupWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val c = (applicationContext as LumaApp).container
        val s = c.settings.current
        c.bin.purgeOlderThan(s.recycleDays)

        if (s.weeklyCheckup && Perms.hasAllFiles(applicationContext)) {
            val report = runCatching { c.junk.scan(Progress.None) }.getOrNull()
            if (report != null && report.totalBytes >= 300_000_000) {
                Notifier.show(
                    applicationContext, 1, Notifier.CHANNEL_CHECKUP,
                    "${report.totalBytes.formatBytes()} can be cleaned",
                    "Your weekly checkup found junk files. ${report.safeBytes.formatBytes()} of it is safe to remove in one tap.",
                    "clean",
                )
            }
        }
        checkStorage(c.storage.primary().usedFraction, c.settings.current, c.settings)
        return Result.success()
    }

    private fun checkStorage(fraction: Float, s: AppSettings, settings: app.lumaclean.data.SettingsRepository) {
        if (!s.storageAlerts || fraction < 0.9f) return
        if (System.currentTimeMillis() - settings.stamp("storageAlert") < 3 * 24 * 3600_000L) return
        settings.setStamp("storageAlert")
        Notifier.show(
            applicationContext, 2, Notifier.CHANNEL_ALERTS,
            "Storage is ${(fraction * 100).toInt()}% full",
            "Your phone may slow down. Open LumaClean to see what's taking up space.",
            "storage",
        )
    }
}

class MonitorWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val c = (applicationContext as LumaApp).container
        val s = c.settings.current
        val b = c.system.battery() ?: return Result.success()
        c.batteryLog.add(BatteryPoint(System.currentTimeMillis(), b.level, b.tempC, b.charging))

        if (s.batteryAlerts && b.tempC >= 45f && System.currentTimeMillis() - c.settings.stamp("heatAlert") > 6 * 3600_000L) {
            c.settings.setStamp("heatAlert")
            Notifier.show(
                applicationContext, 3, Notifier.CHANNEL_ALERTS,
                "Battery is hot: ${b.tempC.toInt()}°C",
                if (b.charging) "Unplug or move the phone somewhere cooler. Heat wears batteries out fastest while charging."
                else "Close heavy apps and let the phone cool down.",
                "battery",
            )
        }
        val storage = c.storage.primary()
        if (s.storageAlerts && storage.usedFraction >= 0.95f &&
            System.currentTimeMillis() - c.settings.stamp("storageAlert") > 24 * 3600_000L
        ) {
            c.settings.setStamp("storageAlert")
            Notifier.show(
                applicationContext, 2, Notifier.CHANNEL_ALERTS,
                "Storage almost full",
                "Only ${storage.free.formatBytes()} left. Apps may stop working properly.",
                "storage",
            )
        }
        return Result.success()
    }
}
