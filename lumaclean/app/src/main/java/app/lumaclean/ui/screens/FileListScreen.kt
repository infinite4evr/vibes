package app.lumaclean.ui.screens

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.SelectAll
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.TaskState
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import app.lumaclean.core.formatDate
import app.lumaclean.core.startSafely
import app.lumaclean.data.FileCategory
import app.lumaclean.data.FileEntry
import app.lumaclean.data.FileQuery
import app.lumaclean.data.FileSort
import app.lumaclean.data.applySort
import app.lumaclean.data.query
import app.lumaclean.ui.components.DeleteConfirm
import app.lumaclean.ui.components.EmptyState
import app.lumaclean.ui.components.FileThumb
import app.lumaclean.ui.components.FilesPermissionCard
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaGrid
import app.lumaclean.ui.components.MediaCell
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SelectionBar
import app.lumaclean.ui.components.TaskProgressCard
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

@Composable
fun FileListScreen(query: FileQuery) {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    val index by c.index.current.collectAsStateWithLifecycle()
    val indexState by c.indexTask.state.collectAsStateWithLifecycle()

    val defaultSort = if (query is FileQuery.OldDownloads) FileSort.OLDEST else FileSort.SIZE
    var sort by rememberSaveable { mutableStateOf(defaultSort) }
    var minBytes by rememberSaveable { mutableLongStateOf((query as? FileQuery.Large)?.minBytes ?: 0L) }
    var days by rememberSaveable { mutableIntStateOf((query as? FileQuery.OldDownloads)?.days ?: 0) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var confirm by remember { mutableStateOf(false) }

    LaunchedEffect(perms.allFiles) { if (perms.allFiles) c.indexTask.ensure() }

    val effective = when (query) {
        is FileQuery.Large -> FileQuery.Large(minBytes)
        is FileQuery.OldDownloads -> FileQuery.OldDownloads(days)
        else -> query
    }
    val results by produceState<List<FileEntry>?>(null, index, effective, sort, settings.showHidden) {
        value = index?.let { idx -> withContext(Dispatchers.Default) { idx.query(effective, settings.showHidden).applySort(sort) } }
    }
    val gallery = when (query) {
        is FileQuery.Category -> query.category == FileCategory.IMAGES || query.category == FileCategory.VIDEOS
        FileQuery.Screenshots, FileQuery.LargeVideos -> true
        else -> false
    }
    val list = results.orEmpty()
    val chosen = list.filter { it.path in selected }
    val chosenBytes = chosen.sumOf { it.size }

    ScreenScaffold(
        title = query.title,
        subtitle = results?.let { "${it.size.formatCount()} files · ${it.sumOf { f -> f.size }.formatBytes()}" },
        onBack = { nav.back() },
        actions = {
            if (list.isNotEmpty()) {
                IconButton(onClick = { selected = if (selected.size == list.size) emptySet() else list.map { it.path }.toSet() }) {
                    Icon(Icons.Rounded.SelectAll, "Select all")
                }
            }
        },
        bottomBar = {
            if (selected.isNotEmpty()) {
                SelectionBar(
                    text = "${chosen.size.formatCount()} selected · ${chosenBytes.formatBytes()}",
                    primaryLabel = "Delete",
                    onPrimary = { confirm = true },
                    onClear = { selected = emptySet() },
                    actions = {
                        if (chosen.size <= 100) {
                            IconButton(onClick = { context.startSafely(c.files.shareIntent(chosen.map { it.path })) }) { Icon(Icons.Rounded.Share, "Share") }
                        }
                    },
                )
            }
        },
    ) { padding ->
        LumaGrid(padding, minCell = if (gallery) 110.dp else 360.dp, spacing = if (gallery) 6.dp else 4.dp) {
            val full: (androidx.compose.foundation.lazy.grid.LazyGridItemSpanScope) -> GridItemSpan = { GridItemSpan(it.maxLineSpan) }
            if (!perms.allFiles) {
                item(span = full) { FilesPermissionCard() }
                return@LumaGrid
            }
            (indexState as? TaskState.Running<*>)?.let { s ->
                item(span = full) { TaskProgressCard(s, "Analyzing storage", onCancel = { c.indexTask.cancel() }) }
            }
            item(span = full) {
                FilterRow(query, sort, { sort = it }, minBytes, { minBytes = it }, days, { days = it })
            }
            if (results == null) {
                if (indexState !is TaskState.Running) item(span = full) { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                return@LumaGrid
            }
            if (list.isEmpty()) {
                item(span = full) { EmptyState(Icons.Rounded.CheckCircle, "Nothing here", "No files match. Nice and tidy.") }
                return@LumaGrid
            }
            items(list, key = { it.path }) { f ->
                val isSel = f.path in selected
                val toggle = { selected = if (isSel) selected - f.path else selected + f.path }
                if (gallery) {
                    MediaCell(
                        model = File(f.path),
                        selected = isSel,
                        onClick = { if (selected.isNotEmpty()) toggle() else context.startSafely(c.files.openIntent(f.path)) },
                        onLongClick = toggle,
                        label = f.size.formatBytes(),
                        isVideo = f.category == FileCategory.VIDEOS,
                    )
                } else {
                    ItemRow(
                        title = f.name,
                        subtitle = "${f.modified.formatDate()} · ${f.parent.substringAfterLast('/')}",
                        leading = { FileThumb(f.path) },
                        trailing = { Text(f.size.formatBytes(), style = MaterialTheme.typography.labelLarge) },
                        selected = isSel,
                        onClick = { if (selected.isNotEmpty()) toggle() else context.startSafely(c.files.openIntent(f.path)) },
                        onLongClick = toggle,
                    )
                }
            }
        }
    }

    if (confirm) {
        DeleteConfirm(chosen.size, chosenBytes, onConfirm = { permanent ->
            c.deleteFiles(chosen.map { it.path }, permanent, query.title.lowercase())
            selected = emptySet()
        }, onDismiss = { confirm = false })
    }
}

@Composable
private fun FilterRow(
    query: FileQuery,
    sort: FileSort,
    onSort: (FileSort) -> Unit,
    minBytes: Long,
    onMin: (Long) -> Unit,
    days: Int,
    onDays: (Int) -> Unit,
) {
    LumaCard(contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp)) {
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FileSort.entries.forEach { s -> FilterChip(selected = sort == s, onClick = { onSort(s) }, label = { Text(s.label) }) }
        }
        when (query) {
            is FileQuery.Large -> {
                Spacer(Modifier.height(4.dp))
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(50L, 100L, 250L, 500L, 1000L).forEach { mb ->
                        FilterChip(
                            selected = minBytes == mb * 1_000_000,
                            onClick = { onMin(mb * 1_000_000) },
                            label = { Text(if (mb >= 1000) "1 GB+" else "$mb MB+") },
                        )
                    }
                }
            }
            is FileQuery.OldDownloads -> {
                Spacer(Modifier.height(4.dp))
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(30, 60, 90, 180, 365).forEach { d ->
                        FilterChip(selected = days == d, onClick = { onDays(d) }, label = { Text(if (d == 365) "1 year+" else "$d days+") })
                    }
                }
            }
            else -> {}
        }
    }
}
