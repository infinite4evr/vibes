@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package app.lumaclean.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridItemSpanScope
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Compress
import androidx.compose.material.icons.rounded.DeleteSweep
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.RestoreFromTrash
import androidx.compose.material.icons.rounded.SelectAll
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.TaskState
import app.lumaclean.core.UiMessage
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import app.lumaclean.core.formatDateTime
import app.lumaclean.core.relativeTime
import app.lumaclean.core.startSafely
import app.lumaclean.data.ChatMedia
import app.lumaclean.data.CompressLevel
import app.lumaclean.data.FileQuery
import app.lumaclean.data.Photo
import app.lumaclean.ui.components.ConfirmDialog
import app.lumaclean.ui.components.DeleteConfirm
import app.lumaclean.ui.components.EmptyState
import app.lumaclean.ui.components.ErrorCard
import app.lumaclean.ui.components.FileThumb
import app.lumaclean.ui.components.FilesPermissionCard
import app.lumaclean.ui.components.HeroCard
import app.lumaclean.ui.components.IconBadge
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaGrid
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.MediaCell
import app.lumaclean.ui.components.Meter
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SelectionBar
import app.lumaclean.ui.components.TaskProgressCard
import app.lumaclean.ui.nav.Route
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private val span: LazyGridItemSpanScope.() -> GridItemSpan = { GridItemSpan(maxLineSpan) }

@Composable
fun SimilarPhotosScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val state by c.similarTask.state.collectAsStateWithLifecycle()
    val groups = state.value
    var selected by remember(groups) {
        mutableStateOf(groups.orEmpty().flatMap { g -> g.photos.filter { it != g.best }.mapNotNull { it.path } }.toSet())
    }
    var confirm by remember { mutableStateOf(false) }
    val photos = groups.orEmpty().flatMap { it.photos }
    val chosen = photos.filter { it.path in selected }
    val chosenBytes = chosen.sumOf { it.size }

    ScreenScaffold(
        title = "Similar photos",
        subtitle = groups?.let { g -> "${g.size} groups · ${g.sumOf { it.reclaimable }.formatBytes()} could be freed" },
        onBack = { nav.back() },
        actions = {
            IconButton(onClick = { c.similarTask.restart() }, enabled = perms.allFiles && state !is TaskState.Running) {
                Icon(Icons.Rounded.Refresh, "Scan again")
            }
        },
        bottomBar = {
            if (selected.isNotEmpty()) {
                SelectionBar(
                    text = "${chosen.size} photos · ${chosenBytes.formatBytes()}",
                    primaryLabel = "Delete",
                    onPrimary = { confirm = true },
                    onClear = { selected = emptySet() },
                )
            }
        },
    ) { padding ->
        LumaGrid(padding, minCell = 104.dp, spacing = 6.dp) {
            if (!perms.allFiles) {
                item(span = span) { FilesPermissionCard(reason = "to compare your photos") }
                return@LumaGrid
            }
            when (val s = state) {
                is TaskState.Running -> item(span = span) { TaskProgressCard(s, "Comparing photos", onCancel = { c.similarTask.cancel() }) }
                is TaskState.Failed -> item(span = span) { ErrorCard(s.message) { c.similarTask.restart() } }
                TaskState.Idle -> item(span = span) {
                    HeroCard(
                        Icons.Rounded.PhotoLibrary,
                        "Find similar photos",
                        "Bursts and near-identical shots taken moments apart. The sharpest, largest photo in each group is kept.",
                        "Start",
                        onClick = { c.similarTask.restart() },
                    )
                }
                is TaskState.Done -> {}
            }
            val list = groups ?: return@LumaGrid
            if (list.isEmpty()) {
                item(span = span) { EmptyState(Icons.Rounded.CheckCircle, "No similar photos", "Your recent photos are all different.") }
                return@LumaGrid
            }
            list.forEach { g ->
                item(span = span) {
                    Text(
                        "${g.photos.size} photos · ${g.best.taken.formatDateTime()}",
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(start = 4.dp, top = 12.dp),
                    )
                }
                items(g.photos, key = { it.id }) { p ->
                    val isSel = p.path in selected
                    MediaCell(
                        model = p.uri,
                        selected = isSel,
                        badge = if (p == g.best) "Best" else null,
                        label = p.size.formatBytes(),
                        onClick = {
                            val path = p.path
                            val keptLeft = g.photos.count { it.path !in selected }
                            if (path == null) {
                                c.message("This photo can't be selected")
                            } else if (isSel) {
                                selected = selected - path
                            } else if (keptLeft > 1) {
                                selected = selected + path
                            } else {
                                c.message("One photo from each group is always kept")
                            }
                        },
                        onLongClick = { p.path?.let { context.startSafely(c.files.openIntent(it)) } },
                    )
                }
            }
        }
    }

    if (confirm) {
        DeleteConfirm(chosen.size, chosenBytes, onConfirm = { permanent ->
            c.deleteFiles(chosen.mapNotNull { it.path }, permanent, "similar photos")
            selected = emptySet()
        }, onDismiss = { confirm = false })
    }
}

@Composable
fun CompressScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val op by c.operations.state.collectAsStateWithLifecycle()
    var refresh by remember { mutableIntStateOf(0) }
    var level by remember { mutableStateOf(CompressLevel.BALANCED) }
    var replace by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf(setOf<Long>()) }
    var confirm by remember { mutableStateOf(false) }
    LaunchedEffect(op == null) { if (op == null) refresh++ }

    val photos by produceState<List<Photo>?>(null, perms.allFiles, refresh) {
        value = if (!perms.allFiles) emptyList() else withContext(Dispatchers.IO) {
            c.media.photos(minBytes = 1_500_000, jpegOnly = true).sortedByDescending { it.size }
        }
    }
    val list = photos.orEmpty()
    val chosen = list.filter { it.id in selected }

    ScreenScaffold(
        title = "Compress photos",
        subtitle = photos?.let { "${it.size} large photos · ${it.sumOf { p -> p.size }.formatBytes()}" },
        onBack = { nav.back() },
        actions = {
            if (list.isNotEmpty()) {
                IconButton(onClick = { selected = if (selected.size == list.size) emptySet() else list.map { it.id }.toSet() }) {
                    Icon(Icons.Rounded.SelectAll, "Select all")
                }
            }
        },
        bottomBar = {
            if (selected.isNotEmpty()) {
                SelectionBar(
                    text = "${chosen.size} photos · ${chosen.sumOf { it.size }.formatBytes()}",
                    primaryLabel = "Compress",
                    onPrimary = { confirm = true },
                    onClear = { selected = emptySet() },
                    destructive = false,
                )
            }
        },
    ) { padding ->
        LumaGrid(padding, minCell = 104.dp, spacing = 6.dp) {
            if (!perms.allFiles) {
                item(span = span) { FilesPermissionCard(reason = "to compress your photos") }
                return@LumaGrid
            }
            item(span = span) {
                LumaCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconBadge(Icons.Rounded.Compress, MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Text("Shrink big photos, keep them looking the same", style = MaterialTheme.typography.titleMedium)
                    }
                    Spacer(Modifier.height(12.dp))
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                        CompressLevel.entries.forEachIndexed { i, l ->
                            SegmentedButton(
                                selected = level == l,
                                onClick = { level = l },
                                shape = SegmentedButtonDefaults.itemShape(i, CompressLevel.entries.size),
                            ) { Text(l.label, maxLines = 1) }
                        }
                    }
                    Text(level.hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Replace the originals", style = MaterialTheme.typography.bodyLarge)
                            Text(
                                if (replace) "The smaller photo takes the original's place" else "Saves a smaller copy next to each photo",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Switch(checked = replace, onCheckedChange = { replace = it })
                    }
                    Text(
                        "Date, location and camera details are kept. Photos that wouldn't get at least 10% smaller are skipped.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (photos == null) {
                item(span = span) { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                return@LumaGrid
            }
            if (list.isEmpty()) {
                item(span = span) { EmptyState(Icons.Rounded.CheckCircle, "No large photos", "None of your JPEG photos are over 1.5 MB.") }
                return@LumaGrid
            }
            items(list, key = { it.id }) { p ->
                val isSel = p.id in selected
                MediaCell(
                    model = p.uri,
                    selected = isSel,
                    label = p.size.formatBytes(),
                    onClick = { selected = if (isSel) selected - p.id else selected + p.id },
                    onLongClick = { selected = if (isSel) selected - p.id else selected + p.id },
                )
            }
        }
    }

    if (confirm) {
        ConfirmDialog(
            title = "Compress ${chosen.size} photos?",
            text = if (replace) "The originals are replaced by the smaller versions. This can't be undone."
            else "Smaller copies are saved next to the originals. Delete the originals afterwards to free the space.",
            confirmLabel = "Compress",
            destructive = replace,
            onConfirm = {
                val items = chosen
                val lvl = level
                val rep = replace
                c.operations.run("Compressing photos") {
                    val r = c.media.compress(items, lvl, rep, this)
                    if (rep) c.history.add("Compressed photos", r.done, r.saved)
                    selected = emptySet()
                    UiMessage(
                        if (r.done == 0) "No photos could be made smaller"
                        else "${r.done} photos compressed · ${r.saved.formatBytes()} ${if (rep) "freed" else "smaller"}" +
                            if (r.skipped > 0) " · ${r.skipped} skipped" else "",
                    )
                }
            },
            onDismiss = { confirm = false },
        )
    }
}

@Composable
fun ChatMediaScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val index by c.index.current.collectAsStateWithLifecycle()
    val indexState by c.indexTask.state.collectAsStateWithLifecycle()
    LaunchedEffect(perms.allFiles) { if (perms.allFiles) c.indexTask.ensure() }
    val apps = remember(index) { index?.let { ChatMedia.analyze(it) } }

    ScreenScaffold(title = "Chat media", subtitle = apps?.let { a -> "${a.sumOf { it.bytes }.formatBytes()} in total" }, onBack = { nav.back() }) { padding ->
        LumaList(padding) {
            if (!perms.allFiles) {
                item { FilesPermissionCard(reason = "to find media your chat apps saved") }
                return@LumaList
            }
            (indexState as? TaskState.Running<*>)?.let { s -> item { TaskProgressCard(s, "Analyzing storage", onCancel = { c.indexTask.cancel() }) } }
            val list = apps ?: return@LumaList
            if (list.isEmpty()) {
                item { EmptyState(Icons.Rounded.Forum, "No chat media found", "WhatsApp, Telegram and Signal haven't saved any files here.") }
            }
            list.forEach { app ->
                item(key = app.name) {
                    LumaCard(contentPadding = PaddingValues(8.dp)) {
                        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                            IconBadge(Icons.Rounded.Forum, MaterialTheme.colorScheme.primary)
                            Spacer(Modifier.width(12.dp))
                            Text(app.name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                            Text(app.bytes.formatBytes(), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
                        }
                        app.buckets.forEach { b ->
                            Column {
                                ItemRow(
                                    title = b.label,
                                    subtitle = "${b.count.formatCount()} files",
                                    trailing = { Text(b.bytes.formatBytes(), style = MaterialTheme.typography.labelLarge) },
                                    onClick = { nav.open(Route.Files(FileQuery.Folder(b.path, "${app.name} · ${b.label}"))) },
                                )
                                Meter(b.bytes / app.bytes.coerceAtLeast(1).toFloat(), MaterialTheme.colorScheme.primary.copy(alpha = 0.6f), Modifier.padding(horizontal = 12.dp), height = 3.dp)
                            }
                        }
                    }
                }
            }
            if (list.isNotEmpty()) {
                item {
                    Text(
                        "Deleting files here removes them from your phone's storage. Chats keep working; old media just won't open anymore.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 8.dp),
                    )
                }
            }
        }
    }
}

@Composable
fun RecycleBinScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val items by c.bin.items.collectAsStateWithLifecycle()
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    var selected by remember { mutableStateOf(setOf<String>()) }
    var confirmEmpty by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val chosen = items.filter { it.id in selected }

    fun purge(ids: List<String>, title: String) {
        c.operations.run(title) {
            val freed = c.bin.deleteForever(ids)
            c.history.add("Emptied recycle bin", ids.size, freed)
            selected = emptySet()
            UiMessage("${freed.formatBytes()} freed")
        }
    }

    ScreenScaffold(
        title = "Recycle bin",
        subtitle = "${items.size} items · ${items.sumOf { it.size }.formatBytes()}",
        onBack = { nav.back() },
        actions = {
            if (items.isNotEmpty()) {
                IconButton(onClick = { confirmEmpty = true }) { Icon(Icons.Rounded.DeleteSweep, "Empty bin") }
            }
        },
        bottomBar = {
            if (selected.isNotEmpty()) {
                SelectionBar(
                    text = "${chosen.size} selected · ${chosen.sumOf { it.size }.formatBytes()}",
                    primaryLabel = "Delete",
                    onPrimary = { confirmDelete = true },
                    onClear = { selected = emptySet() },
                    actions = {
                        IconButton(onClick = {
                            c.restore(chosen.map { it.id })
                            selected = emptySet()
                        }) { Icon(Icons.Rounded.RestoreFromTrash, "Restore") }
                    },
                )
            }
        },
    ) { padding ->
        LumaList(padding, spacing = 2.dp) {
            if (items.isEmpty()) {
                item { EmptyState(Icons.Rounded.DeleteSweep, "The bin is empty", "Files you delete in LumaClean wait here for ${settings.recycleDays} days before they're gone for good.") }
                return@LumaList
            }
            item {
                Text(
                    "Items are deleted for good after ${settings.recycleDays} days. Tap to select, then restore or delete.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
            items(items, key = { it.id }) { b ->
                val isSel = b.id in selected
                ItemRow(
                    title = b.name,
                    subtitle = "Deleted ${b.deletedAt.relativeTime()} · from ${b.originalPath.substringBeforeLast('/').substringAfter("/0/")}",
                    leading = { FileThumb(b.binPath, b.isDir) },
                    trailing = { Text(b.size.formatBytes(), style = MaterialTheme.typography.labelLarge) },
                    selected = isSel,
                    onClick = { selected = if (isSel) selected - b.id else selected + b.id },
                    onLongClick = { selected = if (isSel) selected - b.id else selected + b.id },
                )
            }
        }
    }

    if (confirmEmpty) {
        ConfirmDialog(
            title = "Empty the recycle bin?",
            text = "${items.size} items (${items.sumOf { it.size }.formatBytes()}) will be deleted for good.",
            confirmLabel = "Empty",
            onConfirm = { purge(items.map { it.id }, "Emptying recycle bin") },
            onDismiss = { confirmEmpty = false },
        )
    }
    if (confirmDelete) {
        ConfirmDialog(
            title = "Delete ${chosen.size} items for good?",
            text = "This can't be undone.",
            confirmLabel = "Delete",
            onConfirm = { purge(chosen.map { it.id }, "Deleting") },
            onDismiss = { confirmDelete = false },
        )
    }
}
