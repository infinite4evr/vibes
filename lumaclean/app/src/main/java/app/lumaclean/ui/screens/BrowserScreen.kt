package app.lumaclean.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Sort
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.ContentCut
import androidx.compose.material.icons.rounded.CreateNewFolder
import androidx.compose.material.icons.rounded.DriveFileRenameOutline
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.SelectAll
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.FileClip
import app.lumaclean.core.UiMessage
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import app.lumaclean.core.formatDate
import app.lumaclean.core.startSafely
import app.lumaclean.data.FileSort
import app.lumaclean.ui.components.DeleteConfirm
import app.lumaclean.ui.components.EmptyState
import app.lumaclean.ui.components.FileThumb
import app.lumaclean.ui.components.FilesPermissionCard
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.Meter
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SelectionBar
import app.lumaclean.ui.components.TextInputDialog
import app.lumaclean.ui.nav.Route
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

private data class Entry(
    val path: String,
    val name: String,
    val isDir: Boolean,
    val size: Long?,
    val modified: Long,
    val count: Int?,
)

@Composable
fun BrowserScreen(path: String) {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    val index by c.index.current.collectAsStateWithLifecycle()
    val clip by c.clipboard.collectAsStateWithLifecycle()
    val op by c.operations.state.collectAsStateWithLifecycle()

    var sort by rememberSaveable { mutableStateOf(FileSort.SIZE) }
    var refresh by remember { mutableIntStateOf(0) }
    var selected by remember(path) { mutableStateOf(setOf<String>()) }
    var menu by remember { mutableStateOf(false) }
    var sortMenu by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf<String?>(null) }
    var creating by remember { mutableStateOf(false) }

    // re-list after any operation finishes (delete, paste, rename…)
    LaunchedEffect(op == null) { if (op == null) refresh++ }
    LaunchedEffect(perms.allFiles) { if (perms.allFiles && index == null) c.indexTask.ensure() }

    val entries by produceState<List<Entry>?>(null, path, refresh, settings.showHidden, index, sort) {
        value = withContext(Dispatchers.IO) {
            val idx = index
            File(path).listFiles().orEmpty()
                .filter { settings.showHidden || !it.name.startsWith(".") }
                .filter { it.name != c.index.binDirName }
                .map { f ->
                    val dir = f.isDirectory
                    Entry(
                        path = f.absolutePath,
                        name = f.name,
                        isDir = dir,
                        size = if (dir) idx?.sizeOf(f.absolutePath) else f.length(),
                        modified = f.lastModified(),
                        count = if (dir) f.list()?.size else null,
                    )
                }
                .let { list ->
                    when (sort) {
                        FileSort.SIZE -> list.sortedWith(compareByDescending<Entry> { it.size ?: -1L }.thenBy { it.name.lowercase() })
                        FileSort.NAME -> list.sortedWith(compareBy<Entry> { !it.isDir }.thenBy { it.name.lowercase() })
                        FileSort.DATE -> list.sortedByDescending { it.modified }
                        FileSort.OLDEST -> list.sortedBy { it.modified }
                    }
                }
        }
    }

    val displayPath = remember(path) { c.storage.displayPath(path) }
    val title = displayPath.substringAfterLast(" › ")
    val chosen = entries.orEmpty().filter { it.path in selected }
    val chosenBytes = chosen.sumOf { it.size ?: 0L }
    val maxSize = entries.orEmpty().maxOfOrNull { it.size ?: 0L }?.coerceAtLeast(1L) ?: 1L

    ScreenScaffold(
        title = title,
        subtitle = displayPath.takeIf { it != title },
        onBack = { nav.back() },
        actions = {
            if (selected.isNotEmpty()) {
                IconButton(onClick = { selected = entries.orEmpty().map { it.path }.toSet() }) { Icon(Icons.Rounded.SelectAll, "Select all") }
            }
            IconButton(onClick = { sortMenu = true }) { Icon(Icons.AutoMirrored.Rounded.Sort, "Sort") }
            DropdownMenu(expanded = sortMenu, onDismissRequest = { sortMenu = false }) {
                FileSort.entries.forEach { s ->
                    DropdownMenuItem(
                        text = { Text(s.label) },
                        leadingIcon = { RadioButton(selected = sort == s, onClick = null) },
                        onClick = { sort = s; sortMenu = false },
                    )
                }
            }
            IconButton(onClick = { menu = true }) { Icon(Icons.Rounded.MoreVert, "More") }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(
                    text = { Text("New folder") },
                    leadingIcon = { Icon(Icons.Rounded.CreateNewFolder, null) },
                    onClick = { menu = false; creating = true },
                )
                DropdownMenuItem(
                    text = { Text("Show hidden files") },
                    trailingIcon = { Checkbox(checked = settings.showHidden, onCheckedChange = null) },
                    onClick = { c.settings.update { it.copy(showHidden = !it.showHidden) } },
                )
                DropdownMenuItem(
                    text = { Text("Refresh folder sizes") },
                    onClick = { menu = false; c.refreshIndex() },
                )
            }
        },
        bottomBar = {
            when {
                selected.isNotEmpty() -> SelectionBar(
                    text = "${chosen.size} selected" + if (chosenBytes > 0) " · ${chosenBytes.formatBytes()}" else "",
                    primaryLabel = "Delete",
                    onPrimary = { confirmDelete = true },
                    onClear = { selected = emptySet() },
                    actions = {
                        if (chosen.none { it.isDir }) {
                            IconButton(onClick = { context.startSafely(c.files.shareIntent(chosen.map { it.path })) }) { Icon(Icons.Rounded.Share, "Share") }
                        }
                        IconButton(onClick = {
                            c.clipboard.value = FileClip(chosen.map { it.path }, move = false)
                            selected = emptySet()
                        }) { Icon(Icons.Rounded.ContentCopy, "Copy") }
                        IconButton(onClick = {
                            c.clipboard.value = FileClip(chosen.map { it.path }, move = true)
                            selected = emptySet()
                        }) { Icon(Icons.Rounded.ContentCut, "Move") }
                        if (chosen.size == 1) {
                            IconButton(onClick = { renaming = chosen[0].path }) { Icon(Icons.Rounded.DriveFileRenameOutline, "Rename") }
                        }
                    },
                )
                clip != null -> PasteBar(clip!!, onPaste = {
                    val cl = clip!!
                    c.clipboard.value = null
                    c.operations.run(if (cl.move) "Moving" else "Copying") {
                        val r = c.files.transfer(cl.paths, path, cl.move, this)
                        UiMessage("${if (cl.move) "Moved" else "Copied"} ${r.done} ${if (r.done == 1) "item" else "items"}" + if (r.failed > 0) " · ${r.failed} failed" else "")
                    }
                }, onCancel = { c.clipboard.value = null })
                else -> {}
            }
        },
    ) { padding ->
        LumaList(padding, spacing = 2.dp) {
            if (!perms.allFiles) {
                item { FilesPermissionCard(reason = "to browse your files") }
                return@LumaList
            }
            item { Breadcrumbs(path, c.index.root) { nav.open(Route.Browser(it)) } }
            val list = entries
            if (list == null) {
                item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                return@LumaList
            }
            if (list.isEmpty()) {
                item { EmptyState(Icons.Rounded.FolderOpen, "This folder is empty", "Nothing to see here.") }
            }
            items(list, key = { it.path }) { e ->
                val isSel = e.path in selected
                Column {
                    ItemRow(
                        title = e.name,
                        subtitle = buildString {
                            if (e.isDir) {
                                append(e.count?.let { "${it.formatCount()} items" } ?: "Folder")
                            } else append(e.modified.formatDate())
                            e.size?.let { append(" · ").append(it.formatBytes()) }
                        },
                        leading = { FileThumb(e.path, e.isDir) },
                        selected = isSel,
                        onClick = {
                            when {
                                selected.isNotEmpty() -> selected = if (isSel) selected - e.path else selected + e.path
                                e.isDir -> nav.open(Route.Browser(e.path))
                                else -> context.startSafely(c.files.openIntent(e.path))
                            }
                        },
                        onLongClick = { selected = if (isSel) selected - e.path else selected + e.path },
                    )
                    if (sort == FileSort.SIZE && e.size != null && e.size > 0) {
                        Meter(e.size / maxSize.toFloat(), MaterialTheme.colorScheme.primary.copy(alpha = 0.6f), Modifier.padding(start = 70.dp, end = 12.dp), height = 3.dp)
                    }
                }
            }
        }
    }

    if (confirmDelete) {
        DeleteConfirm(chosen.size, chosenBytes, onConfirm = { permanent ->
            c.deleteFiles(chosen.map { it.path }, permanent)
            selected = emptySet()
        }, onDismiss = { confirmDelete = false })
    }
    renaming?.let { target ->
        TextInputDialog("Rename", target.substringAfterLast('/'), "Rename", onConfirm = { name ->
            runCatching { c.files.rename(target, name) }
                .onSuccess { selected = emptySet(); refresh++ }
                .onFailure { c.message(it.message ?: "Couldn't rename") }
        }, onDismiss = { renaming = null })
    }
    if (creating) {
        TextInputDialog("New folder", "New folder", "Create", onConfirm = { name ->
            runCatching { c.files.createFolder(path, name) }
                .onSuccess { refresh++ }
                .onFailure { c.message(it.message ?: "Couldn't create the folder") }
        }, onDismiss = { creating = false })
    }
}

@Composable
private fun Breadcrumbs(path: String, root: String, onOpen: (String) -> Unit) {
    val base = if (path.startsWith(root)) root else path.split('/').take(3).joinToString("/")
    val parts = path.removePrefix(base).split('/').filter { it.isNotEmpty() }
    val crumbs = listOf((if (base == root) "Internal storage" else base.substringAfterLast('/')) to base) +
        parts.mapIndexed { i, name -> name to base + "/" + parts.take(i + 1).joinToString("/") }
    if (crumbs.size <= 1) return
    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(bottom = 8.dp)) {
        items(crumbs.dropLast(1)) { (name, p) ->
            AssistChip(onClick = { onOpen(p) }, label = { Text(name, maxLines = 1) })
        }
    }
}

@Composable
private fun PasteBar(clip: FileClip, onPaste: () -> Unit, onCancel: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surfaceContainer, tonalElevation = 3.dp) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    "${if (clip.move) "Move" else "Copy"} ${clip.paths.size} ${if (clip.paths.size == 1) "item" else "items"}",
                    style = MaterialTheme.typography.titleSmall,
                )
                Text("Open the destination folder, then paste", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TextButton(onClick = onCancel) { Text("Cancel") }
            Spacer(Modifier.width(4.dp))
            Button(onClick = onPaste) { Text("Paste here") }
        }
    }
    Spacer(Modifier.height(0.dp))
}
