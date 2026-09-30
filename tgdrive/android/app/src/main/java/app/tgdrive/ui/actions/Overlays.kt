package app.tgdrive.ui.actions

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.data.Folder
import app.tgdrive.data.long
import app.tgdrive.data.obj
import app.tgdrive.data.str
import app.tgdrive.player.PlayerController
import app.tgdrive.ui.browse.BrowseModel
import app.tgdrive.ui.browse.SORTS
import app.tgdrive.ui.components.Avatar
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.ChoiceRow
import app.tgdrive.ui.components.ConfirmDialog
import app.tgdrive.ui.components.Divider
import app.tgdrive.ui.components.SheetAction
import app.tgdrive.ui.components.SheetTitle
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.components.TgDialog
import app.tgdrive.ui.components.TgSheet
import app.tgdrive.ui.components.TgSwitch
import app.tgdrive.ui.components.TgTextField
import app.tgdrive.ui.files.FileThumb
import app.tgdrive.ui.files.FolderBadge
import app.tgdrive.ui.files.ThumbSource
import app.tgdrive.ui.nav.Navigator
import app.tgdrive.ui.nav.Screen
import app.tgdrive.ui.nav.SearchScope
import app.tgdrive.ui.nav.View
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgColors
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.TgShape
import app.tgdrive.util.Format
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/** Shows whatever [Actions.overlay] asks for: menus as bottom sheets, questions as dialogs. */
@Composable
fun OverlayHost(actions: Actions, state: AppState, nav: Navigator, thumbs: ThumbSource, upload: () -> Unit, uploadFolder: () -> Unit) {
    val o = actions.overlay ?: return
    val close = { actions.close() }
    when (o) {
        is Overlay.FileMenu -> FileMenu(o.file, actions, state, nav, thumbs)
        is Overlay.SelectionMenu -> SelectionMenu(o.files, actions, state)
        is Overlay.Move -> FolderPickerSheet(
            state,
            title = when {
                o.copy -> "Save a copy to Drive"
                o.files.size == 1 -> "Move to folder"
                else -> "Move ${o.files.size} files to folder"
            },
            okLabel = if (o.copy) "Save copy" else "Move here",
            current = if (o.copy) null else o.files.map { it.folderId }.distinct().singleOrNull(),
            onDismiss = close,
            onPick = { f -> if (o.copy) actions.copyToDrive(o.files, f) else actions.move(o.files, f); actions.model?.clearSelection() },
        )
        is Overlay.Tags -> TagsDialog(o.files, actions, state)
        is Overlay.Rename -> PromptDialog("Rename", "Name in TG Drive (the message in Telegram is unchanged)", o.file.name, "Rename",
            onDismiss = close, onConfirm = { actions.rename(o.file, it) }, selectStem = true, max = 120, allowEmpty = true,
            help = if (o.file.renamed) "Leave it empty to go back to “${o.file.originalName}”." else null)
        is Overlay.BulkRename -> PromptDialog("Rename ${o.files.size} files", "Pattern", "{name}", "Rename", onDismiss = close,
            onConfirm = { actions.bulkRename(o.files, it, 1); actions.model?.clearSelection() },
            help = "Use {n} for a number ({n:02} pads to 2 digits), {name} for the current name, {date}, {chat}. " +
                "The extension is kept. Files are numbered in the order shown.")
        is Overlay.Note -> NoteDialog(o.file, o.note, actions, state)
        is Overlay.Delete -> ConfirmDialog(
            if (o.files.size == 1) "Delete this file from Telegram?" else "Delete ${o.files.size} files from Telegram?",
            "This deletes the messages in their chats, for everyone where Telegram allows it. It can't be undone.",
            "Delete from Telegram", onConfirm = { actions.deleteFromTelegram(o.files); actions.model?.clearSelection() }, onDismiss = close,
            danger = true)
        is Overlay.Forget -> ConfirmDialog("Hide ${Format.plural(o.files.size, "file")} from TG Drive?",
            "They are removed from the index only. Nothing changes in Telegram. “Re-index” on the chat brings them back.",
            "Remove from index", onConfirm = { actions.forget(o.files); actions.model?.clearSelection() }, onDismiss = close)
        is Overlay.Send -> SendFlow(o.files, actions, state)
        is Overlay.SetSubject -> SubjectSheet(o.files, actions, state)
        is Overlay.FolderEdit -> when {
            o.smart -> RulesDialog(o.folder, o.parentId, actions, state, nav)
            o.folder == null -> PromptDialog(
                o.parentId?.let { id -> state.folders.value.folders.firstOrNull { it.id == id }?.name }?.let { "New folder in “$it”" } ?: "New folder",
                "Folder name", "", "Create", onDismiss = close, onConfirm = { actions.createFolder(it, o.parentId) })
            else -> FolderLookDialog(o.folder, actions, state)
        }
        is Overlay.FolderMenu -> FolderMenu(o.folder, actions, state, nav)
        is Overlay.FolderRename -> PromptDialog("Rename folder", "Folder name", o.folder.name, "Rename", onDismiss = close,
            onConfirm = { actions.renameFolder(o.folder, it) })
        is Overlay.FolderMove -> {
            val subs = descendants(state, o.folder.id)
            FolderPickerSheet(state, "Move “${o.folder.name}”", "Move here", o.folder.parentId, onDismiss = close,
                onPick = { actions.moveFolder(o.folder, it) }, exclude = subs + o.folder.id)
        }
        is Overlay.FolderDelete -> {
            val subs = descendants(state, o.folder.id).size
            ConfirmDialog("Delete “${o.folder.name}”?",
                (if (subs > 0) "Its ${Format.plural(subs, "subfolder")} go too. " else "") +
                    (if (o.folder.smart) "Nothing happens to the files it shows." else "Files inside stay in Telegram and simply leave the folder.") +
                    " You can undo this.",
                "Delete folder", onConfirm = {
                    actions.deleteFolder(o.folder)
                    val v = (nav.top.screen as? Screen.Browse)?.view as? View.Drive
                    if (v?.folderId == o.folder.id || v?.folderId in descendants(state, o.folder.id)) nav.pop()
                }, onDismiss = close, danger = true)
        }
        is Overlay.FolderDownload -> TgSheet(close) {
            SheetTitle("Download “${o.folder.name}”", folderSizeLine(o.folder))
            SheetAction(TgIcons.download, "Download the files", { actions.downloadFolder(o.folder, false); close() },
                subtitle = "Into Downloads/TG Drive, keeping its subfolders")
            SheetAction(TgIcons.stack, "Download as one .zip", { actions.downloadFolder(o.folder, true); close() })
        }
        Overlay.NewMenu -> NewMenu(actions, state, nav, upload, uploadFolder)
        Overlay.AccountMenu -> AccountMenu(actions, state, nav)
        is Overlay.Sort -> SortSheet(o.model, close)
        is Overlay.Filters -> FiltersSheet(o.model, state, close)
        is Overlay.ViewOptions -> ViewSheet(o.model, state, close)
        is Overlay.SaveSearch -> PromptDialog("Save this search", "Name", o.q.ifBlank { "My search" }, "Save", onDismiss = close,
            onConfirm = { name -> actions.saveSearch(name, o.q, o.params) { nav.navigate(Screen.Browse(View.Saved(it))) } },
            help = "Saved searches appear in the sidebar and sync to your other devices. They always show current results.")
        is Overlay.ListMenu -> ListMenu(o.model, actions, state, nav)
        is Overlay.ChatMenu -> ChatMenu(o.chatId, actions, state, nav)
    }
}

private fun descendants(state: AppState, id: String): Set<String> {
    val byParent = state.folders.value.folders.groupBy { it.parentId }
    val out = HashSet<String>()
    fun walk(p: String) { byParent[p].orEmpty().forEach { if (out.add(it.id)) walk(it.id) } }
    walk(id)
    return out
}

private fun folderSizeLine(f: Folder) = if (f.fileCount > 0) "${Format.plural(f.fileCount, "file")} · ${Format.size(f.bytes)}" else "Empty"

// ---------------------------------------------------------------------- file menu
@Composable
private fun FileMenu(f: FileItem, actions: Actions, state: AppState, nav: Navigator, thumbs: ThumbSource) {
    val c = Tg.colors
    val ctx = LocalContext.current
    val close = { actions.close() }
    fun then(o: Overlay) { actions.open(o) }
    val inChat = ((nav.top.screen as? Screen.Browse)?.view as? View.Chat)?.chatId == f.chatId
    TgSheet(close) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            FileThumb(f, thumbs, Modifier.size(52.dp).clip(RoundedCornerShape(10.dp)), showBadges = false, iconWidth = 34.dp)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(f.displayName, style = Tg.type.subheading, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(listOfNotNull(f.chatTitle, Format.size(f.size), f.date?.let { Format.date(it) }).joinToString(" · "),
                    style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        Divider()
        Column(Modifier.verticalScroll(rememberScrollState())) {
            Spacer(Modifier.height(4.dp))
            // Quick row: the things people do most, as on the desktop's details panel.
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
                QuickAction(TgIcons.download, "Download") { actions.download(listOf(f)); close() }
                QuickAction(TgIcons.star, if (f.starred) "Starred" else "Star", active = f.starred) { actions.star(listOf(f), !f.starred); close() }
                QuickAction(TgIcons.move, "Move") { then(Overlay.Move(listOf(f))) }
                QuickAction(TgIcons.tag, "Tags") { then(Overlay.Tags(listOf(f))) }
                QuickAction(TgIcons.link, "Link", enabled = f.link != null) { actions.copyLink(f); close() }
            }
            Divider(Modifier.padding(vertical = 4.dp))
            val playable = f.kind in Format.STREAMABLE
            SheetAction(if (playable) TgIcons.play else TgIcons.eye, if (playable) "Play" else "Preview", {
                close()
                if (f.kind in setOf("audio", "voice")) PlayerController.get(ctx).playList(state, listOf(f), f)
                else nav.push(Screen.Viewer(listOf(f), 0))
            })
            SheetAction(TgIcons.info, "Details", { close(); nav.push(Screen.Details(f.ref)) })
            SheetAction(TgIcons.external, "Open with another app", { close(); actions.openWithApp(f) },
                subtitle = if (playable) "Streams to VLC, MX Player …" else "Downloads it first")
            SheetAction(TgIcons.edit, "Rename…", { then(Overlay.Rename(f)) })
            SheetAction(TgIcons.note, "Note…", { then(Overlay.Note(f, "")) })
            SheetAction(TgIcons.book, "Subject…", { then(Overlay.SetSubject(listOf(f))) })
            if (f.kind == "video" || f.kind == "audio" || f.kind == "round") {
                if (f.watched) SheetAction(TgIcons.eye, "Mark as not watched", { actions.markWatched(listOf(f), false); close() })
                else SheetAction(TgIcons.check, "Mark as watched", { actions.markWatched(listOf(f), true); close() })
            }
            SheetAction(TgIcons.copy, "Save a copy to Drive…", { then(Overlay.Move(listOf(f), copy = true)) })
            SheetAction(TgIcons.send, "Send to chat…", { then(Overlay.Send(listOf(f))) })
            if (f.link != null) SheetAction(TgIcons.external, "Share link", { close(); Platform.shareText(ctx, f.link) })
            SheetAction(TgIcons.telegram, "Open in Telegram", { close(); actions.openInTelegram(f) })
            SheetAction(TgIcons.chat, "Show in chat", { close(); nav.push(Screen.ChatContext(f.ref, f.displayName)) })
            if (!inChat) SheetAction(TgIcons.chevron, "Go to ${f.chatTitle ?: "chat"}", { close(); nav.navigate(Screen.Browse(View.Chat(f.chatId))) })
            if (f.groupedId != null) SheetAction(TgIcons.photo, "Show album", { close(); nav.push(Screen.Browse(View.Album(f.chatId, f.groupedId))) })
            SheetAction(TgIcons.sparkle, "Find related files", {
                close()
                val q = f.name.substringBeforeLast('.').replace(Regex("[_\\-.]+"), " ").trim()
                nav.push(Screen.Browse(View.Search(q)))
            })
            Divider(Modifier.padding(vertical = 4.dp))
            SheetAction(TgIcons.close, "Hide from TG Drive", { then(Overlay.Forget(listOf(f))) }, subtitle = "Keeps it in Telegram")
            SheetAction(TgIcons.trash, "Delete from Telegram", { deleteOrConfirm(listOf(f), actions, state) }, danger = true)
        }
    }
}

private fun deleteOrConfirm(files: List<FileItem>, actions: Actions, state: AppState) {
    if (state.setting("confirm_delete") == "false") { actions.close(); actions.deleteFromTelegram(files); actions.model?.clearSelection() }
    else actions.open(Overlay.Delete(files))
}

@Composable
private fun QuickAction(icon: app.tgdrive.ui.theme.TgIcon, label: String, active: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    val c = Tg.colors
    Column(
        Modifier.width(64.dp).clip(RoundedCornerShape(12.dp)).clickable(enabled = enabled, onClick = onClick).padding(vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.size(44.dp).clip(CircleShape).background(if (active) c.accentSoft else c.panel2).border(1.dp, if (active) c.accentLine else c.line2, CircleShape),
            contentAlignment = Alignment.Center) {
            TgIconView(icon, tint = when { !enabled -> c.ink3; active -> if (icon == TgIcons.star) c.star else c.accent; else -> c.ink }, size = 20.dp,
                filled = active && icon == TgIcons.star)
        }
        Spacer(Modifier.height(6.dp))
        Text(label, style = Tg.type.caption, color = if (enabled) c.ink2 else c.ink3, maxLines = 1)
    }
}

// ---------------------------------------------------------------------- selection menu
@Composable
private fun SelectionMenu(files: List<FileItem>, actions: Actions, state: AppState) {
    val close = { actions.close() }
    val done = { close(); actions.model?.clearSelection() }
    val bytes = files.sumOf { it.size }
    val chats = files.map { it.chatId }.distinct().size
    TgSheet(close) {
        SheetTitle("${Format.plural(files.size, "file")} selected", "${Format.size(bytes)} from ${Format.plural(chats, "chat")}")
        Column(Modifier.verticalScroll(rememberScrollState())) {
            actions.model?.let { m ->
                if (m.selected.size < m.items.size) SheetAction(TgIcons.check, "Select all ${Format.num(m.items.size)} shown", { m.selectAll(); close() })
            }
            SheetAction(TgIcons.download, "Download ${Format.plural(files.size, "file")}", { actions.download(files); done() })
            SheetAction(TgIcons.stack, "Download as .zip", { actions.download(files, zip = true); done() })
            SheetAction(TgIcons.move, "Move to folder…", { actions.open(Overlay.Move(files)) })
            val allStarred = files.all { it.starred }
            SheetAction(TgIcons.star, if (allStarred) "Remove stars" else "Star all", { actions.star(files, !allStarred); done() })
            SheetAction(TgIcons.tag, "Tags…", { actions.open(Overlay.Tags(files)) })
            SheetAction(TgIcons.book, "Subject…", { actions.open(Overlay.SetSubject(files)) })
            if (files.any { it.kind == "video" || it.kind == "audio" }) {
                SheetAction(TgIcons.check, "Mark as watched", { actions.markWatched(files, true); done() })
            }
            SheetAction(TgIcons.edit, "Rename with a pattern…", { actions.open(Overlay.BulkRename(files)) })
            SheetAction(TgIcons.copy, "Save copies to Drive…", { actions.open(Overlay.Move(files, copy = true)) })
            SheetAction(TgIcons.send, "Send to chat…", { actions.open(Overlay.Send(files)) })
            SheetAction(TgIcons.link, "Copy links", { actions.copyLinks(files); done() })
            Divider(Modifier.padding(vertical = 4.dp))
            SheetAction(TgIcons.close, "Hide from TG Drive", { actions.open(Overlay.Forget(files)) }, subtitle = "Keeps them in Telegram")
            SheetAction(TgIcons.trash, "Delete from Telegram", { deleteOrConfirm(files, actions, state) }, danger = true)
        }
    }
}

// ---------------------------------------------------------------------- tags, note, subject, send
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TagsDialog(files: List<FileItem>, actions: Actions, state: AppState) {
    val c = Tg.colors
    val all by state.tags.collectAsState()
    val common = remember { files.first().tags.filter { t -> files.all { t in it.tags } } }
    val chosen = remember { mutableStateListOf<String>().apply { addAll(common) } }
    var input by remember { mutableStateOf("") }
    fun addTyped() {
        input.split(',').map { it.trim().trimStart('#').lowercase() }.filter { it.isNotBlank() }.forEach { if (it !in chosen) chosen += it }
        input = ""
    }
    TgDialog(if (files.size == 1) "Tags for “${files[0].displayName}”" else "Tags for ${files.size} files", { actions.close() }, "Save", {
        addTyped()
        val removed = common.filter { it !in chosen }
        actions.setTags(files, chosen.toList(), removed)
        actions.close()
    }) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            chosen.forEach { t -> TgChip("#$t", selected = true, onClose = { chosen.remove(t) }) }
            if (chosen.isEmpty()) Text("No tags yet.", style = Tg.type.body, color = c.ink3)
        }
        Spacer(Modifier.height(12.dp))
        TgTextField(input, { v -> if (v.endsWith(",") || v.endsWith(" ")) { input = v; addTyped() } else input = v },
            placeholder = "Add a tag", leading = TgIcons.tag, onDone = { addTyped() },
            trailing = { if (input.isNotBlank()) TgButton("Add", { addTyped() }, kind = ButtonKind.Ghost, small = true) })
        val suggestions = all.map { it.tag }.filter { it !in chosen && (input.isBlank() || it.contains(input.trim().lowercase())) }.take(24)
        if (suggestions.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text(if (input.isBlank()) "Your tags" else "Matching tags", style = Tg.type.overline, color = c.ink3)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                suggestions.forEach { t -> TgChip("#$t", onClick = { chosen += t; input = "" }) }
            }
        }
    }
}

@Composable
private fun NoteDialog(f: FileItem, initial: String, actions: Actions, state: AppState) {
    var note by remember { mutableStateOf<String?>(initial.ifEmpty { null }) }
    LaunchedEffect(f.key) {
        if (note == null) note = runCatching { state.api.detail(state.aid.value, f.ref).extras.note.orEmpty() }.getOrDefault("")
    }
    val n = note
    if (n == null) {
        TgDialog("Note", { actions.close() }, dismiss = "Cancel") { app.tgdrive.ui.components.Spinner() }
    } else {
        PromptDialog("Note", "Your note (synced, searchable with has:note)", n, "Save", onDismiss = { actions.close() },
            onConfirm = { actions.saveNote(f, it) }, multiline = true, allowEmpty = true, max = 2000)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SubjectSheet(files: List<FileItem>, actions: Actions, state: AppState) {
    val c = Tg.colors
    val subjects by state.subjects.collectAsState()
    val cur = if (files.size == 1) files[0].subject else null
    TgSheet({ actions.close() }) {
        SheetTitle(if (files.size == 1) "Subject" else "Subject for ${Format.plural(files.size, "file")}")
        Text("Subjects are set automatically from names and captions. Pick one to correct it; TG Drive won't change it again.",
            style = Tg.type.meta, color = c.ink2, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
        FlowRow(Modifier.padding(horizontal = 20.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            subjects.forEach { s ->
                TgChip(listOfNotNull(s.emoji, s.name).joinToString(" "), selected = cur == s.id,
                    onClick = { actions.setSubject(files, s.id); actions.close(); actions.model?.clearSelection() })
            }
            TgChip("No subject", icon = TgIcons.close, onClick = { actions.setSubject(files, null); actions.close() })
        }
        if (subjects.isEmpty()) Text("Subjects are off or still being worked out. Turn them on in Settings → Subjects.",
            style = Tg.type.body, color = c.ink3, modifier = Modifier.padding(20.dp))
    }
}

@Composable
private fun SendFlow(files: List<FileItem>, actions: Actions, state: AppState) {
    var chat by remember { mutableStateOf<app.tgdrive.data.Chat?>(null) }
    val ch = chat
    if (ch == null) {
        ChatPickerSheet(state, if (files.size == 1) "Send to chat" else "Send ${files.size} files to chat",
            onDismiss = { if (chat == null) actions.close() }, onPick = { chat = it }, writableOnly = true)
    } else {
        TgDialog("How should ${if (files.size == 1) "it" else "they"} be sent?", { actions.close() }, dismiss = null) {
            Text("A copy looks like you sent it. Forwarding shows where it came from.", style = Tg.type.body, color = Tg.colors.ink2)
            Spacer(Modifier.height(16.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End)) {
                TgButton("Cancel", { actions.close() }, kind = ButtonKind.Ghost)
                TgButton("Forward", { actions.send(files, ch.id, forward = true); actions.close(); actions.model?.clearSelection() })
                TgButton("Send as copy", { actions.send(files, ch.id, forward = false); actions.close(); actions.model?.clearSelection() },
                    kind = ButtonKind.Primary)
            }
        }
    }
}

// ---------------------------------------------------------------------- folders
@Composable
private fun FolderMenu(f: Folder, actions: Actions, state: AppState, nav: Navigator) {
    val close = { actions.close() }
    val hasRule = f.rules is JsonObject
    TgSheet(close) {
        SheetTitle(f.name, folderSizeLine(f), leading = { FolderBadge(f, 40.dp) })
        Column(Modifier.verticalScroll(rememberScrollState())) {
            SheetAction(TgIcons.folder, "Open", { close(); nav.push(Screen.Browse(View.Drive(f.id))) })
            if (!f.smart) SheetAction(TgIcons.folderPlus, "New subfolder", { actions.open(Overlay.FolderEdit(null, f.id)) })
            SheetAction(TgIcons.search, "Search in this folder", {
                close()
                nav.push(Screen.SearchInput(scope = SearchScope(f.name, mapOf("folder_id" to f.id, "folder_tree" to "1"))))
            })
            Divider(Modifier.padding(vertical = 4.dp))
            SheetAction(TgIcons.edit, "Rename", { actions.open(Overlay.FolderRename(f)) })
            SheetAction(TgIcons.palette, "Icon, colour and description…", { actions.open(Overlay.FolderEdit(f, f.parentId)) })
            SheetAction(if (hasRule && f.smart) TgIcons.sparkle else TgIcons.wand,
                when { !hasRule -> "Auto-file matching files…"; f.smart -> "Edit smart rule…"; else -> "Edit auto-filing rule…" },
                { actions.open(Overlay.FolderEdit(f, f.parentId, smart = true)) })
            if (f.auto) SheetAction(TgIcons.wand, "File matching files now", { actions.applyRules(f); close() })
            SheetAction(TgIcons.move, "Move to…", { actions.open(Overlay.FolderMove(f)) })
            if (!f.smart) {
                Divider(Modifier.padding(vertical = 4.dp))
                SheetAction(TgIcons.download, "Download folder", { actions.open(Overlay.FolderDownload(f)) })
            }
            Divider(Modifier.padding(vertical = 4.dp))
            SheetAction(TgIcons.trash, "Delete folder", { actions.open(Overlay.FolderDelete(f)) }, danger = true)
        }
    }
}

/** Icon, colour and description of a folder (desktop: the appearance dialog and description prompt). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FolderLookDialog(f: Folder, actions: Actions, state: AppState) {
    val c = Tg.colors
    var color by remember { mutableStateOf(f.color.orEmpty()) }
    var emoji by remember { mutableStateOf(f.emoji.orEmpty()) }
    var description by remember { mutableStateOf(f.description.orEmpty()) }
    TgDialog("Look of “${f.name}”", { actions.close() }, "Save", {
        actions.updateFolder(f, buildJsonObject { put("color", color); put("emoji", emoji); put("description", description) }, "Folder updated")
        actions.close()
    }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            FolderBadge(f.copy(color = color, emoji = emoji), 52.dp)
            Spacer(Modifier.width(14.dp))
            Text(f.name, style = Tg.type.heading, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.height(18.dp))
        Text("COLOUR", style = Tg.type.overline, color = c.ink3)
        Spacer(Modifier.height(8.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            (listOf("") + TgColors.FOLDER_COLORS.keys).forEach { k ->
                val sw = if (k.isEmpty()) c.folder else TgColors.FOLDER_COLORS.getValue(k)
                Box(Modifier.size(34.dp).clip(CircleShape).background(sw).clickable { color = k }
                    .then(if (color == k) Modifier.border(3.dp, c.panel, CircleShape) else Modifier), contentAlignment = Alignment.Center) {
                    if (color == k) TgIconView(TgIcons.check, tint = Color.White, size = 16.dp, stroke = 2.6f)
                }
            }
        }
        Spacer(Modifier.height(18.dp))
        Text("ICON", style = Tg.type.overline, color = c.ink3)
        Spacer(Modifier.height(8.dp))
        TgTextField(emoji, { if (it.length <= 8) emoji = it.trim() }, placeholder = "Type or paste any emoji",
            trailing = { if (emoji.isNotEmpty()) TgButton("No emoji", { emoji = "" }, kind = ButtonKind.Ghost, small = true) })
        Spacer(Modifier.height(8.dp))
        EMOJI.forEach { (title, list) ->
            Text(title, style = Tg.type.caption, color = c.ink3, modifier = Modifier.padding(top = 8.dp, bottom = 4.dp))
            FlowRow {
                list.split(' ').forEach { e ->
                    Box(Modifier.size(40.dp).clip(RoundedCornerShape(8.dp)).background(if (emoji == e) c.accentSoft else Color.Transparent)
                        .clickable { emoji = e }, contentAlignment = Alignment.Center) { Text(e, fontSize = 20.sp) }
                }
            }
        }
        Spacer(Modifier.height(18.dp))
        Text("DESCRIPTION", style = Tg.type.overline, color = c.ink3)
        Spacer(Modifier.height(8.dp))
        TgTextField(description, { if (it.length <= 500) description = it }, placeholder = "Shown in the folder header", singleLine = false, minLines = 2)
    }
}

private val EMOJI = listOf(
    "Study" to "📚 📖 📝 ✍️ 📓 📔 📒 📕 📗 📘 📙 🗒️ 📑 🎓 🧠 💡 🔖 📐 📏 🧮 🔬 🧪 🧬 🔭 ⚖️ 🏛️ 🌍 🗺️ 🌿 📈 📰 🧭 🛡️ 🤝 🎨 🔤",
    "Things" to "📁 📂 🗂️ 🗃️ 🗄️ 📦 💼 🧾 💳 💰 🏦 🏠 🚗 ✈️ 🧳 🏖️ 🎁 🛒 🧰 🔧 💻 🖥️ 📱 🎧 🎮 📷 🎥 🎬 🎵 🎤 🖼️ 📺 📻 ⌚",
    "Symbols" to "⭐ ❤️ 🔥 ✅ ❗ ❓ 💬 🔒 🔑 🚀 🎯 🏆 🥇 🌟 ✨ ⚡ 💎 🌈 ☀️ 🌙 🍀 🌸 🌻 🐾 🎉 🏁 📌 📍 🔔 ♻️ 🆕 🆓 💯 🔴 🟢 🔵",
)

private val TYPE_OPTS = listOf("" to "Any type", "document" to "Documents", "video" to "Videos", "photo" to "Photos",
    "audio" to "Audio", "voice" to "Voice", "photo,video" to "Photos and videos")

/**
 * A folder's rule (desktop rulesDialog): a smart folder shows every matching file; auto-file moves
 * matching unfiled files in. Shows how many files match while you type.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RulesDialog(f: Folder?, parentId: String?, actions: Actions, state: AppState, nav: Navigator) {
    val c = Tg.colors
    val cur = f?.rules as? JsonObject
    val curParams = cur?.obj("params").orEmpty().mapValues { (it.value as? JsonPrimitive)?.contentOrNull.orEmpty() }
    var name by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf(cur?.str("mode") ?: if (f != null) "auto" else "smart") }
    var q by remember { mutableStateOf(cur?.str("q").orEmpty()) }
    var kinds by remember { mutableStateOf(curParams["kinds"].orEmpty()) }
    var subject by remember { mutableStateOf(curParams["subject"].orEmpty()) }
    var chatId by remember { mutableStateOf(curParams["chat_ids"].orEmpty()) }
    var exts by remember { mutableStateOf(curParams["exts"].orEmpty()) }
    var pickChat by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf<JsonObject?>(null) }
    var previewError by remember { mutableStateOf<String?>(null) }
    val subjects by state.subjects.collectAsState()
    val chats by state.chats.collectAsState()
    fun params() = buildJsonObject {
        if (kinds.isNotBlank()) put("kinds", kinds)
        if (subject.isNotBlank()) put("subject", subject)
        if (chatId.isNotBlank()) put("chat_ids", chatId)
        if (exts.isNotBlank()) put("exts", exts.trim())
    }
    LaunchedEffect(q, kinds, subject, chatId, exts) {
        kotlinx.coroutines.delay(350)
        val p = params()
        if (q.isBlank() && p.isEmpty()) { preview = null; previewError = null; return@LaunchedEffect }
        try { preview = state.api.rulesPreview(state.aid.value, q, p); previewError = null } catch (e: Exception) { previewError = e.message }
    }
    TgDialog(if (f != null) "Rule for “${f.name}”" else "New smart folder", { actions.close() }, if (f != null) "Save rule" else "Create", {
        val rules = buildJsonObject { put("mode", mode); put("q", q.trim()); put("params", params()) }
        if (f == null) {
            if (name.isBlank()) { state.message("Give the folder a name.", error = true); return@TgDialog }
            actions.createFolder(name.trim(), parentId, rules) { id -> nav.push(Screen.Browse(View.Drive(id))) }
        } else actions.saveRule(f, rules)
        actions.close()
    }) {
        if (f == null) {
            TgTextField(name, { name = it }, label = "Folder name", placeholder = "e.g. Polity PDFs")
            Spacer(Modifier.height(14.dp))
        }
        ModeCard(mode == "smart", TgIcons.sparkle, "Smart folder",
            "Shows every file that matches. Nothing is moved, so a file can be in many smart folders.") { mode = "smart" }
        Spacer(Modifier.height(8.dp))
        ModeCard(mode == "auto", TgIcons.wand, "Auto-file",
            "Moves matching files that aren't in any folder yet into this folder, now and as new files arrive.") { mode = "auto" }
        Spacer(Modifier.height(14.dp))
        TgTextField(q, { q = it }, label = "Words", placeholder = "Words in the name or caption")
        Text("Same as the search box: polity ext:pdf in:\"Vision IAS\" -draft", style = Tg.type.meta, color = c.ink3,
            modifier = Modifier.padding(top = 4.dp))
        Spacer(Modifier.height(12.dp))
        Text("Type", style = Tg.type.label, color = c.ink2)
        Spacer(Modifier.height(6.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            TYPE_OPTS.forEach { (k, l) -> TgChip(l, selected = kinds == k, onClick = { kinds = k }) }
        }
        if (subjects.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text("Subject", style = Tg.type.label, color = c.ink2)
            Spacer(Modifier.height(6.dp))
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                TgChip("Any subject", selected = subject.isEmpty(), onClick = { subject = "" })
                subjects.forEach { s -> TgChip(listOfNotNull(s.emoji, s.name).joinToString(" "), selected = subject == s.id, onClick = { subject = s.id }) }
            }
        }
        Spacer(Modifier.height(12.dp))
        Text("From chat", style = Tg.type.label, color = c.ink2)
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            TgButton(chats.firstOrNull { it.id.toString() == chatId }?.title ?: if (chatId.isBlank()) "Any chat" else "A chat", { pickChat = true },
                icon = TgIcons.chat, modifier = Modifier.weight(1f, fill = false))
            if (chatId.isNotBlank()) app.tgdrive.ui.components.IconBtn(TgIcons.close, { chatId = "" }, contentDescription = "Any chat")
        }
        Spacer(Modifier.height(12.dp))
        TgTextField(exts, { exts = it }, label = "Extensions", placeholder = "pdf, epub")
        Spacer(Modifier.height(14.dp))
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(c.panel2).padding(12.dp)) {
            val p = preview
            when {
                previewError != null -> Text(previewError!!, style = Tg.type.meta, color = c.danger)
                p == null -> Text("Add words or a filter to see what matches.", style = Tg.type.meta, color = c.ink3)
                else -> Column {
                    Text(buildString {
                        append(Format.plural(p.long("total"), "file")); append(" match")
                        if (mode == "auto") append(", ${Format.num(p.long("unfiled"))} not in a folder yet (those would move here)")
                    }, style = Tg.type.label, color = c.ink)
                    (p["sample"] as? kotlinx.serialization.json.JsonArray)?.take(5)?.forEach { x ->
                        val o = x as? JsonObject ?: return@forEach
                        Text("· ${o.str("name").orEmpty()}", style = Tg.type.meta, color = c.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
        if (f != null && cur != null) {
            Spacer(Modifier.height(10.dp))
            TgButton("Remove rule", { actions.saveRule(f, null); actions.close() }, kind = ButtonKind.Danger, small = true)
        }
    }
    if (pickChat) ChatPickerSheet(state, "Only files from", onDismiss = { pickChat = false }, onPick = { chatId = it.id.toString() })
}

@Composable
private fun ModeCard(on: Boolean, icon: app.tgdrive.ui.theme.TgIcon, title: String, text: String, onClick: () -> Unit) {
    val c = Tg.colors
    Row(
        Modifier.fillMaxWidth().clip(TgShape.card).background(if (on) c.accentSoft else c.panel)
            .border(if (on) 2.dp else 1.dp, if (on) c.accent else c.line, TgShape.card).clickable(onClick = onClick).padding(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        TgIconView(icon, tint = if (on) c.accent else c.ink2, size = 20.dp)
        Spacer(Modifier.width(12.dp))
        Column {
            Text(title, style = Tg.type.bodyStrong, color = c.ink)
            Text(text, style = Tg.type.meta, color = c.ink2)
        }
    }
}

// ---------------------------------------------------------------------- new, account
@Composable
private fun NewMenu(actions: Actions, state: AppState, nav: Navigator, upload: () -> Unit, uploadFolder: () -> Unit) {
    val close = { actions.close() }
    val here = ((nav.top.screen as? Screen.Browse)?.view as? View.Drive)?.folderId
        ?.let { id -> state.folders.value.folders.firstOrNull { it.id == id } }?.takeIf { !it.smart }
    TgSheet(close) {
        SheetTitle("New", "In ${here?.name ?: state.folders.value.driveTitle.ifBlank { "My Drive" }}")
        SheetAction(TgIcons.upload, "Upload files", { close(); upload() }, subtitle = "From this phone, any size")
        SheetAction(TgIcons.uploadFolder, "Upload a folder", { close(); uploadFolder() }, subtitle = "With everything inside it")
        Divider(Modifier.padding(vertical = 4.dp))
        SheetAction(TgIcons.folderPlus, "New folder", { actions.open(Overlay.FolderEdit(null, here?.id)) })
        SheetAction(TgIcons.folderSmart, "New smart folder", { actions.open(Overlay.FolderEdit(null, here?.id, smart = true)) },
            subtitle = "Shows files that match a search, wherever they are")
    }
}

@Composable
private fun AccountMenu(actions: Actions, state: AppState, nav: Navigator) {
    val c = Tg.colors
    val status by state.status.collectAsState()
    val aid by state.aid.collectAsState()
    val scope = rememberCoroutineScope()
    val close = { actions.close() }
    val accounts = status?.accounts.orEmpty()
    val me = accounts.firstOrNull { it.id == aid }
    TgSheet(close) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Avatar(me?.name, 64.dp)
            Spacer(Modifier.height(10.dp))
            Text(me?.name ?: "TG Drive", style = Tg.type.heading, color = c.ink)
            Text(listOfNotNull(me?.username?.let { "@$it" } ?: me?.phone, if (state.demo) "Sample data" else null).joinToString(" · "),
                style = Tg.type.meta, color = c.ink3)
        }
        Divider(Modifier.padding(vertical = 8.dp))
        accounts.filter { it.id != aid }.forEach { a ->
            SheetAction(TgIcons.user, a.name ?: "Account", { close(); state.selectAccount(a.id) },
                subtitle = listOfNotNull(a.username?.let { "@$it" } ?: a.phone, "Switch to this account").joinToString(" · "))
        }
        if (!state.demo) SheetAction(TgIcons.plus, "Add another account", { close(); nav.push(Screen.SignIn(adding = true)) })
        SheetAction(TgIcons.user, "Manage accounts", { close(); nav.navigate(Screen.Accounts) })
        SheetAction(TgIcons.settings, "Settings", { close(); nav.navigate(Screen.Settings()) })
        if (status?.lockSet == true) SheetAction(TgIcons.lock, "Lock TG Drive", {
            close(); scope.launch { runCatching { state.api.lockNow() }; state.onLocked() }
        })
        Divider(Modifier.padding(vertical = 4.dp))
        if (state.demo) SheetAction(TgIcons.telegram, "Use my Telegram account", { close(); scope.launch { state.switchMode(false) } },
            subtitle = "Leaves the sample data")
        else SheetAction(TgIcons.sparkle, "Try with sample data", { close(); scope.launch { state.switchMode(true) } },
            subtitle = "Explore TG Drive without touching your account")
    }
}

// ---------------------------------------------------------------------- list: sort, filters, view, more
@Composable
private fun SortSheet(model: BrowseModel, close: () -> Unit) {
    val cur = if (model.effectiveSort == "relevance" && model.isTextSearch) "relevance:desc" else "${model.sort}:${model.order}"
    TgSheet(close) {
        SheetTitle("Sort by")
        Column(Modifier.padding(horizontal = 16.dp)) {
            SORTS.filter { it.first != "relevance:desc" || model.isTextSearch }.forEach { (k, l) ->
                ChoiceRow(l, cur == k, { model.applySort(k); close() })
            }
        }
    }
}

private val DATE_PRESETS = listOf("" to "Any time", "today" to "Today", "7d" to "Last 7 days", "30d" to "Last 30 days",
    "3m" to "Last 3 months", "1y" to "Last year")
private val SIZE_PRESETS = listOf("" to "Any size", "0:1mb" to "Under 1 MB", "1mb:10mb" to "1–10 MB", "10mb:100mb" to "10–100 MB",
    "100mb:1g" to "100 MB – 1 GB", "1g:" to "Over 1 GB")
private val SOURCES = listOf("channel" to "Channels", "group" to "Groups", "user" to "Private chats", "bot" to "Bots", "saved" to "Saved Messages")

/** Every filter of the desktop's filter chips and "More filters" panel, as one sheet. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FiltersSheet(model: BrowseModel, state: AppState, close: () -> Unit) {
    val c = Tg.colors
    val chats by state.chats.collectAsState()
    val p = remember { mutableStateOf(model.adv) }
    var pickChat by remember { mutableStateOf(false) }
    fun set(k: String, v: String?) { p.value = if (v.isNullOrBlank()) p.value - k else p.value + (k to v) }
    fun toggle(k: String) = set(k, if (p.value[k] == "1") null else "1")
    val a = p.value
    TgSheet(close) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Filters", style = Tg.type.heading, color = c.ink, modifier = Modifier.weight(1f))
            if (a.isNotEmpty()) TgButton("Clear all", { p.value = emptyMap() }, kind = ButtonKind.Ghost, small = true)
        }
        Divider()
        Column(Modifier.heightIn(max = 560.dp).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 12.dp)) {
            FilterGroup("Date sent") {
                DATE_PRESETS.forEach { (k, l) ->
                    TgChip(l, selected = (a["date_from"] ?: "") == k, onClick = { set("date_from", k); set("date_to", null) })
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TgTextField(a["date_from"].takeIf { it?.contains('-') == true }.orEmpty(), { set("date_from", it) }, Modifier.weight(1f),
                    placeholder = "From 2024-01-31")
                TgTextField(a["date_to"].orEmpty(), { set("date_to", it) }, Modifier.weight(1f), placeholder = "To 2024-12-31")
            }
            FilterGroup("Size") {
                val cur = if (a["size_min"] == null && a["size_max"] == null) "" else "${a["size_min"] ?: "0"}:${a["size_max"] ?: ""}"
                SIZE_PRESETS.forEach { (k, l) ->
                    TgChip(l, selected = cur == k, onClick = {
                        val (lo, hi) = if (k.isEmpty()) "" to "" else k.split(":").let { it[0] to it[1] }
                        set("size_min", lo.takeIf { it != "0" }); set("size_max", hi)
                    })
                }
            }
            if (model.view !is View.Chat) {
                FilterGroup("Source") {
                    TgChip("Anywhere", selected = a["chat_kinds"] == null, onClick = { set("chat_kinds", null) })
                    SOURCES.forEach { (k, l) -> TgChip(l, selected = a["chat_kinds"] == k, onClick = { set("chat_kinds", k) }) }
                }
                FilterGroup("Chat") {
                    val name = a["chat_ids"]?.let { id -> chats.firstOrNull { it.id.toString() == id }?.title ?: "A chat" }
                    TgChip(name ?: "Any chat", icon = TgIcons.chat, selected = name != null, onClick = { pickChat = true },
                        onClose = if (name != null) ({ set("chat_ids", null) }) else null)
                }
            }
            FilterGroup("Show only") {
                TgChip("Starred", icon = TgIcons.star, selected = a["starred"] == "1", onClick = { toggle("starred") })
                TgChip("Has caption", selected = a["has_caption"] == "1", onClick = { toggle("has_caption") })
                TgChip("Forwarded", selected = a["forwarded"] == "1", onClick = { toggle("forwarded") })
                TgChip("Sent by me", selected = a["mine"] == "1", onClick = { toggle("mine") })
                TgChip("Has a note", selected = a["has_note"] == "1", onClick = { toggle("has_note") })
                TgChip("Not watched", selected = a["watched"] == "0", onClick = { set("watched", if (a["watched"] == "0") null else "0") })
            }
            FilterGroup("Folder") {
                listOf("" to "Anywhere", "1" to "In a folder", "0" to "Not in a folder").forEach { (k, l) ->
                    TgChip(l, selected = (a["filed"] ?: "") == k, onClick = { set("filed", k) })
                }
            }
            if (model.isTextSearch) FilterGroup("Matching") {
                TgChip("Smart", selected = a["match"] != "exact", onClick = { set("match", null) })
                TgChip("Exact words only", selected = a["match"] == "exact", onClick = { set("match", "exact") })
            }
            Spacer(Modifier.height(14.dp))
            TgTextField(a["exts"].orEmpty(), { set("exts", it) }, label = "File extensions", placeholder = "pdf, zip, mp4")
            Spacer(Modifier.height(12.dp))
            TgTextField(a["sender"].orEmpty(), { set("sender", it) }, label = "Sent by", placeholder = "Name of the sender")
            Spacer(Modifier.height(12.dp))
            TgTextField(a["tag"].orEmpty(), { set("tag", it.trimStart('#')) }, label = "Tag", placeholder = "Any tag")
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TgTextField(a["dur_min"].orEmpty(), { set("dur_min", it) }, Modifier.weight(1f), label = "Longer than", placeholder = "5m")
                TgTextField(a["dur_max"].orEmpty(), { set("dur_max", it) }, Modifier.weight(1f), label = "Shorter than", placeholder = "1h")
            }
        }
        Divider()
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End)) {
            TgButton("Cancel", close, kind = ButtonKind.Ghost)
            TgButton("Show files", { model.setFilters(p.value); close() }, kind = ButtonKind.Primary)
        }
    }
    if (pickChat) ChatPickerSheet(state, "Only files from", onDismiss = { pickChat = false }, onPick = { set("chat_ids", it.id.toString()) })
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FilterGroup(title: String, content: @Composable () -> Unit) {
    Text(title.uppercase(), style = Tg.type.overline, color = Tg.colors.ink3, modifier = Modifier.padding(top = 12.dp, bottom = 8.dp))
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) { content() }
    Spacer(Modifier.height(4.dp))
}

@Composable
private fun ViewSheet(model: BrowseModel, state: AppState, close: () -> Unit) {
    val c = Tg.colors
    val settings by state.settings.collectAsState()
    val local by state.local.collectAsState()
    val list = settings.str("view") == "list"
    TgSheet(close) {
        SheetTitle("View")
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Text("FILES", style = Tg.type.overline, color = c.ink3, modifier = Modifier.padding(top = 4.dp, start = 4.dp))
            Row(Modifier.padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ViewChoice(TgIcons.grid, "Grid", !list, Modifier.weight(1f)) { state.setSetting("view", "grid") }
                ViewChoice(TgIcons.list, "List", list, Modifier.weight(1f)) { state.setSetting("view", "list") }
            }
            if (!list) {
                Row(Modifier.padding(bottom = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("s" to "Small", "m" to "Medium", "l" to "Large").forEach { (k, l) ->
                        TgChip(l, selected = (settings.str("grid_size") ?: "m") == k, onClick = { state.setSetting("grid_size", k) })
                    }
                }
            }
            SwitchRow("Group by date", "Today, Yesterday, months", settings.str("group_by_date") == "true") { state.setSetting("group_by_date", it) }
            SwitchRow("Albums as stacks", "Files sent together as one card", settings.str("stack_albums") != "false") { state.setSetting("stack_albums", it) }
            SwitchRow("One card per file", "Fold copies of the same file", settings.str("hide_duplicates") != "false") {
                state.setSetting("hide_duplicates", it); model.reload()
            }
            if (model.view is View.Drive) {
                Divider(Modifier.padding(vertical = 8.dp))
                Text("FOLDERS", style = Tg.type.overline, color = c.ink3, modifier = Modifier.padding(start = 4.dp))
                Row(Modifier.padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val fs = settings.str("folder_style") ?: "tiles"
                    ViewChoice(TgIcons.tiles, "Tiles", fs == "tiles", Modifier.weight(1f)) { state.setSetting("folder_style", "tiles") }
                    ViewChoice(TgIcons.cards, "Cards", fs == "cards", Modifier.weight(1f)) { state.setSetting("folder_style", "cards") }
                    ViewChoice(TgIcons.list, "List", fs == "list", Modifier.weight(1f)) { state.setSetting("folder_style", "list") }
                }
                Text("Sort folders", style = Tg.type.label, color = c.ink2, modifier = Modifier.padding(start = 4.dp, top = 4.dp))
                listOf("name" to "Name", "newest" to "Recently changed", "files" to "Most files", "size" to "Largest").forEach { (k, l) ->
                    ChoiceRow(l, (local["folder_sort"] ?: "name") == k, { state.setPref("folder_sort", k) })
                }
            }
        }
    }
}

@Composable
private fun ViewChoice(icon: app.tgdrive.ui.theme.TgIcon, label: String, on: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val c = Tg.colors
    Column(
        modifier.clip(TgShape.card).background(if (on) c.accentSoft else c.panel2).border(if (on) 2.dp else 1.dp, if (on) c.accent else c.line, TgShape.card)
            .clickable(onClick = onClick).padding(vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        TgIconView(icon, tint = if (on) c.accent else c.ink2, size = 22.dp)
        Spacer(Modifier.height(6.dp))
        Text(label, style = Tg.type.label, color = if (on) c.accent else c.ink)
    }
}

@Composable
fun SwitchRow(title: String, subtitle: String?, checked: Boolean, onChange: (Boolean) -> Unit) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { onChange(!checked) }.padding(horizontal = 4.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = Tg.type.bodyStrong, color = c.ink)
            if (subtitle != null) Text(subtitle, style = Tg.type.meta, color = c.ink3)
        }
        Spacer(Modifier.width(12.dp))
        TgSwitch(checked, onChange)
    }
}

@Composable
private fun ListMenu(model: BrowseModel, actions: Actions, state: AppState, nav: Navigator) {
    val ctx = LocalContext.current
    val close = { actions.close() }
    val v = model.view
    TgSheet(close) {
        SheetTitle(app.tgdrive.ui.browse.viewTitle(state, v))
        Column(Modifier.verticalScroll(rememberScrollState())) {
            if (model.items.isNotEmpty()) SheetAction(TgIcons.check, "Select all", { model.selectAll(); close() })
            SheetAction(TgIcons.refresh, "Refresh", { model.reload(); close() })
            val audio = model.items.filter { it.kind == "audio" || it.kind == "voice" }
            if (audio.size > 1) SheetAction(TgIcons.play, "Play all ${Format.num(audio.size)} audio files", {
                close(); PlayerController.get(ctx).playList(state, audio, audio.first())
            })
            val pics = model.items.filter { it.kind == "photo" }
            if (pics.size > 1) SheetAction(TgIcons.slides, "Slideshow (${Format.plural(pics.size, "picture")})", {
                close(); nav.push(Screen.Viewer(pics, 0))
            })
            if (model.isTextSearch || v is View.Search) SheetAction(TgIcons.bookmark, "Save this search", {
                val params = model.params(withKind = true).orEmpty() - setOf("sort", "order", "copies", "q", "limit")
                actions.open(Overlay.SaveSearch((v as? View.Search)?.q ?: model.viewParams()?.get("q").orEmpty(), params))
            })
            when (v) {
                is View.Drive -> v.folderId?.let { id -> state.folders.value.folders.firstOrNull { it.id == id } }?.let { f ->
                    SheetAction(TgIcons.folder, "Folder options…", { actions.open(Overlay.FolderMenu(f)) })
                }
                is View.Chat -> SheetAction(TgIcons.chat, "Chat options…", { actions.open(Overlay.ChatMenu(v.chatId)) })
                is View.Saved -> SheetAction(TgIcons.trash, "Delete this saved search", { actions.deleteSaved(v.savedId); close(); nav.navigate(Screen.Browse(View.Drive(null))) },
                    danger = true)
                else -> {}
            }
            if (v is View.Drive || v is View.Chat || v is View.TgFolder) {
                SheetAction(TgIcons.search, "Search in here", {
                    close()
                    val p = model.viewParams().orEmpty().filterKeys { it != "filed" }
                    nav.push(Screen.SearchInput(scope = scopeOf(state, v, model)))
                })
            }
        }
    }
}

/** "Search in here": the place a list shows, as a search scope. */
fun scopeOf(state: AppState, v: View, model: BrowseModel?): SearchScope? = when {
    v is View.Drive && v.folderId != null -> SearchScope(app.tgdrive.ui.browse.viewTitle(state, v), mapOf("folder_id" to v.folderId, "folder_tree" to "1"))
    v is View.Chat || v is View.TgFolder || v is View.TagView || v is View.SubjectView || v == View.Starred ->
        SearchScope(app.tgdrive.ui.browse.viewTitle(state, v), model?.viewParams().orEmpty())
    else -> null
}

@Composable
private fun ChatMenu(chatId: Long, actions: Actions, state: AppState, nav: Navigator) {
    val chats by state.chats.collectAsState()
    val ch = chats.firstOrNull { it.id == chatId }
    val close = { actions.close() }
    TgSheet(close) {
        SheetTitle(ch?.title ?: "Chat", ch?.let { listOfNotNull(Format.CHAT_KIND_NAME[it.kind], Format.plural(it.fileCount, "file"), Format.size(it.totalBytes)).joinToString(" · ") },
            leading = { Avatar(ch?.title, 40.dp) })
        SheetAction(TgIcons.pin, if (ch?.pinned == 1) "Unpin from the sidebar" else "Pin to the sidebar", { actions.pinChat(chatId, ch?.pinned != 1); close() })
        SheetAction(TgIcons.refresh, "Re-index this chat", { actions.rescanChat(chatId); close() }, subtitle = "Reads its history again from the start")
        if (ch?.username != null) SheetAction(TgIcons.telegram, "Open in Telegram", { close(); actions.openUrl("https://t.me/${ch.username}") })
        Divider(Modifier.padding(vertical = 4.dp))
        SheetAction(TgIcons.close, if (ch?.excluded == 1) "Include in TG Drive again" else "Exclude from TG Drive",
            { actions.excludeChat(chatId, ch?.excluded != 1); close(); if (ch?.excluded != 1) nav.pop() },
            subtitle = if (ch?.excluded == 1) null else "Its files leave the index; nothing changes in Telegram", danger = ch?.excluded != 1)
    }
}
