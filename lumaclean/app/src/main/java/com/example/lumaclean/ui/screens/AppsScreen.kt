package com.example.lumaclean.ui.screens

import android.app.Activity
import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.lumaclean.data.SystemActions
import com.example.lumaclean.model.InstalledAppInfo
import com.example.lumaclean.ui.components.PermissionBanner
import com.example.lumaclean.util.formatBytes
import com.example.lumaclean.util.formatDate

@Composable
fun AppsScreen(
    context: Context,
    activity: Activity,
    apps: List<InstalledAppInfo>,
    busy: Boolean,
    hasUsageAccess: Boolean,
    onUsageAccess: () -> Unit,
    onLoad: () -> Unit
) {
    var guideIndex by remember(apps) { mutableIntStateOf(-1) }
    val cacheApps = remember(apps) { apps.filter { it.cacheBytes > 0 }.sortedByDescending { it.cacheBytes } }
    val guided = guideIndex >= 0 && cacheApps.isNotEmpty()
    val current = if (guided) cacheApps[guideIndex.coerceIn(cacheApps.indices)] else null

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("App manager", style = MaterialTheme.typography.headlineSmall)
            Text("Inspect cache/storage, spot unused apps, open Android's per-app cleanup page, or uninstall.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (!hasUsageAccess) item {
            PermissionBanner(
                "Usage Access recommended",
                "Android requires a Settings grant before another app can read per-app storage and last-used statistics.",
                "Grant Usage Access",
                onUsageAccess
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onLoad, enabled = !busy, modifier = Modifier.weight(1f)) { Text(if (busy) "Loading…" else "Refresh") }
                FilledTonalButton(
                    onClick = {
                        val launched = SystemActions.requestClearAllCaches(activity)
                        if (!launched && cacheApps.isNotEmpty()) guideIndex = 0
                    },
                    enabled = apps.isNotEmpty(),
                    modifier = Modifier.weight(1f)
                ) { Text("Clean caches") }
            }
            Text(
                "LumaClean first asks Android to clear caches through the system flow. If that isn't available, use the guided per-app cleaner below.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        if (current != null) item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(.55f))) {
                Column(Modifier.padding(16.dp)) {
                    Text("Guided cache clean ${guideIndex + 1}/${cacheApps.size}", fontWeight = FontWeight.SemiBold)
                    Text(current.label, style = MaterialTheme.typography.titleMedium)
                    Text("Cache ${formatBytes(current.cacheBytes)}", color = MaterialTheme.colorScheme.primary)
                    Text("Open Android's app page, tap Storage & cache → Clear cache, then return here and continue.", style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Button(onClick = { SystemActions.openAppDetails(context, current.packageName) }) { Text("Open settings") }
                        TextButton(onClick = {
                            guideIndex = if (guideIndex >= cacheApps.lastIndex) -1 else guideIndex + 1
                        }) { Text(if (guideIndex >= cacheApps.lastIndex) "Finish" else "Next") }
                        TextButton(onClick = { guideIndex = -1 }) { Text("Stop") }
                    }
                }
            }
        }

        items(apps, key = { it.packageName }) { app ->
            Card {
                Column(Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(app.label, fontWeight = FontWeight.SemiBold)
                            Text(app.packageName, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text(formatBytes(app.cacheBytes), color = MaterialTheme.colorScheme.primary)
                    }
                    Spacer(Modifier.height(6.dp))
                    val unused = app.lastUsed > 0 && System.currentTimeMillis() - app.lastUsed > 30L * 24 * 60 * 60 * 1000
                    Text("Total ${formatBytes(app.totalBytes)} • Last used ${formatDate(app.lastUsed)}", style = MaterialTheme.typography.bodySmall)
                    if (unused) Text("Unused for 30+ days", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { SystemActions.openAppDetails(context, app.packageName) }) { Text("Storage & cache") }
                        if (!app.systemApp) TextButton(onClick = { SystemActions.uninstall(context, app.packageName) }) { Text("Uninstall") }
                    }
                }
            }
        }
        item { Spacer(Modifier.height(90.dp)) }
    }
}
