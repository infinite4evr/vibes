package app.tgdrive.ui.files

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import app.tgdrive.data.FileItem
import app.tgdrive.data.Folder
import app.tgdrive.ui.components.shimmer
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.TgShape
import app.tgdrive.ui.theme.mix
import app.tgdrive.util.Format

/** Search words highlighted in a name (desktop highlight(): <mark> in the folder colour). */
@Composable
fun highlighted(text: String, words: List<String>): AnnotatedString {
    val c = Tg.colors
    val ws = words.filter { it.length > 1 }
    if (ws.isEmpty()) return AnnotatedString(text)
    val lower = text.lowercase()
    val marks = BooleanArray(text.length)
    for (w in ws) {
        var i = lower.indexOf(w.lowercase())
        while (i >= 0) {
            for (k in i until minOf(text.length, i + w.length)) marks[k] = true
            i = lower.indexOf(w.lowercase(), i + 1)
        }
    }
    val bg = mix(c.folder, Color.Transparent, .38f)
    return buildAnnotatedString {
        var i = 0
        while (i < text.length) {
            val on = marks[i]
            var j = i
            while (j < text.length && marks[j] == on) j++
            if (on) withStyle(SpanStyle(background = bg)) { append(text.substring(i, j)) } else append(text.substring(i, j))
            i = j
        }
    }
}

/** A file in the grid (desktop .card): picture, name on two lines, where it's from, size and date. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FileCard(
    f: FileItem,
    src: ThumbSource,
    selected: Boolean,
    selecting: Boolean,
    words: List<String>,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onMore: () -> Unit,
    modifier: Modifier = Modifier,
    stack: Int = 0,
    compact: Boolean = false,
) {
    val c = Tg.colors
    val haptics = LocalHapticFeedback.current
    Box(modifier) {
        if (stack > 1) {
            // Album: two sheets peeking out behind the card.
            Box(Modifier.matchParentSize().padding(horizontal = 10.dp).offset(y = (-6).dp).clip(TgShape.card)
                .background(c.panel2).border(1.dp, c.line2, TgShape.card))
            Box(Modifier.matchParentSize().padding(horizontal = 5.dp).offset(y = (-3).dp).clip(TgShape.card)
                .background(c.panel).border(1.dp, c.line2, TgShape.card))
        }
        Column(
            Modifier
                .fillMaxWidth()
                .clip(TgShape.card)
                .background(if (selected) c.accentSoft else c.panel)
                .border(if (selected) 2.dp else 1.dp, if (selected) c.accent else c.line, TgShape.card)
                .combinedClickable(onClick = onClick, onLongClick = { haptics.performHapticFeedback(HapticFeedbackType.LongPress); onLongClick() }),
        ) {
            Box(Modifier.fillMaxWidth().aspectRatio(4f / 3f)) {
                FileThumb(f, src, Modifier.fillMaxSize(), iconWidth = if (compact) 44.dp else 62.dp)
                if (stack > 1) {
                    Text("$stack", style = Tg.type.caption, color = Color.White,
                        modifier = Modifier.align(Alignment.TopEnd).padding(7.dp).clip(RoundedCornerShape(5.dp))
                            .background(Color(0xB80C1018)).padding(horizontal = 6.dp, vertical = 1.dp))
                }
                if (selecting) SelectMark(selected, Modifier.align(Alignment.TopEnd).padding(7.dp))
                else MoreButton(onMore, Modifier.align(Alignment.TopEnd).padding(4.dp))
                if (f.match != null && f.match != "exact") MatchBadge(f.match, Modifier.align(Alignment.TopStart).padding(start = if (f.starred) 30.dp else 7.dp, top = 7.dp))
            }
            if (!compact) {
                Column(Modifier.fillMaxWidth().padding(start = 10.dp, end = 10.dp, top = 8.dp, bottom = 9.dp)) {
                    Text(highlighted(f.displayName, words), style = Tg.type.cardName, color = c.ink, maxLines = 2,
                        overflow = TextOverflow.Ellipsis, minLines = 2)
                    Spacer(Modifier.height(2.dp))
                    Text(sourceLine(f), style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(metaLine(f), style = Tg.type.meta, color = c.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false))
                        if (f.tags.isNotEmpty()) {
                            Spacer(Modifier.width(8.dp))
                            TgIconView(TgIcons.tag, tint = c.ink3, size = 12.dp)
                            Text("${f.tags.size}", style = Tg.type.caption, color = c.ink3, modifier = Modifier.padding(start = 2.dp))
                        }
                        if (f.note?.toString() == "true") {
                            Spacer(Modifier.width(6.dp))
                            TgIconView(TgIcons.note, tint = c.ink3, size = 12.dp)
                        }
                    }
                }
            }
        }
    }
}

fun sourceLine(f: FileItem): String {
    val who = f.chatTitle ?: Format.CHAT_KIND_NAME[f.chatKind] ?: ""
    return if (f.isForward && f.fwdFrom != null) "$who · from ${f.fwdFrom}" else who
}

fun metaLine(f: FileItem): String = buildList {
    add(Format.size(f.size))
    if (f.date != null) add(Format.date(f.date))
}.joinToString("  ·  ")

@Composable
fun SelectMark(on: Boolean, modifier: Modifier = Modifier) {
    val c = Tg.colors
    Box(modifier.size(24.dp).clip(CircleShape).background(if (on) c.accent else Color(0xCCFFFFFF))
        .border(if (on) 0.dp else 1.5.dp, if (on) Color.Transparent else Color(0x99334455), CircleShape),
        contentAlignment = Alignment.Center) {
        if (on) TgIconView(TgIcons.check, tint = Color.White, size = 15.dp, stroke = 2.6f)
    }
}

@Composable
private fun MoreButton(onClick: () -> Unit, modifier: Modifier = Modifier) {
    Box(modifier.size(34.dp).clip(RoundedCornerShape(9.dp)).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Box(Modifier.size(28.dp).clip(RoundedCornerShape(8.dp)).background(Color(0xE6FFFFFF)), contentAlignment = Alignment.Center) {
            TgIconView(TgIcons.more, tint = Color(0xFF333344), size = 17.dp, contentDescription = "File options")
        }
    }
}

/** A file in the list view (desktop .row): small picture, name on one line, details under it. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FileRow(
    f: FileItem,
    src: ThumbSource,
    selected: Boolean,
    selecting: Boolean,
    words: List<String>,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onMore: () -> Unit,
    compact: Boolean = false,
) {
    val c = Tg.colors
    val haptics = LocalHapticFeedback.current
    Row(
        Modifier
            .fillMaxWidth()
            .background(if (selected) c.accentSoft else Color.Transparent)
            .combinedClickable(onClick = onClick, onLongClick = { haptics.performHapticFeedback(HapticFeedbackType.LongPress); onLongClick() })
            .heightIn(min = if (compact) 52.dp else 64.dp)
            .padding(start = 16.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box {
            FileThumb(f, src, Modifier.size(if (compact) 36.dp else 44.dp).clip(RoundedCornerShape(8.dp)), showBadges = false, iconWidth = 26.dp)
            if (selecting) SelectMark(selected, Modifier.align(Alignment.BottomEnd).padding(0.dp).size(18.dp))
            if (f.starred && !selecting) Box(Modifier.align(Alignment.TopStart).padding(2.dp)) {
                TgIconView(TgIcons.star, tint = c.star, size = 12.dp, filled = true)
            }
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f).padding(vertical = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(highlighted(f.displayName, words), style = Tg.type.bodyStrong, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false))
                if (f.match != null && f.match != "exact") { Spacer(Modifier.width(6.dp)); MatchBadge(f.match) }
            }
            val sub = buildList {
                add(Format.size(f.size))
                f.duration?.takeIf { it > 0 }?.let { add(Format.duration(it)) }
                if (f.date != null) add(Format.date(f.date))
                sourceLine(f).takeIf { it.isNotEmpty() }?.let { add(it) }
            }.joinToString("  ·  ")
            Text(sub, style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val p = f.progress
            if (p != null && !f.watched) {
                Box(Modifier.padding(top = 5.dp).fillMaxWidth(.6f).height(3.dp).clip(RoundedCornerShape(2.dp)).background(c.line2)) {
                    Box(Modifier.fillMaxWidth(p).height(3.dp).background(c.danger))
                }
            }
        }
        Box(Modifier.size(44.dp).clip(RoundedCornerShape(10.dp)).clickable(onClick = onMore), contentAlignment = Alignment.Center) {
            TgIconView(TgIcons.more, tint = c.ink3, size = 20.dp)
        }
    }
}

/** A folder as the desktop's tile: badge, name, what's in it, and a menu. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FolderTile(folder: Folder, children: Int, onClick: () -> Unit, onMore: () -> Unit, modifier: Modifier = Modifier) {
    val c = Tg.colors
    Row(
        modifier
            .fillMaxWidth()
            .clip(TgShape.card)
            .background(c.panel)
            .border(1.dp, c.line, TgShape.card)
            .combinedClickable(onClick = onClick, onLongClick = onMore)
            .padding(start = 12.dp, top = 10.dp, bottom = 10.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FolderBadge(folder, 40.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(folder.name, style = Tg.type.bodyStrong.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = c.ink,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(folderSubtitle(folder, children), style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).clickable(onClick = onMore), contentAlignment = Alignment.Center) {
            TgIconView(TgIcons.more, tint = c.ink3, size = 20.dp)
        }
    }
}

/** A folder as a card with up to four recent pictures from it (desktop folder_style "cards"). */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FolderCard(folder: Folder, children: Int, covers: List<String>, onClick: () -> Unit, onMore: () -> Unit, modifier: Modifier = Modifier) {
    val c = Tg.colors
    val fc = c.folderColor(folder.color)
    Column(modifier.fillMaxWidth().clip(TgShape.card).background(c.panel).border(1.dp, c.line, TgShape.card)
        .combinedClickable(onClick = onClick, onLongClick = onMore)) {
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).background(mix(fc, c.panel, .14f))) {
            if (covers.isEmpty()) {
                Box(Modifier.align(Alignment.Center)) { FolderBadge(folder, 52.dp) }
            } else {
                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    covers.take(if (covers.size >= 3) 3 else covers.size).forEach { url ->
                        coil3.compose.AsyncImage(url, null, Modifier.weight(1f).fillMaxSize(),
                            contentScale = androidx.compose.ui.layout.ContentScale.Crop)
                    }
                }
                Box(Modifier.align(Alignment.BottomStart).padding(8.dp)) { FolderBadge(folder, 30.dp) }
            }
        }
        Row(Modifier.padding(start = 12.dp, top = 8.dp, bottom = 8.dp, end = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(folder.name, style = Tg.type.cardName, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(folderSubtitle(folder, children), style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Box(Modifier.size(36.dp).clip(RoundedCornerShape(9.dp)).clickable(onClick = onMore), contentAlignment = Alignment.Center) {
                TgIconView(TgIcons.more, tint = c.ink3, size = 18.dp)
            }
        }
    }
}

/** Placeholder card while a page loads (desktop .card.skel). */
@Composable
fun SkeletonCard(modifier: Modifier = Modifier) {
    val c = Tg.colors
    Column(modifier.fillMaxWidth().clip(TgShape.card).background(c.panel).border(1.dp, c.line2, TgShape.card)) {
        Box(Modifier.fillMaxWidth().aspectRatio(4f / 3f).shimmer(RoundedCornerShape(0.dp)))
        Column(Modifier.padding(10.dp)) {
            Box(Modifier.fillMaxWidth().height(11.dp).shimmer())
            Spacer(Modifier.height(8.dp))
            Box(Modifier.fillMaxWidth(.6f).height(11.dp).shimmer())
        }
    }
}
