package app.lumaclean.ui.screens

import android.content.Intent
import android.os.Build
import android.os.storage.StorageManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Android
import androidx.compose.material.icons.rounded.Cached
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.CleaningServices
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.InsertDriveFile
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Timer
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TriStateCheckbox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.TaskState
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import app.lumaclean.core.relativeTime
import app.lumaclean.core.startSafely
import app.lumaclean.data.JunkGroup
import app.lumaclean.data.JunkItem
import app.lumaclean.data.JunkKind
import app.lumaclean.ui.components.ConfirmDialog
import app.lumaclean.ui.components.EmptyState
import app.lumaclean.ui.components.ErrorCard
import app.lumaclean.ui.components.FilesPermissionCard
import app.lumaclean.ui.components.HeroCard
import app.lumaclean.ui.components.IconBadge
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SelectionBar
import app.lumaclean.ui.components.SmallTonalButton
import app.lumaclean.ui.components.TaskProgressCard
import app.lumaclean.ui.theme.LocalExtraColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

private fun kindIcon(kind: JunkKind): ImageVector = when (kind) {
    JunkKind.APP_CACHE -> Icons.Rounded.Cached
    JunkKind.THUMBNAILS -> Icons.Rounded.Image
    JunkKind.TEMP -> Icons.Rounded.Timer
    JunkKind.LOGS -> Icons.Rounded.Description
    JunkKind.APKS -> Icons.Rounded.Android
    JunkKind.LEFTOVERS -> Icons.Rounded.Folder
    JunkKind.EMPTY_FOLDERS -> Icons.Rounded.FolderOpen
    JunkKind.EMPTY_FILES -> Icons.Rounded.InsertDriveFile
    JunkKind.DELETED_MEDIA -> Icons.Rounded.Delete
    JunkKind.OLD_DOWNLOADS -> Icons.Rounded.Download
}

@Composable
fun CleanScreen() {
    val c = LocalContainer.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val state by c.junkTask.state.collectAsStateWithLifecycle()
    val report = state.value

    var selected by remember(report?.finishedAt) { mutableStateOf(report?.defaultSelection ?: emptySet()) }
    var expanded by remember { mutableStateOf(setOf<JunkKind>()) }
    var confirm by remember { mutableStateOf(false) }
    var exclude by remember { mutableStateOf<JunkItem?>(null) }

    LaunchedEffect(perms.allFiles) { c.junkTask.ensure() }

    val allItems = report?.groups?.flatMap { it.items }.orEmpty()
    val chosen = allItems.filter { it.path in selected }
    val chosenBytes = chosen.sumOf { it.size }

    ScreenScaffold(
        title = "Smart Clean",
        subtitle = report?.let {
            if (it.scannedFiles > 0) "${it.scannedFiles.formatCount()} files checked ${it.finishedAt.relativeTime()}"
            else "Checked ${it.finishedAt.relativeTime()}"
        },
        actions = {
            IconButton(onClick = { c.junkTask.restart() }, enabled = state !is TaskState.Running) {
                Icon(Icons.Rounded.Refresh, "Scan again")
            }
        },
        bottomBar = {
            if (report != null && allItems.isNotEmpty()) {
                SelectionBar(
                    text = if (chosen.isEmpty()) "Nothing selected" else "${chosen.size.formatCount()} items · ${chosenBytes.formatBytes()}",
                    primaryLabel = "Clean",
                    onPrimary = { confirm = true },
                    onClear = { selected = emptySet() },
                    primaryEnabled = chosen.isNotEmpty() && state !is TaskState.Running,
                    destructive = false,
                )
            }
        },
    ) { padding ->
        LumaList(padding) {
            if (!perms.allFiles) item { FilesPermissionCard() }
            when (val s = state) {
                is TaskState.Running -> item { TaskProgressCard(s, "Looking for junk", onCancel = { c.junkTask.cancel() }) }
                is TaskState.Failed -> item { ErrorCard(s.message) { c.junkTask.restart() } }
                TaskState.Idle -> item {
                    HeroCard(
                        Icons.Rounded.CleaningServices,
                        "Find junk files",
                        "Caches, leftovers, old installers and empty folders. Nothing is removed until you tap Clean.",
                        "Scan now",
                        onClick = { c.junkTask.restart() },
                    )
                }
                is TaskState.Done -> {}
            }
            if (report != null) {
                item { Summary(report.totalBytes, chosenBytes, onSafe = { selected = report.defaultSelection }, onAll = { selected = allItems.map { it.path }.toSet() }, onNone = { selected = emptySet() }) }
                item { SystemCacheCard(report.otherAppsCache, perms.allFiles, perms.usage) }
                if (report.groups.isEmpty() && state is TaskState.Done) {
                    item { EmptyState(Icons.Rounded.CheckCircle, "No junk found", "Your phone is already clean. Check back in a week.") }
                }
                report.groups.forEach { group ->
                    item(key = group.kind.name) {
                        JunkGroupCard(
                            group = group,
                            selected = selected,
                            expanded = group.kind in expanded,
                            onExpand = { expanded = if (group.kind in expanded) expanded - group.kind else expanded + group.kind },
                            onToggleGroup = { on ->
                                val paths = group.items.map { it.path }
                                selected = if (on) selected + paths else selected - paths.toSet()
                            },
                            onToggle = { item -> selected = if (item.path in selected) selected - item.path else selected + item.path },
                            onLongPress = { exclude = it },
                        )
                    }
                }
                if (report.groups.isNotEmpty()) {
                    item {
                        Text(
                            "Long-press any item to never clean it. Safe items are pre-selected; the rest are worth a look first.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 8.dp),
                        )
                    }
                }
            }
        }
    }

    if (confirm) {
        ConfirmDialog(
            title = "Clean ${chosenBytes.formatBytes()}?",
            text = "${chosen.size.formatCount()} items will be deleted for good. Apps rebuild caches and thumbnails when they need them.",
            confirmLabel = "Clean",
            destructive = false,
            onConfirm = { c.cleanJunk(chosen) },
            onDismiss = { confirm = false },
        )
    }
    exclude?.let { item ->
        ConfirmDialog(
            title = "Never clean this?",
            text = "\"${item.name}\" will be skipped by every future scan. You can undo this in Settings › Never clean.",
            confirmLabel = "Never clean",
            destructive = false,
            onConfirm = {
                c.exclusions.add(item.path)
                c.junkTask.update { it.without(setOf(item.path)) }
            },
            onDismiss = { exclude = null },
        )
    }
}

@Composable
private fun Summary(total: Long, chosen: Long, onSafe: () -> Unit, onAll: () -> Unit, onNone: () -> Unit) {
    LumaCard {
        Text("Junk found", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(total.formatBytes(), style = MaterialTheme.typography.displaySmall)
        Text("${chosen.formatBytes()} selected", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = false, onClick = onSafe, label = { Text("Safe only") })
            FilterChip(selected = false, onClick = onAll, label = { Text("All") })
            FilterChip(selected = false, onClick = onNone, label = { Text("None") })
        }
    }
}

@Composable
private fun SystemCacheCard(bytes: Long?, allFiles: Boolean, usage: Boolean) {
    val c = LocalContainer.current
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        c.scope.launch(Dispatchers.IO) {
            val left = c.junk.otherAppsCache()
            c.junkTask.update { it.copy(otherAppsCache = left) }
            if (bytes != null && bytes > left) {
                c.history.add("Cleared app caches", 1, bytes - left)
                c.message("Cleared ${(bytes - left).formatBytes()} of app caches")
            }
        }
    }
    LumaCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBadge(Icons.Rounded.Cached, MaterialTheme.colorScheme.tertiary)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text("Other apps' cache", style = MaterialTheme.typography.titleMedium)
                Text(
                    when {
                        bytes != null -> "${bytes.formatBytes()} in temporary files"
                        !usage -> "Allow usage access to measure it"
                        else -> "Measuring…"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            "Android can clear every app's cache in one step. You stay signed in everywhere; apps just rebuild temporary files.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            SmallTonalButton("Clear all app caches", enabled = allFiles, onClick = {
                runCatching { launcher.launch(Intent(StorageManager.ACTION_CLEAR_APP_CACHE)) }
                    .onFailure { context.startSafely(Intent(Settings.ACTION_INTERNAL_STORAGE_SETTINGS)) }
            })
        } else {
            SmallTonalButton("Open storage settings", onClick = { context.startSafely(Intent(Settings.ACTION_INTERNAL_STORAGE_SETTINGS)) })
        }
    }
}

@Composable
private fun JunkGroupCard(
    group: JunkGroup,
    selected: Set<String>,
    expanded: Boolean,
    onExpand: () -> Unit,
    onToggleGroup: (Boolean) -> Unit,
    onToggle: (JunkItem) -> Unit,
    onLongPress: (JunkItem) -> Unit,
) {
    val count = group.items.count { it.path in selected }
    val tri = when (count) {
        0 -> ToggleableState.Off
        group.items.size -> ToggleableState.On
        else -> ToggleableState.Indeterminate
    }
    val allSafe = group.items.all { it.safe }
    LumaCard(Modifier.animateContentSize(), contentPadding = PaddingValues(start = 8.dp, end = 12.dp, top = 12.dp, bottom = 12.dp), onClick = onExpand) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TriStateCheckbox(state = tri, onClick = { onToggleGroup(tri != ToggleableState.On) })
            IconBadge(kindIcon(group.kind), MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(group.kind.label, style = MaterialTheme.typography.titleMedium)
                Text(
                    "${group.items.size.formatCount()} items · " + if (allSafe) "safe to remove" else group.kind.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (allSafe) LocalExtraColors.current.success else MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(group.bytes.formatBytes(), style = MaterialTheme.typography.titleSmall)
            Icon(if (expanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore, if (expanded) "Collapse" else "Expand")
        }
        if (expanded) {
            var limit by remember { mutableIntStateOf(60) }
            Spacer(Modifier.height(8.dp))
            group.items.take(limit).forEach { item ->
                ItemRow(
                    title = item.name.ifBlank { item.path },
                    subtitle = listOfNotNull(item.note, item.path.substringBeforeLast('/').substringAfter("/0/")).joinToString(" · "),
                    leading = { Checkbox(checked = item.path in selected, onCheckedChange = { onToggle(item) }) },
                    trailing = { Text(item.size.formatBytes(), style = MaterialTheme.typography.labelMedium) },
                    onClick = { onToggle(item) },
                    onLongClick = { onLongPress(item) },
                )
            }
            if (group.items.size > limit) {
                TextButton(onClick = { limit += 200 }, modifier = Modifier.fillMaxWidth()) {
                    Text("Show ${minOf(200, group.items.size - limit)} more")
                }
            }
        }
    }
}
