package app.lumaclean.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Apps
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.DeleteSweep
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.SdCard
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material.icons.rounded.Straighten
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.TaskState
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import app.lumaclean.core.relativeTime
import app.lumaclean.data.FileCategory
import app.lumaclean.data.FileIndex
import app.lumaclean.data.FileQuery
import app.lumaclean.data.VolumeInfo
import app.lumaclean.ui.components.FilesPermissionCard
import app.lumaclean.ui.components.IconBadge
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SectionHeader
import app.lumaclean.ui.components.SegmentBar
import app.lumaclean.ui.components.SmallTonalButton
import app.lumaclean.ui.components.TaskProgressCard
import app.lumaclean.ui.components.categoryIcon
import app.lumaclean.ui.nav.Route
import app.lumaclean.ui.nav.Tab
import app.lumaclean.ui.theme.LocalExtraColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun StorageScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    val indexState by c.indexTask.state.collectAsStateWithLifecycle()
    val index by c.index.current.collectAsStateWithLifecycle()
    val apps by c.appsTask.state.collectAsStateWithLifecycle()
    val bin by c.bin.items.collectAsStateWithLifecycle()
    val volumes by produceState(emptyList<VolumeInfo>(), index) { value = withContext(Dispatchers.IO) { c.storage.volumes() } }

    LaunchedEffect(perms.allFiles) { if (perms.allFiles && c.index.current.value == null) c.indexTask.ensure() }
    LaunchedEffect(perms.usage) { if (perms.usage) c.appsTask.ensure() }

    ScreenScaffold(
        title = "Storage",
        subtitle = index?.let { "Analyzed ${it.builtAt.relativeTime()}" },
        actions = {
            IconButton(onClick = { nav.open(Route.Search) }) { Icon(Icons.Rounded.Search, "Search files") }
            IconButton(onClick = { c.refreshIndex() }, enabled = perms.allFiles && indexState !is TaskState.Running) {
                Icon(Icons.Rounded.Refresh, "Analyze again")
            }
        },
    ) { padding ->
        LumaList(padding) {
            if (!perms.allFiles) item { FilesPermissionCard(reason = "to show what's using your storage") }
            volumes.firstOrNull()?.let { primary ->
                item {
                    val appsBytes = apps.value?.sumOf { it.totalBytes }
                    PrimaryVolumeCard(primary, index, appsBytes, onCategory = { nav.open(Route.Files(FileQuery.Category(it))) }, onApps = { nav.select(Tab.APPS) })
                }
            }
            (indexState as? TaskState.Running<*>)?.let { s ->
                item { TaskProgressCard(s, "Analyzing storage", onCancel = { c.indexTask.cancel() }) }
            }
            item { SectionHeader("Explore") }
            item {
                LumaCard(contentPadding = PaddingValues(8.dp)) {
                    val root = c.index.root
                    ItemRow(
                        "Browse files", subtitle = "Every folder, largest first",
                        leading = { IconBadge(Icons.Rounded.Folder, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.Browser(root)) },
                    )
                    ItemRow(
                        "Large files", subtitle = "Files over ${settings.largeFileMb} MB",
                        leading = { IconBadge(Icons.Rounded.Straighten, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.Files(FileQuery.Large(settings.largeFileMb * 1_000_000L))) },
                    )
                    ItemRow(
                        "Duplicate files", subtitle = "Exact copies, checked byte for byte",
                        leading = { IconBadge(Icons.Rounded.ContentCopy, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.Duplicates) },
                    )
                    ItemRow(
                        "Old downloads", subtitle = "Untouched for ${settings.oldDownloadDays}+ days",
                        leading = { IconBadge(Icons.Rounded.Download, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.Files(FileQuery.OldDownloads(settings.oldDownloadDays))) },
                    )
                    ItemRow(
                        "Chat media", subtitle = "WhatsApp, Telegram and Signal files",
                        leading = { IconBadge(Icons.Rounded.Forum, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.ChatMedia) },
                    )
                    ItemRow(
                        "Recycle bin", subtitle = if (bin.isEmpty()) "Empty" else "${bin.size} items · ${bin.sumOf { it.size }.formatBytes()}",
                        leading = { IconBadge(Icons.Rounded.DeleteSweep, MaterialTheme.colorScheme.primary) },
                        onClick = { nav.open(Route.RecycleBin) },
                    )
                }
            }
            volumes.drop(1).forEach { vol ->
                item {
                    LumaCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            IconBadge(Icons.Rounded.SdCard, MaterialTheme.colorScheme.tertiary)
                            Spacer(Modifier.width(12.dp))
                            Text(vol.name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                            Text("${vol.used.formatBytes()} of ${vol.total.formatBytes()}", style = MaterialTheme.typography.bodySmall)
                        }
                        Spacer(Modifier.height(12.dp))
                        SegmentBar(listOf(vol.usedFraction to MaterialTheme.colorScheme.tertiary))
                        Spacer(Modifier.height(12.dp))
                        vol.path?.let { p -> SmallTonalButton("Browse", onClick = { nav.open(Route.Browser(p)) }) }
                    }
                }
            }
        }
    }
}

@Composable
private fun PrimaryVolumeCard(
    vol: VolumeInfo,
    index: FileIndex?,
    appsBytes: Long?,
    onCategory: (FileCategory) -> Unit,
    onApps: () -> Unit,
) {
    val extra = LocalExtraColors.current
    LumaCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBadge(Icons.Rounded.Storage, MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(12.dp))
            Text(vol.name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
        }
        Spacer(Modifier.height(12.dp))
        Text("${vol.used.formatBytes()} used", style = MaterialTheme.typography.headlineMedium)
        Text("${vol.free.formatBytes()} free of ${vol.total.formatBytes()}", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(16.dp))
        val total = vol.total.toFloat().coerceAtLeast(1f)
        if (index == null) {
            SegmentBar(listOf(vol.usedFraction to MaterialTheme.colorScheme.primary))
            return@LumaCard
        }
        val cats = FileCategory.entries.map { it to (index.categoryBytes[it] ?: 0L) }.filter { it.second > 0 }.sortedByDescending { it.second }
        val filesBytes = index.totalBytes
        val apps = appsBytes ?: 0L
        val system = (vol.used - filesBytes - apps).coerceAtLeast(0)
        val segments = cats.map { (cat, b) -> b / total to extra.categories.getValue(cat) } +
            listOf(apps / total to extra.apps, system / total to extra.system)
        SegmentBar(segments)
        Spacer(Modifier.height(8.dp))
        cats.forEach { (cat, bytes) ->
            LegendRow(
                color = extra.categories.getValue(cat),
                label = cat.label,
                detail = "${(index.categoryCounts[cat] ?: 0).formatCount()} files",
                bytes = bytes,
                icon = categoryIcon(cat),
                onClick = { onCategory(cat) },
            )
        }
        if (appsBytes != null) LegendRow(extra.apps, "Apps & app data", "Installed apps", apps, Icons.Rounded.Apps, onApps)
        LegendRow(extra.system, "System & other", "Android itself and files apps keep private", system, Icons.Rounded.Storage, null)
        if (index.truncated) {
            Text("Very large storage: only the first 600,000 files were analyzed.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun LegendRow(
    color: Color,
    label: String,
    detail: String,
    bytes: Long,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: (() -> Unit)?,
) {
    ItemRow(
        title = label,
        subtitle = detail,
        leading = {
            Box(contentAlignment = Alignment.Center) {
                IconBadge(icon, color, size = 36.dp)
            }
        },
        trailing = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(color))
                Spacer(Modifier.width(8.dp))
                Text(bytes.formatBytes(), style = MaterialTheme.typography.titleSmall)
            }
        },
        onClick = onClick,
    )
}

@Composable
fun IndexLoading(state: TaskState<*>, onCancel: () -> Unit) {
    if (state is TaskState.Running) TaskProgressCard(state, "Analyzing storage", onCancel)
    else LinearProgressIndicator()
}
