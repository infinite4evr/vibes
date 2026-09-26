package app.lumaclean.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Apps
import androidx.compose.material.icons.rounded.BatteryChargingFull
import androidx.compose.material.icons.rounded.BatteryFull
import androidx.compose.material.icons.rounded.CleaningServices
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.DeleteSweep
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.TaskState
import app.lumaclean.core.formatBytes
import app.lumaclean.core.percent
import app.lumaclean.core.relativeTime
import app.lumaclean.data.FileCategory
import app.lumaclean.data.FileQuery
import app.lumaclean.data.Health
import app.lumaclean.data.HealthAction
import app.lumaclean.data.HealthEngine
import app.lumaclean.data.VolumeInfo
import app.lumaclean.ui.components.IconBadge
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaGrid
import app.lumaclean.ui.components.RingGauge
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SegmentBar
import app.lumaclean.ui.components.StatTile
import app.lumaclean.ui.nav.Navigator
import app.lumaclean.ui.nav.Route
import app.lumaclean.ui.nav.Tab
import app.lumaclean.ui.theme.LocalExtraColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun HomeScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val junkState by c.junkTask.state.collectAsStateWithLifecycle()
    val appsState by c.appsTask.state.collectAsStateWithLifecycle()
    val battery by remember { c.system.batteryFlow() }.collectAsStateWithLifecycle(null)
    val memory by remember { c.system.memoryFlow() }.collectAsStateWithLifecycle(null)
    val bin by c.bin.items.collectAsStateWithLifecycle()
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    val index by c.index.current.collectAsStateWithLifecycle()
    val storage by produceState<VolumeInfo?>(null, junkState, index) {
        value = withContext(Dispatchers.IO) { c.storage.primary() }
    }

    LaunchedEffect(perms.allFiles) { if (perms.allFiles) c.junkTask.ensure() }
    LaunchedEffect(perms.usage) { if (perms.usage) c.appsTask.ensure() }

    val binBytes = bin.sumOf { it.size }
    val health = remember(storage, memory, battery, junkState.value, appsState.value, perms, binBytes) {
        HealthEngine.compute(storage, memory, battery, junkState.value, appsState.value, perms, binBytes)
    }

    ScreenScaffold(
        title = "LumaClean",
        actions = {
            IconButton(onClick = { nav.open(Route.Search) }) { Icon(Icons.Rounded.Search, "Search") }
            IconButton(onClick = { nav.open(Route.Settings) }) { Icon(Icons.Rounded.Settings, "Settings") }
        },
    ) { padding ->
        LumaGrid(padding, minCell = 340.dp) {
            item { HealthCard(health, junkState, nav) }
            item {
                StorageCard(storage, index?.categoryBytes) { nav.select(Tab.STORAGE) }
            }
            item(span = { GridItemSpan(maxLineSpan) }) { QuickActions(nav, settings.largeFileMb) }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    val mem = memory
                    StatTile(
                        icon = Icons.Rounded.Memory,
                        label = "Memory in use",
                        value = mem?.usedFraction?.percent() ?: "—",
                        detail = mem?.let { "${it.available.formatBytes()} free" },
                        modifier = Modifier.weight(1f),
                        onClick = { nav.open(Route.Ram) },
                    )
                    val b = battery
                    StatTile(
                        icon = if (b?.charging == true) Icons.Rounded.BatteryChargingFull else Icons.Rounded.BatteryFull,
                        label = "Battery",
                        value = b?.let { "${it.level}%" } ?: "—",
                        detail = b?.let { "${it.statusText} · ${it.tempC.toInt()}°C" },
                        tint = LocalExtraColors.current.success,
                        modifier = Modifier.weight(1f),
                        onClick = { nav.open(Route.Battery) },
                    )
                }
            }
            item {
                LumaCard(contentPadding = androidx.compose.foundation.layout.PaddingValues(8.dp)) {
                    ItemRow(
                        title = "Cleanup history",
                        subtitle = if (settings.lastCleanAt > 0) "Last: ${settings.lastCleanBytes.formatBytes()} freed ${settings.lastCleanAt.relativeTime()}"
                        else "Nothing cleaned yet",
                        leading = { IconBadge(Icons.Rounded.History, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.History) },
                    )
                    ItemRow(
                        title = "Recycle bin",
                        subtitle = if (bin.isEmpty()) "Empty" else "${bin.size} items · ${binBytes.formatBytes()}",
                        leading = { IconBadge(Icons.Rounded.DeleteSweep, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.RecycleBin) },
                    )
                }
            }
        }
    }
}

@Composable
private fun HealthCard(health: Health, junk: TaskState<*>, nav: Navigator) {
    val extra = LocalExtraColors.current
    val color = when {
        health.score >= 75 -> extra.success
        health.score >= 55 -> extra.warning
        else -> extra.danger
    }
    LumaCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            RingGauge(health.score / 100f, Modifier.size(112.dp), color = color, stroke = 10.dp) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("${health.score}", fontSize = 34.sp, style = MaterialTheme.typography.headlineMedium)
                    Text("of 100", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.width(20.dp))
            Column(Modifier.weight(1f)) {
                Text("Phone health", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(health.label, style = MaterialTheme.typography.headlineSmall)
                Spacer(Modifier.height(4.dp))
                val subtitle = when (junk) {
                    is TaskState.Running -> junk.message
                    else -> if (health.issues.none { it.severity >= 2 }) "Everything looks good" else "${health.issues.count { it.severity >= 2 }} things need a look"
                }
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        if (junk is TaskState.Running) {
            Spacer(Modifier.height(12.dp))
            LinearProgressIndicator(Modifier.fillMaxWidth().clip(RoundedCornerShape(4.dp)))
        }
        if (health.issues.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            health.issues.take(4).forEach { issue ->
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    val dot = when (issue.severity) {
                        3 -> extra.danger
                        2 -> extra.warning
                        else -> MaterialTheme.colorScheme.primary
                    }
                    Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(issue.title, style = MaterialTheme.typography.bodyMedium)
                        Text(issue.detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    TextButton(onClick = { runHealthAction(issue.action, nav) }) { Text(issue.actionLabel) }
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        Button(onClick = { nav.select(Tab.CLEAN) }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Rounded.CleaningServices, null, Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Smart Clean")
        }
    }
}

fun runHealthAction(action: HealthAction, nav: Navigator) {
    when (action) {
        HealthAction.CLEAN -> nav.select(Tab.CLEAN)
        HealthAction.STORAGE -> nav.select(Tab.STORAGE)
        HealthAction.UNUSED_APPS -> nav.open(Route.UnusedApps)
        HealthAction.BATTERY -> nav.open(Route.Battery)
        HealthAction.RAM -> nav.open(Route.Ram)
        HealthAction.PERMISSIONS -> nav.open(Route.Permissions)
        HealthAction.RECYCLE_BIN -> nav.open(Route.RecycleBin)
        HealthAction.DUPLICATES -> nav.open(Route.Duplicates)
    }
}

@Composable
private fun StorageCard(storage: VolumeInfo?, categories: Map<FileCategory, Long>?, onClick: () -> Unit) {
    val extra = LocalExtraColors.current
    LumaCard(onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBadge(Icons.Rounded.Storage, MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(12.dp))
            Text("Internal storage", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            storage?.let { Text(it.usedFraction.percent(), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary) }
        }
        Spacer(Modifier.height(16.dp))
        if (storage == null) {
            LinearProgressIndicator(Modifier.fillMaxWidth())
            return@LumaCard
        }
        Text(
            "${storage.used.formatBytes()} used",
            style = MaterialTheme.typography.headlineSmall,
        )
        Text("of ${storage.total.formatBytes()} · ${storage.free.formatBytes()} free", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(14.dp))
        val total = storage.total.toFloat().coerceAtLeast(1f)
        val segments = if (categories != null) {
            val files = FileCategory.entries.map { (categories[it] ?: 0L) / total to extra.categories.getValue(it) }
            val other = (storage.used - categories.values.sum()).coerceAtLeast(0) / total
            files + (other to extra.system)
        } else listOf(storage.usedFraction to MaterialTheme.colorScheme.primary)
        SegmentBar(segments)
        if (categories != null) {
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                listOf(FileCategory.IMAGES, FileCategory.VIDEOS, FileCategory.AUDIO, FileCategory.DOCUMENTS).forEach { cat ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).clip(CircleShape).background(extra.categories.getValue(cat)))
                        Spacer(Modifier.width(4.dp))
                        Text(cat.label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

@Composable
private fun QuickActions(nav: Navigator, largeMb: Int) {
    val actions = listOf(
        Triple("Smart Clean", Icons.Rounded.CleaningServices) { nav.select(Tab.CLEAN) },
        Triple("Free RAM", Icons.Rounded.Memory) { nav.open(Route.Ram) },
        Triple("Large files", Icons.Rounded.Storage) { nav.open(Route.Files(FileQuery.Large(largeMb * 1_000_000L))) },
        Triple("Duplicates", Icons.Rounded.ContentCopy) { nav.open(Route.Duplicates) },
        Triple("Similar photos", Icons.Rounded.PhotoLibrary) { nav.open(Route.Similar) },
        Triple("Unused apps", Icons.Rounded.Apps) { nav.open(Route.UnusedApps) },
    )
    LumaCard(contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 16.dp, horizontal = 8.dp)) {
        Text("Quick actions", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = 12.dp, bottom = 8.dp))
        androidx.compose.foundation.layout.BoxWithConstraints {
            val perRow = if (maxWidth > 560.dp) 6 else 3
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                actions.chunked(perRow).forEach { row ->
                    Row(Modifier.fillMaxWidth()) {
                        row.forEach { (label, icon, onClick) -> QuickAction(label, icon, onClick, Modifier.weight(1f)) }
                        repeat(perRow - row.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
            }
        }
    }
}

@Composable
private fun QuickAction(label: String, icon: ImageVector, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Column(
        modifier.clip(RoundedCornerShape(16.dp)).clickable(onClick = onClick).padding(vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        IconBadge(icon, MaterialTheme.colorScheme.primary, size = 48.dp)
        Spacer(Modifier.height(6.dp))
        Text(label, style = MaterialTheme.typography.labelMedium, textAlign = TextAlign.Center, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

