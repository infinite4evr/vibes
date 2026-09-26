package app.lumaclean.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.AppContainer
import app.lumaclean.data.FileQuery
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.nav.Navigator
import app.lumaclean.ui.nav.Route
import app.lumaclean.ui.nav.Tab
import app.lumaclean.ui.screens.AppDetailScreen
import app.lumaclean.ui.screens.AppUsageScreen
import app.lumaclean.ui.screens.AppsScreen
import app.lumaclean.ui.screens.BatteryScreen
import app.lumaclean.ui.screens.BrowserScreen
import app.lumaclean.ui.screens.ChatMediaScreen
import app.lumaclean.ui.screens.CleanScreen
import app.lumaclean.ui.screens.CompressScreen
import app.lumaclean.ui.screens.DeviceScreen
import app.lumaclean.ui.screens.DuplicatesScreen
import app.lumaclean.ui.screens.ExclusionsScreen
import app.lumaclean.ui.screens.FileListScreen
import app.lumaclean.ui.screens.HistoryScreen
import app.lumaclean.ui.screens.HomeScreen
import app.lumaclean.ui.screens.NetworkScreen
import app.lumaclean.ui.screens.OnboardingScreen
import app.lumaclean.ui.screens.PermissionsScreen
import app.lumaclean.ui.screens.RamScreen
import app.lumaclean.ui.screens.RecycleBinScreen
import app.lumaclean.ui.screens.SearchScreen
import app.lumaclean.ui.screens.SettingsScreen
import app.lumaclean.ui.screens.SimilarPhotosScreen
import app.lumaclean.ui.screens.StorageScreen
import app.lumaclean.ui.screens.ToolsScreen
import app.lumaclean.ui.screens.UnusedAppsScreen
import app.lumaclean.ui.theme.LumaTheme
import kotlinx.coroutines.flow.MutableStateFlow

@Composable
fun LumaRoot(container: AppContainer, pendingRoute: MutableStateFlow<String?>) {
    val settings by container.settings.flow.collectAsStateWithLifecycle()
    LumaTheme(settings) {
        CompositionLocalProvider(LocalContainer provides container) {
            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
                if (!settings.onboarded) {
                    OnboardingScreen(onDone = { container.settings.update { it.copy(onboarded = true) } })
                } else {
                    MainShell(container, pendingRoute)
                }
                OperationDialog(container)
            }
        }
    }
}

@Composable
private fun MainShell(container: AppContainer, pendingRoute: MutableStateFlow<String?>) {
    val navigator = remember { Navigator(Tab.valueOf(container.settings.current.startTab.name)) }
    val route by pendingRoute.collectAsStateWithLifecycle()
    LaunchedEffect(route) {
        route?.let {
            openDeepLink(navigator, it, container)
            pendingRoute.value = null
        }
    }
    BackHandler(enabled = navigator.canGoBack) { navigator.back() }

    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) {
        container.messages.collect { m ->
            val result = snackbar.showSnackbar(
                message = m.text,
                actionLabel = m.actionLabel,
                withDismissAction = m.actionLabel == null,
                duration = if (m.actionLabel != null) SnackbarDuration.Long else SnackbarDuration.Short,
            )
            if (result == SnackbarResult.ActionPerformed) m.action?.invoke()
        }
    }

    val wide = LocalConfiguration.current.screenWidthDp >= 600
    CompositionLocalProvider(LocalNavigator provides navigator) {
        if (wide) {
            Row(Modifier.fillMaxSize()) {
                NavigationRail(containerColor = MaterialTheme.colorScheme.surfaceContainer) {
                    Spacer(Modifier.height(12.dp))
                    Tab.entries.forEach { t ->
                        NavigationRailItem(
                            selected = navigator.tab == t,
                            onClick = { navigator.select(t) },
                            icon = { Icon(if (navigator.tab == t) t.selectedIcon else t.icon, null) },
                            label = { Text(t.label) },
                        )
                    }
                }
                Box(
                    Modifier.weight(1f).fillMaxSize()
                        .windowInsetsPadding(WindowInsets.navigationBars.only(WindowInsetsSides.Bottom + WindowInsetsSides.End)),
                ) {
                    NavContent(navigator)
                    SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).padding(16.dp))
                }
            }
        } else {
            Scaffold(
                contentWindowInsets = WindowInsets(0, 0, 0, 0),
                snackbarHost = { SnackbarHost(snackbar) },
                bottomBar = {
                    NavigationBar {
                        Tab.entries.forEach { t ->
                            NavigationBarItem(
                                selected = navigator.tab == t,
                                onClick = { navigator.select(t) },
                                icon = { Icon(if (navigator.tab == t) t.selectedIcon else t.icon, null) },
                                label = { Text(t.label) },
                            )
                        }
                    }
                },
            ) { padding ->
                Box(Modifier.padding(padding).fillMaxSize()) { NavContent(navigator) }
            }
        }
    }
}

@Composable
private fun NavContent(navigator: Navigator) {
    val holder = rememberSaveableStateHolder()
    val tab = navigator.tab
    val stack = navigator.stack(tab)
    val target = Triple(tab, stack.size, stack.lastOrNull())
    AnimatedContent(
        targetState = target,
        transitionSpec = { fadeIn(tween(200)) togetherWith fadeOut(tween(120)) },
        label = "screens",
    ) { (t, depth, route) ->
        holder.SaveableStateProvider("${t.name}/$depth/$route") {
            ScreenFor(t, route)
        }
    }
}

@Composable
private fun ScreenFor(tab: Tab, route: Route?) {
    when (route) {
        null -> when (tab) {
            Tab.HOME -> HomeScreen()
            Tab.CLEAN -> CleanScreen()
            Tab.STORAGE -> StorageScreen()
            Tab.APPS -> AppsScreen()
            Tab.TOOLS -> ToolsScreen()
        }
        is Route.Browser -> BrowserScreen(route.path)
        is Route.Files -> FileListScreen(route.query)
        is Route.AppDetail -> AppDetailScreen(route.packageName)
        Route.Duplicates -> DuplicatesScreen()
        Route.AppUsage -> AppUsageScreen()
        Route.UnusedApps -> UnusedAppsScreen()
        Route.Ram -> RamScreen()
        Route.Battery -> BatteryScreen()
        Route.Device -> DeviceScreen()
        Route.Network -> NetworkScreen()
        Route.Similar -> SimilarPhotosScreen()
        Route.Compress -> CompressScreen()
        Route.ChatMedia -> ChatMediaScreen()
        Route.RecycleBin -> RecycleBinScreen()
        Route.Settings -> SettingsScreen()
        Route.History -> HistoryScreen()
        Route.Exclusions -> ExclusionsScreen()
        Route.Permissions -> PermissionsScreen()
        Route.Search -> SearchScreen()
    }
}

private fun openDeepLink(nav: Navigator, link: String, container: AppContainer) {
    when (link) {
        "clean" -> nav.jump(Tab.CLEAN)
        "storage" -> nav.jump(Tab.STORAGE)
        "ram" -> nav.jump(Tab.TOOLS, Route.Ram)
        "battery" -> nav.jump(Tab.TOOLS, Route.Battery)
        "large" -> nav.jump(Tab.STORAGE, Route.Files(FileQuery.Large(container.settings.current.largeFileMb * 1_000_000L)))
    }
}

@Composable
private fun OperationDialog(container: AppContainer) {
    val op by container.operations.state.collectAsStateWithLifecycle()
    val state = op ?: return
    AlertDialog(
        onDismissRequest = {},
        properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false),
        title = { Text(state.title) },
        text = {
            Column {
                Text(state.message, style = MaterialTheme.typography.bodyMedium, maxLines = 2)
                Spacer(Modifier.height(16.dp))
                val p = state.progress
                if (p == null) LinearProgressIndicator(Modifier.fillMaxWidth().clip(RoundedCornerShape(4.dp)))
                else LinearProgressIndicator(progress = { p }, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(4.dp)))
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = { container.operations.cancel() }) { Text("Cancel") } },
    )
}
