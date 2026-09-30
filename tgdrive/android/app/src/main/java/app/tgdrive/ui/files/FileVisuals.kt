package app.tgdrive.ui.files

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.tgdrive.data.FileItem
import app.tgdrive.data.Folder
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.extColor
import app.tgdrive.ui.theme.mix
import app.tgdrive.util.Format
import coil3.compose.AsyncImage
import coil3.compose.AsyncImagePainter
import coil3.compose.LocalPlatformContext
import coil3.request.ImageRequest
import coil3.request.crossfade

/** Where thumbnails come from; supplied by the screen that knows the account and the service. */
interface ThumbSource {
    fun thumb(f: FileItem, big: Boolean = false): String?
    fun docThumb(f: FileItem): String?
    fun cover(chatId: Long, msgId: Long): String
}

fun kindIcon(kind: String?): TgIcon = when (kind) {
    "photo" -> TgIcons.photo
    "video" -> TgIcons.video
    "audio" -> TgIcons.audio
    "voice" -> TgIcons.voice
    "round" -> TgIcons.round
    "gif" -> TgIcons.gif
    else -> TgIcons.document
}

/** The desktop's .docicon: a sheet of paper with ruled lines, a folded corner and the extension. */
@Composable
fun DocIcon(ext: String?, modifier: Modifier = Modifier, width: Dp = 64.dp) {
    val ec = extColor(ext)
    val paper = Tg.colors.paper
    val label = (ext ?: "FILE").uppercase().take(5)
    BoxWithConstraints(modifier.width(width).aspectRatio(3f / 3.7f)) {
        val h = maxHeight
        Canvas(Modifier.fillMaxSize()) {
            val w = size.width
            val hh = size.height
            val fold = w * .22f
            val r = 6.dp.toPx()
            val body = Path().apply {
                moveTo(r, 0f); lineTo(w - fold, 0f); lineTo(w, fold); lineTo(w, hh - r)
                quadraticTo(w, hh, w - r, hh); lineTo(r, hh); quadraticTo(0f, hh, 0f, hh - r); lineTo(0f, r); quadraticTo(0f, 0f, r, 0f); close()
            }
            // soft shadow under the sheet
            drawPath(body, Color(0x14141C28), style = androidx.compose.ui.graphics.drawscope.Fill)
            drawContext.canvas.save()
            drawContext.transform.translate(0f, -2.dp.toPx())
            drawPath(body, paper)
            val left = w * .16f
            val right = w * .78f
            var y = hh * .26f
            val lineColor = mix(ec, Color.Transparent, .22f)
            while (y < hh * .56f) {
                drawRect(lineColor, Offset(left, y), Size(right - left, 2.dp.toPx()))
                y += 7.dp.toPx()
            }
            val corner = mix(ec, Color.White, .45f)
            drawPath(Path().apply { moveTo(w - fold, 0f); lineTo(w, fold); lineTo(w - fold, fold); close() }, corner)
            drawPath(Path().apply { moveTo(w, hh * .78f); lineTo(w, hh - r); quadraticTo(w, hh, w - r, hh); lineTo(w * .78f, hh); close() }, corner)
            drawContext.canvas.restore()
        }
        Box(
            Modifier.align(Alignment.BottomCenter).padding(bottom = h * .14f + 2.dp).fillMaxWidth()
                .clip(RoundedCornerShape(bottomStart = 2.dp, bottomEnd = 2.dp)).background(ec).padding(vertical = 3.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(label, color = Color.White, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                fontSize = (width.value * .16f).coerceIn(9f, 16f).sp, letterSpacing = .03.sp, maxLines = 1)
        }
    }
}

/** A voice note or song without cover art: a waveform drawn from the file's id (desktop waveHtml). */
@Composable
fun Waveform(f: FileItem, color: Color, modifier: Modifier = Modifier, bars: Int = 34) {
    val heights = remember(f.key) {
        var h = (app.tgdrive.ui.theme.hue("${f.chatId}:${f.msgId}").toLong() + 7)
        List(bars) { i ->
            h = (h * 1103515245 + 12345) % 2147483648
            val env = Math.sin(i / (bars - 1.0) * Math.PI) * .55 + .45
            maxOf(.12, env * (.35 + (h % 1000) / 1540.0)).toFloat()
        }
    }
    Canvas(modifier) {
        val w = size.width / bars
        heights.forEachIndexed { i, v ->
            val bh = v * size.height * .9f
            drawRoundRect(color, Offset(i * w + w * .18f, (size.height - bh) / 2), Size(w * .64f, bh), CornerRadius(w * .32f))
        }
    }
}

/**
 * The picture area of a card (desktop .thumb): the kind's tint, then the doc icon or glyph, then the
 * tiny inline preview (blurred) and the real thumbnail over it once loaded.
 */
@Composable
fun FileThumb(f: FileItem, src: ThumbSource, modifier: Modifier = Modifier, big: Boolean = false, showBadges: Boolean = true,
              iconWidth: Dp = 64.dp) {
    val c = Tg.colors
    val kc = c.kind(f.kind)
    val bg = if (f.kind == "document") mix(kc, c.panel2, .07f) else mix(kc, c.panel, .12f)
    var loaded by remember(f.key) { mutableStateOf(false) }
    val ctx = LocalPlatformContext.current
    Box(modifier.background(bg), contentAlignment = Alignment.Center) {
        when {
            f.kind == "voice" || (f.kind == "audio" && !f.hasThumb) ->
                Waveform(f, kc.copy(alpha = .75f), Modifier.fillMaxWidth(.8f).fillMaxHeight(.4f))
            f.kind == "document" && !loaded -> DocIcon(f.ext, width = iconWidth)
            !loaded -> TgIconView(kindIcon(f.kind), tint = kc, size = 40.dp, stroke = 1.35f)
        }
        val inline = remember(f.inline) { Format.inlineJpeg(f.inline) }
        if (inline != null && !loaded) {
            AsyncImage(inline, null, Modifier.fillMaxSize().blur(6.dp), contentScale = ContentScale.Crop)
        }
        val url = if (f.hasThumb || f.kind == "photo") src.thumb(f, big) else if (f.isPdf) src.docThumb(f) else null
        if (url != null) {
            AsyncImage(
                model = ImageRequest.Builder(ctx).data(url).crossfade(220).build(),
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
                onState = { st -> if (st is AsyncImagePainter.State.Success) loaded = true },
            )
        }
        if (showBadges) Badges(f)
    }
}

@Composable
private fun BoxScope.Badges(f: FileItem) {
    if (f.starred) {
        Box(Modifier.align(Alignment.TopStart).padding(7.dp)) {
            TgIconView(TgIcons.star, tint = Tg.colors.star, size = 18.dp, filled = true)
        }
    }
    if (f.streamable && f.kind != "gif") {
        Box(Modifier.align(Alignment.BottomStart).padding(7.dp).size(26.dp).clip(CircleShape).background(Color(0x990C1018)),
            contentAlignment = Alignment.Center) {
            TgIconView(TgIcons.play, tint = Color.White, size = 13.dp, filled = true, modifier = Modifier.offset(x = 1.dp))
        }
    }
    val dur = f.duration
    if (dur != null && dur > 0) {
        Text(Format.duration(dur), style = Tg.type.caption.copy(fontWeight = FontWeight.SemiBold), color = Color.White,
            modifier = Modifier.align(Alignment.BottomEnd).padding(7.dp).clip(RoundedCornerShape(5.dp)).background(Color(0xB80C1018))
                .padding(horizontal = 6.dp, vertical = 1.dp))
    }
    val p = f.progress
    if (p != null && !f.watched) {
        Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(3.dp).background(Color(0x55000000))) {
            Box(Modifier.fillMaxWidth(p).fillMaxHeight().background(Tg.colors.danger))
        }
    }
    if (f.watched) {
        Box(Modifier.align(Alignment.TopEnd).padding(7.dp).size(20.dp).clip(CircleShape).background(Color(0xB80C1018)),
            contentAlignment = Alignment.Center) { TgIconView(TgIcons.check, tint = Color.White, size = 12.dp, stroke = 2.4f) }
    }
    if (f.copies > 0 && f.kind != "photo") {
        Text("⧉ ${f.copies + 1}", style = Tg.type.caption, color = Color.White,
            modifier = Modifier.align(Alignment.TopEnd).padding(7.dp).clip(RoundedCornerShape(5.dp)).background(Color(0x990C1018))
                .padding(horizontal = 5.dp, vertical = 1.dp))
    }
}

/** How a search result matched (desktop .mbadge): exact, variant, similar, related. */
@Composable
fun MatchBadge(match: String?, modifier: Modifier = Modifier) {
    val label = when (match) {
        "variant" -> "Variant"
        "similar" -> "Similar"
        "related" -> "Related"
        else -> return
    }
    val mc = when (match) {
        "variant" -> Color(0xFF2F8A7D)
        "similar" -> Color(0xFFB7791F)
        else -> Color(0xFF7A5AC9)
    }
    Text(label, style = Tg.type.caption.copy(fontWeight = FontWeight.SemiBold), color = mc,
        modifier = modifier.clip(RoundedCornerShape(9.dp)).background(mix(mc, Tg.colors.panel, .14f)).padding(horizontal = 7.dp, vertical = 1.dp))
}

/** A folder's picture: its emoji on a soft tile, or the folder glyph in its colour. */
@Composable
fun FolderBadge(folder: Folder, size: Dp = 40.dp) {
    val c = Tg.colors
    val fc = c.folderColor(folder.color)
    Box(Modifier.size(size).clip(RoundedCornerShape(size * .28f)).background(mix(fc, c.panel, .16f)), contentAlignment = Alignment.Center) {
        val e = folder.emoji
        if (!e.isNullOrBlank()) Text(e, fontSize = (size.value * .5f).sp)
        else TgIconView(if (folder.smart) TgIcons.folderSmart else TgIcons.folder, tint = fc, size = size * .55f)
    }
}

fun folderSubtitle(f: Folder, childCount: Int): String {
    val parts = ArrayList<String>()
    if (f.smart) parts += "Smart folder"
    if (f.auto) parts += "Files itself"
    when {
        f.fileCount > 0 -> parts += Format.plural(f.fileCount, "file") + " · " + Format.size(f.bytes)
        childCount > 0 -> parts += Format.plural(childCount, "folder")
        !f.smart -> parts += "Empty"
    }
    return parts.joinToString(" · ")
}

