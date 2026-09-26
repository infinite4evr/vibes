package com.example.lumaclean.ui

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.lumaclean.data.SystemActions
import com.example.lumaclean.ui.screens.*

enum class RootPage { HOME, CLEAN, APPS, SETTINGS }

@Composable
fun LumaCleanApp(vm: MainViewModel = viewModel()) {
    val context = LocalContext.current
    val activity = context as Activity
    val storage by vm.storage.collectAsState()
    val junk by vm.junk.collectAsState()
    val duplicates by vm.duplicates.collectAsState()
    val largeFiles by vm.largeFiles.collectAsState()
    val apps by vm.apps.collectAsState()
    val mediaStats by vm.mediaStats.collectAsState()
    val similarPhotos by vm.similarPhotos.collectAsState()
    val optimizeResult by vm.optimizeResult.collectAsState()
    val busy by vm.busy.collectAsState()
    val status by vm.status.collectAsState()
    val migration by vm.migration.collectAsState()

    var page by remember { mutableStateOf(RootPage.HOME) }
    var tool by remember { mutableStateOf<ToolRoute?>(null) }

    val photoPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(30)
    ) { uris -> if (uris.isNotEmpty()) vm.optimizePhotos(uris) }

    val treePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            runCatching {
                context.contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                )
            }
            vm.rememberSdTree(uri)
        }
    }

    val mediaPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33) {
            mediaPermission.launch(arrayOf(
                Manifest.permission.READ_MEDIA_IMAGES,
                Manifest.permission.READ_MEDIA_VIDEO,
                Manifest.permission.READ_MEDIA_AUDIO,
                Manifest.permission.POST_NOTIFICATIONS
            ))
        } else {
            val legacy = mutableListOf(Manifest.permission.READ_EXTERNAL_STORAGE)
            if (Build.VERSION.SDK_INT <= 29) legacy += Manifest.permission.WRITE_EXTERNAL_STORAGE
            mediaPermission.launch(legacy.toTypedArray())
        }
    }

    LumaCleanTheme {
        Scaffold(
            topBar = {
                CenterAlignedTopAppBar(
                    title = { Text(if (tool == null) "LumaClean" else when (tool) {
                        ToolRoute.CLEAN -> "Cleaner"
                        ToolRoute.DUPLICATES -> "Duplicates"
                        ToolRoute.LARGE -> "Large files"
                        ToolRoute.MEDIA -> "Media lab"
                        ToolRoute.APPS -> "Apps"
                        ToolRoute.MOVE -> "SD migration"
                        ToolRoute.SETTINGS -> "Settings"
                        null -> "LumaClean"
                    }) },
                    navigationIcon = {
                        if (tool != null) IconButton(onClick = { tool = null }) { Icon(Icons.Rounded.ArrowBack, "Back") }
                    }
                )
            },
            bottomBar = {
                if (tool == null) NavigationBar {
                    listOf(
                        Triple(RootPage.HOME, Icons.Rounded.Home, "Home"),
                        Triple(RootPage.CLEAN, Icons.Rounded.CleaningServices, "Clean"),
                        Triple(RootPage.APPS, Icons.Rounded.Apps, "Apps"),
                        Triple(RootPage.SETTINGS, Icons.Rounded.Settings, "Settings")
                    ).forEach { (target, icon, label) ->
                        NavigationBarItem(
                            selected = page == target,
                            onClick = { page = target },
                            icon = { Icon(icon, label) },
                            label = { Text(label) }
                        )
                    }
                }
            },
            snackbarHost = {
                SnackbarHost(remember { SnackbarHostState() })
            }
        ) { padding ->
            Box(Modifier.padding(padding).fillMaxSize()) {
                AnimatedContent(targetState = tool to page, label = "screen") { (route, root) ->
                    when (route) {
                        ToolRoute.CLEAN -> CleanScreen(junk, busy, { SystemActions.openAllFilesAccess(context) }, vm::scanJunk, vm::cleanSelected)
                        ToolRoute.DUPLICATES -> DuplicateScreen(duplicates, busy, vm::scanDuplicates, vm::deleteDuplicateExtras)
                        ToolRoute.LARGE -> LargeFilesScreen(largeFiles, busy, vm::loadLargeFiles)
                        ToolRoute.MEDIA -> MediaToolsScreen(mediaStats, similarPhotos, optimizeResult, busy, vm::analyzeMedia, vm::findSimilarPhotos) {
                            photoPicker.launch(androidx.activity.result.PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                        }
                        ToolRoute.APPS -> AppsScreen(context, activity, apps, busy, vm.hasUsageAccess, { SystemActions.openUsageAccess(context) }, vm::loadApps)
                        ToolRoute.MOVE -> MoveScreen(vm.sdTreeUri != null, migration, busy, { treePicker.launch(vm.sdTreeUri) }, vm::migrateWhatsApp, vm::migrateSharedStorage)
                        ToolRoute.SETTINGS -> SettingsScreen(vm.scheduledScan, vm::setScheduledScan)
                        null -> when (root) {
                            RootPage.HOME -> HomeScreen(storage) { selected -> tool = selected }
                            RootPage.CLEAN -> CleanScreen(junk, busy, { SystemActions.openAllFilesAccess(context) }, vm::scanJunk, vm::cleanSelected)
                            RootPage.APPS -> AppsScreen(context, activity, apps, busy, vm.hasUsageAccess, { SystemActions.openUsageAccess(context) }, vm::loadApps)
                            RootPage.SETTINGS -> SettingsScreen(vm.scheduledScan, vm::setScheduledScan)
                        }
                    }
                }
                AnimatedVisibility(visible = busy, enter = fadeIn(), exit = fadeOut()) {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }
                if (status.isNotBlank()) {
                    AssistChip(
                        onClick = {},
                        label = { Text(status, maxLines = 1) },
                        modifier = Modifier.padding(12.dp)
                    )
                }
            }
        }
    }
}
