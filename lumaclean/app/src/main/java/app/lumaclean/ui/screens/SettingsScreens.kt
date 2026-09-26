@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package app.lumaclean.ui.screens

import android.Manifest
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.DocumentsContract
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Insights
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.BuildConfig
import app.lumaclean.core.Perms
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatDateTime
import app.lumaclean.core.startSafely
import app.lumaclean.data.Accent
import app.lumaclean.data.StartTab
import app.lumaclean.data.ThemeMode
import app.lumaclean.ui.components.ConfirmDialog
import app.lumaclean.ui.components.EmptyState
import app.lumaclean.ui.components.IconBadge
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SectionHeader
import app.lumaclean.ui.nav.Route
import app.lumaclean.ui.theme.LocalExtraColors
import app.lumaclean.ui.theme.accentSwatch

@Composable
private fun SwitchRow(title: String, subtitle: String?, checked: Boolean, enabled: Boolean = true, onChange: (Boolean) -> Unit) {
    ItemRow(
        title = title,
        subtitle = subtitle,
        trailing = { Switch(checked = checked, onCheckedChange = onChange, enabled = enabled) },
        onClick = { if (enabled) onChange(!checked) },
    )
}

@Composable
private fun ChoiceRow(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
        Text(title, style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
private fun <T> Chips(options: List<T>, selected: T, label: (T) -> String, onSelect: (T) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { o -> FilterChip(selected = o == selected, onClick = { onSelect(o) }, label = { Text(label(o)) }) }
    }
}

@Composable
private fun NavRow(title: String, subtitle: String?, icon: ImageVector, onClick: () -> Unit) {
    ItemRow(
        title = title,
        subtitle = subtitle,
        leading = { IconBadge(icon, MaterialTheme.colorScheme.primary, size = 36.dp) },
        trailing = { Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, null) },
        onClick = onClick,
    )
}

@Composable
fun SettingsScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val s by c.settings.flow.collectAsStateWithLifecycle()
    val exclusions by c.exclusions.paths.collectAsStateWithLifecycle()
    val history by c.history.entries.collectAsStateWithLifecycle()
    val perms by c.perms.state.collectAsStateWithLifecycle()

    ScreenScaffold(title = "Settings", onBack = { nav.back() }) { padding ->
        LumaList(padding) {
            item { SectionHeader("Appearance") }
            item {
                LumaCard(contentPadding = PaddingValues(8.dp)) {
                    ChoiceRow("Theme") {
                        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                            ThemeMode.entries.forEachIndexed { i, m ->
                                SegmentedButton(
                                    selected = s.themeMode == m,
                                    onClick = { c.settings.update { it.copy(themeMode = m) } },
                                    shape = SegmentedButtonDefaults.itemShape(i, ThemeMode.entries.size),
                                ) { Text(m.label) }
                            }
                        }
                    }
                    if (Build.VERSION.SDK_INT >= 31) {
                        SwitchRow("Colours from wallpaper", "Match your phone's Material You colours", s.dynamicColor) { v ->
                            c.settings.update { it.copy(dynamicColor = v) }
                        }
                    }
                    if (!s.dynamicColor || Build.VERSION.SDK_INT < 31) {
                        ChoiceRow("Accent colour") {
                            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                                Accent.entries.forEach { a ->
                                    val sel = s.accent == a
                                    Box(
                                        Modifier.size(44.dp).clip(CircleShape).background(accentSwatch(a))
                                            .then(if (sel) Modifier.border(3.dp, MaterialTheme.colorScheme.onSurface, CircleShape) else Modifier)
                                            .clickable { c.settings.update { it.copy(accent = a) } },
                                        contentAlignment = Alignment.Center,
                                    ) { if (sel) Icon(Icons.Rounded.Check, a.label, tint = MaterialTheme.colorScheme.surface) }
                                }
                            }
                        }
                    }
                    ChoiceRow("Open the app on") {
                        Chips(StartTab.entries, s.startTab, { it.label }) { t -> c.settings.update { it.copy(startTab = t) } }
                    }
                }
            }

            item { SectionHeader("Cleaning") }
            item {
                LumaCard(contentPadding = PaddingValues(8.dp)) {
                    SwitchRow("Use the recycle bin", "Deleted files can be restored for a while", s.useRecycleBin) { v ->
                        c.settings.update { it.copy(useRecycleBin = v) }
                    }
                    if (s.useRecycleBin) {
                        ChoiceRow("Keep deleted files for") {
                            Chips(listOf(7, 14, 30, 60), s.recycleDays, { "$it days" }) { d -> c.settings.update { it.copy(recycleDays = d) } }
                        }
                    }
                    ChoiceRow("A download counts as old after") {
                        Chips(listOf(30, 60, 90, 180, 365), s.oldDownloadDays, { if (it == 365) "1 year" else "$it days" }) { d ->
                            c.settings.update { it.copy(oldDownloadDays = d) }
                        }
                    }
                    ChoiceRow("A file counts as large from") {
                        Chips(listOf(50, 100, 250, 500, 1000), s.largeFileMb, { if (it >= 1000) "1 GB" else "$it MB" }) { mb ->
                            c.settings.update { it.copy(largeFileMb = mb) }
                        }
                    }
                    SwitchRow("Show hidden files", "Files and folders starting with a dot", s.showHidden) { v ->
                        c.settings.update { it.copy(showHidden = v) }
                    }
                    NavRow("Never clean", if (exclusions.isEmpty()) "Nothing excluded" else "${exclusions.size} folders and files", Icons.Rounded.Block) {
                        nav.open(Route.Exclusions)
                    }
                    NavRow("Cleanup history", if (history.isEmpty()) "Nothing yet" else "${history.sumOf { it.bytes }.formatBytes()} freed so far", Icons.Rounded.History) {
                        nav.open(Route.History)
                    }
                }
            }

            item { SectionHeader("Background") }
            item {
                LumaCard(contentPadding = PaddingValues(8.dp)) {
                    SwitchRow("Weekly checkup", "A quiet scan each week; you're told only if there's lots to clean", s.weeklyCheckup) { v ->
                        c.settings.update { it.copy(weeklyCheckup = v) }
                    }
                    SwitchRow("Storage alerts", "When storage is almost full", s.storageAlerts) { v ->
                        c.settings.update { it.copy(storageAlerts = v) }
                    }
                    SwitchRow("Battery alerts", "When the battery gets too hot", s.batteryAlerts) { v ->
                        c.settings.update { it.copy(batteryAlerts = v) }
                    }
                    if (!perms.notifications) {
                        Text(
                            "Notifications are off for LumaClean, so alerts can't appear.",
                            style = MaterialTheme.typography.bodySmall,
                            color = LocalExtraColors.current.warning,
                            modifier = Modifier.padding(horizontal = 12.dp),
                        )
                    }
                }
            }

            item { SectionHeader("Privacy & access") }
            item {
                LumaCard(contentPadding = PaddingValues(8.dp)) {
                    NavRow("Permissions", "What LumaClean can access and why", Icons.Rounded.Lock) { nav.open(Route.Permissions) }
                    ItemRow(
                        title = "Works fully offline",
                        subtitle = "LumaClean has no internet permission. Your files, apps and usage never leave the phone.",
                        leading = { IconBadge(Icons.Rounded.Shield, LocalExtraColors.current.success, size = 36.dp) },
                    )
                }
            }
            item {
                ItemRow(
                    title = "LumaClean ${BuildConfig.VERSION_NAME}",
                    subtitle = "Build ${BuildConfig.VERSION_CODE}",
                    leading = { IconBadge(Icons.Rounded.Info, MaterialTheme.colorScheme.primary, size = 36.dp) },
                )
            }
        }
    }
}

@Composable
fun HistoryScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val entries by c.history.entries.collectAsStateWithLifecycle()
    var confirm by remember { mutableStateOf(false) }
    ScreenScaffold(
        title = "Cleanup history",
        subtitle = "${entries.sumOf { it.bytes }.formatBytes()} freed in total",
        onBack = { nav.back() },
        actions = { if (entries.isNotEmpty()) IconButton(onClick = { confirm = true }) { Icon(Icons.Rounded.Delete, "Clear history") } },
    ) { padding ->
        LumaList(padding, spacing = 2.dp) {
            if (entries.isEmpty()) item { EmptyState(Icons.Rounded.History, "No cleanups yet", "Every cleanup and how much it freed shows up here.") }
            items(entries, key = { "${it.time}-${it.title}" }) { e ->
                ItemRow(
                    title = e.title,
                    subtitle = "${e.time.formatDateTime()} · ${e.items} items",
                    leading = { IconBadge(Icons.Rounded.CheckCircle, LocalExtraColors.current.success, size = 36.dp) },
                    trailing = { Text(e.bytes.formatBytes(), style = MaterialTheme.typography.titleSmall) },
                )
            }
        }
    }
    if (confirm) {
        ConfirmDialog("Clear history?", "The list of past cleanups is removed. Nothing else changes.", "Clear", onConfirm = { c.history.clear() }, onDismiss = { confirm = false })
    }
}

/** Turns a document-tree URI from the folder picker into a file path on primary storage. */
private fun treeToPath(uri: Uri): String? {
    val id = runCatching { DocumentsContract.getTreeDocumentId(uri) }.getOrNull() ?: return null
    val volume = id.substringBefore(':')
    val rel = id.substringAfter(':', "")
    val root = if (volume == "primary") Environment.getExternalStorageDirectory().absolutePath else "/storage/$volume"
    return if (rel.isEmpty()) root else "$root/$rel"
}

@Composable
fun ExclusionsScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val paths by c.exclusions.paths.collectAsStateWithLifecycle()
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        uri?.let(::treeToPath)?.let {
            c.exclusions.add(it)
            c.message("Won't clean anything in ${it.substringAfterLast('/')}")
        }
    }
    ScreenScaffold(
        title = "Never clean",
        onBack = { nav.back() },
        actions = { IconButton(onClick = { picker.launch(null) }) { Icon(Icons.Rounded.Add, "Add a folder") } },
    ) { padding ->
        LumaList(padding, spacing = 2.dp) {
            item {
                Text(
                    "Smart Clean and duplicate scans skip these folders and files. Long-press an item in Smart Clean to add it here.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 8.dp),
                )
            }
            if (paths.isEmpty()) {
                item { EmptyState(Icons.Rounded.Block, "Nothing excluded", "Add folders you never want touched.", actionLabel = "Add a folder", onAction = { picker.launch(null) }) }
            }
            items(paths, key = { it }) { p ->
                ItemRow(
                    title = p.substringAfterLast('/'),
                    subtitle = c.storage.displayPath(p),
                    leading = { IconBadge(Icons.Rounded.Folder, MaterialTheme.colorScheme.primary, size = 36.dp) },
                    trailing = { IconButton(onClick = { c.exclusions.remove(p) }) { Icon(Icons.Rounded.Close, "Remove") } },
                )
            }
        }
    }
}

/** The three permission rows, shared by the permissions screen and onboarding. */
@Composable
fun PermissionRows() {
    val c = LocalContainer.current
    val context = LocalContext.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val storageLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { c.perms.refresh() }
    val notifLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { c.perms.refresh() }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        PermissionRow(
            Icons.Rounded.Folder, "Files", "Needed for Smart Clean, duplicates, large files, photos and the file manager.", perms.allFiles,
        ) {
            if (Perms.needsSettingsForFiles) context.startSafely(Perms.allFilesIntent(context), Perms.allFilesFallbackIntent())
            else storageLauncher.launch(Perms.legacyStorage)
        }
        PermissionRow(
            Icons.Rounded.Insights, "Usage access", "App sizes, unused apps, screen time and data usage.", perms.usage,
        ) { context.startSafely(Perms.usageIntent(context)) }
        PermissionRow(
            Icons.Rounded.Notifications, "Notifications", "Weekly checkup results and alerts. Optional.", perms.notifications,
        ) {
            if (Build.VERSION.SDK_INT >= 33) notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            else context.startSafely(Perms.notificationSettingsIntent(context))
        }
    }
}

@Composable
private fun PermissionRow(icon: ImageVector, title: String, why: String, granted: Boolean, onGrant: () -> Unit) {
    LumaCard(contentPadding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBadge(icon, if (granted) LocalExtraColors.current.success else MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                Text(why, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.width(8.dp))
            if (granted) {
                Icon(Icons.Rounded.CheckCircle, "Allowed", tint = LocalExtraColors.current.success)
            } else {
                FilledTonalButton(onClick = onGrant) { Text("Allow") }
            }
        }
    }
}

@Composable
fun PermissionsScreen() {
    val nav = LocalNavigator.current
    ScreenScaffold(title = "Permissions", onBack = { nav.back() }) { padding ->
        LumaList(padding) {
            item { PermissionRows() }
            item {
                Text(
                    "You can take any of these back in Android settings. LumaClean has no internet access, so nothing it reads can leave your phone.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 8.dp),
                )
            }
        }
    }
}

@Composable
fun OnboardingScreen(onDone: () -> Unit) {
    val c = LocalContainer.current
    var step by remember { mutableStateOf(0) }
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    androidx.compose.material3.Scaffold { padding ->
        LumaList(padding, spacing = 16.dp) {
            item { Spacer(Modifier.height(32.dp)) }
            when (step) {
                0 -> {
                    item {
                        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                            IconBadge(Icons.Rounded.Shield, MaterialTheme.colorScheme.primary, size = 96.dp)
                            Spacer(Modifier.height(24.dp))
                            Text("Welcome to LumaClean", style = MaterialTheme.typography.headlineMedium)
                            Spacer(Modifier.height(8.dp))
                            Text(
                                "Free up space, find what's slowing your phone down and keep it healthy.",
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                            )
                        }
                    }
                    listOf(
                        Triple(Icons.Rounded.CheckCircle, "Honest cleaning", "Only real junk, shown before anything is removed. Deleted files wait in a recycle bin."),
                        Triple(Icons.Rounded.Insights, "Everything in one place", "Storage, apps, battery, photos, duplicates, screen time and more."),
                        Triple(Icons.Rounded.Lock, "Private by design", "No internet permission, no ads, no tracking. Nothing leaves your phone."),
                    ).forEach { (icon, title, body) ->
                        item {
                            LumaCard(contentPadding = PaddingValues(16.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    IconBadge(icon, MaterialTheme.colorScheme.primary)
                                    Spacer(Modifier.width(14.dp))
                                    Column {
                                        Text(title, style = MaterialTheme.typography.titleMedium)
                                        Text(body, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            }
                        }
                    }
                    item { Button(onClick = { step = 1 }, modifier = Modifier.fillMaxWidth()) { Text("Get started") } }
                }
                1 -> {
                    item {
                        Text("A few permissions", style = MaterialTheme.typography.headlineSmall)
                        Text(
                            "Allow what you're comfortable with. Every feature explains what it needs when you open it.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    item { PermissionRows() }
                    item {
                        LumaCard(contentPadding = PaddingValues(8.dp)) {
                            SwitchRow("Weekly checkup", "A quiet scan each week", settings.weeklyCheckup) { v -> c.settings.update { it.copy(weeklyCheckup = v) } }
                        }
                    }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = { step = 0 }) { Text("Back") }
                            Spacer(Modifier.weight(1f))
                            Button(onClick = onDone) { Text("Start using LumaClean") }
                        }
                    }
                }
                else -> {}
            }
        }
    }
}
