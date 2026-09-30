package app.tgdrive.ui.main

import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.tgdrive.MainActivity
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.engine.UploadService
import app.tgdrive.graph
import app.tgdrive.player.PlayerController
import app.tgdrive.ui.actions.Actions
import app.tgdrive.ui.actions.OverlayHost
import app.tgdrive.ui.actions.Overlay
import app.tgdrive.ui.browse.BrowseModel
import app.tgdrive.ui.browse.BrowseScreen
import app.tgdrive.ui.components.Avatar
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.files.ThumbSource
import app.tgdrive.ui.nav.Entry
import app.tgdrive.ui.nav.Navigator
import app.tgdrive.ui.nav.Screen
import app.tgdrive.ui.nav.View
import app.tgdrive.ui.onboarding.ApiKeyScreen
import app.tgdrive.ui.onboarding.SignInScreen
import app.tgdrive.ui.pages.ActivityScreen
import app.tgdrive.ui.pages.DuplicatesScreen
import app.tgdrive.ui.pages.IndexScreen
import app.tgdrive.ui.pages.StorageScreen
import app.tgdrive.ui.pages.TransfersScreen
import app.tgdrive.ui.photos.PhotosScreen
import app.tgdrive.ui.search.SearchInputScreen
import app.tgdrive.ui.settings.AccountsScreen
import app.tgdrive.ui.settings.SettingsScreen
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.viewer.ChatContextScreen
import app.tgdrive.ui.viewer.DetailsScreen
import app.tgdrive.ui.viewer.MiniPlayer
import app.tgdrive.ui.viewer.ViewerScreen
import kotlinx.coroutines.launch

/** Everything once TG Drive is ready: sidebar, top bar, the current page, and what floats over it. */
@Composable
fun MainScreen(activity: MainActivity, state: AppState) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val nav = remember { Navigator(Screen.Browse(View.Drive(null))) }
    val actions = remember { Actions(state, scope, ctx.applicationContext) }
    val player = remember { PlayerController.get(ctx.applicationContext) }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val snackbar = remember { SnackbarHostState() }
    val aid by state.aid.collectAsState()
    val thumbs = rememberThumbs(state)
    val top = nav.top

    // Pickers for uploads (files, or a whole folder with its sub-folders).
    val pickFiles = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris: List<Uri> ->
        if (uris.isNotEmpty()) UploadService.start(ctx, aid, uris, currentFolder(top.screen, state))
    }
    val pickTree = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri: Uri? ->
        if (uri != null) UploadService.startTree(ctx, aid, uri, currentFolder(top.screen, state))
    }
    val upload = { pickFiles.launch(arrayOf("*/*")) }

    // Files shared from another app: upload them to the folder you're in (or My Drive).
    val shared by activity.incomingShare.collectAsState()
    LaunchedEffect(shared) {
        if (shared.isNotEmpty()) {
            UploadService.start(ctx, aid, shared, currentFolder(top.screen, state))
            activity.incomingShare.value = emptyList()
        }
    }
    val openPlayer by activity.openPlayer.collectAsState()

    LaunchedEffect(Unit) {
        state.messages.collect { m ->
            val r = snackbar.showSnackbar(m.text, actionLabel = m.action, withDismissAction = m.error,
                duration = if (m.action != null) SnackbarDuration.Long else SnackbarDuration.Short)
            if (r == SnackbarResult.ActionPerformed) m.onAction?.invoke()
        }
    }

    val model: BrowseModel? = (top.screen as? Screen.Browse)?.let { b -> top.keep("model") { BrowseModel(state, b.view, scope) } }
    actions.model = model

    BackHandler(enabled = drawer.isOpen || model?.selecting == true || nav.canPop || actions.overlay != null) {
        when {
            actions.overlay != null -> actions.close()
            drawer.isOpen -> scope.launch { drawer.close() }
            model?.selecting == true -> model.clearSelection()
            else -> nav.pop()
        }
    }

    fun go(s: Screen) {
        scope.launch { drawer.close() }
        if (s is Screen.Browse || s in ROOTS || s is Screen.Settings) nav.navigate(s) else nav.push(s)
    }

    val openFiles: (List<FileItem>, Int) -> Unit = { list, i ->
        val f = list[i]
        if (f.kind in setOf("audio", "voice") ) player.playList(state, list.filter { it.kind in setOf("audio", "voice") }, f)
        else nav.push(Screen.Viewer(list, i))
    }

    val fullScreen = top.screen is Screen.Viewer
    ModalNavigationDrawer(
        drawerState = drawer,
        gesturesEnabled = !fullScreen,
        scrimColor = Tg.colors.scrim,
        drawerContent = {
            ModalDrawerSheet(drawerContainerColor = Tg.colors.panel, drawerShape = RoundedCornerShape(topEnd = 18.dp, bottomEnd = 18.dp),
                windowInsets = WindowInsets(0)) {
                Sidebar(state, top.screen, onGo = { go(it) }, onNew = { scope.launch { drawer.close() }; actions.open(Overlay.NewMenu) },
                    onPauseIndex = { pause -> scope.launch { runCatching { state.api.index(aid, if (pause) "pause" else "resume") } } })
            }
        },
    ) {
        Box(Modifier.fillMaxSize().background(Tg.colors.canvas)) {
            AnimatedContent(top, transitionSpec = { fadeIn(tween(160)) togetherWith fadeOut(tween(120)) }, label = "page",
                contentKey = { it.id }) { entry ->
                Page(entry, state, actions, nav, thumbs, scope, model = if (entry === top) model else null,
                    onMenu = { scope.launch { drawer.open() } }, onGo = { go(it) }, onOpen = openFiles, onUpload = upload,
                    onNewFolder = { actions.open(Overlay.FolderEdit(null, currentFolder(entry.screen, state))) })
            }

            // Floating things at the bottom: selection bar, mini player, "New".
            Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().navigationBarsPadding()) {
                AnimatedVisibility(model?.selecting == true, enter = slideInVertically { it } + fadeIn(), exit = slideOutVertically { it } + fadeOut()) {
                    if (model != null) SelectionBar(model, actions)
                }
                if (!fullScreen && model?.selecting != true) MiniPlayer(player, state, onOpen = { nav.push(Screen.Viewer(listOf(it), 0)) })
            }
            AnimatedVisibility(top.screen is Screen.Browse && model?.selecting != true && player.current == null,
                modifier = Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(20.dp),
                enter = scaleIn() + fadeIn(), exit = scaleOut() + fadeOut()) {
                NewButton { actions.open(Overlay.NewMenu) }
            }
            val reconnecting by state.reconnecting.collectAsState()
            AnimatedVisibility(reconnecting, modifier = Modifier.align(Alignment.TopCenter).statusBarsPadding().padding(top = 64.dp),
                enter = fadeIn() + slideInVertically { -it }, exit = fadeOut()) {
                Row(Modifier.shadow(8.dp, RoundedCornerShape(20.dp)).clip(RoundedCornerShape(20.dp)).background(Tg.colors.panel)
                    .border(1.dp, Tg.colors.line, RoundedCornerShape(20.dp)).padding(horizontal = 14.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    app.tgdrive.ui.components.Spinner(14.dp, stroke = 2.dp)
                    Spacer(Modifier.width(10.dp))
                    Text("Reconnecting to TG Drive's service…", style = Tg.type.label, color = Tg.colors.ink2)
                }
            }
            SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 76.dp)) { data ->
                Snackbar(data, containerColor = Color(0xFF1D2330), contentColor = Color.White, actionColor = Color(0xFF8CC4FF),
                    dismissActionContentColor = Color(0xFFB8C0CC), shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.padding(horizontal = 12.dp).widthIn(max = 560.dp))
            }
        }
    }

    OverlayHost(actions, state, nav, thumbs, upload = upload, uploadFolder = { pickTree.launch(null) })
    if (openPlayer) {
        LaunchedEffect(Unit) {
            player.current?.let { nav.push(Screen.Viewer(listOf(it), 0)) }
            activity.openPlayer.value = false
        }
    }
}

private val ROOTS = setOf(Screen.Photos, Screen.Transfers, Screen.Storage, Screen.Duplicates, Screen.Index, Screen.Activity, Screen.Accounts)

private fun currentFolder(s: Screen, state: AppState): String? {
    val v = (s as? Screen.Browse)?.view as? View.Drive ?: return null
    val f = v.folderId?.let { id -> state.folders.value.folders.firstOrNull { it.id == id } }
    return if (f?.smart == true) null else v.folderId
}

@Composable
private fun Page(
    entry: Entry, state: AppState, actions: Actions, nav: Navigator, thumbs: ThumbSource, scope: kotlinx.coroutines.CoroutineScope,
    model: BrowseModel?,
    onMenu: () -> Unit, onGo: (Screen) -> Unit, onOpen: (List<FileItem>, Int) -> Unit, onUpload: () -> Unit, onNewFolder: () -> Unit,
) {
    val back: (() -> Unit)? = if (nav.stack.size > 1 && nav.top === entry) ({ nav.pop() }) else null
    when (val s = entry.screen) {
        is Screen.Browse -> {
            val m = model ?: entry.keep("model") { BrowseModel(state, s.view, scope) }
            Column(Modifier.fillMaxSize()) {
                TopBar(state, onMenu = onMenu, onBack = back, onSearch = {
                    val v = s.view
                    nav.push(if (v is View.Search) Screen.SearchInput(v.q, v.scope)
                    else Screen.SearchInput(scope = if (state.setting("search_scope_default") == "here") app.tgdrive.ui.actions.scopeOf(state, v, m) else null))
                },
                    onTransfers = { onGo(Screen.Transfers) }, onAccount = { actions.open(Overlay.AccountMenu) },
                    searchText = (s.view as? View.Search)?.q)
                BrowseScreen(m, state, actions, thumbs, onOpen = onOpen, onNavigate = { v -> if (v is View.Drive || v is View.Album || v is View.Search) nav.push(Screen.Browse(v)) else onGo(Screen.Browse(v)) },
                    onUpload = onUpload, onNewFolder = onNewFolder, contentPadding = PaddingValues(0.dp))
            }
        }
        is Screen.Viewer -> ViewerScreen(s.files, s.index, state, actions, thumbs, onClose = { nav.pop() },
            onDetails = { nav.push(Screen.Details(it.ref)) }, onShowInChat = { f -> nav.push(Screen.ChatContext(f.ref, f.displayName)) })
        is Screen.Details -> DetailsScreen(s.ref, state, actions, thumbs, onBack = { nav.pop() }, onOpen = onOpen,
            onNavigate = { nav.push(Screen.Browse(it)) }, onShowInChat = { f -> nav.push(Screen.ChatContext(f.ref, f.displayName)) })
        is Screen.ChatContext -> ChatContextScreen(s.ref, s.title, state, thumbs, onBack = { nav.pop() }, onOpen = onOpen)
        is Screen.SearchInput -> SearchInputScreen(state, s.q, s.scope, onBack = { nav.pop() }, onSearch = { q, scope ->
            val under = nav.stack.getOrNull(nav.stack.size - 2)?.screen
            // Searching again from a results page replaces it, so Back goes to where the search started.
            if (under is Screen.Browse && under.view is View.Search) { nav.pop(); nav.replace(Screen.Browse(View.Search(q, scope))) }
            else nav.replace(Screen.Browse(View.Search(q, scope)))
        }, onOpenFile = { f -> nav.replace(Screen.Viewer(listOf(f), 0)) }, onNavigate = { v -> nav.replace(Screen.Browse(v)) })
        Screen.Transfers -> TransfersScreen(state, onMenu = onMenu, onBack = back)
        Screen.Photos -> PhotosScreen(state, thumbs, onMenu = onMenu, onOpen = onOpen)
        Screen.Storage -> StorageScreen(state, onMenu = onMenu, onNavigate = { onGo(Screen.Browse(it)) }, onOpen = onOpen)
        Screen.Duplicates -> DuplicatesScreen(state, actions, thumbs, onMenu = onMenu, onOpen = onOpen)
        Screen.Index -> IndexScreen(state, onMenu = onMenu, onOpenChat = { onGo(Screen.Browse(View.Chat(it))) })
        Screen.Activity -> ActivityScreen(state, onMenu = onMenu)
        is Screen.Settings -> SettingsScreen(state, s.section, onMenu = onMenu, onAccounts = { nav.push(Screen.Accounts) })
        Screen.Accounts -> AccountsScreen(state, onBack = back ?: onMenu, onAdd = { nav.push(Screen.SignIn(adding = true)) },
            onApiKey = { nav.push(Screen.ApiKey) })
        is Screen.SignIn -> SignInScreen(state, adding = s.adding, onDone = { nav.navigate(Screen.Browse(View.Drive(null))) }, onBack = { nav.pop() })
        Screen.ApiKey -> ApiKeyScreen(state, onBack = { nav.pop() })
    }
}

// ---------------------------------------------------------------------- top bar
@Composable
fun TopBar(state: AppState, onMenu: () -> Unit, onBack: (() -> Unit)?, onSearch: () -> Unit, onTransfers: () -> Unit, onAccount: () -> Unit,
           searchText: String? = null) {
    val c = Tg.colors
    val account by state.account.collectAsState()
    val status by state.status.collectAsState()
    val aid by state.aid.collectAsState()
    val me = status?.accounts?.firstOrNull { it.id == aid }
    Row(
        Modifier.fillMaxWidth().background(c.panel).statusBarsPadding().padding(start = 6.dp, end = 8.dp, top = 6.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) IconBtn(TgIcons.chevLeft, onBack, contentDescription = "Back", iconSize = 24.dp)
        else IconBtn(TgIcons.sidebar, onMenu, contentDescription = "Menu", iconSize = 23.dp)
        Spacer(Modifier.width(4.dp))
        Row(
            Modifier.weight(1f).height(46.dp).clip(RoundedCornerShape(23.dp)).background(c.panel2).border(1.dp, c.line, RoundedCornerShape(23.dp))
                .clickable(onClick = onSearch).padding(start = 14.dp, end = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TgIconView(TgIcons.search, tint = c.ink3, size = 19.dp)
            Spacer(Modifier.width(10.dp))
            Text(searchText?.takeIf { it.isNotBlank() } ?: "Search everything…", style = Tg.type.body,
                color = if (searchText.isNullOrBlank()) c.ink3 else c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f))
            TgIconView(TgIcons.sliders, tint = c.ink3, size = 19.dp)
        }
        Spacer(Modifier.width(4.dp))
        TransfersButton(account?.transfers?.active ?: 0, account?.transfers?.let { if (it.size > 0) it.done.toFloat() / it.size else null }, onTransfers)
        Box(Modifier.size(42.dp).clip(CircleShape).clickable(onClick = onAccount), contentAlignment = Alignment.Center) {
            Avatar(me?.name, 34.dp, Modifier.semantics { contentDescription = "Account" })
            val online = me?.status == "online"
            Box(Modifier.align(Alignment.BottomEnd).padding(3.dp).size(10.dp).clip(CircleShape).background(c.panel).padding(2.dp)
                .clip(CircleShape).background(if (online) c.ok else c.warn))
        }
    }
    Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
}

/** Transfers, with a ring that fills as they progress (desktop: the button with a progress ring). */
@Composable
private fun TransfersButton(active: Int, progress: Float?, onClick: () -> Unit) {
    val c = Tg.colors
    Box(Modifier.size(42.dp).clip(RoundedCornerShape(10.dp)).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        if (active > 0) {
            Canvas(Modifier.size(34.dp)) {
                drawArc(c.line, 0f, 360f, false, style = Stroke(2.5.dp.toPx()))
                drawArc(c.accent, -90f, 360f * (progress ?: .1f).coerceIn(.04f, 1f), false, style = Stroke(2.5.dp.toPx(), cap = StrokeCap.Round),
                    topLeft = Offset.Zero, size = Size(size.width, size.height))
            }
        }
        TgIconView(TgIcons.transfers, tint = if (active > 0) c.accent else c.ink2, size = 21.dp, contentDescription = "Transfers")
    }
}

@Composable
private fun NewButton(onClick: () -> Unit) {
    val c = Tg.colors
    Row(
        Modifier.shadow(10.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(c.panel)
            .clickable(onClick = onClick).padding(horizontal = 20.dp).height(56.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TgIconView(TgIcons.plus, tint = c.accent, size = 22.dp, stroke = 2.2f)
        Spacer(Modifier.width(10.dp))
        Text("New", style = Tg.type.subheading, color = c.ink)
    }
}

/** The floating selection bar (desktop 2.2): count, and the actions for what's selected. */
@Composable
private fun SelectionBar(model: BrowseModel, actions: Actions) {
    val c = Tg.colors
    val files = model.selected.values.toList()
    Row(
        Modifier.padding(horizontal = 12.dp, vertical = 10.dp).fillMaxWidth().shadow(12.dp, RoundedCornerShape(16.dp))
            .clip(RoundedCornerShape(16.dp)).background(Color(0xFF1D2330)).padding(horizontal = 6.dp).height(58.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconBtn(TgIcons.close, { model.clearSelection() }, tint = Color.White, contentDescription = "Clear selection")
        Text("${files.size}", style = Tg.type.subheading, color = Color.White, modifier = Modifier.padding(horizontal = 4.dp))
        Spacer(Modifier.weight(1f))
        val white = Color(0xFFE8EBF1)
        IconBtn(TgIcons.download, { actions.download(files); model.clearSelection() }, tint = white, contentDescription = "Download")
        IconBtn(TgIcons.move, { actions.open(Overlay.Move(files)) }, tint = white, contentDescription = "Move to folder")
        IconBtn(TgIcons.star, { actions.star(files, !files.all { it.starred }); model.clearSelection() }, tint = white,
            filled = files.isNotEmpty() && files.all { it.starred }, contentDescription = "Star")
        IconBtn(TgIcons.tag, { actions.open(Overlay.Tags(files)) }, tint = white, contentDescription = "Tags")
        IconBtn(TgIcons.more, { actions.open(Overlay.SelectionMenu(files)) }, tint = white, contentDescription = "More")
    }
}

// ---------------------------------------------------------------------- thumbnails
@Composable
private fun rememberThumbs(state: AppState): ThumbSource {
    val aid by state.aid.collectAsState()
    val settings by state.settings.collectAsState()
    val pdf = settings["pdf_card_previews"]?.toString() != "false"
    val ctx = LocalContext.current
    return remember(aid, pdf) {
        val pdfs = app.tgdrive.ui.viewer.PdfThumbs.get(ctx.applicationContext)
        object : ThumbSource {
            override fun thumb(f: FileItem, big: Boolean): String = state.api.thumbUrl(aid, f.chatId, f.msgId, if (big) "b" else "s")
            override fun docThumb(f: FileItem): String? = if (pdf) pdfs.urlFor(state, aid, f) else null
            override fun cover(chatId: Long, msgId: Long): String = state.api.thumbUrl(aid, chatId, msgId)
        }
    }
}
