package app.lumaclean.ui.screens

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import app.lumaclean.data.DuplicateEngine
import app.lumaclean.data.KeepRule
import app.lumaclean.ui.components.DeleteConfirm
import app.lumaclean.ui.components.EmptyState
import app.lumaclean.ui.components.ErrorCard
import app.lumaclean.ui.components.FileThumb
import app.lumaclean.ui.components.FilesPermissionCard
import app.lumaclean.ui.components.HeroCard
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SelectionBar
import app.lumaclean.ui.components.TaskProgressCard
import app.lumaclean.ui.theme.LocalExtraColors

@Composable
fun DuplicatesScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val state by c.duplicatesTask.state.collectAsStateWithLifecycle()
    val groups = state.value

    var rule by remember { mutableStateOf(KeepRule.OLDEST) }
    var selected by remember(groups) { mutableStateOf(groups?.let { DuplicateEngine.selectionFor(it, rule) } ?: emptySet()) }
    var confirm by remember { mutableStateOf(false) }

    val files = groups.orEmpty().flatMap { it.files }
    val chosen = files.filter { it.path in selected }
    val chosenBytes = chosen.sumOf { it.size }

    ScreenScaffold(
        title = "Duplicate files",
        subtitle = groups?.let { g -> "${g.size.formatCount()} groups · ${g.sumOf { it.reclaimable }.formatBytes()} reclaimable" },
        onBack = { nav.back() },
        actions = {
            IconButton(onClick = { c.duplicatesTask.restart() }, enabled = perms.allFiles && state !is TaskState.Running) {
                Icon(Icons.Rounded.Refresh, "Scan again")
            }
        },
        bottomBar = {
            if (selected.isNotEmpty()) {
                SelectionBar(
                    text = "${chosen.size.formatCount()} copies · ${chosenBytes.formatBytes()}",
                    primaryLabel = "Delete",
                    onPrimary = { confirm = true },
                    onClear = { selected = emptySet() },
                )
            }
        },
    ) { padding ->
        LumaList(padding) {
            if (!perms.allFiles) {
                item { FilesPermissionCard(reason = "to compare your files") }
                return@LumaList
            }
            when (val s = state) {
                is TaskState.Running -> item { TaskProgressCard(s, "Finding duplicates", onCancel = { c.duplicatesTask.cancel() }) }
                is TaskState.Failed -> item { ErrorCard(s.message) { c.duplicatesTask.restart() } }
                TaskState.Idle -> item {
                    HeroCard(
                        Icons.Rounded.ContentCopy,
                        "Find exact duplicates",
                        "Files are compared byte for byte, so only true copies are shown. One copy of each file is always kept.",
                        "Start scan",
                        onClick = { c.duplicatesTask.restart() },
                    )
                }
                is TaskState.Done -> {}
            }
            val list = groups ?: return@LumaList
            if (list.isEmpty()) {
                item { EmptyState(Icons.Rounded.CheckCircle, "No duplicates", "Every file on your phone is unique.") }
                return@LumaList
            }
            item {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KeepRule.entries.forEach { r ->
                        FilterChip(selected = rule == r, onClick = {
                            rule = r
                            selected = DuplicateEngine.selectionFor(list, r)
                        }, label = { Text(r.label) })
                    }
                }
            }
            list.forEach { group ->
                item(key = group.key) {
                    LumaCard(contentPadding = PaddingValues(8.dp)) {
                        Text(
                            "${group.files.size} copies · ${group.size.formatBytes()} each",
                            style = MaterialTheme.typography.titleSmall,
                            modifier = Modifier.padding(start = 12.dp, top = 8.dp),
                            color = MaterialTheme.colorScheme.primary,
                        )
                        Spacer(Modifier.height(4.dp))
                        group.files.forEach { f ->
                            val isSel = f.path in selected
                            val keptLeft = group.files.count { it.path !in selected }
                            ItemRow(
                                title = f.name,
                                subtitle = "${f.path.substringBeforeLast('/').substringAfter("/0/")} · ${f.modified.formatDate()}",
                                leading = { FileThumb(f.path) },
                                trailing = {
                                    if (isSel) Checkbox(checked = true, onCheckedChange = { selected = selected - f.path })
                                    else Text("Keep", style = MaterialTheme.typography.labelLarge, color = LocalExtraColors.current.success)
                                },
                                selected = isSel,
                                onClick = {
                                    if (isSel) selected = selected - f.path
                                    else if (keptLeft > 1) selected = selected + f.path
                                    else c.message("One copy is always kept")
                                },
                                onLongClick = { context.startSafely(c.files.openIntent(f.path)) },
                            )
                        }
                    }
                }
            }
        }
    }

    if (confirm) {
        DeleteConfirm(chosen.size, chosenBytes, onConfirm = { permanent ->
            c.deleteFiles(chosen.map { it.path }, permanent, "duplicates")
            selected = emptySet()
        }, onDismiss = { confirm = false })
    }
}
