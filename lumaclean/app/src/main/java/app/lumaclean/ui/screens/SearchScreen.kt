package app.lumaclean.ui.screens

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.formatBytes
import app.lumaclean.core.startSafely
import app.lumaclean.data.FileCategory
import app.lumaclean.data.FileEntry
import app.lumaclean.data.FileQuery
import app.lumaclean.data.applySort
import app.lumaclean.data.FileSort
import app.lumaclean.data.query
import app.lumaclean.ui.components.AppIcon
import app.lumaclean.ui.components.FileThumb
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SectionHeader
import app.lumaclean.ui.nav.Navigator
import app.lumaclean.ui.nav.Route
import app.lumaclean.ui.nav.Tab
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

private data class Destination(val title: String, val keywords: String, val go: (Navigator, Int) -> Unit)

private val destinations = listOf(
    Destination("Smart Clean", "junk clean cache temp leftovers") { n, _ -> n.select(Tab.CLEAN) },
    Destination("Storage", "space storage analyzer full") { n, _ -> n.select(Tab.STORAGE) },
    Destination("Apps", "apps uninstall installed") { n, _ -> n.select(Tab.APPS) },
    Destination("Browse files", "files file manager folders explorer") { n, _ -> n.open(Route.Browser(android.os.Environment.getExternalStorageDirectory().absolutePath)) },
    Destination("Large files", "big large huge files") { n, mb -> n.open(Route.Files(FileQuery.Large(mb * 1_000_000L))) },
    Destination("Duplicate files", "duplicates copies same") { n, _ -> n.open(Route.Duplicates) },
    Destination("Similar photos", "similar photos burst pictures") { n, _ -> n.open(Route.Similar) },
    Destination("Screenshots", "screenshots screen captures") { n, _ -> n.open(Route.Files(FileQuery.Screenshots)) },
    Destination("Compress photos", "compress shrink photos images") { n, _ -> n.open(Route.Compress) },
    Destination("Chat media", "whatsapp telegram signal chat media") { n, _ -> n.open(Route.ChatMedia) },
    Destination("Installer files", "apk installers packages") { n, _ -> n.open(Route.Files(FileQuery.Category(FileCategory.APKS))) },
    Destination("Recycle bin", "trash bin restore deleted undo") { n, _ -> n.open(Route.RecycleBin) },
    Destination("Free up RAM", "ram memory boost speed slow") { n, _ -> n.open(Route.Ram) },
    Destination("Battery", "battery charge health temperature") { n, _ -> n.open(Route.Battery) },
    Destination("Screen time & data", "screen time usage data mobile wifi") { n, _ -> n.open(Route.AppUsage) },
    Destination("Unused apps", "unused old apps") { n, _ -> n.open(Route.UnusedApps) },
    Destination("Device info", "device phone hardware cpu specs model android version") { n, _ -> n.open(Route.Device) },
    Destination("Network", "network wifi internet ip") { n, _ -> n.open(Route.Network) },
    Destination("Settings", "settings theme dark options") { n, _ -> n.open(Route.Settings) },
    Destination("Never clean list", "exclude ignore never clean") { n, _ -> n.open(Route.Exclusions) },
    Destination("Cleanup history", "history freed log") { n, _ -> n.open(Route.History) },
    Destination("Permissions", "permissions access privacy") { n, _ -> n.open(Route.Permissions) },
)

@Composable
fun SearchScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    val apps by c.appsTask.state.collectAsStateWithLifecycle()
    val index by c.index.current.collectAsStateWithLifecycle()
    var text by rememberSaveable { mutableStateOf("") }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) {
        c.appsTask.ensure()
        focus.requestFocus()
    }
    val q = text.trim()
    val pages = if (q.isEmpty()) destinations.take(8) else destinations.filter { it.title.contains(q, true) || it.keywords.contains(q, true) }
    val appHits = if (q.length < 2) emptyList() else apps.value.orEmpty().filter { it.label.contains(q, true) }.take(8)
    val fileHits by produceState(emptyList<FileEntry>(), q, index) {
        if (q.length < 2) {
            value = emptyList()
            return@produceState
        }
        delay(200)
        value = withContext(Dispatchers.Default) { index?.query(FileQuery.Search(q), settings.showHidden)?.applySort(FileSort.SIZE)?.take(30).orEmpty() }
    }

    ScreenScaffold(title = "Search", onBack = { nav.back() }) { padding ->
        LumaList(padding, modifier = Modifier.imePadding(), spacing = 2.dp) {
            item {
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    placeholder = { Text("Tools, apps or files") },
                    leadingIcon = { Icon(Icons.Rounded.Search, null) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().focusRequester(focus),
                )
            }
            if (pages.isNotEmpty()) {
                item { SectionHeader(if (q.isEmpty()) "Jump to" else "Tools & pages") }
                items(pages, key = { "p" + it.title }) { d ->
                    ItemRow(
                        title = d.title,
                        trailing = { Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, null) },
                        onClick = { d.go(nav, settings.largeFileMb) },
                    )
                }
            }
            if (appHits.isNotEmpty()) {
                item { SectionHeader("Apps") }
                items(appHits, key = { "a" + it.packageName }) { a ->
                    ItemRow(
                        title = a.label,
                        subtitle = a.totalBytes.formatBytes(),
                        leading = { AppIcon(a.packageName) },
                        onClick = { nav.open(Route.AppDetail(a.packageName)) },
                    )
                }
            }
            if (fileHits.isNotEmpty()) {
                item { SectionHeader("Files") }
                items(fileHits, key = { "f" + it.path }) { f ->
                    ItemRow(
                        title = f.name,
                        subtitle = "${f.size.formatBytes()} · ${f.parent.substringAfter("/0/", f.parent)}",
                        leading = { FileThumb(f.path) },
                        onClick = { context.startSafely(c.files.openIntent(f.path)) },
                        onLongClick = { nav.open(Route.Browser(f.parent)) },
                    )
                }
            } else if (q.length >= 2 && index == null) {
                item {
                    Text(
                        "Open Storage once to include files in search.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
