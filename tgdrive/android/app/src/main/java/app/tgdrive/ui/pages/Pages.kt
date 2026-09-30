package app.tgdrive.ui.pages

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.Chat
import app.tgdrive.data.FileItem
import app.tgdrive.data.JsonCodec
import app.tgdrive.data.Transfer
import app.tgdrive.data.arr
import app.tgdrive.data.bool
import app.tgdrive.data.long
import app.tgdrive.data.obj
import app.tgdrive.data.str
import app.tgdrive.engine.UploadService
import app.tgdrive.ui.actions.Actions
import app.tgdrive.ui.actions.Overlay
import app.tgdrive.ui.actions.Platform
import app.tgdrive.ui.components.Avatar
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.ConfirmDialog
import app.tgdrive.ui.components.Divider
import app.tgdrive.ui.components.EmptyState
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.components.Panel
import app.tgdrive.ui.components.SheetAction
import app.tgdrive.ui.components.SheetTitle
import app.tgdrive.ui.components.Spinner
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.components.TgSheet
import app.tgdrive.ui.components.TgTextField
import app.tgdrive.ui.components.ThinProgress
import app.tgdrive.ui.components.shimmer
import app.tgdrive.ui.files.FileThumb
import app.tgdrive.ui.files.SelectMark
import app.tgdrive.ui.files.ThumbSource
import app.tgdrive.ui.nav.View
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.extColor
import app.tgdrive.util.Format
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject

// ---------------------------------------------------------------------- shared page frame
/** A tool page (desktop .page-head): a bar with the menu or back button, a big title and a line about it. */
@Composable
fun PageBar(title: String, onMenu: () -> Unit, onBack: (() -> Unit)? = null, actions: @Composable RowScope.() -> Unit = {}) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().background(c.panel).statusBarsPadding().padding(start = 6.dp, end = 8.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) IconBtn(TgIcons.chevLeft, onBack, contentDescription = "Back", iconSize = 24.dp)
        else IconBtn(TgIcons.sidebar, onMenu, contentDescription = "Menu", iconSize = 23.dp)
        Spacer(Modifier.width(6.dp))
        Text(title, style = Tg.type.heading, color = c.ink, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        actions()
    }
    Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
}

@Composable
fun PageIntro(text: String, modifier: Modifier = Modifier) {
    Text(text, style = Tg.type.body, color = Tg.colors.ink2, modifier = modifier.padding(horizontal = 16.dp, vertical = 12.dp))
}

@Composable
fun PageError(message: String?, onRetry: () -> Unit) =
    EmptyState(TgIcons.info, "Couldn't load this", message ?: "TG Drive isn't responding.", action = "Try again", onAction = onRetry)

@Composable
fun SectionCard(title: String, modifier: Modifier = Modifier, trailing: (@Composable RowScope.() -> Unit)? = null,
                content: @Composable ColumnScope.() -> Unit) {
    val c = Tg.colors
    Panel(modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), padding = PaddingValues(0.dp)) {
        Column(Modifier.fillMaxWidth()) {
            Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 12.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = Tg.type.subheading, color = c.ink, modifier = Modifier.weight(1f))
                trailing?.invoke(this)
            }
            content()
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
private fun Pill(text: String, color: Color) {
    Text(text, style = Tg.type.caption, color = color, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(color.copy(alpha = .13f)).padding(horizontal = 8.dp, vertical = 2.dp))
}

// ---------------------------------------------------------------------- transfers
@Composable
fun TransfersScreen(state: AppState, onMenu: () -> Unit, onBack: (() -> Unit)?) {
    val c = Tg.colors
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val resp by state.transfers.collectAsState()
    val status by state.status.collectAsState()
    val sending by UploadService.sending.collectAsState()
    val aid = state.aid.value
    val list = resp.transfers
    val s = resp.summary
    var removeDone by remember { mutableStateOf<Transfer?>(null) }

    // Refresh while anything moves (the live status only says how many are active).
    LaunchedEffect(aid) {
        while (true) {
            state.loadTransfers()
            delay(if (state.transfers.value.transfers.any { it.status == "running" || it.status == "queued" }) 1000 else 4000)
        }
    }
    fun act(block: suspend () -> Unit) = scope.launch {
        try { block(); state.loadTransfers() } catch (e: Exception) { state.message(e.message ?: "That didn't work.", error = true) }
    }

    Column(Modifier.fillMaxSize().background(c.canvas)) {
        PageBar("Transfers", onMenu, onBack)
        val running = list.any { it.status == "running" || it.status == "queued" }
        val paused = list.any { it.status == "paused" }
        val failed = list.any { it.status == "error" }
        val finished = list.any { it.status == "done" || it.status == "cancelled" }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
            if (s.active > 0) item("summary") {
                Column(Modifier.fillMaxWidth().background(c.panel).padding(16.dp)) {
                    ThinProgress(if (s.size > 0) s.done.toFloat() / s.size else null, Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    val eta = if (s.speed > 0) " · " + Format.eta((s.size - s.done).toDouble() / s.speed) else ""
                    Text("${Format.plural(s.active, "transfer")} · ${Format.size(s.done)} of ${Format.size(s.size)}" +
                        (if (s.speed > 0) " · ${Format.size(s.speed)}/s" else "") + eta, style = Tg.type.meta, color = c.ink2)
                }
                Divider(color = c.line)
            }
            if (running || paused || failed || finished) item("bulk") {
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (running) TgButton("Pause all", { act { state.api.transfersBulk(aid, "pause") } }, icon = TgIcons.pause, small = true)
                    if (paused) TgButton("Resume all", { act { state.api.transfersBulk(aid, "resume") } }, icon = TgIcons.play, small = true)
                    if (failed) TgButton("Retry failed", { act { state.api.transfersBulk(aid, "retry") } }, icon = TgIcons.refresh, small = true)
                    if (finished) TgButton("Clear finished", { act { state.api.transfersBulk(aid, "clear") } }, kind = ButtonKind.Ghost, small = true)
                    if (running || paused) TgButton("Cancel all", { act { state.api.transfersBulk(aid, "cancel") } }, kind = ButtonKind.Danger, small = true)
                }
            }
            sending?.let { up ->
                item("sending") {
                    TransferCard(TgIcons.upload, up.name, "Sending to TG Drive" + if (up.total > 1) " · ${up.index} of ${up.total}" else "", null, c.accent) {}
                }
            }
            items(list, key = { it.id }) { t ->
                val sub = transferWords(t)
                TransferCard(if (t.up) TgIcons.upload else TgIcons.download, t.name.ifBlank { "File" }, sub,
                    if (t.status in setOf("running", "paused", "queued", "error")) t.fraction else null,
                    when (t.status) { "error" -> c.danger; "paused" -> c.warn; "done" -> c.ok; else -> c.accent },
                    path = if (t.status == "done" && !t.up) t.path else null,
                    onOpen = if (t.status == "done" && !t.up && t.path != null) ({
                        if (!Platform.openFile(ctx, t.path, null)) state.message("No app on this phone opens this kind of file.", error = true)
                    }) else null) {
                    when (t.status) {
                        "running", "queued" -> {
                            IconBtn(TgIcons.pause, { act { state.api.transferAction(aid, t.id, "pause") } }, contentDescription = "Pause", size = 36.dp, iconSize = 18.dp)
                            IconBtn(TgIcons.close, { act { state.api.transferAction(aid, t.id, "cancel") } }, contentDescription = "Cancel", size = 36.dp, iconSize = 18.dp)
                        }
                        "paused", "error" -> {
                            IconBtn(if (t.status == "error") TgIcons.refresh else TgIcons.play, { act { state.api.transferAction(aid, t.id, "resume") } },
                                contentDescription = if (t.status == "error") "Retry" else "Resume", size = 36.dp, iconSize = 18.dp)
                            IconBtn(TgIcons.close, { act { state.api.transferAction(aid, t.id, "cancel") } }, contentDescription = "Cancel", size = 36.dp, iconSize = 18.dp)
                        }
                        "done" -> {
                            if (!t.up && t.path != null) IconBtn(TgIcons.send, { runCatching { Platform.shareFiles(ctx, listOf(t.path)) } },
                                contentDescription = "Share", size = 36.dp, iconSize = 18.dp)
                            IconBtn(TgIcons.trash, { if (t.up) act { state.api.removeTransfer(aid, t.id, false) } else removeDone = t },
                                contentDescription = "Remove from list", size = 36.dp, iconSize = 18.dp)
                        }
                        else -> IconBtn(TgIcons.trash, { act { state.api.removeTransfer(aid, t.id, false) } }, contentDescription = "Remove from list",
                            size = 36.dp, iconSize = 18.dp)
                    }
                }
            }
            if (list.isEmpty() && sending == null) item("empty") {
                EmptyState(TgIcons.transfers, "Downloads and uploads show up here",
                    "Downloads are saved to ${status?.downloadDir ?: "Downloads/TG Drive"}. Uploads go into the folder you're in.")
            }
        }
    }
    removeDone?.let { t ->
        app.tgdrive.ui.components.TgDialog("Remove “${t.name}” from the list?", { removeDone = null }, dismiss = null) {
            Text("The downloaded file can stay on this phone, or be deleted too.", style = Tg.type.body, color = c.ink2)
            Spacer(Modifier.height(16.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                TgButton("Cancel", { removeDone = null }, kind = ButtonKind.Ghost)
                TgButton("Delete file", { act { state.api.removeTransfer(aid, t.id, true) }; removeDone = null }, kind = ButtonKind.Danger)
                TgButton("Keep file", { act { state.api.removeTransfer(aid, t.id, false) }; removeDone = null }, kind = ButtonKind.Primary)
            }
        }
    }
}

private fun transferWords(t: Transfer): String {
    val pct = (t.fraction * 100).toInt()
    val eta = if (t.speed > 0) " · " + Format.eta((t.size - t.done).toDouble() / t.speed) else ""
    return when (t.status) {
        "queued" -> "Waiting to start"
        "running" -> "${if (t.up) "Uploading" else "Downloading"} $pct% · ${Format.size(t.done)} of ${Format.size(t.size)}" +
            (if (t.speed > 0) " · ${Format.size(t.speed)}/s" else "") + eta
        "paused" -> "Paused at $pct% · ${Format.size(t.done)} of ${Format.size(t.size)}"
        "done" -> if (t.up) "Uploaded · ${Format.size(t.size)}" else "Downloaded · ${Format.size(t.size)}"
        "error" -> "Failed: ${t.error ?: "unknown error"}"
        "cancelled" -> "Cancelled"
        else -> t.status
    }
}

@Composable
private fun TransferCard(icon: TgIcon, name: String, sub: String, fraction: Float?, color: Color, path: String? = null,
                         onOpen: (() -> Unit)? = null, buttons: @Composable RowScope.() -> Unit) {
    val c = Tg.colors
    Column(Modifier.fillMaxWidth().background(c.panel).then(if (onOpen != null) Modifier.clickable(onClick = onOpen) else Modifier)
        .padding(start = 16.dp, end = 6.dp, top = 12.dp, bottom = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(36.dp).clip(RoundedCornerShape(10.dp)).background(color.copy(alpha = .12f)), contentAlignment = Alignment.Center) {
                TgIconView(icon, tint = color, size = 19.dp)
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(name, style = Tg.type.bodyStrong, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(sub, style = Tg.type.meta, color = if (color == c.danger) c.danger else c.ink3, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            Row(verticalAlignment = Alignment.CenterVertically, content = buttons)
        }
        if (fraction != null) {
            Spacer(Modifier.height(8.dp))
            ThinProgress(fraction, Modifier.fillMaxWidth().padding(start = 48.dp, end = 10.dp), color = color)
        }
        if (path != null) Text(path, style = Tg.type.caption, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(start = 48.dp, top = 4.dp, end = 10.dp))
    }
    Divider()
}

// ---------------------------------------------------------------------- storage
@Composable
fun StorageScreen(state: AppState, onMenu: () -> Unit, onNavigate: (View) -> Unit, onOpen: (List<FileItem>, Int) -> Unit) {
    val c = Tg.colors
    val aid by state.aid.collectAsState()
    var data by remember { mutableStateOf<JsonObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    LaunchedEffect(aid, reload) {
        error = null
        try { data = state.api.storage(aid) } catch (e: Exception) { error = e.message }
    }
    Column(Modifier.fillMaxSize().background(c.canvas)) {
        PageBar("Storage", onMenu) { IconBtn(TgIcons.refresh, { data = null; reload++ }, contentDescription = "Refresh") }
        val r = data
        when {
            error != null && r == null -> PageError(error) { reload++ }
            r == null -> LoadingCards()
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                item { PageIntro("What your indexed files are made of. Everything stays in Telegram; this is what TG Drive can see.") }
                item {
                    val tot = r.obj("total")
                    val dup = r.obj("duplicates")
                    val local = r.obj("local")
                    val here = local.long("index_db") + local.long("thumbs") + local.long("stream_cache") + local.long("semantic")
                    Column(Modifier.padding(horizontal = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Kpi("Files", Format.num(tot.long("n")), null, Modifier.weight(1f))
                            Kpi("Total size", Format.size(tot.long("bytes")), null, Modifier.weight(1f))
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Kpi("Duplicate copies", Format.size(dup.long("bytes")), "${Format.plural(dup.long("groups"), "file")} appear more than once",
                                Modifier.weight(1f))
                            Kpi("On this phone", Format.size(here),
                                "index ${Format.size(local.long("index_db"))} · previews ${Format.size(local.long("thumbs"))} · stream cache ${Format.size(local.long("stream_cache"))}",
                                Modifier.weight(1f))
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                }
                item {
                    SectionCard("By type") {
                        Bars(r.arr("by_kind").map { it as JsonObject }, { Format.KIND_NAME[it.str("kind")] ?: it.str("kind").orEmpty() },
                            { c.kind(it.str("kind")) }, { onNavigate(View.Search("type:${it.str("kind")}")) })
                    }
                }
                item {
                    SectionCard("By source") {
                        Bars(r.arr("by_source").map { it as JsonObject }, { Format.CHAT_KIND_NAME[it.str("kind")] ?: it.str("kind").orEmpty() },
                            { c.accent }, { onNavigate(View.Search("source:${it.str("kind")}")) })
                    }
                }
                item {
                    SectionCard("By year sent") { YearBars(r.arr("by_year").map { it as JsonObject }.filter { !it.str("year").isNullOrBlank() }) }
                }
                item {
                    SectionCard("Biggest sources") {
                        Bars(r.arr("by_chat").take(15).map { it as JsonObject }, { it.str("title") ?: it.str("chat_id").orEmpty() },
                            { c.folder }, { onNavigate(View.Chat(it.long("chat_id"))) }, avatar = true)
                    }
                }
                item {
                    SectionCard("By extension") {
                        Bars(r.arr("by_ext").take(15).map { it as JsonObject }, { o -> o.str("ext")?.takeIf { it.isNotBlank() }?.let { ".$it" } ?: "(none)" },
                            { extColor(it.str("ext")) }, { o -> o.str("ext")?.takeIf { it.isNotBlank() }?.let { onNavigate(View.Search("ext:$it")) } })
                    }
                }
                item {
                    val largest = remember(r) {
                        runCatching { JsonCodec.decodeFromJsonElement(ListSerializer(FileItem.serializer()), r.arr("largest")) }.getOrDefault(emptyList())
                    }
                    SectionCard("Largest files") {
                        largest.take(25).forEachIndexed { i, f ->
                            Row(Modifier.fillMaxWidth().clickable { onOpen(largest, i) }.padding(horizontal = 16.dp, vertical = 9.dp),
                                verticalAlignment = Alignment.CenterVertically) {
                                val label = (f.ext ?: f.kind).take(4).uppercase()
                                Box(Modifier.size(34.dp, 28.dp).clip(RoundedCornerShape(6.dp)).background(extColor(f.ext)), contentAlignment = Alignment.Center) {
                                    Text(label, style = Tg.type.caption, color = Color.White, maxLines = 1)
                                }
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(f.displayName, style = Tg.type.label, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(f.chatTitle.orEmpty(), style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                Spacer(Modifier.width(8.dp))
                                Text(Format.size(f.size), style = Tg.type.label, color = c.ink)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Kpi(label: String, value: String, sub: String?, modifier: Modifier) {
    val c = Tg.colors
    Panel(modifier, padding = PaddingValues(14.dp)) {
        Column {
            Text(label, style = Tg.type.meta, color = c.ink3)
            Text(value, style = Tg.type.title, color = c.ink, maxLines = 1)
            if (sub != null) Text(sub, style = Tg.type.caption, color = c.ink3, maxLines = 3)
        }
    }
}

@Composable
private fun Bars(rows: List<JsonObject>, label: (JsonObject) -> String, color: (JsonObject) -> Color, onClick: ((JsonObject) -> Unit)?,
                 avatar: Boolean = false) {
    val c = Tg.colors
    val max = (rows.maxOfOrNull { it.long("bytes") } ?: 1L).coerceAtLeast(1L)
    rows.forEach { x ->
        Column(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable { onClick(x) } else Modifier).padding(horizontal = 16.dp, vertical = 7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (avatar) { Avatar(label(x), 22.dp); Spacer(Modifier.width(8.dp)) }
                Text(label(x), style = Tg.type.label, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Text(Format.size(x.long("bytes")), style = Tg.type.label, color = c.ink)
                Spacer(Modifier.width(8.dp))
                Text(Format.compact(x.long("n")), style = Tg.type.caption, color = c.ink3, modifier = Modifier.width(44.dp),
                    textAlign = androidx.compose.ui.text.style.TextAlign.End)
            }
            Spacer(Modifier.height(5.dp))
            Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.line2)) {
                Box(Modifier.fillMaxWidth((x.long("bytes").toFloat() / max).coerceIn(.01f, 1f)).fillMaxHeight().clip(RoundedCornerShape(3.dp)).background(color(x)))
            }
        }
    }
    if (rows.isEmpty()) Text("Nothing yet.", style = Tg.type.meta, color = c.ink3, modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp))
}

@Composable
private fun YearBars(years: List<JsonObject>) {
    val c = Tg.colors
    val max = (years.maxOfOrNull { it.long("bytes") } ?: 1L).coerceAtLeast(1L)
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp).height(150.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Bottom) {
        years.forEach { y ->
            Column(Modifier.width(34.dp).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Bottom) {
                Text(Format.size(y.long("bytes")).substringBefore(' '), style = Tg.type.caption, color = c.ink3, maxLines = 1)
                Box(Modifier.width(22.dp).fillMaxHeight((y.long("bytes").toFloat() / max * .78f).coerceAtLeast(.02f))
                    .clip(RoundedCornerShape(topStart = 4.dp, topEnd = 4.dp)).background(c.accent))
                Text(y.str("year").orEmpty(), style = Tg.type.caption, color = c.ink2, maxLines = 1)
            }
        }
    }
}

@Composable
private fun LoadingCards() {
    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(4) { Box(Modifier.fillMaxWidth().height(if (it == 0) 80.dp else 150.dp).shimmer(RoundedCornerShape(12.dp))) }
    }
}

// ---------------------------------------------------------------------- duplicates
private class DupGroup(val n: Long, val size: Long, val waste: Long, val files: List<FileItem>)

@Composable
fun DuplicatesScreen(state: AppState, actions: Actions, thumbs: ThumbSource, onMenu: () -> Unit, onOpen: (List<FileItem>, Int) -> Unit) {
    val c = Tg.colors
    val aid by state.aid.collectAsState()
    val folders by state.folders.collectAsState()
    var mode by remember { mutableStateOf("exact") }
    val groups = remember { mutableStateListOf<DupGroup>() }
    var more by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val selected = remember { mutableStateMapOf<String, FileItem>() }
    val scope = rememberCoroutineScope()

    suspend fun load(offset: Int) {
        loading = true
        try {
            val r = state.api.duplicates(aid, mode, offset)
            if (offset == 0) groups.clear()
            groups += r.arr("groups").map { g ->
                val o = g as JsonObject
                DupGroup(o.long("n"), o.long("size"), o.long("waste"),
                    JsonCodec.decodeFromJsonElement(ListSerializer(FileItem.serializer()), o.arr("files")))
            }
            more = r.bool("more")
            error = null
        } catch (e: Exception) {
            if (offset == 0) error = e.message else state.message(e.message ?: "Couldn't load more.", error = true)
        } finally {
            loading = false
        }
    }
    LaunchedEffect(aid, mode, reload) { selected.clear(); load(0) }
    LaunchedEffect(Unit) { state.changes.collectLatest { reload++ } }

    Box(Modifier.fillMaxSize().background(c.canvas)) {
        Column(Modifier.fillMaxSize()) {
            PageBar("Duplicates", onMenu)
            Row(Modifier.fillMaxWidth().background(c.panel).padding(horizontal = 12.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TgChip("Same file", selected = mode == "exact", onClick = { mode = "exact" })
                TgChip("Same name and size", selected = mode == "similar", onClick = { mode = "similar" })
            }
            Divider(color = c.line)
            when {
                error != null && groups.isEmpty() -> PageError(error) { reload++ }
                loading && groups.isEmpty() -> LoadingCards()
                groups.isEmpty() -> EmptyState(TgIcons.dupes, "No duplicates", "Every file you have is unique.")
                else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 120.dp)) {
                    item {
                        PageIntro("“Same file” means Telegram stores one copy that was forwarded into several chats; “Same name and size” catches re-uploads.")
                        Row(Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
                            TgButton("Select all but the oldest copy", {
                                selected.clear()
                                groups.forEach { g -> g.files.drop(1).forEach { selected[it.key] = it } }
                            }, icon = TgIcons.check, small = true)
                        }
                    }
                    items(groups.size) { gi ->
                        val g = groups[gi]
                        SectionCard(g.files.firstOrNull()?.displayName ?: "") {
                            Text("${Format.plural(g.n, "copy", "copies")} · ${Format.size(g.size)} each · ${Format.size(g.waste)} extra",
                                style = Tg.type.meta, color = c.ink3, modifier = Modifier.padding(start = 16.dp, bottom = 6.dp))
                            g.files.forEachIndexed { i, f ->
                                val on = selected.containsKey(f.key)
                                Row(Modifier.fillMaxWidth().clickable { if (on) selected.remove(f.key) else selected[f.key] = f }
                                    .padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                    SelectMark(on)
                                    Spacer(Modifier.width(12.dp))
                                    FileThumb(f, thumbs, Modifier.size(40.dp).clip(RoundedCornerShape(8.dp)), showBadges = false, iconWidth = 28.dp)
                                    Spacer(Modifier.width(12.dp))
                                    Column(Modifier.weight(1f)) {
                                        Text(f.chatTitle.orEmpty(), style = Tg.type.label, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                        val folder = f.folderId?.let { id -> folders.folders.firstOrNull { it.id == id }?.name }
                                        Text(listOfNotNull(Format.date(f.date), if (i == 0) "oldest" else null, folder?.let { "in $it" }).joinToString(" · "),
                                            style = Tg.type.meta, color = c.ink3, maxLines = 1)
                                    }
                                    IconBtn(TgIcons.eye, { onOpen(g.files, i) }, contentDescription = "Open this copy", size = 36.dp, iconSize = 18.dp)
                                }
                            }
                        }
                    }
                    if (more) item {
                        Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                            TgButton("Show more", { scope.launch { load(groups.size) } }, icon = TgIcons.chevronDown, busy = loading)
                        }
                    }
                }
            }
        }
        if (selected.isNotEmpty()) {
            val files = selected.values.toList()
            Row(Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(12.dp).fillMaxWidth()
                .shadow(12.dp, RoundedCornerShape(16.dp)).clip(RoundedCornerShape(16.dp)).background(Color(0xFF1D2330))
                .padding(horizontal = 6.dp).height(58.dp), verticalAlignment = Alignment.CenterVertically) {
                IconBtn(TgIcons.close, { selected.clear() }, tint = Color.White, contentDescription = "Clear selection")
                Text("${files.size}", style = Tg.type.subheading, color = Color.White)
                Spacer(Modifier.weight(1f))
                val w = Color(0xFFE8EBF1)
                IconBtn(TgIcons.move, { actions.open(Overlay.Move(files)) }, tint = w, contentDescription = "Move to folder")
                IconBtn(TgIcons.tag, { actions.open(Overlay.Tags(files)) }, tint = w, contentDescription = "Tags")
                IconBtn(TgIcons.close, { actions.open(Overlay.Forget(files)) }, tint = w, contentDescription = "Hide from TG Drive")
                IconBtn(TgIcons.trash, { actions.open(Overlay.Delete(files)) }, tint = Color(0xFFFF8A80), contentDescription = "Delete from Telegram")
            }
        }
    }
}

// ---------------------------------------------------------------------- index manager
private val STATES = listOf("" to "Any state", "done" to "Up to date", "pending" to "Waiting", "running" to "Indexing",
    "error" to "Problem", "excluded" to "Excluded", "gone" to "Left")
private val KINDS = listOf("" to "All kinds", "channel" to "Channels", "group" to "Groups", "user" to "Private chats", "bot" to "Bots",
    "saved" to "Saved Messages")

@Composable
fun IndexScreen(state: AppState, onMenu: () -> Unit, onOpenChat: (Long) -> Unit) {
    val c = Tg.colors
    val chats by state.chats.collectAsState()
    val account by state.account.collectAsState()
    val scope = rememberCoroutineScope()
    val aid = state.aid.value
    var q by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("") }
    var st by remember { mutableStateOf("") }
    var menuFor by remember { mutableStateOf<Chat?>(null) }
    var bulk by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { state.loadChats() }

    val rows = remember(chats, q, kind, st) {
        chats.filter { ch ->
            (q.isBlank() || ch.title.orEmpty().contains(q, ignoreCase = true)) &&
                (kind.isEmpty() || (if (kind == "group") ch.kind in setOf("group", "supergroup") else ch.kind == kind)) &&
                (st.isEmpty() || (if (st == "excluded") ch.excluded == 1 else ch.excluded == 0 && ch.indexState == st))
        }.sortedByDescending { it.fileCount }
    }
    fun act(block: suspend () -> Unit) = scope.launch {
        try { block(); state.loadChats() } catch (e: Exception) { state.message(e.message ?: "That didn't work.", error = true) }
    }
    val idx = account?.index
    val paused = idx?.phase == "paused"
    Column(Modifier.fillMaxSize().background(c.canvas)) {
        PageBar("Index manager", onMenu) {
            IconBtn(if (paused) TgIcons.play else TgIcons.pause, { act { state.api.index(aid, if (paused) "resume" else "pause") } },
                contentDescription = if (paused) "Resume indexing" else "Pause indexing")
            IconBtn(TgIcons.refresh, { act { state.api.index(aid, "resync"); state.message("Checking every chat for new files") } },
                contentDescription = "Check all chats now")
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
            item {
                val line = buildString {
                    append("TG Drive indexes every file in every chat, then keeps up with new ones live.")
                    if (idx != null) {
                        append(" ${Format.num(idx.chatsDone.toLong())} of ${Format.plural(idx.chatsTotal, "chat")} done")
                        if (idx.chatsPending > 0) append(", ${Format.num(idx.chatsPending.toLong())} waiting")
                        if (idx.filesPerMin > 0) append(", ${Format.num(idx.filesPerMin)} files/min")
                        append(".")
                        if (paused) append(" Indexing is paused.")
                    }
                }
                PageIntro(line)
                TgTextField(q, { q = it }, Modifier.padding(horizontal = 12.dp), placeholder = "Filter chats", leading = TgIcons.search)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    KINDS.forEach { (k, l) -> TgChip(l, selected = kind == k, onClick = { kind = k }) }
                }
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    STATES.forEach { (k, l) -> TgChip(l, selected = st == k, onClick = { st = k }) }
                }
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(Format.plural(rows.size, "chat"), style = Tg.type.label, color = c.ink2)
                    TgButton("Exclude shown", { bulk = "exclude" }, small = true, enabled = rows.isNotEmpty())
                    TgButton("Include shown", { bulk = "include" }, small = true, enabled = rows.isNotEmpty())
                    TgButton("Re-index shown", { bulk = "rescan" }, small = true, enabled = rows.isNotEmpty())
                }
                Divider(color = c.line)
            }
            items(rows.take(1500), key = { it.id }) { ch -> IndexRow(ch, onClick = { menuFor = ch }) }
            if (rows.size > 1500) item { PageIntro("${Format.num(rows.size - 1500)} more; narrow the filter.") }
        }
    }
    menuFor?.let { ch ->
        TgSheet({ menuFor = null }) {
            SheetTitle(ch.title ?: "Chat", listOfNotNull(Format.CHAT_KIND_NAME[ch.kind], Format.plural(ch.fileCount, "file")).joinToString(" · "),
                leading = { Avatar(ch.title, 40.dp) })
            if (ch.indexError != null) Text(ch.indexError, style = Tg.type.meta, color = c.danger, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
            SheetAction(TgIcons.folder, "Open files", { menuFor = null; onOpenChat(ch.id) })
            SheetAction(TgIcons.refresh, "Re-index", { menuFor = null; act { state.api.rescanChat(aid, ch.id) } }, subtitle = "Reads its history again from the start")
            SheetAction(TgIcons.pin, if (ch.pinned == 1) "Unpin from the sidebar" else "Pin to the sidebar",
                { menuFor = null; act { state.api.pinChat(aid, ch.id, ch.pinned != 1) } })
            SheetAction(TgIcons.close, if (ch.excluded == 1) "Include" else "Exclude", { menuFor = null; act { state.api.excludeChat(aid, ch.id, ch.excluded != 1) } },
                danger = ch.excluded != 1, subtitle = if (ch.excluded == 1) "Index it again" else "Its files leave the index; nothing changes in Telegram")
        }
    }
    bulk?.let { b ->
        val verb = when (b) { "exclude" -> "Exclude"; "include" -> "Include"; else -> "Re-index" }
        ConfirmDialog("$verb ${Format.plural(rows.size, "chat")}?",
            if (b == "exclude") "Their files leave the index. Nothing changes in Telegram." else "They go back into the indexing queue.",
            "Go ahead", onConfirm = { val ids = rows.map { it.id }; act { state.api.chatsBulk(aid, b, ids) } }, onDismiss = { bulk = null },
            danger = b == "exclude")
    }
}

@Composable
private fun IndexRow(ch: Chat, onClick: () -> Unit) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().background(c.panel).clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Avatar(ch.title, 38.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(ch.title ?: "Chat", style = Tg.type.bodyStrong, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false))
                if (ch.pinned == 1) { Spacer(Modifier.width(4.dp)); TgIconView(TgIcons.pin, tint = c.ink3, size = 13.dp) }
            }
            Text(listOfNotNull(Format.CHAT_KIND_NAME[ch.kind], "${Format.num(ch.fileCount)} files", Format.size(ch.totalBytes),
                ch.lastIndexed?.let { Format.relative(it) }).joinToString(" · "), style = Tg.type.meta, color = c.ink3, maxLines = 1)
        }
        Spacer(Modifier.width(8.dp))
        when {
            ch.excluded == 1 -> Pill("Excluded", c.ink3)
            ch.indexState == "done" -> Pill("Up to date", c.ok)
            ch.indexState == "running" -> Pill("Indexing", c.accent)
            ch.indexState == "error" -> Pill("Problem", c.danger)
            ch.indexState == "gone" -> Pill("Left", c.ink3)
            else -> Pill("Waiting", c.warn)
        }
    }
    Divider()
}

// ---------------------------------------------------------------------- activity
@Composable
fun ActivityScreen(state: AppState, onMenu: () -> Unit) {
    val c = Tg.colors
    val aid by state.aid.collectAsState()
    var list by remember { mutableStateOf<List<app.tgdrive.data.Activity>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    LaunchedEffect(aid, reload) {
        try { list = state.api.activityLog(aid); error = null } catch (e: Exception) { error = e.message }
    }
    Column(Modifier.fillMaxSize().background(c.canvas)) {
        PageBar("Activity", onMenu) { IconBtn(TgIcons.refresh, { reload++ }, contentDescription = "Refresh") }
        val l = list
        when {
            error != null && l == null -> PageError(error) { reload++ }
            l == null -> Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) { Spinner() }
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                item { PageIntro("What TG Drive did on your behalf: folder changes, copies, sends, deletions and clean-ups.") }
                if (l.isEmpty()) item { EmptyState(TgIcons.activity, "Nothing yet") }
                items(l.size) { i ->
                    val a = l[i]
                    Row(Modifier.fillMaxWidth().background(c.panel).padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
                        Pill(a.action, c.accent)
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(a.detail, style = Tg.type.body, color = c.ink)
                            Text(Format.dateTime(a.at), style = Tg.type.meta, color = c.ink3)
                        }
                    }
                    Divider()
                }
            }
        }
    }
}
