package app.tgdrive.ui.search

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.data.FileRef
import app.tgdrive.data.Suggestions
import app.tgdrive.ui.components.Avatar
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.files.kindIcon
import app.tgdrive.ui.nav.SearchScope
import app.tgdrive.ui.nav.View
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.util.Format
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Typing a search (desktop search.js): suggestions for what you type — did you mean, filters,
 * files, chats to search inside, folders, saved and recent searches — and a scope chip when the
 * search is limited to a folder or chat.
 */
@Composable
fun SearchInputScreen(
    state: AppState,
    initial: String,
    initialScope: SearchScope?,
    onBack: () -> Unit,
    onSearch: (String, SearchScope?) -> Unit,
    onOpenFile: (FileItem) -> Unit,
    onNavigate: (View) -> Unit,
) {
    val c = Tg.colors
    var text by remember { mutableStateOf(TextFieldValue(initial, TextRange(initial.length))) }
    var scope by remember { mutableStateOf(initialScope) }
    var sug by remember { mutableStateOf<Suggestions?>(null) }
    var refresh by remember { mutableStateOf(0) }
    val focus = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    val co = rememberCoroutineScope()
    val aid = state.aid.value
    val q = text.text.trim()

    LaunchedEffect(q, refresh) {
        delay(if (q.isEmpty()) 0 else 120)
        sug = runCatching { state.api.suggest(aid, q) }.getOrNull() ?: sug
    }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }

    fun submit(query: String = text.text.trim()) {
        keyboard?.hide()
        if (query.isEmpty() && scope == null) return
        onSearch(query, scope)
    }
    fun insertOperator(insert: String) {
        val v = text.text.trimEnd()
        val i = v.lastIndexOf(' ')
        val next = (if (i >= 0) v.substring(0, i + 1) else "") + insert + " "
        text = TextFieldValue(next, TextRange(next.length))
    }

    Column(Modifier.fillMaxSize().background(c.panel)) {
        Row(Modifier.fillMaxWidth().statusBarsPadding().padding(start = 4.dp, end = 8.dp, top = 6.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            IconBtn(TgIcons.chevLeft, onBack, contentDescription = "Back", iconSize = 24.dp)
            Row(
                Modifier.weight(1f).height(46.dp).clip(RoundedCornerShape(23.dp)).background(c.panel2)
                    .border(2.dp, c.accent, RoundedCornerShape(23.dp)).padding(start = 14.dp, end = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TgIconView(TgIcons.search, tint = c.accent, size = 19.dp)
                Spacer(Modifier.width(10.dp))
                Box(Modifier.weight(1f), contentAlignment = Alignment.CenterStart) {
                    if (text.text.isEmpty()) {
                        Text(if (scope != null) "Search in ${scope!!.label}" else "Search everything", style = Tg.type.body, color = c.ink3,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    BasicTextField(
                        text, { text = it }, singleLine = true, textStyle = Tg.type.body.copy(color = c.ink),
                        cursorBrush = SolidColor(c.accent),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                        keyboardActions = KeyboardActions(onSearch = { submit() }),
                        modifier = Modifier.fillMaxWidth().focusRequester(focus),
                    )
                }
                if (text.text.isNotEmpty()) IconBtn(TgIcons.close, { text = TextFieldValue("") }, size = 36.dp, iconSize = 18.dp,
                    contentDescription = "Clear")
            }
        }
        if (scope != null) {
            Row(Modifier.padding(start = 16.dp, bottom = 8.dp)) {
                TgChip("In: ${scope!!.label}", icon = TgIcons.folder, selected = true, onClose = { scope = null })
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))

        val s = sug
        LazyColumn(Modifier.fillMaxSize().imePadding(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp)) {
            if (s != null) {
                val dym = s.didYouMean
                if (dym != null && q.isNotEmpty()) {
                    header("Did you mean")
                    item { SugRow(TgIcons.wand, dym, onClick = { text = TextFieldValue(dym, TextRange(dym.length)); submit(dym) }) }
                }
                if (s.operators.isNotEmpty()) {
                    header("Filter")
                    items(s.operators) { o ->
                        SugRow(TgIcons.filter, o.label ?: o.op, trailingCode = o.insert, onClick = { insertOperator(o.insert ?: o.op) })
                    }
                }
                if (s.files.isNotEmpty()) {
                    header("Files")
                    items(s.files, key = { "f${it.chatId}:${it.msgId}" }) { f ->
                        SugRow(kindIcon(f.kind), f.name, meta = f.chatTitle, tint = c.kind(f.kind), onClick = {
                            keyboard?.hide()
                            co.launch {
                                runCatching { state.api.detail(aid, FileRef(f.chatId, f.msgId)).file }
                                    .onSuccess(onOpenFile).onFailure { state.failed("Opening that file", it) }
                            }
                        })
                    }
                }
                if (s.chats.isNotEmpty()) {
                    header("Search inside a chat")
                    items(s.chats, key = { "c${it.id}" }) { ch ->
                        SugRow(null, ch.title ?: "Chat", meta = Format.plural(ch.fileCount, "file"), leading = { Avatar(ch.title, 30.dp) }, onClick = {
                            val title = ch.title.orEmpty().lowercase()
                            val rest = text.text.trim().split(Regex("\\s+")).filter { it.isNotBlank() && !title.contains(it.lowercase()) }.joinToString(" ")
                            scope = SearchScope(ch.title ?: "Chat", mapOf("chat_ids" to ch.id.toString()))
                            text = TextFieldValue(rest, TextRange(rest.length))
                            if (rest.isNotEmpty()) submit(rest)
                        })
                    }
                }
                if (s.folders.isNotEmpty()) {
                    header("Folders")
                    items(s.folders, key = { "d${it.id}" }) { f ->
                        SugRow(TgIcons.folder, f.name, tint = c.folder, onClick = { keyboard?.hide(); onNavigate(View.Drive(f.id)) })
                    }
                }
                if (s.saved.isNotEmpty()) {
                    header("Saved searches")
                    items(s.saved, key = { "s${it.id}" }) { sv ->
                        SugRow(TgIcons.bookmark, sv.name, meta = sv.q.ifBlank { null }, onClick = { keyboard?.hide(); onNavigate(View.Saved(sv.id)) })
                    }
                }
                if (s.history.isNotEmpty()) {
                    header(if (q.isEmpty()) "Recent searches" else "Earlier searches")
                    items(s.history, key = { "h${it.q}" }) { h ->
                        SugRow(TgIcons.history, h.q, onClick = { text = TextFieldValue(h.q, TextRange(h.q.length)); submit(h.q) },
                            onRemove = { co.launch { runCatching { state.api.clearHistory(aid, h.q) }; refresh++ } })
                    }
                }
            }
            if (q.isEmpty()) item { Tips() }
        }
    }
}

private fun LazyListScope.header(title: String) = item(key = "h:$title") {
    Text(title.uppercase(), style = Tg.type.overline, color = Tg.colors.ink3, modifier = Modifier.padding(start = 20.dp, top = 16.dp, bottom = 4.dp))
}

@Composable
private fun SugRow(
    icon: TgIcon?, text: String, meta: String? = null, trailingCode: String? = null, tint: androidx.compose.ui.graphics.Color? = null,
    leading: (@Composable () -> Unit)? = null, onRemove: (() -> Unit)? = null, onClick: () -> Unit,
) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).heightIn(min = 50.dp).padding(start = 20.dp, end = 8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(30.dp), contentAlignment = Alignment.Center) {
            if (leading != null) leading() else if (icon != null) TgIconView(icon, tint = tint ?: c.ink3, size = 20.dp)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f).padding(vertical = 6.dp)) {
            Text(text, style = Tg.type.body, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (meta != null) Text(meta, style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (trailingCode != null) {
            Text(trailingCode, style = Tg.type.mono, color = c.ink2, modifier = Modifier.padding(horizontal = 8.dp).clip(RoundedCornerShape(5.dp))
                .background(c.panel2).padding(horizontal = 6.dp, vertical = 2.dp))
        }
        if (onRemove != null) IconBtn(TgIcons.close, onRemove, size = 36.dp, iconSize = 16.dp, tint = c.ink3, contentDescription = "Remove from history")
        else Spacer(Modifier.width(8.dp))
    }
}

private val OPERATORS = listOf(
    "type:video,gif" to "photo, video, document, audio, voice, round, gif",
    "ext:pdf" to "file extension, comma-separated for several",
    "in:\"Chat name\"" to "chat title or @username contains the text",
    "from:priya" to "sender or forwarded-from name",
    "size>50mb" to "also size<1g, size>=500k",
    "dur>10m" to "duration of audio and video",
    "after:2024-06" to "also before:, date:2023, after:7d",
    "folder:tax" to "files in a folder whose name contains the text",
    "tag:exam" to "files with a tag; also has:tags, has:note",
    "is:starred" to "also is:forwarded, is:mine, is:filed, is:unfiled",
    "\"exact words\"" to "phrase match",
    "-word" to "leave out matches, e.g. -type:gif",
)

@Composable
private fun Tips() {
    val c = Tg.colors
    Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 18.dp).navigationBarsPadding()) {
        Text("Search understands joined and split words (test series = testseries), typos, abbreviations like PYQ, " +
            "Hindi ↔ Latin script, and related meanings.", style = Tg.type.meta, color = c.ink2)
        Spacer(Modifier.height(14.dp))
        Text("OPERATORS YOU CAN TYPE", style = Tg.type.overline, color = c.ink3)
        Spacer(Modifier.height(6.dp))
        OPERATORS.forEach { (op, help) ->
            Text(buildAnnotatedString {
                withStyle(SpanStyle(fontFamily = FontFamily.Monospace, color = c.ink, background = c.panel2)) { append(op) }
                append("  ")
                append(help)
            }, style = Tg.type.meta, color = c.ink3, modifier = Modifier.padding(vertical = 3.dp))
        }
    }
}
