package app.tgdrive.ui.viewer

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withLink
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.explain
import app.tgdrive.data.ChatContext
import app.tgdrive.data.ContextMessage
import app.tgdrive.data.FileDetail
import app.tgdrive.data.FileItem
import app.tgdrive.data.FileRef
import app.tgdrive.data.str
import app.tgdrive.player.PlayerController
import app.tgdrive.ui.actions.Actions
import app.tgdrive.ui.actions.Overlay
import app.tgdrive.ui.actions.Platform
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.Divider
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.components.Spinner
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.components.TgTextField
import app.tgdrive.ui.components.shimmer
import app.tgdrive.ui.files.FileThumb
import app.tgdrive.ui.files.ThumbSource
import app.tgdrive.ui.nav.View
import app.tgdrive.ui.pages.PageBar
import app.tgdrive.ui.pages.PageError
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.extColor
import app.tgdrive.util.Format
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

// ---------------------------------------------------------------------- details
/** Everything about one file (desktop: the details panel): preview, facts, tags, note, copies. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DetailsScreen(
    ref: FileRef,
    state: AppState,
    actions: Actions,
    thumbs: ThumbSource,
    onBack: () -> Unit,
    onOpen: (List<FileItem>, Int) -> Unit,
    onNavigate: (View) -> Unit,
    onShowInChat: (FileItem) -> Unit,
) {
    val c = Tg.colors
    val ctx = LocalContext.current
    val aid by state.aid.collectAsState()
    val chats by state.chats.collectAsState()
    val subjects by state.subjects.collectAsState()
    var det by remember { mutableStateOf<FileDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var note by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(ref, aid, reload) {
        try {
            val d = state.api.detail(aid, ref)
            det = d
            if (note == null) note = d.extras.note.orEmpty()
            error = null
        } catch (e: Exception) { error = e.explain("loading the file details") }
    }
    // Stars, tags and renames from the menu: show them here too.
    LaunchedEffect(Unit) { state.messages.collect { reload++ } }

    Column(Modifier.fillMaxSize().background(c.canvas)) {
        PageBar("Details", onMenu = onBack, onBack = onBack) {
            det?.let { d -> IconBtn(TgIcons.more, { actions.open(Overlay.FileMenu(d.file)) }, contentDescription = "More") }
        }
        val d = det
        when {
            d == null && error != null -> PageError(error) { reload++ }
            d == null -> Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.fillMaxWidth().aspectRatio(1.6f).shimmer(RoundedCornerShape(14.dp)))
                repeat(5) { Box(Modifier.fillMaxWidth(.4f + it * .1f).height(14.dp).shimmer()) }
            }
            else -> {
                val f = d.file
                val x = d.extras
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 110.dp)) {
                    item {
                        Box(Modifier.fillMaxWidth().background(c.panel).padding(16.dp), contentAlignment = Alignment.Center) {
                            val ratio = if ((f.width ?: 0) > 0 && (f.height ?: 0) > 0) (f.width!!.toFloat() / f.height!!).coerceIn(.6f, 2.2f) else 1.6f
                            Box(Modifier.widthIn(max = 560.dp).fillMaxWidth().aspectRatio(ratio).clip(RoundedCornerShape(14.dp))
                                .border(1.dp, c.line2, RoundedCornerShape(14.dp)).clickable { onOpen(listOf(f), 0) }) {
                                FileThumb(f, thumbs, Modifier.fillMaxSize(), big = true, iconWidth = 96.dp)
                                if (f.streamable) {
                                    Box(Modifier.align(Alignment.Center).size(58.dp).clip(CircleShape).background(Color(0x99000000)),
                                        contentAlignment = Alignment.Center) {
                                        TgIconView(TgIcons.play, tint = Color.White, size = 26.dp, filled = true)
                                    }
                                }
                            }
                        }
                    }
                    item {
                        Column(Modifier.fillMaxWidth().background(c.panel).padding(horizontal = 16.dp).padding(bottom = 14.dp)) {
                            Text(f.displayName, style = Tg.type.title, color = c.ink)
                            if (f.renamed && f.originalName != null) {
                                Text("Original name: ${f.originalName}", style = Tg.type.meta, color = c.ink3)
                            }
                            Text(listOfNotNull(Format.KIND_NAME[f.kind] ?: f.kind, Format.size(f.size), f.duration?.let { Format.duration(it) },
                                Format.date(f.date)).joinToString(" · "), style = Tg.type.meta, color = c.ink3, modifier = Modifier.padding(top = 2.dp))
                            Spacer(Modifier.height(14.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                TgButton(if (f.streamable) "Play" else "Open", {
                                    if (f.kind == "audio" || f.kind == "voice") PlayerController.get(ctx).playList(state, listOf(f), f) else onOpen(listOf(f), 0)
                                }, kind = ButtonKind.Primary, icon = if (f.streamable) TgIcons.play else TgIcons.eye, modifier = Modifier.weight(1f))
                                TgButton("Download", { actions.download(listOf(f)) }, icon = TgIcons.download, modifier = Modifier.weight(1f))
                            }
                            Spacer(Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                                Tool(TgIcons.star, if (f.starred) "Starred" else "Star", on = f.starred) { actions.star(listOf(f), !f.starred) }
                                Tool(TgIcons.move, "Move") { actions.open(Overlay.Move(listOf(f))) }
                                Tool(TgIcons.tag, "Tags") { actions.open(Overlay.Tags(listOf(f))) }
                                Tool(TgIcons.send, "Send") { actions.open(Overlay.Send(listOf(f))) }
                                Tool(TgIcons.chat, "In chat") { onShowInChat(f) }
                            }
                        }
                        Divider(color = c.line)
                    }
                    if (f.tags.isNotEmpty() || f.subject != null) item {
                        Section("Tags and subject") {
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                f.subject?.takeIf { it != "_none" }?.let { sid ->
                                    val s = subjects.firstOrNull { it.id == sid }
                                    TgChip(listOfNotNull(s?.emoji, s?.name ?: sid).joinToString(" "), icon = TgIcons.book,
                                        onClick = { onNavigate(View.SubjectView(sid)) })
                                }
                                f.tags.forEach { t -> TgChip("#$t", onClick = { onNavigate(View.TagView(t)) }) }
                                TgChip("Edit", icon = TgIcons.edit, onClick = { actions.open(Overlay.Tags(listOf(f))) })
                            }
                        }
                    }
                    item {
                        Section("Note") {
                            TgTextField(note.orEmpty(), { note = it }, placeholder = "Add a note (synced, searchable with has:note)",
                                singleLine = false, minLines = 2)
                            if ((note ?: "") != x.note.orEmpty()) {
                                Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                                    TgButton("Discard", { note = x.note.orEmpty() }, kind = ButtonKind.Ghost, small = true)
                                    TgButton("Save note", { actions.saveNote(f, note.orEmpty()) ; scope.launch { delay(400); reload++ } },
                                        kind = ButtonKind.Primary, small = true)
                                }
                            }
                        }
                    }
                    item {
                        val chat = chats.firstOrNull { it.id == f.chatId }
                        Section("About") {
                            Fact("Type", "${Format.KIND_NAME[f.kind] ?: f.kind}${f.ext?.let { " · .$it" } ?: ""}")
                            Fact("Size", Format.size(f.size) + if (f.size > 1024) " (${Format.num(f.size)} bytes)" else "")
                            if ((f.width ?: 0) > 0 && (f.height ?: 0) > 0) Fact("Dimensions", "${f.width} × ${f.height}")
                            f.duration?.let { Fact("Duration", Format.duration(it)) }
                            if (f.performer != null || f.audioTitle != null) Fact("Track", listOfNotNull(f.performer, f.audioTitle).joinToString(" · "))
                            Fact("Sent", Format.dateTime(f.date))
                            Fact("Chat", listOfNotNull(f.chatTitle, chat?.let { Format.CHAT_KIND_NAME[it.kind] }).joinToString(" · "),
                                onClick = { onNavigate(View.Chat(f.chatId)) })
                            x.topic?.let { Fact("Topic", it) }
                            f.senderName?.let { Fact("From", it) }
                            f.fwdFrom?.let { Fact("Forwarded from", it) }
                            if (x.folderPath.isNotEmpty()) Fact("Folder", x.folderPath.joinToString(" / ") { it.name },
                                onClick = { onNavigate(View.Drive(x.folderPath.last().id)) })
                            else Fact("Folder", "Not in a folder", onClick = { actions.open(Overlay.Move(listOf(f))) })
                            if (x.album > 1 && f.groupedId != null) Fact("Album", "${x.album} files sent together",
                                onClick = { onNavigate(View.Album(f.chatId, f.groupedId)) })
                            x.localPath?.let { p ->
                                Fact("On this phone", p, onClick = {
                                    if (!Platform.openFile(ctx, p, f.mime)) state.message("No app on this phone opens this kind of file.", error = true)
                                })
                            }
                            f.mime?.let { Fact("Mime type", it) }
                        }
                    }
                    if (f.caption.isNotBlank()) item {
                        Section("Caption") { LinkedText(f.caption, Tg.type.body, c.ink) }
                    }
                    if (x.copyList.size > 1) item {
                        Section("Copies (${x.copyList.size})") {
                            x.copyList.forEach { cp ->
                                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable(enabled = !cp.isThis) {
                                    onNavigate(View.Chat(cp.chatId))
                                }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                    TgIconView(if (cp.isThis) TgIcons.check else TgIcons.copy, tint = if (cp.isThis) c.accent else c.ink3, size = 17.dp)
                                    Spacer(Modifier.width(12.dp))
                                    Column(Modifier.weight(1f)) {
                                        Text(cp.chatTitle ?: "Chat", style = Tg.type.label, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                        Text(listOfNotNull(Format.date(cp.date), if (cp.isThis) "this copy" else null,
                                            if (cp.folderId != null) "in a folder" else null, if (cp.starred) "starred" else null).joinToString(" · "),
                                            style = Tg.type.meta, color = c.ink3)
                                    }
                                }
                            }
                        }
                    }
                    item {
                        Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (x.tgLink != null || f.link != null) TgButton("Open in Telegram", { actions.openInTelegram(f) }, icon = TgIcons.telegram,
                                modifier = Modifier.weight(1f))
                            if (f.link != null) TgButton("Copy link", { actions.copyLink(f) }, icon = TgIcons.link, modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Tool(icon: TgIcon, label: String, on: Boolean = false, onClick: () -> Unit) {
    val c = Tg.colors
    Column(Modifier.clip(RoundedCornerShape(10.dp)).clickable(onClick = onClick).padding(horizontal = 6.dp, vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally) {
        TgIconView(icon, tint = if (on) (if (icon == TgIcons.star) c.star else c.accent) else c.ink2, size = 22.dp, filled = on && icon == TgIcons.star)
        Spacer(Modifier.height(4.dp))
        Text(label, style = Tg.type.caption, color = c.ink2)
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    val c = Tg.colors
    Column(Modifier.fillMaxWidth().padding(top = 8.dp).background(c.panel).padding(16.dp)) {
        Text(title.uppercase(), style = Tg.type.overline, color = c.ink3)
        Spacer(Modifier.height(10.dp))
        content()
    }
}

@Composable
private fun Fact(label: String, value: String, onClick: (() -> Unit)? = null) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClick = onClick) else Modifier)
        .padding(vertical = 6.dp)) {
        Text(label, style = Tg.type.meta, color = c.ink3, modifier = Modifier.width(118.dp))
        Text(value, style = Tg.type.label, color = if (onClick != null) c.accent else c.ink, modifier = Modifier.weight(1f))
    }
}

private val URL = Regex("https?://[^\\s<]+")

/** Text with its web links tappable. */
@Composable
fun LinkedText(text: String, style: androidx.compose.ui.text.TextStyle, color: Color) {
    val accent = Tg.colors.accent
    val s = remember(text, accent) {
        buildAnnotatedString {
            var last = 0
            for (m in URL.findAll(text)) {
                append(text.substring(last, m.range.first))
                withLink(LinkAnnotation.Url(m.value)) {
                    pushStyle(SpanStyle(color = accent, textDecoration = TextDecoration.Underline)); append(m.value); pop()
                }
                last = m.range.last + 1
            }
            append(text.substring(last))
        }
    }
    Text(s, style = style, color = color)
}

// ---------------------------------------------------------------------- show in chat
/** The messages around a file in its chat (desktop context.js), like Telegram shows them. */
@Composable
fun ChatContextScreen(ref: FileRef, title: String, state: AppState, thumbs: ThumbSource, onBack: () -> Unit, onOpen: (List<FileItem>, Int) -> Unit) {
    val c = Tg.colors
    val aid by state.aid.collectAsState()
    var ctxData by remember { mutableStateOf<ChatContext?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()

    LaunchedEffect(ref, aid, reload) {
        try {
            val r = state.api.context(aid, ref)
            ctxData = r
            error = null
            val target = r.messages.indexOfFirst { it.target }
            if (target >= 0) list.scrollToItem(target + 1, -300)
        } catch (e: Exception) { error = e.explain("reading the chat") }
    }
    fun more(older: Boolean) {
        val cur = ctxData ?: return
        if (busy || cur.messages.isEmpty()) return
        busy = true
        scope.launch {
            try {
                val anchor = if (older) cur.messages.first() else cur.messages.last()
                val r = state.api.context(aid, FileRef(ref.chatId, anchor.id), if (older) 25 else 0, if (older) 0 else 25)
                val have = cur.messages.mapTo(HashSet()) { it.id }
                ctxData = if (older) cur.copy(messages = r.messages.filter { it.id !in have && it.id < anchor.id } + cur.messages, hasOlder = r.hasOlder)
                else cur.copy(messages = cur.messages + r.messages.filter { it.id !in have && it.id > anchor.id }, hasNewer = r.hasNewer)
            } catch (e: Exception) {
                state.failed("Couldn't load more messages.", e)
            } finally { busy = false }
        }
    }

    Column(Modifier.fillMaxSize().background(c.canvas)) {
        val chatTitle = ctxData?.chat?.str("title")
        PageBar(chatTitle ?: "Show in chat", onMenu = onBack, onBack = onBack) {
            ctxData?.chat?.str("username")?.let { u ->
                val ctx = LocalContext.current
                IconBtn(TgIcons.telegram, { Platform.openUrl(ctx, "https://t.me/$u/${ref.msgId}") }, contentDescription = "Open in Telegram")
            }
        }
        val d = ctxData
        when {
            d == null && error != null -> Column {
                PageError(error) { reload++ }
                Text("Telegram needs to be connected to read the messages around a file.", style = Tg.type.meta, color = c.ink3,
                    modifier = Modifier.padding(horizontal = 32.dp))
            }
            d == null -> Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) { Spinner() }
            else -> {
                val files = remember(d) { d.messages.mapNotNull { it.file } }
                val byId = remember(d) { d.messages.associateBy { it.id } }
                val zone = ZoneId.systemDefault()
                val timeFmt = remember { DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT) }
                LazyColumn(Modifier.fillMaxSize(), state = list, contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)) {
                    item {
                        if (d.hasOlder) Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                            TgButton("Earlier messages", { more(true) }, kind = ButtonKind.Ghost, icon = TgIcons.up, small = true, busy = busy)
                        }
                    }
                    itemsIndexed(d.messages, key = { _, m -> m.id }) { i, m ->
                        val prev = d.messages.getOrNull(i - 1)
                        val day = m.date?.let { Instant.ofEpochSecond(it).atZone(zone).toLocalDate() }
                        val prevDay = prev?.date?.let { Instant.ofEpochSecond(it).atZone(zone).toLocalDate() }
                        if (day != null && day != prevDay) {
                            Box(Modifier.fillMaxWidth().padding(vertical = 10.dp), contentAlignment = Alignment.Center) {
                                Text(Format.date(m.date), style = Tg.type.caption, color = c.ink2,
                                    modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(c.panel2).padding(horizontal = 10.dp, vertical = 3.dp))
                            }
                        }
                        val showName = !m.out && m.sender.isNotBlank() && (day != prevDay || prev?.sender != m.sender)
                        Bubble(m, showName, m.replyTo?.let { byId[it] }, thumbs, time = m.date?.let {
                            Instant.ofEpochSecond(it).atZone(zone).toLocalTime().format(timeFmt)
                        }.orEmpty(), onFile = { f -> onOpen(files, files.indexOfFirst { it.key == f.key }.coerceAtLeast(0)) })
                    }
                    item {
                        if (d.hasNewer) Box(Modifier.fillMaxWidth().padding(top = 6.dp), contentAlignment = Alignment.Center) {
                            TgButton("Later messages", { more(false) }, kind = ButtonKind.Ghost, icon = TgIcons.down, small = true, busy = busy)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Bubble(m: ContextMessage, showName: Boolean, reply: ContextMessage?, thumbs: ThumbSource, time: String, onFile: (FileItem) -> Unit) {
    val c = Tg.colors
    val bg = when {
        m.out -> if (c.dark) Color(0xFF2B5278) else Color(0xFFE3F0FD)
        else -> c.panel
    }
    Box(Modifier.fillMaxWidth().padding(vertical = 2.dp), contentAlignment = if (m.out) Alignment.CenterEnd else Alignment.CenterStart) {
        Column(
            Modifier.widthIn(max = 330.dp).shadow(if (m.target) 0.dp else .5.dp, RoundedCornerShape(14.dp)).clip(RoundedCornerShape(14.dp))
                .background(bg).then(if (m.target) Modifier.border(2.dp, c.accent, RoundedCornerShape(14.dp)) else Modifier)
                .padding(horizontal = 10.dp, vertical = 7.dp),
        ) {
            if (showName) Text(m.sender, style = Tg.type.label, color = c.accent, maxLines = 1)
            m.fwd?.let {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TgIconView(TgIcons.send, tint = c.ink3, size = 12.dp)
                    Spacer(Modifier.width(4.dp))
                    Text(if (it == "Forwarded") "Forwarded" else "Forwarded from $it", style = Tg.type.caption, color = c.ink3, maxLines = 1)
                }
            }
            if (m.replyTo != null) {
                Row(Modifier.padding(vertical = 3.dp).clip(RoundedCornerShape(6.dp)).background(c.accent.copy(alpha = .1f))) {
                    Box(Modifier.width(3.dp).height(30.dp).background(c.accent))
                    Text(reply?.let { r -> (r.text.ifBlank { r.file?.name ?: r.media ?: "" }).take(90) } ?: "Reply to an earlier message",
                        style = Tg.type.meta, color = c.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp))
                }
            }
            val file = m.file
            if (file != null) {
                val pic = file.hasThumb || file.inline != null
                Row(Modifier.padding(vertical = 3.dp).clip(RoundedCornerShape(10.dp)).clickable { onFile(file) }, verticalAlignment = Alignment.CenterVertically) {
                    if (pic) FileThumb(file, thumbs, Modifier.size(64.dp).clip(RoundedCornerShape(8.dp)), showBadges = false, iconWidth = 34.dp)
                    else Box(Modifier.size(44.dp).clip(RoundedCornerShape(8.dp)).background(extColor(file.ext)), contentAlignment = Alignment.Center) {
                        Text((file.ext ?: file.kind).take(4).uppercase(), style = Tg.type.caption, color = Color.White)
                    }
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.widthIn(max = 220.dp)) {
                        Text(file.displayName, style = Tg.type.label, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(Format.size(file.size), style = Tg.type.meta, color = c.ink3)
                    }
                }
            } else if (m.media != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TgIconView(TgIcons.info, tint = c.ink3, size = 14.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(m.media, style = Tg.type.meta, color = c.ink3)
                }
            }
            if (m.text.isNotBlank()) LinkedText(m.text, Tg.type.body, c.ink)
            Text(time, style = Tg.type.caption, color = c.ink3, modifier = Modifier.align(Alignment.End))
        }
    }
}

// ---------------------------------------------------------------------- mini player
/** The bar over the bottom of the screen while something plays (desktop: the mini player). */
@Composable
fun MiniPlayer(player: PlayerController, state: AppState, onOpen: (FileItem) -> Unit) {
    val f = player.current ?: return
    val c = Tg.colors
    val fraction = if (player.duration > 0) (player.position.toFloat() / player.duration).coerceIn(0f, 1f) else 0f
    val thumbUrl = if (f.hasThumb) state.api.thumbUrl(state.aid.value, f.chatId, f.msgId) else null
    Column(
        Modifier.padding(horizontal = 10.dp, vertical = 8.dp).fillMaxWidth().shadow(10.dp, RoundedCornerShape(16.dp))
            .clip(RoundedCornerShape(16.dp)).background(c.panel).clickable { onOpen(f) },
    ) {
        Row(Modifier.fillMaxWidth().heightIn(min = 60.dp).padding(start = 8.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(44.dp).clip(RoundedCornerShape(10.dp)).background(c.kind(f.kind).copy(alpha = .15f)), contentAlignment = Alignment.Center) {
                if (thumbUrl != null) coil3.compose.AsyncImage(thumbUrl, null, Modifier.fillMaxSize(),
                    contentScale = androidx.compose.ui.layout.ContentScale.Crop)
                else TgIconView(if (f.kind == "voice") TgIcons.voice else TgIcons.audio, tint = c.kind(f.kind), size = 22.dp)
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(f.audioTitle ?: f.displayName, style = Tg.type.label, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(listOfNotNull(f.performer ?: f.chatTitle, "${player.positionLabel} / ${player.durationLabel}").joinToString(" · "),
                    style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (player.queueSize > 1) IconBtn(TgIcons.prev, { player.previous() }, size = 38.dp, iconSize = 19.dp, contentDescription = "Previous")
            Box(Modifier.size(42.dp).clip(CircleShape).background(c.accent).clickable { player.toggle() }, contentAlignment = Alignment.Center) {
                if (player.buffering) Spinner(18.dp, color = c.accentInk)
                else TgIconView(if (player.playing) TgIcons.pause else TgIcons.play, tint = c.accentInk, size = 19.dp, filled = true)
            }
            if (player.queueSize > 1) IconBtn(TgIcons.next, { player.next() }, size = 38.dp, iconSize = 19.dp, contentDescription = "Next")
            IconBtn(TgIcons.close, { player.stop() }, size = 38.dp, iconSize = 18.dp, tint = c.ink3, contentDescription = "Stop")
        }
        Box(Modifier.fillMaxWidth().height(2.dp).background(c.line2)) {
            Box(Modifier.fillMaxWidth(fraction).height(2.dp).background(c.accent))
        }
        player.error?.let { Text(it, style = Tg.type.caption, color = c.danger, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) }
    }
}
