package app.lumaclean.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Sort
import androidx.compose.material.icons.rounded.Apps
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.DataUsage
import androidx.compose.material.icons.rounded.HourglassEmpty
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.DAY_MS
import app.lumaclean.core.TaskState
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount
import app.lumaclean.core.relativeTime
import app.lumaclean.data.AppInfo
import app.lumaclean.ui.components.AppIcon
import app.lumaclean.ui.components.ConfirmDialog
import app.lumaclean.ui.components.EmptyState
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SelectionBar
import app.lumaclean.ui.components.StatTile
import app.lumaclean.ui.components.TaskProgressCard
import app.lumaclean.ui.components.UsagePermissionCard
import app.lumaclean.ui.nav.Route

enum class AppFilter(val label: String) { USER("Installed"), SYSTEM("System"), ALL("All") }

enum class AppSort(val label: String) { SIZE("Size"), NAME("Name"), CACHE("Cache"), LAST_USED("Least used"), INSTALLED("Recently installed") }

fun uninstallIntent(pkg: String): Intent =
    Intent(Intent.ACTION_DELETE, Uri.parse("package:$pkg")).putExtra(Intent.EXTRA_RETURN_RESULT, true)

/** Runs Android's uninstall prompt for each package in turn; returns the function that starts it. */
@Composable
fun rememberUninstaller(onRemoved: (String) -> Unit = {}): (List<String>) -> Unit {
    val c = LocalContainer.current
    var queue by remember { mutableStateOf(listOf<String>()) }
    var removed by remember { mutableIntStateOf(0) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        val pkg = queue.firstOrNull()
        if (pkg != null && !c.apps.isInstalled(pkg)) {
            removed++
            c.appsTask.update { list -> list.filter { it.packageName != pkg } }
            onRemoved(pkg)
        }
        queue = queue.drop(1)
    }
    LaunchedEffect(queue) {
        val next = queue.firstOrNull()
        if (next != null) {
            runCatching { launcher.launch(uninstallIntent(next)) }.onFailure { queue = queue.drop(1) }
        } else if (removed > 0) {
            c.message("Uninstalled $removed ${if (removed == 1) "app" else "apps"}")
            removed = 0
        }
    }
    return { pkgs -> queue = pkgs }
}

@Composable
fun AppsScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val state by c.appsTask.state.collectAsStateWithLifecycle()
    val apps = state.value

    var filter by rememberSaveable { mutableStateOf(AppFilter.USER) }
    var sort by rememberSaveable { mutableStateOf(AppSort.SIZE) }
    var query by rememberSaveable { mutableStateOf("") }
    var searching by rememberSaveable { mutableStateOf(false) }
    var sortMenu by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var confirm by remember { mutableStateOf(false) }
    val uninstall = rememberUninstaller { pkg -> selected = selected - pkg }

    LaunchedEffect(perms.usage) {
        if (perms.usage && state.value?.any { !it.hasSizes && !it.system } == true) c.appsTask.restart() else c.appsTask.ensure()
    }

    val list = apps.orEmpty()
        .filter {
            when (filter) {
                AppFilter.USER -> !it.system || it.updatedSystem
                AppFilter.SYSTEM -> it.system
                AppFilter.ALL -> true
            }
        }
        .filter { query.isBlank() || it.label.contains(query, true) || it.packageName.contains(query, true) }
        .let { l ->
            when (sort) {
                AppSort.SIZE -> l.sortedByDescending { it.totalBytes }
                AppSort.NAME -> l.sortedBy { it.label.lowercase() }
                AppSort.CACHE -> l.sortedByDescending { it.cacheBytes }
                AppSort.LAST_USED -> l.sortedBy { if (it.lastUsed == 0L) Long.MAX_VALUE else it.lastUsed }
                AppSort.INSTALLED -> l.sortedByDescending { it.firstInstall }
            }
        }
    val chosen = list.filter { it.packageName in selected }

    ScreenScaffold(
        title = "Apps",
        subtitle = apps?.let { "${list.size} apps · ${list.sumOf { it.totalBytes }.formatBytes()}" },
        actions = {
            IconButton(onClick = { searching = !searching; if (!searching) query = "" }) {
                Icon(if (searching) Icons.Rounded.Close else Icons.Rounded.Search, "Search apps")
            }
            IconButton(onClick = { sortMenu = true }) { Icon(Icons.AutoMirrored.Rounded.Sort, "Sort") }
            DropdownMenu(expanded = sortMenu, onDismissRequest = { sortMenu = false }) {
                AppSort.entries.forEach { s ->
                    DropdownMenuItem(
                        text = { Text(s.label) },
                        leadingIcon = { RadioButton(selected = sort == s, onClick = null) },
                        onClick = { sort = s; sortMenu = false },
                    )
                }
            }
            IconButton(onClick = { c.appsTask.restart() }, enabled = state !is TaskState.Running) { Icon(Icons.Rounded.Refresh, "Reload") }
        },
        bottomBar = {
            if (selected.isNotEmpty()) {
                SelectionBar(
                    text = "${chosen.size} apps · ${chosen.sumOf { it.totalBytes }.formatBytes()}",
                    primaryLabel = "Uninstall",
                    onPrimary = { confirm = true },
                    onClear = { selected = emptySet() },
                )
            }
        },
    ) { padding ->
        LumaList(padding, spacing = 2.dp) {
            if (searching) {
                item {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        placeholder = { Text("Search apps") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            if (!perms.usage) item { UsagePermissionCard("app sizes, last-used dates and data usage") }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    StatTile(Icons.Rounded.DataUsage, "Screen time & data", "Usage", Modifier.weight(1f), onClick = { nav.open(Route.AppUsage) })
                    val unused = apps?.let { unusedApps(it, 60).size }
                    StatTile(
                        Icons.Rounded.HourglassEmpty, "Unused 60+ days", unused?.toString() ?: "—", Modifier.weight(1f),
                        onClick = { nav.open(Route.UnusedApps) },
                    )
                }
            }
            item {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AppFilter.entries.forEach { f -> FilterChip(selected = filter == f, onClick = { filter = f }, label = { Text(f.label) }) }
                }
            }
            (state as? TaskState.Running<*>)?.let { s ->
                if (apps == null) item { TaskProgressCard(s, "Reading your apps", onCancel = { c.appsTask.cancel() }) }
            }
            if (apps != null && list.isEmpty()) {
                item { EmptyState(Icons.Rounded.Apps, "No apps", if (query.isNotBlank()) "Nothing matches \"$query\"." else "Nothing to show here.") }
            }
            items(list, key = { it.packageName }) { app ->
                AppRow(
                    app = app,
                    detail = when (sort) {
                        AppSort.CACHE -> "Cache ${app.cacheBytes.formatBytes()}"
                        AppSort.INSTALLED -> "Installed ${app.firstInstall.relativeTime()}"
                        else -> if (app.lastUsed > 0) "Used ${app.lastUsed.relativeTime()}" else app.versionName.ifBlank { app.packageName }
                    },
                    selected = app.packageName in selected,
                    onClick = {
                        if (selected.isNotEmpty() && app.canUninstall) {
                            selected = if (app.packageName in selected) selected - app.packageName else selected + app.packageName
                        } else nav.open(Route.AppDetail(app.packageName))
                    },
                    onLongClick = {
                        if (app.canUninstall) selected = if (app.packageName in selected) selected - app.packageName else selected + app.packageName
                        else c.message("${app.label} is part of Android and can't be uninstalled")
                    },
                )
            }
        }
    }

    if (confirm) {
        ConfirmDialog(
            title = "Uninstall ${chosen.size} ${if (chosen.size == 1) "app" else "apps"}?",
            text = "Android asks you to confirm each one. Their data is removed too.",
            confirmLabel = "Continue",
            onConfirm = { uninstall(chosen.map { it.packageName }) },
            onDismiss = { confirm = false },
        )
    }
}

@Composable
fun AppRow(app: AppInfo, detail: String, selected: Boolean, onClick: () -> Unit, onLongClick: () -> Unit) {
    ItemRow(
        title = app.label,
        subtitle = detail,
        leading = { AppIcon(app.packageName) },
        trailing = {
            Text(
                if (app.hasSizes) app.totalBytes.formatBytes() else app.appBytes.formatBytes(),
                style = MaterialTheme.typography.labelLarge,
            )
        },
        selected = selected,
        onClick = onClick,
        onLongClick = onLongClick,
    )
}

fun unusedApps(apps: List<AppInfo>, days: Int): List<AppInfo> {
    val cutoff = System.currentTimeMillis() - days * DAY_MS
    return apps.filter { !it.system && it.firstInstall < cutoff && it.lastUsed < cutoff && it.packageName != "app.lumaclean" }
}

@Composable
fun UnusedAppsScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val state by c.appsTask.state.collectAsStateWithLifecycle()
    var days by rememberSaveable { mutableIntStateOf(60) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var confirm by remember { mutableStateOf(false) }
    val uninstall = rememberUninstaller { pkg -> selected = selected - pkg }
    LaunchedEffect(Unit) { c.appsTask.ensure() }

    val list = state.value?.let { unusedApps(it, days).sortedByDescending { a -> a.totalBytes } }.orEmpty()
    val chosen = list.filter { it.packageName in selected }

    ScreenScaffold(
        title = "Unused apps",
        subtitle = "${list.size} apps · ${list.sumOf { it.totalBytes }.formatBytes()}",
        onBack = { nav.back() },
        bottomBar = {
            if (selected.isNotEmpty()) {
                SelectionBar(
                    text = "${chosen.size} apps · ${chosen.sumOf { it.totalBytes }.formatBytes()}",
                    primaryLabel = "Uninstall",
                    onPrimary = { confirm = true },
                    onClear = { selected = emptySet() },
                )
            }
        },
    ) { padding ->
        LumaList(padding, spacing = 2.dp) {
            if (!perms.usage) {
                item { UsagePermissionCard("when you last opened each app") }
                return@LumaList
            }
            item {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(30, 60, 90, 180).forEach { d -> FilterChip(selected = days == d, onClick = { days = d }, label = { Text("$d+ days") }) }
                }
            }
            (state as? TaskState.Running<*>)?.let { s -> if (state.value == null) item { TaskProgressCard(s, "Reading your apps", onCancel = { c.appsTask.cancel() }) } }
            if (state.value != null && list.isEmpty()) {
                item { EmptyState(Icons.Rounded.CheckCircle, "No unused apps", "You've opened every app in the last $days days.") }
            }
            items(list, key = { it.packageName }) { app ->
                AppRow(
                    app = app,
                    detail = if (app.lastUsed > 0) "Last used ${app.lastUsed.relativeTime()}" else "Not opened in over a year",
                    selected = app.packageName in selected,
                    onClick = { selected = if (app.packageName in selected) selected - app.packageName else selected + app.packageName },
                    onLongClick = { nav.open(Route.AppDetail(app.packageName)) },
                )
            }
            if (list.isNotEmpty()) {
                item {
                    Text(
                        "Tap to select, long-press for details. ${list.size.formatCount()} apps could free ${list.sumOf { it.totalBytes }.formatBytes()}.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }

    if (confirm) {
        ConfirmDialog(
            title = "Uninstall ${chosen.size} ${if (chosen.size == 1) "app" else "apps"}?",
            text = "Android asks you to confirm each one.",
            confirmLabel = "Continue",
            onConfirm = { uninstall(chosen.map { it.packageName }) },
            onDismiss = { confirm = false },
        )
    }
}
