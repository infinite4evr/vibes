package app.tgdrive.ui.actions

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.Chat
import app.tgdrive.data.Folder
import app.tgdrive.ui.components.Avatar
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.Divider
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgDialog
import app.tgdrive.ui.components.TgSheet
import app.tgdrive.ui.components.TgTextField
import app.tgdrive.ui.files.FolderBadge
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.TgShape
import app.tgdrive.util.Format
import kotlinx.coroutines.launch

/**
 * A one-field dialog (the desktop's promptDialog): rename, new folder, note …. With [selectStem] the
 * name is selected without its extension, so typing replaces just the name.
 */
@Composable
fun PromptDialog(
    title: String,
    label: String?,
    initial: String,
    confirm: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
    help: String? = null,
    placeholder: String = "",
    multiline: Boolean = false,
    allowEmpty: Boolean = false,
    selectStem: Boolean = false,
    max: Int = 255,
) {
    val stemEnd = if (selectStem) initial.lastIndexOf('.').takeIf { it > 0 } ?: initial.length else initial.length
    var value by remember { mutableStateOf(TextFieldValue(initial, TextRange(0, stemEnd))) }
    val focus = remember { FocusRequester() }
    val ok = allowEmpty || value.text.isNotBlank()
    TgDialog(title, onDismiss, confirm, { if (ok) { onConfirm(value.text.trim()); onDismiss() } }, confirmEnabled = ok) {
        if (label != null) Text(label, style = Tg.type.label, color = Tg.colors.ink2, modifier = Modifier.padding(bottom = 6.dp))
        PlainField(value, { if (it.text.length <= max) value = it }, Modifier.focusRequester(focus), placeholder, multiline,
            onDone = { if (ok && !multiline) { onConfirm(value.text.trim()); onDismiss() } })
        if (help != null) Text(help, style = Tg.type.meta, color = Tg.colors.ink3, modifier = Modifier.padding(top = 10.dp))
    }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
}

/** A text field that keeps its selection (so a rename starts with the name selected). */
@Composable
private fun PlainField(value: TextFieldValue, onChange: (TextFieldValue) -> Unit, modifier: Modifier, placeholder: String,
                       multiline: Boolean, onDone: () -> Unit) {
    val c = Tg.colors
    androidx.compose.foundation.text.BasicTextField(
        value = value, onValueChange = onChange, singleLine = !multiline, minLines = if (multiline) 4 else 1,
        textStyle = Tg.type.body.copy(color = c.ink),
        cursorBrush = androidx.compose.ui.graphics.SolidColor(c.accent),
        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
            imeAction = if (multiline) androidx.compose.ui.text.input.ImeAction.Default else androidx.compose.ui.text.input.ImeAction.Done),
        keyboardActions = androidx.compose.foundation.text.KeyboardActions(onDone = { onDone() }),
        modifier = modifier.fillMaxWidth(),
        decorationBox = { inner ->
            Box(Modifier.fillMaxWidth().heightIn(min = 46.dp).clip(TgShape.control).background(c.panel)
                .border(2.dp, c.accent, TgShape.control).padding(horizontal = 12.dp, vertical = 12.dp),
                contentAlignment = Alignment.CenterStart) {
                if (value.text.isEmpty() && placeholder.isNotEmpty()) Text(placeholder, style = Tg.type.body, color = c.ink3)
                inner()
            }
        },
    )
}

/**
 * Choose a folder (desktop folderPicker): the folder tree under My Drive, with the current place
 * marked and a way to make a new folder on the spot. Smart folders can't hold files, so they're left out.
 */
@Composable
fun FolderPickerSheet(
    state: AppState,
    title: String,
    okLabel: String,
    current: String?,
    onDismiss: () -> Unit,
    onPick: (Folder?) -> Unit,
    exclude: Set<String> = emptySet(),
) {
    val c = Tg.colors
    val folders by state.folders.collectAsState()
    val scope = rememberCoroutineScope()
    var chosen by remember { mutableStateOf(current) }
    var creating by remember { mutableStateOf(false) }
    val list = folders.folders.filter { !it.smart && it.id !in exclude }
    val byParent = list.groupBy { it.parentId }
    val open = remember { mutableStateListOf<String>().apply {
        // Open the path to the current folder.
        var id = current
        val byId = list.associateBy { it.id }
        while (id != null) { byId[id]?.parentId?.let { add(it) }; id = byId[id]?.parentId }
    } }

    fun flatten(parent: String?, depth: Int, out: MutableList<Pair<Folder, Int>>) {
        for (f in byParent[parent].orEmpty().sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.name })) {
            out += f to depth
            if (f.id in open) flatten(f.id, depth + 1, out)
        }
    }
    val rows = remember(list, open.toList()) { ArrayList<Pair<Folder, Int>>().also { flatten(null, 0, it) } }

    TgSheet(onDismiss) {
        Text(title, style = Tg.type.heading, color = c.ink, modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 10.dp))
        Divider()
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 440.dp)) {
            item(key = "root") {
                PickRow(null, 0, chosen == null, hasChildren = false, isOpen = false, onToggle = {}, onClick = { chosen = null },
                    name = folders.driveTitle.ifBlank { "My Drive" })
            }
            items(rows, key = { it.first.id }) { (f, depth) ->
                PickRow(f, depth + 1, chosen == f.id, hasChildren = byParent[f.id].orEmpty().isNotEmpty(), isOpen = f.id in open,
                    onToggle = { if (f.id in open) open.remove(f.id) else open.add(f.id) }, onClick = { chosen = f.id }, name = f.name)
            }
        }
        Divider()
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            TgButton("New folder", { creating = true }, kind = ButtonKind.Ghost, icon = TgIcons.folderPlus)
            Spacer(Modifier.weight(1f))
            TgButton(okLabel, { onPick(chosen?.let { id -> list.firstOrNull { it.id == id } }); onDismiss() }, kind = ButtonKind.Primary,
                enabled = chosen != current || current == null)
        }
    }
    if (creating) {
        val parentName = chosen?.let { id -> list.firstOrNull { it.id == id }?.name }
        PromptDialog(if (parentName != null) "New folder in “$parentName”" else "New folder", "Folder name", "", "Create",
            onDismiss = { creating = false }, onConfirm = { name ->
                scope.launch {
                    try {
                        val f = state.api.createFolder(state.aid.value, name, chosen)
                        state.loadFolders()
                        chosen?.let { if (it !in open) open.add(it) }
                        chosen = f.id
                    } catch (e: Exception) {
                        state.failed("Couldn't create the folder.", e)
                    }
                }
            })
    }
}

@Composable
private fun PickRow(f: Folder?, depth: Int, selected: Boolean, hasChildren: Boolean, isOpen: Boolean, onToggle: () -> Unit,
                    onClick: () -> Unit, name: String) {
    val c = Tg.colors
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 1.dp).clip(RoundedCornerShape(10.dp))
            .background(if (selected) c.accentSoft else androidx.compose.ui.graphics.Color.Transparent)
            .clickable(onClick = onClick).heightIn(min = 48.dp).padding(start = (8 + depth * 18).dp, end = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(28.dp).clip(RoundedCornerShape(6.dp)).clickable(enabled = hasChildren, onClick = onToggle), contentAlignment = Alignment.Center) {
            if (hasChildren) TgIconView(if (isOpen) TgIcons.chevronDown else TgIcons.chevron, tint = c.ink3, size = 16.dp)
        }
        if (f == null) {
            Box(Modifier.size(30.dp).clip(RoundedCornerShape(8.dp)).background(c.accentSoft), contentAlignment = Alignment.Center) {
                TgIconView(TgIcons.disk, tint = c.accent, size = 17.dp)
            }
        } else FolderBadge(f, 30.dp)
        Spacer(Modifier.width(12.dp))
        Text(name, style = Tg.type.bodyStrong, color = if (selected) c.accent else c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f))
        if (selected) TgIconView(TgIcons.check, tint = c.accent, size = 18.dp)
    }
}

/** Choose a chat (send to, filter by, rule "from chat"): searchable, pinned and busiest first. */
@Composable
fun ChatPickerSheet(state: AppState, title: String, onDismiss: () -> Unit, onPick: (Chat) -> Unit, writableOnly: Boolean = false) {
    val c = Tg.colors
    val chats by state.chats.collectAsState()
    var q by remember { mutableStateOf("") }
    val shown = remember(chats, q) {
        val words = q.lowercase().split(' ').filter { it.isNotBlank() }
        chats.asSequence()
            .filter { ch -> !writableOnly || ch.kind != "channel" || ch.isCreator == 1 || ch.isAdmin == 1 }
            .filter { ch -> val t = "${ch.title.orEmpty()} ${ch.username.orEmpty()}".lowercase(); words.all { it in t } }
            .sortedWith(compareByDescending<Chat> { it.pinned }.thenByDescending { it.fileCount })
            .take(400).toList()
    }
    TgSheet(onDismiss) {
        Text(title, style = Tg.type.heading, color = c.ink, modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 10.dp))
        TgTextField(q, { q = it }, Modifier.padding(horizontal = 16.dp), placeholder = "Search chats", leading = TgIcons.search)
        Spacer(Modifier.padding(top = 8.dp))
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 460.dp)) {
            items(shown, key = { it.id }) { ch ->
                Row(Modifier.fillMaxWidth().clickable { onPick(ch); onDismiss() }.padding(horizontal = 16.dp, vertical = 9.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Avatar(ch.title, 38.dp)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(ch.title ?: "Chat", style = Tg.type.bodyStrong, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(listOfNotNull(Format.CHAT_KIND_NAME[ch.kind], if (ch.fileCount > 0) Format.plural(ch.fileCount, "file") else null)
                            .joinToString(" · "), style = Tg.type.meta, color = c.ink3)
                    }
                    if (ch.pinned == 1) TgIconView(TgIcons.pin, tint = c.ink3, size = 16.dp)
                }
            }
            if (shown.isEmpty()) item {
                Text(if (chats.isEmpty()) "No chats yet." else "No chat matches “$q”.", style = Tg.type.body, color = c.ink3,
                    modifier = Modifier.padding(20.dp))
            }
        }
    }
}

/** Buttons in a wrapping row (dialog footers with more than two choices). */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun ButtonRow(content: @Composable () -> Unit) {
    androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        content()
    }
}
