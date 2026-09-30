package app.tgdrive.ui.photos

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.data.Month
import app.tgdrive.ui.actions.ChatPickerSheet
import app.tgdrive.ui.components.EmptyState
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.components.shimmer
import app.tgdrive.ui.files.FileThumb
import app.tgdrive.ui.files.ThumbSource
import app.tgdrive.ui.pages.PageBar
import app.tgdrive.ui.pages.PageError
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.util.Format
import kotlinx.coroutines.launch
import java.time.YearMonth
import java.time.format.TextStyle
import java.util.Locale

private val SIZES = mapOf("s" to 96.dp, "m" to 132.dp, "l" to 196.dp)

/**
 * Photos (desktop photos.js): every photo and video on one timeline, month by month, with a date
 * scrubber on the right. Only the months on screen are loaded, so it stays quick with 100,000 pictures.
 */
@Composable
fun PhotosScreen(state: AppState, thumbs: ThumbSource, onMenu: () -> Unit, onOpen: (List<FileItem>, Int) -> Unit) {
    val c = Tg.colors
    val aid by state.aid.collectAsState()
    val chats by state.chats.collectAsState()
    var kind by remember { mutableStateOf(state.pref("photos_kind").orEmpty()) }
    var size by remember { mutableStateOf(state.pref("photos_size") ?: "m") }
    var chat by remember { mutableStateOf<Long?>(null) }
    var starred by remember { mutableStateOf(false) }
    var pickChat by remember { mutableStateOf(false) }
    var months by remember { mutableStateOf<List<Month>?>(null) }
    var total by remember { mutableStateOf(0L) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val cache = remember { mutableStateMapOf<String, List<FileItem>>() }
    val loading = remember { HashSet<String>() }
    val scope = rememberCoroutineScope()

    fun filters(): Map<String, String> = buildMap {
        put("kinds", kind.ifEmpty { "photo,video" })
        put("copies", if (state.setting("hide_duplicates") == "false") "show" else "hide")
        chat?.let { put("chat_ids", it.toString()) }
        if (starred) put("starred", "1")
    }

    LaunchedEffect(aid, kind, chat, starred, reload) {
        months = null; error = null; cache.clear(); loading.clear()
        try {
            val t = state.api.timeline(aid, filters())
            months = t.months
            total = t.total
        } catch (e: Exception) { error = e.message }
    }

    fun loadMonth(ym: String) {
        if (ym in cache || !loading.add(ym)) return
        val p = filters()
        scope.launch {
            try {
                val out = ArrayList<FileItem>()
                var cursor: String? = null
                do {
                    val page = state.api.files(aid, p + mapOf("date_from" to ym, "date_to" to ym, "sort" to "date", "order" to "desc", "limit" to "500") +
                        (cursor?.let { mapOf("cursor" to it) } ?: emptyMap()))
                    out += page.items
                    cursor = page.next
                } while (cursor != null && out.size < 5000)
                if (p == filters()) cache[ym] = out
            } catch (_: Exception) {
            } finally {
                loading.remove(ym)
            }
        }
    }

    Column(Modifier.fillMaxSize().background(c.canvas)) {
        PageBar("Photos", onMenu) {
            IconBtn(TgIcons.slides, {
                val all = months.orEmpty().flatMap { cache[it.ym].orEmpty() }.filter { it.kind == "photo" }
                if (all.isNotEmpty()) onOpen(all, 0) else state.message("Scroll to load some photos first.")
            }, contentDescription = "Slideshow")
        }
        Row(Modifier.fillMaxWidth().background(c.panel).horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            listOf("" to "All", "photo" to "Photos", "video" to "Videos").forEach { (k, l) ->
                TgChip(l, selected = kind == k, onClick = { kind = k; state.setPref("photos_kind", k) })
            }
            val chatName = chat?.let { id -> chats.firstOrNull { it.id == id }?.title ?: "A chat" }
            TgChip(chatName ?: "Any chat", icon = TgIcons.chat, selected = chatName != null, onClick = { pickChat = true },
                onClose = if (chatName != null) ({ chat = null }) else null)
            TgChip("Starred", icon = TgIcons.star, selected = starred, onClick = { starred = !starred })
            Spacer(Modifier.width(6.dp))
            listOf("s" to TgIcons.photos, "m" to TgIcons.grid, "l" to TgIcons.image).forEach { (k, ic) ->
                IconBtn(ic, { size = k; state.setPref("photos_size", k) }, active = size == k, size = 34.dp, iconSize = 18.dp,
                    contentDescription = mapOf("s" to "Small", "m" to "Medium", "l" to "Large")[k])
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
        val ms = months
        when {
            error != null && ms == null -> PageError(error) { reload++ }
            ms == null -> Column(Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                repeat(4) { Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) { repeat(3) { Box(Modifier.weight(1f).aspectRatio(1f).shimmer(RoundedCornerShape(2.dp))) } } }
            }
            ms.isEmpty() || total == 0L -> EmptyState(TgIcons.image, "No photos or videos here yet", "They show up as TG Drive indexes your chats.")
            else -> Timeline(ms, cache, thumbs, SIZES.getValue(size), size == "l", ::loadMonth, onOpen, total, kind)
        }
    }
    if (pickChat) ChatPickerSheet(state, "Only photos from", onDismiss = { pickChat = false }, onPick = { chat = it.id })
}

private fun monthLabel(ym: String): String = runCatching {
    val m = YearMonth.parse(ym)
    "${m.month.getDisplayName(TextStyle.FULL, Locale.getDefault())} ${m.year}"
}.getOrDefault(ym)

@Composable
private fun Timeline(
    months: List<Month>, cache: Map<String, List<FileItem>>, thumbs: ThumbSource, cell: androidx.compose.ui.unit.Dp, big: Boolean,
    loadMonth: (String) -> Unit, onOpen: (List<FileItem>, Int) -> Unit, total: Long, kind: String,
) {
    val c = Tg.colors
    val grid = rememberLazyGridState()
    val scope = rememberCoroutineScope()
    // Index of each month's header in the grid, to jump there from the scrubber.
    val starts = remember(months) {
        var i = 1   // after the count line
        months.map { m -> i.also { i += 1 + m.n.toInt() } }
    }
    val totalItems = remember(months) { 1 + months.sumOf { 1 + it.n.toInt() } }
    val currentMonth by remember(months) {
        derivedStateOf {
            val first = grid.firstVisibleItemIndex
            val idx = starts.indexOfLast { it <= first }.coerceAtLeast(0)
            months.getOrNull(idx)?.ym
        }
    }
    var dragging by remember { mutableStateOf(false) }
    var dragFraction by remember { mutableStateOf(0f) }

    Box(Modifier.fillMaxSize()) {
        LazyVerticalGrid(GridCells.Adaptive(cell), state = grid, modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 4.dp, end = 22.dp, bottom = 96.dp),
            horizontalArrangement = Arrangement.spacedBy(3.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            item(key = "count", span = { GridItemSpan(maxLineSpan) }) {
                Text(Format.plural(total, when (kind) { "video" -> "video"; "photo" -> "photo"; else -> "item" }), style = Tg.type.meta, color = c.ink3,
                    modifier = Modifier.padding(start = 8.dp, top = 10.dp))
            }
            months.forEach { m ->
                item(key = "h${m.ym}", span = { GridItemSpan(maxLineSpan) }) {
                    LaunchedEffect(m.ym) { loadMonth(m.ym) }
                    Row(Modifier.fillMaxWidth().padding(start = 8.dp, top = 18.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(monthLabel(m.ym), style = Tg.type.heading, color = c.ink)
                        Spacer(Modifier.width(8.dp))
                        Text(Format.num(m.n), style = Tg.type.meta, color = c.ink3)
                        Spacer(Modifier.weight(1f))
                        val items = cache[m.ym].orEmpty().filter { it.kind == "photo" }
                        if (items.size > 1) IconBtn(TgIcons.slides, { onOpen(items, 0) }, size = 32.dp, iconSize = 17.dp,
                            contentDescription = "Slideshow of ${monthLabel(m.ym)}")
                    }
                }
                items(m.n.toInt(), key = { "${m.ym}#$it" }) { i ->
                    val list = cache[m.ym]
                    val f = list?.getOrNull(i)
                    if (list == null) LaunchedEffect(m.ym) { loadMonth(m.ym) }
                    Box(Modifier.aspectRatio(1f).clip(RoundedCornerShape(2.dp)).background(c.hover)
                        .then(if (f != null) Modifier.clickable { onOpen(list, i) } else Modifier.shimmer(RoundedCornerShape(2.dp)))) {
                        if (f != null) {
                            FileThumb(f, thumbs, Modifier.fillMaxSize(), big = big, showBadges = false)
                            val video = f.kind == "video" || f.kind == "gif" || f.kind == "round"
                            if (video && f.duration != null) {
                                Row(Modifier.align(Alignment.BottomEnd).padding(4.dp).clip(RoundedCornerShape(5.dp)).background(Color(0x99000000))
                                    .padding(horizontal = 5.dp, vertical = 1.dp), verticalAlignment = Alignment.CenterVertically) {
                                    TgIconView(TgIcons.play, tint = Color.White, size = 10.dp, filled = true)
                                    Spacer(Modifier.width(3.dp))
                                    Text(Format.duration(f.duration), style = Tg.type.caption, color = Color.White)
                                }
                            }
                            if (f.starred) TgIconView(TgIcons.star, tint = c.star, size = 15.dp, filled = true,
                                modifier = Modifier.align(Alignment.TopEnd).padding(5.dp))
                        }
                    }
                }
            }
        }

        // The scrubber: drag along the right edge to jump through the years.
        BoxWithConstraints(Modifier.align(Alignment.CenterEnd).fillMaxHeight().width(22.dp).padding(vertical = 8.dp)) {
            val h = constraints.maxHeight.toFloat()
            val density = LocalDensity.current
            val progress by remember(months) {
                derivedStateOf { if (totalItems == 0) 0f else grid.firstVisibleItemIndex.toFloat() / totalItems }
            }
            val y = if (dragging) dragFraction else progress
            Box(Modifier.fillMaxSize().pointerInput(months) {
                detectVerticalDragGestures(
                    onDragStart = { o -> dragging = true; dragFraction = (o.y / h).coerceIn(0f, 1f) },
                    onDragEnd = { dragging = false },
                    onDragCancel = { dragging = false },
                ) { change, _ ->
                    dragFraction = (change.position.y / h).coerceIn(0f, 1f)
                    val target = (dragFraction * totalItems).toInt().coerceIn(0, (totalItems - 1).coerceAtLeast(0))
                    scope.launch { grid.scrollToItem(target) }
                }
            }) {
                Box(Modifier.offset { IntOffset(0, (y * (h - with(density) { 36.dp.toPx() })).toInt()) }
                    .align(Alignment.TopCenter).size(6.dp, 36.dp).clip(RoundedCornerShape(3.dp))
                    .background(if (dragging) c.accent else c.ink3.copy(alpha = .5f)))
            }
            if (dragging) {
                currentMonth?.let { ym ->
                    Text(monthLabel(ym), style = Tg.type.label, color = c.ink,
                        modifier = Modifier.offset { IntOffset(-with(density) { 150.dp.toPx() }.toInt(), (y * (h - 40)).toInt()) }
                            .width(140.dp).shadow(6.dp, RoundedCornerShape(10.dp)).clip(RoundedCornerShape(10.dp)).background(c.panel)
                            .padding(horizontal = 12.dp, vertical = 8.dp))
                }
            }
        }
    }
}
