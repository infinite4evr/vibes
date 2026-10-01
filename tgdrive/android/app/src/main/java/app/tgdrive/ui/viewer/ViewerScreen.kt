package app.tgdrive.ui.viewer

import android.view.ViewGroup
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.data.str
import app.tgdrive.graph
import app.tgdrive.player.PlayerController
import app.tgdrive.ui.actions.Actions
import app.tgdrive.ui.actions.Overlay
import app.tgdrive.ui.actions.Platform
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.components.Spinner
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.files.DocIcon
import app.tgdrive.ui.files.ThumbSource
import app.tgdrive.ui.files.Waveform
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.util.Format
import coil3.compose.AsyncImage
import coil3.compose.AsyncImagePainter
import coil3.compose.LocalPlatformContext
import coil3.request.ImageRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Request

private val Black = Color(0xFF0B0D11)

/** Full-screen preview of files, swiping between them (desktop viewer.js). */
@Composable
fun ViewerScreen(
    files: List<FileItem>,
    start: Int,
    state: AppState,
    actions: Actions,
    thumbs: ThumbSource,
    onClose: () -> Unit,
    onDetails: (FileItem) -> Unit,
    onShowInChat: (FileItem) -> Unit,
) {
    val pager = rememberPagerState(initialPage = start.coerceIn(0, (files.size - 1).coerceAtLeast(0))) { files.size }
    var chrome by remember { mutableStateOf(true) }
    var zoomed by remember { mutableStateOf(false) }
    var slideshow by remember { mutableStateOf(false) }
    val settings by state.settings.collectAsState()
    val pagerScope = rememberCoroutineScope()
    val current = files.getOrNull(pager.currentPage)
    // Starred / renamed while the viewer is open.
    var overrides by remember { mutableStateOf<Map<String, FileItem>>(emptyMap()) }
    val shown = current?.let { overrides[it.key] ?: it }

    LaunchedEffect(slideshow, pager.currentPage) {
        if (!slideshow) return@LaunchedEffect
        val secs = settings.str("slideshow_seconds")?.toIntOrNull() ?: 4
        delay(secs * 1000L)
        val next = (pager.currentPage + 1 until files.size).firstOrNull { files[it].kind == "photo" || files[it].isImage }
        if (next == null) slideshow = false else pager.animateScrollToPage(next)
    }

    Box(Modifier.fillMaxSize().background(Black)) {
        HorizontalPager(pager, Modifier.fillMaxSize(), userScrollEnabled = !zoomed, beyondViewportPageCount = 1, key = { files[it].key }) { page ->
            val f = files[page]
            val active = page == pager.currentPage
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                when {
                    f.kind == "photo" || f.isImage -> ZoomableImage(f, state, thumbs, onZoom = { zoomed = it }, onTap = { chrome = !chrome })
                    f.kind in setOf("video", "round", "gif") -> if (active) VideoPage(f, state, onTap = { chrome = !chrome }, onEnded = {
                        // Settings → Streaming → Play the next file automatically.
                        val next = (page + 1 until files.size).firstOrNull { files[it].kind in setOf("video", "round") }
                        if (settings.str("autoplay_next") != "false" && next != null) pagerScope.launch { pager.animateScrollToPage(next) }
                    }) else PosterPage(f, thumbs)
                    f.kind in setOf("audio", "voice") -> AudioPage(f, state, thumbs, active)
                    f.isPdf -> if (active) PdfPage(f, state) else PosterPage(f, thumbs)
                    f.isText && f.size < 8 * 1024 * 1024 -> if (active) TextPage(f, state) else PosterPage(f, thumbs)
                    else -> OtherPage(f, state, actions)
                }
            }
        }

        AnimatedVisibility(chrome, enter = fadeIn(), exit = fadeOut()) {
            Column(Modifier.fillMaxWidth().background(Brush.verticalGradient(listOf(Color(0xCC000000), Color.Transparent)))
                .statusBarsPadding().padding(horizontal = 4.dp, vertical = 6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconBtn(TgIcons.chevLeft, onClose, tint = Color.White, iconSize = 24.dp, contentDescription = "Close")
                    Column(Modifier.weight(1f).padding(horizontal = 4.dp)) {
                        Text(shown?.displayName ?: "", style = Tg.type.subheading, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(listOfNotNull(shown?.chatTitle, shown?.date?.let { Format.date(it) }, shown?.size?.let { Format.size(it) }).joinToString(" · "),
                            style = Tg.type.meta, color = Color(0xFFB8C0CC), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    if (shown != null) {
                        if (shown.kind == "photo" && files.count { it.kind == "photo" } > 1) {
                            IconBtn(if (slideshow) TgIcons.pause else TgIcons.slides, { slideshow = !slideshow }, tint = Color.White,
                                contentDescription = "Slideshow")
                        }
                        IconBtn(TgIcons.star, {
                            val on = !shown.starred
                            actions.star(listOf(shown), on)
                            overrides = overrides + (shown.key to shown.copy(starred = on))
                        }, tint = if (shown.starred) Tg.colors.star else Color.White, filled = shown.starred, contentDescription = "Star")
                        IconBtn(TgIcons.download, { actions.download(listOf(shown)) }, tint = Color.White, contentDescription = "Download")
                        IconBtn(TgIcons.info, { onDetails(shown) }, tint = Color.White, contentDescription = "Details")
                        IconBtn(TgIcons.more, { actions.open(Overlay.FileMenu(shown)) }, tint = Color.White, contentDescription = "More")
                    }
                }
            }
        }
        if (files.size > 1 && chrome) {
            Text("${pager.currentPage + 1} / ${files.size}", style = Tg.type.caption, color = Color(0xFFB8C0CC),
                modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 14.dp)
                    .clip(RoundedCornerShape(10.dp)).background(Color(0x66000000)).padding(horizontal = 10.dp, vertical = 3.dp))
        }
    }
    LaunchedEffect(current?.key) {
        // Opening a file counts as using it (Recent).
        current?.let { f -> runCatching { withContext(Dispatchers.IO) { state.api.detail(state.aid.value, f.ref) } } }
    }
}

@Composable
private fun PosterPage(f: FileItem, thumbs: ThumbSource) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        val url = if (f.hasThumb) thumbs.thumb(f, big = true) else null
        if (url != null) AsyncImage(url, null, Modifier.fillMaxWidth(), contentScale = ContentScale.Fit)
        else DocIcon(f.ext, width = 120.dp)
    }
}

// ---------------------------------------------------------------------- photos
@Composable
private fun ZoomableImage(f: FileItem, state: AppState, thumbs: ThumbSource, onZoom: (Boolean) -> Unit, onTap: () -> Unit) {
    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    var loading by remember { mutableStateOf(true) }
    var failed by remember { mutableStateOf(false) }
    val ctx = LocalPlatformContext.current
    val aid = state.aid.value
    // The full picture: Telegram's biggest size for photos, the file itself for image documents.
    val full = if (f.kind == "photo") state.api.thumbUrl(aid, f.chatId, f.msgId, "full") else state.api.streamUrl(aid, f)
    Box(
        Modifier.fillMaxSize()
            .pointerInput(f.key) {
                detectTapGestures(onDoubleTap = { p ->
                    if (scale > 1.1f) { scale = 1f; offset = Offset.Zero; onZoom(false) }
                    else { scale = 2.5f; offset = (Offset(size.width / 2f, size.height / 2f) - p) * 1.5f; onZoom(true) }
                }, onTap = { onTap() })
            }
            .pointerInput(f.key) {
                detectTransformGestures { _, pan, zoom, _ ->
                    val s = (scale * zoom).coerceIn(1f, 6f)
                    scale = s
                    offset = if (s <= 1.01f) Offset.Zero else offset + pan
                    onZoom(s > 1.01f)
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        val lowres = thumbs.thumb(f, big = true)
        val layer = Modifier.fillMaxSize().graphicsLayer {
            scaleX = scale; scaleY = scale; translationX = offset.x; translationY = offset.y
        }
        // The preview stays under the full picture until it arrives, and instead of it if it can't.
        if ((loading || failed) && lowres != null) AsyncImage(lowres, null, layer, contentScale = ContentScale.Fit)
        AsyncImage(ImageRequest.Builder(ctx).data(full).build(), f.displayName, layer, contentScale = ContentScale.Fit,
            onState = { st ->
                loading = st is AsyncImagePainter.State.Loading
                failed = st is AsyncImagePainter.State.Error
            })
        if (loading) Spinner(28.dp, color = Color.White)
        if (failed) Text(if (lowres != null) "Showing a preview: the full picture couldn't be loaded." else "Couldn't load this picture.",
            style = Tg.type.label, color = Color(0xFFB8C0CC),
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 80.dp))
    }
}

// ---------------------------------------------------------------------- video
@Composable
private fun VideoPage(f: FileItem, state: AppState, onTap: () -> Unit, onEnded: () -> Unit) {
    val ctx = LocalContext.current
    val aid = state.aid.value
    // Saving where it stopped must outlive this page (it runs as the page goes away).
    val scope = ctx.graph.scope
    val player = remember(f.key) {
        ExoPlayer.Builder(ctx).setSeekBackIncrementMs(10_000).setSeekForwardIncrementMs(10_000).build().apply {
            setMediaItem(MediaItem.fromUri(state.api.streamUrl(aid, f)))
            if (f.kind == "gif") { repeatMode = Player.REPEAT_MODE_ONE; volume = 0f }
            if (!f.watched && f.playPos > 5) seekTo((f.playPos * 1000).toLong())
            playWhenReady = true
            prepare()
        }
    }
    var error by remember { mutableStateOf<String?>(null) }
    DisposableEffect(player) {
        PlayerController.get(ctx).pauseForVideo()
        val l = object : Player.Listener {
            override fun onPlaybackStateChanged(playbackState: Int) {
                if (playbackState == Player.STATE_ENDED && f.kind != "gif") onEnded()
            }

            override fun onPlayerError(e: androidx.media3.common.PlaybackException) {
                error = if (e.errorCode == androidx.media3.common.PlaybackException.ERROR_CODE_DECODING_FORMAT_UNSUPPORTED ||
                    e.errorCode == androidx.media3.common.PlaybackException.ERROR_CODE_DECODER_INIT_FAILED)
                    "This phone can't decode this video. Open it in another player (VLC, MX Player)."
                else "Couldn't play this video: ${e.errorCodeName.removePrefix("ERROR_CODE_").lowercase().replace('_', ' ')}"
            }
        }
        player.addListener(l)
        onDispose {
            val pos = player.currentPosition / 1000.0
            val dur = player.duration.takeIf { it > 0 }?.div(1000.0)
            if (f.kind != "gif" && pos > 3) scope.launch {
                runCatching { state.api.savePlayback(aid, f.ref, pos, dur, if (dur != null && pos > dur * .95) true else null) }
            }
            player.removeListener(l)
            player.release()
        }
    }
    LaunchedEffect(player) {
        // Where it stopped, every 10 s (Continue watching, resume on the computer too).
        while (true) {
            delay(10_000)
            if (player.isPlaying && f.kind != "gif") runCatching {
                state.api.savePlayback(aid, f.ref, player.currentPosition / 1000.0, player.duration.takeIf { it > 0 }?.div(1000.0))
            }
        }
    }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        AndroidView(factory = { c ->
            PlayerView(c).apply {
                layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                this.player = player
                setShowNextButton(false)
                setShowPreviousButton(false)
                setShowBuffering(PlayerView.SHOW_BUFFERING_ALWAYS)
                controllerAutoShow = true
                setControllerVisibilityListener(PlayerView.ControllerVisibilityListener { onTap() })
            }
        }, modifier = Modifier.fillMaxSize(), update = { it.player = player })
        val msg = error
        if (msg != null) {
            Column(Modifier.padding(24.dp).clip(RoundedCornerShape(14.dp)).background(Color(0xE61D2330)).padding(18.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text(msg, style = Tg.type.body, color = Color.White)
                Spacer(Modifier.height(12.dp))
                TgButton("Open in another player", {
                    Platform.openStream(ctx, state.api.externalStreamUrl(aid, f), f.mime, f.displayName)
                }, kind = ButtonKind.Primary, icon = TgIcons.external)
            }
        }
    }
}

// ---------------------------------------------------------------------- audio
@Composable
private fun AudioPage(f: FileItem, state: AppState, thumbs: ThumbSource, active: Boolean) {
    val ctx = LocalContext.current
    val player = remember { PlayerController.get(ctx) }
    val mine = player.current?.key == f.key
    LaunchedEffect(active) {
        if (active && !mine) player.playList(state, listOf(f), f)
    }
    val c = Tg.colors
    Column(Modifier.fillMaxSize().padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Box(Modifier.widthIn(max = 320.dp).fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(22.dp))
            .background(Brush.linearGradient(listOf(c.kind(f.kind).copy(alpha = .9f), c.kind(f.kind).copy(alpha = .5f)))),
            contentAlignment = Alignment.Center) {
            if (f.hasThumb) AsyncImage(thumbs.thumb(f, big = true), null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            else Waveform(f, Color.White.copy(alpha = .85f), Modifier.fillMaxWidth(.8f).height(120.dp))
        }
        Spacer(Modifier.height(24.dp))
        Text(f.audioTitle ?: f.displayName, style = Tg.type.heading, color = Color.White, maxLines = 2, overflow = TextOverflow.Ellipsis)
        Text(f.performer ?: f.chatTitle ?: "", style = Tg.type.body, color = Color(0xFFB8C0CC), maxLines = 1)
        Spacer(Modifier.height(20.dp))
        if (mine) {
            Seek(player)
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                IconBtn(TgIcons.prev, { player.previous() }, tint = Color.White, size = 52.dp, iconSize = 26.dp, contentDescription = "Previous")
                Box(Modifier.size(68.dp).clip(RoundedCornerShape(34.dp)).background(Color.White).clickable { player.toggle() },
                    contentAlignment = Alignment.Center) {
                    if (player.buffering) Spinner(26.dp, color = Black)
                    else TgIconView(if (player.playing) TgIcons.pause else TgIcons.play, tint = Black, size = 30.dp, filled = true)
                }
                IconBtn(TgIcons.next, { player.next() }, tint = Color.White, size = 52.dp, iconSize = 26.dp, contentDescription = "Next")
            }
            Spacer(Modifier.height(10.dp))
            SpeedRow(player)
        } else {
            Spinner(26.dp, color = Color.White)
        }
    }
}

@Composable
fun Seek(player: PlayerController, dark: Boolean = true) {
    val fg = if (dark) Color.White else Tg.colors.ink
    val sub = if (dark) Color(0xFFB8C0CC) else Tg.colors.ink3
    var dragging by remember { mutableStateOf<Float?>(null) }
    val frac = if (player.duration > 0) (player.position.toFloat() / player.duration).coerceIn(0f, 1f) else 0f
    Column(Modifier.fillMaxWidth()) {
        androidx.compose.material3.Slider(
            value = dragging ?: frac,
            onValueChange = { dragging = it },
            onValueChangeFinished = { dragging?.let { player.seekTo((it * player.duration).toLong()) }; dragging = null },
            enabled = player.duration > 0,
            colors = androidx.compose.material3.SliderDefaults.colors(thumbColor = fg, activeTrackColor = fg,
                inactiveTrackColor = fg.copy(alpha = .25f)),
        )
        Row(Modifier.fillMaxWidth()) {
            Text(player.positionLabel, style = Tg.type.meta, color = sub)
            Spacer(Modifier.weight(1f))
            Text(player.durationLabel, style = Tg.type.meta, color = sub)
        }
    }
}

@Composable
fun SpeedRow(player: PlayerController, dark: Boolean = true) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        for (s in PlayerController.SPEEDS) {
            val on = player.speed == s
            Text(if (s == 1f) "1×" else "${s}×".replace(".0×", "×"), style = Tg.type.caption,
                color = if (on) (if (dark) Black else Color.White) else (if (dark) Color.White else Tg.colors.ink2),
                modifier = Modifier.clip(RoundedCornerShape(8.dp))
                    .background(if (on) (if (dark) Color.White else Tg.colors.accent) else Color.Transparent)
                    .clickable { player.changeSpeed(s) }.padding(horizontal = 9.dp, vertical = 5.dp))
        }
    }
}

// ---------------------------------------------------------------------- pdf
@Composable
private fun PdfPage(f: FileItem, state: AppState) {
    val ctx = LocalContext.current
    val aid = state.aid.value
    var attempt by remember { mutableIntStateOf(0) }
    val pdf by produceState<Result<RemotePdf>?>(null, f.key, attempt) {
        value = runCatching { withContext(Dispatchers.IO) { RemotePdf.open(ctx, ctx.graph.mediaHttp, state.api.streamUrl(aid, f), f.size) } }
        awaitDispose { value?.getOrNull()?.close() }
    }
    val widthPx = with(LocalDensity.current) { LocalConfiguration.current.screenWidthDp.dp.toPx() }.toInt()
    var zoom by remember { mutableFloatStateOf(1f) }
    Box(Modifier.fillMaxSize().background(Color(0xFF2A2F38)), contentAlignment = Alignment.Center) {
        val r = pdf
        when {
            r == null -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Spinner(28.dp, color = Color.White)
                Spacer(Modifier.height(10.dp))
                Text("Opening the PDF…", style = Tg.type.label, color = Color(0xFFB8C0CC))
            }
            r.isFailure -> Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(24.dp)) {
                Text("Couldn't open this PDF: ${r.exceptionOrNull()?.message ?: "unknown error"}", style = Tg.type.body, color = Color.White)
                Spacer(Modifier.height(12.dp))
                TgButton("Try again", { attempt++ }, kind = ButtonKind.Primary, icon = TgIcons.refresh)
            }
            else -> {
                val doc = r.getOrThrow()
                val list = rememberLazyListState()
                LazyColumn(
                    state = list,
                    modifier = Modifier.fillMaxSize().pointerInput(Unit) {
                        detectTransformGestures { _, _, z, _ -> zoom = (zoom * z).coerceIn(1f, 3f) }
                    },
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 88.dp, bottom = 40.dp, start = 8.dp, end = 8.dp),
                ) {
                    items(doc.pageCount) { i -> PdfPageImage(doc, i, (widthPx * zoom).toInt()) }
                }
                Text("${(list.firstVisibleItemIndex + 1).coerceAtMost(doc.pageCount)} / ${doc.pageCount}", style = Tg.type.caption,
                    color = Color.White, modifier = Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(14.dp)
                        .clip(RoundedCornerShape(8.dp)).background(Color(0x99000000)).padding(horizontal = 8.dp, vertical = 3.dp))
            }
        }
    }
}

@Composable
private fun PdfPageImage(doc: RemotePdf, index: Int, widthPx: Int) {
    var attempt by remember { mutableIntStateOf(0) }
    val ratio = remember(index) { runCatching { doc.pageSize(index).let { it.second.toFloat() / it.first } }.getOrDefault(1.414f) }
    val bmp by produceState<Result<android.graphics.Bitmap>?>(null, index, widthPx, attempt) {
        value = runCatching { doc.render(index, widthPx) }
    }
    Box(Modifier.fillMaxWidth().aspectRatio(1f / ratio).background(Color.White), contentAlignment = Alignment.Center) {
        val r = bmp
        when {
            r == null -> Spinner(22.dp)
            r.isFailure -> TgButton("Try again", { attempt++ }, small = true, icon = TgIcons.refresh)
            else -> androidx.compose.foundation.Image(r.getOrThrow().asImageBitmap(), "Page ${index + 1}", Modifier.fillMaxSize(),
                contentScale = ContentScale.FillWidth)
        }
    }
}

// ---------------------------------------------------------------------- text
@Composable
private fun TextPage(f: FileItem, state: AppState) {
    val ctx = LocalContext.current
    var attempt by remember { mutableIntStateOf(0) }
    val text by produceState<Result<String>?>(null, f.key, attempt) {
        value = runCatching {
            withContext(Dispatchers.IO) {
                val req = Request.Builder().url(state.api.streamUrl(state.aid.value, f)).header("Range", "bytes=0-${512 * 1024 - 1}").build()
                ctx.graph.mediaHttp.newCall(req).execute().use { r ->
                    if (!r.isSuccessful) throw java.io.IOException(r.body.string().take(200).ifBlank { "HTTP ${r.code}" })
                    String(r.body.bytes(), Charsets.UTF_8)
                }
            }
        }
    }
    Box(Modifier.fillMaxSize().background(Tg.colors.panel).statusBarsPadding().padding(top = 60.dp)) {
        val r = text
        when {
            r == null -> Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                Spinner(); Spacer(Modifier.height(8.dp)); Text("Loading text…", style = Tg.type.label, color = Tg.colors.ink2)
            }
            r.isFailure -> Column(Modifier.align(Alignment.Center).padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Couldn't load the text: ${r.exceptionOrNull()?.message}", style = Tg.type.body, color = Tg.colors.ink2)
                Spacer(Modifier.height(10.dp))
                TgButton("Try again", { attempt++ }, kind = ButtonKind.Primary, icon = TgIcons.refresh)
            }
            else -> SelectionContainer {
                Text(r.getOrThrow() + if (f.size > 512 * 1024) "\n\n… (first 512 KB of ${Format.size(f.size)}; download for the rest)" else "",
                    style = Tg.type.mono.copy(fontFamily = FontFamily.Monospace, fontSize = 12.5.sp), color = Tg.colors.ink,
                    modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp))
            }
        }
    }
}

// ---------------------------------------------------------------------- other
@Composable
private fun OtherPage(f: FileItem, state: AppState, actions: Actions) {
    val ctx = LocalContext.current
    val aid = state.aid.value
    val detail by produceState<app.tgdrive.data.FileDetail?>(null, f.key) {
        value = runCatching { state.api.detail(aid, f.ref) }.getOrNull()
    }
    Column(Modifier.padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        DocIcon(f.ext, width = 128.dp)
        Spacer(Modifier.height(22.dp))
        Text(f.displayName, style = Tg.type.heading, color = Color.White, maxLines = 3, overflow = TextOverflow.Ellipsis)
        Text("${Format.size(f.size)} · ${f.ext?.uppercase() ?: "File"}", style = Tg.type.body, color = Color(0xFFB8C0CC))
        Spacer(Modifier.height(22.dp))
        val local = detail?.extras?.localPath
        if (local != null) {
            TgButton("Open", { if (!Platform.openFile(ctx, local, f.mime)) state.message("No app on this phone opens this kind of file.", error = true) },
                kind = ButtonKind.Primary, icon = TgIcons.external)
        } else {
            TgButton("Download", { actions.download(listOf(f)) }, kind = ButtonKind.Primary, icon = TgIcons.download)
            Spacer(Modifier.height(8.dp))
            Text("Previews aren't available for this kind of file. Download it to open it with another app.",
                style = Tg.type.meta, color = Color(0xFF8A94A3))
        }
    }
}

