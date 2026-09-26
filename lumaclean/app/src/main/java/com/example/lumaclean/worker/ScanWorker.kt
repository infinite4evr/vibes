package com.example.lumaclean.worker

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.example.lumaclean.data.JunkScanner
import com.example.lumaclean.util.formatBytes
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class ScanWorker(appContext: Context, params: WorkerParameters) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val junk = JunkScanner(applicationContext).scan()
        val bytes = junk.sumOf { it.sizeBytes }
        if (bytes > 100L * 1024 * 1024) notify(bytes)
        Result.success()
    }

    private fun notify(bytes: Long) {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel("cleanup", "Cleanup suggestions", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            applicationContext.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return

        val notification = NotificationCompat.Builder(applicationContext, "cleanup")
            .setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentTitle("LumaClean found space to review")
            .setContentText("About ${formatBytes(bytes)} can be reviewed for cleanup.")
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(applicationContext).notify(41, notification)
    }
}
