package app.tgdrive.ui.main

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.tgdrive.data.AppState
import app.tgdrive.data.Chat
import app.tgdrive.data.Folder
import app.tgdrive.ui.components.ThinProgress
import app.tgdrive.ui.files.FolderBadge
import app.tgdrive.ui.nav.Screen
import app.tgdrive.ui.nav.View
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.util.Format

/** The desktop's sidebar, as the navigation drawer. `current` highlights where you are. */
@Composable
fun Sidebar(
    state: AppState,
    current: Screen?,
    onGo: (Screen) -> Unit,
    onNew: () -> Unit,
    onPauseIndex: (Boolean) -> Unit,
) {
    val c = Tg.colors
    val folders by state.folders.collectAsState()
    val chats by state.chats.collectAsState()
    val filters by state.dialogFilters.collectAsState()
    val tags by state.tags.collectAsState()
    val subjects by state.subjects.collectAsState()
    val account by state.account.collectAsState()
    val open = remember { mutableStateMapOf("drive" to true, "saved" to true, "tg" to false, "subjects" to false, "tags" to false,
        "channel" to false, "group" to false, "user" to false, "bot" to false, "saved-msgs" to true, "tools" to true) }
    val expanded = remember { mutableStateMapOf<String, Boolean>() }
    val view = (current as? Screen.Browse)?.view

    Column(Modifier.fillMaxHeight().width(304.dp).background(c.panel).statusBarsPadding()) {
        Row(Modifier.fillMaxWidth().padding(start = 18.dp, end = 12.dp, top = 14.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            app.tgdrive.ui.components.TgLogo(30.dp)
            Spacer(Modifier.width(10.dp))
            Text("TG Drive", style = Tg.type.heading.copy(fontWeight = FontWeight.Bold), color = c.ink)
            if (state.demo) {
                Spacer(Modifier.width(8.dp))
                Text("Sample", style = Tg.type.caption, color = c.accent,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(c.accentSoft).padding(horizontal = 6.dp, vertical = 2.dp))
            }
        }
        // "New": the desktop's pill button
        Row(
            Modifier.padding(start = 14.dp, top = 8.dp, bottom = 6.dp).clip(RoundedCornerShape(14.dp)).background(c.panel)
                .border(1.dp, c.line, RoundedCornerShape(14.dp)).clickable(onClick = onNew).padding(horizontal = 18.dp).height(46.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TgIconView(TgIcons.plus, tint = c.ink, size = 20.dp, stroke = 2f)
            Spacer(Modifier.width(10.dp))
            Text("New", style = Tg.type.bodyStrong, color = c.ink)
        }

        LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
            // My Drive and its tree
            item("drive") {
                NavRow(TgIcons.folder, "My Drive", selected = view is View.Drive && (view as View.Drive).folderId == null,
                    onClick = { onGo(Screen.Browse(View.Drive(null))) })
            }
            folderTree(folders.folders, null, 1, view, expanded, onGo)
            item("all") { NavRow(TgIcons.grid, "All files", count = account?.index?.files, selected = view == View.All, onClick = { onGo(Screen.Browse(View.All)) }) }
            item("starred") { NavRow(TgIcons.star, "Starred", count = folders.starred, selected = view == View.Starred, onClick = { onGo(Screen.Browse(View.Starred)) }) }
            item("recent") { NavRow(TgIcons.clock, "Recent", selected = view == View.Recent, onClick = { onGo(Screen.Browse(View.Recent)) }) }
            if (folders.continueWatching > 0) item("continue") {
                NavRow(TgIcons.play, "Continue watching", count = folders.continueWatching, selected = view == View.Continue,
                    onClick = { onGo(Screen.Browse(View.Continue)) })
            }
            item("photos") { NavRow(TgIcons.photos, "Photos", selected = current == Screen.Photos, onClick = { onGo(Screen.Photos) }) }

            if (folders.saved.isNotEmpty()) {
                group("saved", "Saved searches", open)
                if (open["saved"] == true) for (s in folders.saved) item("s:${s.id}") {
                    NavRow(TgIcons.search, s.name, selected = view == View.Saved(s.id), onClick = { onGo(Screen.Browse(View.Saved(s.id))) })
                }
            }
            if (filters.isNotEmpty()) {
                group("tg", "Telegram folders", open)
                if (open["tg"] == true) for (f in filters) item("tg:${f.id}") {
                    NavRow(TgIcons.telegram, f.title, emoji = f.emoticon, selected = view == View.TgFolder(f.id),
                        onClick = { onGo(Screen.Browse(View.TgFolder(f.id))) })
                }
            }
            val subs = subjects.filter { it.n > 0 }
            if (subs.isNotEmpty()) {
                group("subjects", "Subjects", open)
                if (open["subjects"] == true) for (s in subs) item("sub:${s.id}") {
                    NavRow(TgIcons.book, s.name, emoji = s.emoji, count = s.n, selected = view == View.SubjectView(s.id),
                        onClick = { onGo(Screen.Browse(View.SubjectView(s.id))) })
                }
            }
            if (tags.isNotEmpty()) {
                group("tags", "Tags", open)
                if (open["tags"] == true) for (t in tags) item("tag:${t.tag}") {
                    NavRow(TgIcons.tag, t.tag, count = t.n, selected = view == View.TagView(t.tag), onClick = { onGo(Screen.Browse(View.TagView(t.tag))) })
                }
            }
            chatGroups(chats, view, open, onGo)

            group("tools", "Tools", open)
            if (open["tools"] == true) {
                item("t-transfers") { NavRow(TgIcons.transfers, "Transfers", count = account?.transfers?.active?.toLong()?.takeIf { it > 0 },
                    selected = current == Screen.Transfers, onClick = { onGo(Screen.Transfers) }) }
                item("t-offline") { NavRow(TgIcons.download, "Offline & recovery", selected = current == Screen.Offline, onClick = { onGo(Screen.Offline) }) }
                item("t-storage") { NavRow(TgIcons.chart, "Storage", selected = current == Screen.Storage, onClick = { onGo(Screen.Storage) }) }
                item("t-dupes") { NavRow(TgIcons.dupes, "Duplicates", selected = current == Screen.Duplicates, onClick = { onGo(Screen.Duplicates) }) }
                item("t-index") { NavRow(TgIcons.database, "Chats and indexing", selected = current == Screen.Index, onClick = { onGo(Screen.Index) }) }
                item("t-activity") { NavRow(TgIcons.activity, "Activity", selected = current == Screen.Activity, onClick = { onGo(Screen.Activity) }) }
                item("t-settings") { NavRow(TgIcons.settings, "Settings", selected = current is Screen.Settings, onClick = { onGo(Screen.Settings()) }) }
            }
            item("bottom-space") { Spacer(Modifier.height(12.dp)) }
        }
        IndexCard(state, onPauseIndex, onOpen = { onGo(Screen.Index) })
    }
}

private fun LazyListScope.group(key: String, title: String, open: MutableMap<String, Boolean>) = item("h:$key") {
    val c = Tg.colors
    val isOpen = open[key] == true
    Row(Modifier.fillMaxWidth().clickable { open[key] = !isOpen }.padding(start = 20.dp, end = 16.dp, top = 16.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(title.uppercase(), style = Tg.type.overline, color = c.ink3, modifier = Modifier.weight(1f))
        TgIconView(if (isOpen) TgIcons.chevronDown else TgIcons.chevron, tint = c.ink3, size = 15.dp)
    }
}

private fun LazyListScope.folderTree(all: List<Folder>, parent: String?, depth: Int, view: View?, expanded: MutableMap<String, Boolean>,
                                     onGo: (Screen) -> Unit) {
    val kids = all.filter { it.parentId == parent }.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.name })
    for (f in kids) {
        val hasKids = all.any { it.parentId == f.id }
        item("f:${f.id}") {
            NavRow(null, f.name, indent = depth, count = f.fileCount.takeIf { it > 0 },
                selected = view is View.Drive && view.folderId == f.id,
                leading = { FolderBadge(f, 22.dp) },
                expander = if (hasKids) (expanded[f.id] == true) else null,
                onExpand = { expanded[f.id] = expanded[f.id] != true },
                onClick = { onGo(Screen.Browse(View.Drive(f.id))) })
        }
        if (hasKids && expanded[f.id] == true && depth < 6) folderTree(all, f.id, depth + 1, view, expanded, onGo)
    }
}

private val CHAT_GROUPS = listOf("saved" to "Saved Messages", "channel" to "Channels", "group" to "Groups", "user" to "Private chats", "bot" to "Bots")

private fun LazyListScope.chatGroups(chats: List<Chat>, view: View?, open: MutableMap<String, Boolean>, onGo: (Screen) -> Unit) {
    val visible = chats.filter { it.excluded == 0 && it.fileCount > 0 }
    for ((kind, title) in CHAT_GROUPS) {
        val list = visible.filter { it.group == kind }.sortedWith(compareByDescending<Chat> { it.pinned }.thenByDescending { it.fileCount })
        if (list.isEmpty()) continue
        if (kind == "saved") {
            for (ch in list) item("c:${ch.id}") {
                NavRow(TgIcons.bookmark, "Saved Messages", count = ch.fileCount, selected = view == View.Chat(ch.id), onClick = { onGo(Screen.Browse(View.Chat(ch.id))) })
            }
            continue
        }
        val key = kind
        group(key, "$title · ${list.size}", open)
        if (open[key] == true) for (ch in list.take(300)) item("c:${ch.id}") {
            NavRow(null, ch.title ?: "Chat", count = ch.fileCount, selected = view is View.Chat && view.chatId == ch.id,
                leading = { app.tgdrive.ui.components.Avatar(ch.title, 24.dp) }, onClick = { onGo(Screen.Browse(View.Chat(ch.id))) })
        }
    }
}

@Composable
fun NavRow(
    icon: TgIcon?,
    text: String,
    selected: Boolean = false,
    count: Long? = null,
    indent: Int = 0,
    emoji: String? = null,
    leading: (@Composable () -> Unit)? = null,
    expander: Boolean? = null,
    onExpand: () -> Unit = {},
    onClick: () -> Unit,
) {
    val c = Tg.colors
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 10.dp, vertical = 1.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (selected) c.accentSoft else Color.Transparent)
            .clickable(onClick = onClick)
            .heightIn(min = 42.dp)
            .padding(start = (10 + indent * 14).dp, end = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (expander != null) {
            Box(Modifier.size(22.dp).clip(RoundedCornerShape(6.dp)).clickable(onClick = onExpand), contentAlignment = Alignment.Center) {
                TgIconView(if (expander) TgIcons.chevronDown else TgIcons.chevron, tint = c.ink3, size = 14.dp)
            }
            Spacer(Modifier.width(2.dp))
        } else if (indent > 0) Spacer(Modifier.width(24.dp))
        when {
            leading != null -> leading()
            !emoji.isNullOrBlank() -> Box(Modifier.size(22.dp), contentAlignment = Alignment.Center) { Text(emoji, fontSize = 15.sp) }
            icon != null -> TgIconView(icon, tint = if (selected) c.accent else c.ink2, size = 20.dp)
        }
        Spacer(Modifier.width(14.dp))
        Text(text, style = Tg.type.label.copy(fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium),
            color = if (selected) c.accent else c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        if (count != null && count > 0) Text(Format.compact(count), style = Tg.type.meta, color = if (selected) c.accent else c.ink3)
    }
}

/** The indexing status at the foot of the sidebar (desktop: "Indexing files · 7/8 chats · 327 files"). */
@Composable
private fun IndexCard(state: AppState, onPause: (Boolean) -> Unit, onOpen: () -> Unit) {
    val c = Tg.colors
    val account by state.account.collectAsState()
    val idx = account?.index ?: return
    val paused = idx.phase == "paused"
    val busy = idx.phase !in setOf("idle", "paused", "")
    Column(Modifier.fillMaxWidth().background(c.panel2).clickable(onClick = onOpen).navigationBarsPadding()
        .padding(start = 18.dp, end = 10.dp, top = 12.dp, bottom = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(when {
                idx.error != null -> c.danger; paused -> c.warn; busy -> c.accent; else -> c.ok
            }))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(when {
                    idx.error != null -> "Indexing stopped"
                    paused -> "Indexing paused"
                    busy -> idx.phase.replaceFirstChar { it.uppercase() }
                    else -> "Up to date"
                }, style = Tg.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.ink)
                Text("${idx.chatsDone}/${idx.chatsTotal} chats · ${Format.compact(idx.files)} files", style = Tg.type.meta, color = c.ink3)
            }
            if (busy || paused) {
                app.tgdrive.ui.components.IconBtn(if (paused) TgIcons.play else TgIcons.pause, { onPause(!paused) }, size = 36.dp, iconSize = 18.dp,
                    contentDescription = if (paused) "Resume indexing" else "Pause indexing")
            }
        }
        if (busy && idx.chatsTotal > 0) {
            Spacer(Modifier.height(8.dp))
            ThinProgress(idx.chatsDone.toFloat() / idx.chatsTotal, Modifier.fillMaxWidth())
            if (!idx.current.isNullOrBlank()) {
                Spacer(Modifier.height(6.dp))
                Text("Now: ${idx.current}", style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
