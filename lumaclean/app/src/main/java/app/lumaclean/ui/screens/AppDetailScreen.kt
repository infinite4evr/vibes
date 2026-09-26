package app.lumaclean.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.AssistChip
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.Perms
import app.lumaclean.core.Progress
import app.lumaclean.core.UiMessage
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatDate
import app.lumaclean.core.formatDuration
import app.lumaclean.core.relativeTime
import app.lumaclean.core.startSafely
import app.lumaclean.data.AppInfo
import app.lumaclean.data.AppPermission
import app.lumaclean.data.AppUsage
import app.lumaclean.ui.components.AppIcon
import app.lumaclean.ui.components.KeyValue
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.Meter
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.theme.LocalExtraColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

fun androidVersionName(sdk: Int): String = when (sdk) {
    in 0..25 -> "Android 7 or older"
    26 -> "Android 8.0"
    27 -> "Android 8.1"
    28 -> "Android 9"
    29 -> "Android 10"
    30 -> "Android 11"
    31 -> "Android 12"
    32 -> "Android 12L"
    33 -> "Android 13"
    34 -> "Android 14"
    35 -> "Android 15"
    36 -> "Android 16"
    37 -> "Android 17"
    else -> "API $sdk"
}

@Composable
fun AppDetailScreen(packageName: String) {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val perms by c.perms.state.collectAsStateWithLifecycle()
    var refresh by remember { mutableStateOf(0) }

    val app by produceState(c.appsTask.value?.find { it.packageName == packageName }, packageName, refresh) {
        value = withContext(Dispatchers.IO) { c.apps.loadOne(packageName) } ?: value
    }
    val permissions by produceState<List<AppPermission>?>(null, packageName) {
        value = withContext(Dispatchers.IO) { c.apps.permissions(packageName) }
    }
    val usage by produceState<AppUsage?>(null, packageName, perms.usage) {
        if (perms.usage) {
            value = withContext(Dispatchers.IO) {
                runCatching { c.apps.usage(7, Progress.None).apps.find { it.packageName == packageName } }.getOrNull()
            }
        }
    }
    val uninstaller = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (!c.apps.isInstalled(packageName)) {
            c.appsTask.update { list -> list.filter { it.packageName != packageName } }
            c.message("Uninstalled")
            nav.back()
        } else refresh++
    }

    val a = app
    ScreenScaffold(title = a?.label ?: "App", onBack = { nav.back() }) { padding ->
        LumaList(padding) {
            if (a == null) {
                item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                return@LumaList
            }
            item { Header(a, onOpen = { c.apps.launchIntent(packageName)?.let { context.startSafely(it) } }, onUninstall = {
                runCatching { uninstaller.launch(uninstallIntent(packageName)) }
            }, onInfo = { context.startSafely(Perms.appDetailsIntent(packageName)) }) }
            item { StorageSection(a, onManage = { context.startSafely(Perms.appDetailsIntent(packageName)) }) }
            item {
                LumaCard {
                    Text("Usage", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    if (!perms.usage) {
                        Text("Allow usage access to see screen time and data use.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        KeyValue("Last used", if (a.lastUsed > 0) a.lastUsed.relativeTime() else "Not in the past year")
                        KeyValue("Screen time, 7 days", usage?.foregroundMs?.formatDuration() ?: "—")
                        KeyValue("Wi-Fi data, 7 days", usage?.wifiBytes?.formatBytes() ?: "—")
                        KeyValue("Mobile data, 7 days", usage?.mobileBytes?.formatBytes() ?: "—")
                    }
                }
            }
            item {
                LumaCard {
                    Text("Installer file", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Keep a copy of this app to reinstall later or send to another phone." +
                            if (a.splitCount > 0) " This app is split into ${a.splitCount + 1} parts, so it's saved as an .apks bundle." else "",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilledTonalButton(onClick = {
                            c.operations.run("Saving installer") {
                                val where = c.apps.backupApk(a)
                                UiMessage("Saved to $where")
                            }
                        }) {
                            Icon(Icons.Rounded.Save, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("Save APK")
                        }
                        FilledTonalButton(onClick = {
                            scope.launch {
                                val intent = withContext(Dispatchers.IO) { runCatching { c.apps.shareApkIntent(a) }.getOrNull() }
                                if (intent != null) context.startSafely(intent) else c.message("Couldn't prepare the file")
                            }
                        }) {
                            Icon(Icons.Rounded.Share, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("Share")
                        }
                    }
                }
            }
            item {
                LumaCard {
                    Text("Details", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    KeyValue("Version", "${a.versionName} (${a.versionCode})")
                    KeyValue("Installed", a.firstInstall.formatDate())
                    KeyValue("Last updated", a.lastUpdate.formatDate())
                    KeyValue("Installed from", a.installer)
                    KeyValue("Built for", androidVersionName(a.targetSdk))
                    if (a.minSdk > 0) KeyValue("Needs at least", androidVersionName(a.minSdk))
                    KeyValue("Package", a.packageName)
                    KeyValue("User ID", a.uid.toString())
                    KeyValue("Status", if (a.enabled) "Enabled" else "Disabled")
                }
            }
            item { PermissionsSection(permissions) }
        }
    }
}

@Composable
private fun Header(a: AppInfo, onOpen: () -> Unit, onUninstall: () -> Unit, onInfo: () -> Unit) {
    LumaCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            AppIcon(a.packageName, size = 64.dp)
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f)) {
                Text(a.label, style = MaterialTheme.typography.headlineSmall)
                Text("Version ${a.versionName}", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(4.dp))
                AssistChip(onClick = {}, label = { Text(a.installer) })
            }
        }
        Spacer(Modifier.height(16.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            if (a.launchable) Action(Icons.AutoMirrored.Rounded.OpenInNew, "Open", onOpen)
            if (a.canUninstall) Action(Icons.Rounded.Delete, if (a.system) "Remove updates" else "Uninstall", onUninstall)
            Action(Icons.Rounded.Info, "App info", onInfo)
        }
    }
}

@Composable
private fun Action(icon: ImageVector, label: String, onClick: () -> Unit) {
    TextButton(onClick = onClick) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, null)
            Spacer(Modifier.height(4.dp))
            Text(label, style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
private fun StorageSection(a: AppInfo, onManage: () -> Unit) {
    LumaCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Storage", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            Text(a.totalBytes.formatBytes(), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
        }
        Spacer(Modifier.height(12.dp))
        if (!a.hasSizes) {
            Text("Allow usage access to see how much space the app's data and cache take.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        val total = a.totalBytes.coerceAtLeast(1).toFloat()
        listOf("App" to a.appBytes, "Data" to (a.dataBytes - a.cacheBytes).coerceAtLeast(0), "Cache" to a.cacheBytes).forEach { (label, bytes) ->
            KeyValue(label, bytes.formatBytes())
            Meter(bytes / total, MaterialTheme.colorScheme.primary, height = 4.dp)
        }
        Spacer(Modifier.height(8.dp))
        TextButton(onClick = onManage) { Text("Clear cache or data in Android settings") }
    }
}

@Composable
private fun PermissionsSection(permissions: List<AppPermission>?) {
    var showAll by remember { mutableStateOf(false) }
    LumaCard(contentPadding = PaddingValues(20.dp)) {
        Text("Permissions", style = MaterialTheme.typography.titleMedium)
        if (permissions == null) {
            LinearProgressIndicator(Modifier.fillMaxWidth())
            return@LumaCard
        }
        val sensitive = permissions.filter { it.sensitive }
        Text(
            "${sensitive.count { it.granted }} of ${sensitive.size} sensitive permissions allowed · ${permissions.size} requested in total",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        val shown = if (showAll) permissions else sensitive
        shown.forEach { p ->
            Row(Modifier.fillMaxWidth().height(36.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (p.granted) Icons.Rounded.CheckCircle else Icons.Rounded.Block,
                    if (p.granted) "Allowed" else "Not allowed",
                    tint = if (p.granted) LocalExtraColors.current.success else MaterialTheme.colorScheme.outline,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(12.dp))
                Text(p.label, style = MaterialTheme.typography.bodyMedium, maxLines = 1)
            }
        }
        if (permissions.size > sensitive.size) {
            TextButton(onClick = { showAll = !showAll }) { Text(if (showAll) "Show sensitive only" else "Show all ${permissions.size}") }
        }
    }
}
