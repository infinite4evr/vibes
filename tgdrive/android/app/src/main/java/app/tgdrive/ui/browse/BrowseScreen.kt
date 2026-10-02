package app.tgdrive.ui.browse

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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.data.Folder
import app.tgdrive.data.str
import app.tgdrive.ui.actions.Actions
import app.tgdrive.ui.actions.Overlay
import app.tgdrive.ui.components.CountTab
import app.tgdrive.ui.components.EmptyState
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.components.SectionHeader
import app.tgdrive.ui.components.Spinner
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.files.FileCard
import app.tgdrive.ui.files.FileRow
import app.tgdrive.ui.files.FolderCard
import app.tgdrive.ui.files.FolderTile
import app.tgdrive.ui.files.SkeletonCard
import app.tgdrive.ui.files.ThumbSource
import app.tgdrive.ui.nav.View
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.util.Format
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter

/** One entry of the grid: a file, or an album (files sent together) shown as one stack. */
private data class Entry(val f: FileItem, val stack: List<FileItem>? = null)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BrowseScreen(
    model: BrowseModel,
    state: AppState,
    actions: Actions,
    thumbs: ThumbSource,
    onOpen: (List<FileItem>, Int) -> Unit,
    onNavigate: (View) -> Unit,
    onUpload: () -> Unit,
    onNewFolder: () -> Unit,
    contentPadding: PaddingValues,
) {
    val c = Tg.colors
    val settings by state.settings.collectAsState()
    val foldersResp by state.folders.collectAsState()
    val local by state.local.collectAsState()
    val gridView = (settings.str("view") ?: "grid") != "list"
    val size = settings.str("grid_size") ?: "m"
    val minCell: Dp = when (size) { "s" -> 104.dp; "l" -> 230.dp; else -> 156.dp }
    val groupByDate = settings.str("group_by_date") == "true"
    val stackAlbums = settings.str("stack_albums") != "false"
    val folderStyle = settings.str("folder_style") ?: "tiles"
    val compact = settings.str("density") == "compact"

    LaunchedEffect(model) { if (!model.loaded && !model.loading) model.reload() }
    LaunchedEffect(model) {
        state.changes.collectLatest { what ->
            when {
                what == "transfer" && model.view !is View.Drive -> {}
                // New files while you're further down the list: don't pull it from under you.
                what == "new" && model.items.size > BrowseModel.PAGE -> model.hasNew = true
                what == "new" -> model.reload(silent = true)
                // The service is up (the list showed what was saved, or waited for it): refresh in place.
                what == "reconnected" -> model.reload(silent = model.loaded)
                else -> model.reload(keepStats = false)
            }
        }
    }

    val folderId = (model.view as? View.Drive)?.folderId
    val subFolders: List<Folder> = remember(foldersResp, model.view, local["folder_sort"]) {
        if (model.view is View.Drive && model.smartFolder == null) sortFolders(foldersResp.folders.filter { it.parentId == folderId }, local["folder_sort"])
        else emptyList()
    }
    var foldersOpen by rememberSaveable(model.view) { mutableStateOf(true) }
    val covers by produceCovers(state, folderStyle == "cards" && subFolders.isNotEmpty())

    val entries: List<Entry> = remember(model.items.toList(), stackAlbums, gridView, model.view) {
        val out = ArrayList<Entry>()
        val stack = stackAlbums && gridView && model.view !is View.Album
        for (f in model.items) {
            val last = out.lastOrNull()
            if (stack && f.groupedId != null && last != null && last.f.groupedId == f.groupedId && last.f.chatId == f.chatId) {
                out[out.lastIndex] = last.copy(stack = (last.stack ?: listOf(last.f)) + f)
            } else out += Entry(f)
        }
        out
    }

    val grid = rememberLazyGridState()
    LaunchedEffect(grid, model) {
        snapshotFlow { grid.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0 }
            .distinctUntilChanged()
            .filter { it >= grid.layoutInfo.totalItemsCount - 24 }
            .collectLatest { if (model.next != null) model.loadMore() }
    }

    val refreshing = model.loading && model.loaded && !model.silent
    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { model.reload(); state.reloadAll() }, modifier = Modifier.fillMaxSize()) {
        LazyVerticalGrid(
            columns = if (gridView) GridCells.Adaptive(minCell) else GridCells.Fixed(1),
            state = grid,
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = if (gridView) 12.dp else 0.dp, end = if (gridView) 12.dp else 0.dp,
                top = contentPadding.calculateTopPadding(), bottom = contentPadding.calculateBottomPadding() + 96.dp,
            ),
            horizontalArrangement = Arrangement.spacedBy(if (gridView) 10.dp else 0.dp),
            verticalArrangement = Arrangement.spacedBy(if (gridView) 10.dp else 0.dp),
        ) {
            full("head") { Header(model, state, actions, onNavigate, gridView) }
            full("tabs") { KindTabs(model) }
            if (model.adv.isNotEmpty()) full("filters") { ActiveFilters(model) }
            val correction = model.corrected
            if (correction != null && model.view is View.Search) full("did-you-mean") { DidYouMean(correction, (model.view as View.Search).q, onNavigate) }

            if (subFolders.isNotEmpty()) {
                full("folders-head") {
                    SectionHeader("Folders", subFolders.size.toLong(), Modifier.padding(horizontal = if (gridView) 4.dp else 16.dp)
                        .clickable { foldersOpen = !foldersOpen }) {
                        TgIconView(if (foldersOpen) TgIcons.chevronDown else TgIcons.chevron, tint = c.ink3, size = 16.dp)
                    }
                }
                if (foldersOpen) {
                    for (fo in subFolders) {
                        val kids = foldersResp.folders.count { it.parentId == fo.id }
                        if (folderStyle == "cards") {
                            item(key = "fo:${fo.id}", span = { GridItemSpan(if (gridView) 1 else maxLineSpan) }) {
                                FolderCard(fo, kids, covers[fo.id].orEmpty(), onClick = { onNavigate(View.Drive(fo.id)) },
                                    onMore = { actions.open(Overlay.FolderMenu(fo)) },
                                    modifier = if (gridView) Modifier else Modifier.padding(horizontal = 16.dp, vertical = 5.dp))
                            }
                        } else {
                            item(key = "fo:${fo.id}", span = { GridItemSpan(maxLineSpan) }) {
                                FolderTile(fo, kids, onClick = { onNavigate(View.Drive(fo.id)) }, onMore = { actions.open(Overlay.FolderMenu(fo)) },
                                    modifier = Modifier.padding(horizontal = if (gridView) 0.dp else 16.dp, vertical = if (folderStyle == "list") 0.dp else 0.dp))
                            }
                        }
                    }
                }
                if (entries.isNotEmpty()) full("files-head") {
                    SectionHeader("Files", null, Modifier.padding(start = if (gridView) 4.dp else 16.dp, top = 8.dp))
                }
            }

            when {
                model.error != null && model.items.isEmpty() -> full("error") {
                    // The error dialog (with "Create GitHub issue") opens by itself, once per error.
                    var details by remember(model.error) { mutableStateOf(true) }
                    EmptyState(TgIcons.info, "Couldn't load the files", model.error, action = "Try again", onAction = { model.reload() },
                        secondary = "Report this", onSecondary = { details = true })
                    if (details) app.tgdrive.diag.ErrorDetailsDialog("Couldn't load ${model.view}: ${model.error}", null) { details = false }
                }
                !model.loaded && model.loading -> {
                    if (gridView) items(8, key = null) { SkeletonCard() }
                    else full("loading") { Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) { Spinner() } }
                }
                model.loaded && entries.isEmpty() && subFolders.isEmpty() -> full("empty") { EmptyFor(model, onUpload, onNewFolder, onNavigate) }
                else -> fileItems(entries, model, actions, thumbs, gridView, groupByDate, compact, onOpen, onNavigate)
            }

            if (model.loadingMore) full("more") { Box(Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) { Spinner(20.dp) } }
            val moreErr = model.moreError
            if (moreErr != null) full("more-error") {
                Column(Modifier.fillMaxWidth().padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Couldn't load more files: $moreErr", style = Tg.type.meta, color = c.ink2)
                    app.tgdrive.diag.AutoErrorDialog("Couldn't load more files in ${model.view}: $moreErr")
                    Spacer(Modifier.height(8.dp))
                    TgButton("Try again", { model.loadMore() }, small = true, icon = TgIcons.refresh)
                }
            }
        }
        if (model.hasNew) {
            val pillScope = androidx.compose.runtime.rememberCoroutineScope()
            TgButton("New files · Show", {
                model.reload()
                pillScope.launch { grid.scrollToItem(0) }
            }, small = true, icon = TgIcons.refresh, kind = ButtonKind.Primary,
                modifier = Modifier.align(Alignment.TopCenter).padding(top = 10.dp))
        }
    }
}

private fun LazyGridScope.full(key: String, content: @Composable () -> Unit) =
    item(key = key, span = { GridItemSpan(maxLineSpan) }) { content() }

private fun LazyGridScope.fileItems(
    entries: List<Entry>, model: BrowseModel, actions: Actions, thumbs: ThumbSource, gridView: Boolean, groupByDate: Boolean,
    compact: Boolean, onOpen: (List<FileItem>, Int) -> Unit, onNavigate: (View) -> Unit,
) {
    var lastGroup: String? = null
    val bySort = model.effectiveSort
    entries.forEachIndexed { i, e ->
        val group = when {
            e.f.match == "related" && bySort == "relevance" -> "Related by meaning"
            groupByDate && (bySort == "date" || bySort == "recent") -> Format.dateGroup(e.f.date)
            else -> null
        }
        if (group != null && group != lastGroup) {
            val g = group
            item(key = "g:$g:$i", span = { GridItemSpan(maxLineSpan) }) { GroupSeparator(g, gridView) }
        }
        lastGroup = group ?: lastGroup
        item(key = e.f.key) {
            val f = e.f
            val selected = model.selected.containsKey(f.key)
            val click = {
                when {
                    model.selecting -> model.toggle(f)
                    e.stack != null -> onNavigate(View.Album(f.chatId, f.groupedId!!))
                    else -> {
                        val list = model.items.toList()
                        onOpen(list, list.indexOfFirst { it.key == f.key }.coerceAtLeast(0))
                    }
                }
            }
            if (gridView) {
                FileCard(f, thumbs, selected, model.selecting, model.words, onClick = click, onLongClick = { model.toggle(f) },
                    onMore = { actions.open(Overlay.FileMenu(f)) }, stack = e.stack?.size ?: 0, compact = false)
            } else {
                FileRow(f, thumbs, selected, model.selecting, model.words, onClick = click, onLongClick = { model.toggle(f) },
                    onMore = { actions.open(Overlay.FileMenu(f)) }, compact = compact)
            }
        }
    }
}

@Composable
private fun GroupSeparator(label: String, gridView: Boolean) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().padding(start = if (gridView) 4.dp else 16.dp, end = if (gridView) 4.dp else 16.dp, top = 10.dp, bottom = 2.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = Tg.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.ink2)
        Spacer(Modifier.width(10.dp))
        Box(Modifier.weight(1f).height(1.dp).background(c.line2))
    }
}

// ---------------------------------------------------------------------- header
@Composable
private fun Header(model: BrowseModel, state: AppState, actions: Actions, onNavigate: (View) -> Unit, gridView: Boolean) {
    val c = Tg.colors
    val folders by state.folders.collectAsState()
    val v = model.view
    Column(Modifier.fillMaxWidth().padding(start = if (gridView) 4.dp else 16.dp, end = if (gridView) 0.dp else 8.dp, top = 6.dp)) {
        if (v is View.Drive && v.folderId != null) {
            // Breadcrumbs: My Drive › Study › Economy
            val path = remember(folders, v.folderId) {
                val byId = folders.folders.associateBy { it.id }
                generateSequence(byId[v.folderId]) { f -> f.parentId?.let { byId[it] } }.toList().reversed()
            }
            Row(Modifier.horizontalScroll(rememberScrollState()), verticalAlignment = Alignment.CenterVertically) {
                Crumb("My Drive") { onNavigate(View.Drive(null)) }
                for (p in path.dropLast(1)) {
                    TgIconView(TgIcons.chevron, tint = c.ink3, size = 14.dp)
                    Crumb(p.name) { onNavigate(View.Drive(p.id)) }
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(viewTitle(state, v), style = Tg.type.title, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).padding(vertical = 4.dp))
            model.smartFolder?.let {
                TgChip("Smart", icon = TgIcons.folderSmart, selected = true)
            }
        }
        val st = model.stats
        val bits = buildList {
            if (st != null) {
                val n = if (model.kind.isEmpty()) st.total else st.kindCounts[model.kind] ?: 0
                add(Format.plural(n, "file"))
                if (model.kind.isEmpty()) add(Format.size(st.totalBytes))
            }
            if (model.isTextSearch && model.tookMs != null) add("${model.tookMs} ms")
        }
        if (bits.isNotEmpty()) Text(bits.joinToString(" · "), style = Tg.type.meta, color = c.ink3)
        Spacer(Modifier.height(10.dp))
        Toolbar(model, actions, gridView, state)
    }
}

@Composable
private fun Crumb(text: String, onClick: () -> Unit) {
    Text(text, style = Tg.type.label, color = Tg.colors.ink2, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClick = onClick).padding(horizontal = 4.dp, vertical = 4.dp))
}

@Composable
private fun Toolbar(model: BrowseModel, actions: Actions, gridView: Boolean, state: AppState) {
    val c = Tg.colors
    val sortKey = if (model.effectiveSort == "relevance" && model.isTextSearch) "relevance:desc" else "${model.sort}:${model.order}"
    val sortLabel = SORTS.firstOrNull { it.first == sortKey }?.second ?: when (model.effectiveSort) {
        "recent" -> "Recently opened"; "played" -> "Recently played"; else -> "Newest first"
    }
    val hide = state.setting("hide_duplicates") != "false"
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        // Sort, copies and filters scroll sideways when they don't fit (a narrow phone, large text, a long
        // sort name); View and More always stay on screen.
        Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(
                Modifier.clip(RoundedCornerShape(9.dp)).border(1.dp, c.line, RoundedCornerShape(9.dp)).background(c.panel)
                    .clickable { actions.open(Overlay.Sort(model)) }.padding(start = 12.dp, end = 8.dp).height(36.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(sortLabel, style = Tg.type.label, color = c.ink, maxLines = 1)
                Spacer(Modifier.width(4.dp))
                TgIconView(TgIcons.chevronDown, tint = c.ink2, size = 16.dp)
            }
            IconBtn(TgIcons.copy, { state.setSetting("hide_duplicates", !hide); model.reload() }, active = hide, size = 36.dp, iconSize = 19.dp,
                contentDescription = if (hide) "Showing one card per file (tap to show copies)" else "Showing every copy")
            Row(
                Modifier.clip(RoundedCornerShape(9.dp)).border(1.dp, if (model.adv.isNotEmpty()) c.accentLine else c.line, RoundedCornerShape(9.dp))
                    .background(if (model.adv.isNotEmpty()) c.accentSoft else c.panel)
                    .clickable { actions.open(Overlay.Filters(model)) }.padding(horizontal = 10.dp).height(36.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TgIconView(TgIcons.filter, tint = if (model.adv.isNotEmpty()) c.accent else c.ink2, size = 17.dp)
                Spacer(Modifier.width(6.dp))
                Text(if (model.adv.isEmpty()) "Filters" else "Filters · ${model.adv.size}", style = Tg.type.label,
                    color = if (model.adv.isNotEmpty()) c.accent else c.ink, maxLines = 1)
            }
        }
        IconBtn(if (gridView) TgIcons.grid else TgIcons.list, { actions.open(Overlay.ViewOptions(model)) }, size = 36.dp, iconSize = 20.dp,
            contentDescription = "View")
        IconBtn(TgIcons.more, { actions.open(Overlay.ListMenu(model)) }, size = 36.dp, iconSize = 20.dp, contentDescription = "More")
    }
}

@Composable
private fun KindTabs(model: BrowseModel) {
    val c = Tg.colors
    val st = model.stats
    val tabs = Format.KIND_PLURAL.filter { (k, _) -> k.isEmpty() || (st?.kindCounts?.get(k) ?: 0) > 0 || model.kind == k }
    // A lazy row, not a scrolled Row: screen readers (and UI tests) get the tabs' real positions
    // after it scrolls, and can scroll it themselves.
    val scroll = androidx.compose.foundation.lazy.rememberLazyListState()
    Column(Modifier.fillMaxWidth()) {
        Box(Modifier.fillMaxWidth()) {
            androidx.compose.foundation.lazy.LazyRow(Modifier.fillMaxWidth(), state = scroll,
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 4.dp)) {
                items(tabs.size, key = { tabs[it].first }) { i ->
                    val (k, label) = tabs[i]
                    val n = if (k.isEmpty()) st?.total else st?.kindCounts?.get(k)
                    CountTab(label, n, model.kind == k, { model.setKindFilter(k) }, dot = if (k.isEmpty()) null else c.kind(k))
                }
            }
            // More types to the side: fade the edge, so it's clear the row scrolls.
            if (scroll.canScrollForward) Box(Modifier.align(Alignment.CenterEnd).width(36.dp).height(45.dp)
                .background(androidx.compose.ui.graphics.Brush.horizontalGradient(listOf(c.canvas.copy(alpha = 0f), c.canvas))))
            if (scroll.canScrollBackward) Box(Modifier.align(Alignment.CenterStart).width(28.dp).height(45.dp)
                .background(androidx.compose.ui.graphics.Brush.horizontalGradient(listOf(c.canvas, c.canvas.copy(alpha = 0f)))))
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
        Spacer(Modifier.height(6.dp))
    }
}

@Composable
private fun ActiveFilters(model: BrowseModel) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        for ((k, v) in model.adv) {
            TgChip(filterLabel(k, v), selected = true, onClose = { model.setFilters(model.adv - k) })
        }
        TgChip("Clear all", onClick = { model.setFilters(emptyMap()) })
    }
}

fun filterLabel(k: String, v: String): String = when (k) {
    "exts" -> v.split(",").joinToString(", ") { ".$it" }
    "size_min" -> "Bigger than $v"
    "size_max" -> "Smaller than $v"
    "date_from" -> "After $v"
    "date_to" -> "Before $v"
    "dur_min" -> "Longer than $v"
    "dur_max" -> "Shorter than $v"
    "chat_kinds" -> v.split(",").joinToString(", ") { Format.CHAT_KIND_NAME[it] ?: it }
    "sender" -> "From $v"
    "starred" -> if (v == "1") "Starred" else "Not starred"
    "forwarded" -> if (v == "1") "Forwarded" else "Not forwarded"
    "mine" -> if (v == "1") "Sent by me" else "Sent by others"
    "has_caption" -> if (v == "1") "With a caption" else "Without a caption"
    "has_note" -> "With a note"
    "has_tags" -> "With tags"
    "filed" -> if (v == "1") "In a folder" else "Not in a folder"
    "watched" -> if (v == "1") "Watched" else "Not watched"
    "in_progress" -> "Started"
    "tag" -> "#$v"
    "match" -> if (v == "exact") "Exact words" else "Smart"
    else -> "$k: $v"
}

@Composable
private fun DidYouMean(corrected: String, q: String, onNavigate: (View) -> Unit) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp).clip(RoundedCornerShape(10.dp)).background(c.panel2)
        .padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
        TgIconView(TgIcons.sparkle, tint = c.accent, size = 18.dp)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text("Showing results for “$corrected”", style = Tg.type.label, color = c.ink)
            Text("Search only for “$q”", style = Tg.type.meta, color = c.accent,
                modifier = Modifier.clickable { onNavigate(View.Search("$q match:exact")) })
        }
    }
}

@Composable
private fun EmptyFor(model: BrowseModel, onUpload: () -> Unit, onNewFolder: () -> Unit, onNavigate: (View) -> Unit) {
    val v = model.view
    val filtered = model.adv.isNotEmpty() || model.kind.isNotEmpty()
    when {
        filtered -> EmptyState(TgIcons.filter, "Nothing matches these filters", "Try fewer filters or another type.",
            action = "Clear filters", onAction = { model.kind = ""; model.setFilters(emptyMap()) })
        v is View.Search -> EmptyState(TgIcons.search, "Nothing matches “${v.q}”",
            "Try other words, fewer words or check the spelling. Search also finds files by meaning once TG Drive has read their names.")
        v is View.Drive && model.smartFolder != null -> EmptyState(TgIcons.folderSmart, "No files match this smart folder's rule yet",
            "Files that match appear here by themselves.")
        v is View.Drive -> EmptyState(TgIcons.folder, if (v.folderId == null) "Nothing in My Drive yet" else "This folder is empty",
            "Upload files from this phone, or move files here from any chat.", action = "Upload", onAction = onUpload,
            secondary = "New folder", onSecondary = onNewFolder)
        v == View.Starred -> EmptyState(TgIcons.star, "No starred files", "Star files to find them here quickly.")
        v == View.Recent -> EmptyState(TgIcons.clock, "Nothing opened yet", "Files you open or play show up here.")
        v == View.Continue -> EmptyState(TgIcons.play, "Nothing to continue", "Videos and audio you stop part-way through show up here.")
        v is View.Chat -> EmptyState(TgIcons.chat, "No files in this chat", "TG Drive may still be indexing it.",
            action = "All files", onAction = { onNavigate(View.All) })
        else -> EmptyState(TgIcons.document, "No files here")
    }
}

private fun sortFolders(list: List<Folder>, how: String?): List<Folder> = when (how) {
    "files" -> list.sortedByDescending { it.fileCount }
    "size" -> list.sortedByDescending { it.bytes }
    "newest" -> list.sortedByDescending { it.created ?: 0 }
    else -> list.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.name })
}

@Composable
private fun produceCovers(state: AppState, wanted: Boolean): androidx.compose.runtime.State<Map<String, List<String>>> {
    val aid by state.aid.collectAsState()
    return androidx.compose.runtime.produceState(emptyMap(), wanted, aid) {
        if (!wanted) return@produceState
        value = try {
            state.api.covers(aid).mapValues { (_, list) -> list.map { state.api.thumbUrl(aid, it.chatId, it.msgId) } }
        } catch (_: Exception) { emptyMap() }
    }
}
