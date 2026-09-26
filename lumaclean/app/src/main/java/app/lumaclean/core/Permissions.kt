package app.lumaclean.core

import android.Manifest
import android.app.AppOpsManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Process
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class PermissionSnapshot(
    val allFiles: Boolean = false,
    val usage: Boolean = false,
    val notifications: Boolean = false,
)

object Perms {
    /** Runtime permissions to request on Android 10 and older instead of all-files access. */
    val legacyStorage = arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE)

    val needsSettingsForFiles: Boolean get() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R

    fun hasAllFiles(context: Context): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Environment.isExternalStorageManager()
        else legacyStorage.all { granted(context, it) }

    @Suppress("DEPRECATION")
    fun hasUsage(context: Context): Boolean {
        val ops = context.getSystemService(AppOpsManager::class.java) ?: return false
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        } else {
            ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun hasNotifications(context: Context): Boolean =
        if (Build.VERSION.SDK_INT >= 33) granted(context, Manifest.permission.POST_NOTIFICATIONS)
        else NotificationManagerCompat.from(context).areNotificationsEnabled()

    fun granted(context: Context, permission: String) =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    fun allFilesIntent(context: Context): Intent =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:${context.packageName}"))
        } else appDetailsIntent(context.packageName)

    fun allFilesFallbackIntent(): Intent =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
        else Intent(Settings.ACTION_SETTINGS)

    fun usageIntent(context: Context): Intent {
        val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
        // Android 10+ can jump straight to this app's row on some builds
        intent.data = Uri.parse("package:${context.packageName}")
        return if (intent.resolveActivity(context.packageManager) != null) intent
        else Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
    }

    fun notificationSettingsIntent(context: Context): Intent =
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)

    fun appDetailsIntent(packageName: String): Intent =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
}

/** The permissions the UI cares about, refreshed whenever the app comes back to the foreground. */
class PermissionState(private val context: Context) {
    private val _state = MutableStateFlow(read())
    val state: StateFlow<PermissionSnapshot> = _state.asStateFlow()

    val current: PermissionSnapshot get() = _state.value

    fun refresh() {
        _state.value = read()
    }

    private fun read() = PermissionSnapshot(
        allFiles = Perms.hasAllFiles(context),
        usage = Perms.hasUsage(context),
        notifications = Perms.hasNotifications(context),
    )
}

/** Starts an activity, falling back quietly when a vendor build lacks the screen. */
fun Context.startSafely(intent: Intent, fallback: Intent? = null): Boolean {
    val flagged = Intent(intent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    return runCatching { startActivity(flagged); true }.getOrElse {
        if (fallback != null) runCatching { startActivity(Intent(fallback).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true }.getOrDefault(false)
        else false
    }
}
