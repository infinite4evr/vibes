package com.example.lumaclean.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Chat
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.SdStorage
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.lumaclean.model.MigrationProgress
import com.example.lumaclean.ui.components.ToolCard
import com.example.lumaclean.util.formatBytes

@Composable
fun MoveScreen(
    destinationSet: Boolean,
    progress: MigrationProgress,
    busy: Boolean,
    onChooseDestination: () -> Unit,
    onMoveWhatsApp: () -> Unit,
    onMoveShared: () -> Unit
) {
    var confirmWhatsApp by remember { mutableStateOf(false) }
    var confirmShared by remember { mutableStateOf(false) }

    if (confirmWhatsApp) AlertDialog(
        onDismissRequest = { confirmWhatsApp = false },
        title = { Text("Move WhatsApp media?") },
        text = { Text("Media will be merged into the selected SD folder. WhatsApp may no longer show moved files in old chats because their original paths change. Private WhatsApp databases and login data are not moved.") },
        confirmButton = { TextButton(onClick = { confirmWhatsApp = false; onMoveWhatsApp() }) { Text("Move media") } },
        dismissButton = { TextButton(onClick = { confirmWhatsApp = false }) { Text("Cancel") } }
    )

    if (confirmShared) AlertDialog(
        onDismissRequest = { confirmShared = false },
        title = { Text("Move shared storage?") },
        text = { Text("This is a powerful operation. Photos, downloads, documents and other user-accessible shared files can change paths, so apps or playlists may lose references. Android/data, Android/obb and private app data are excluded.") },
        confirmButton = { TextButton(onClick = { confirmShared = false; onMoveShared() }) { Text("Move shared files") } },
        dismissButton = { TextButton(onClick = { confirmShared = false }) { Text("Cancel") } }
    )

    Column(Modifier.fillMaxSize().padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Move to SD card", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Merges user-accessible shared files into a folder you choose on the SD card. Existing identical files are skipped; true name conflicts are safely renamed.",
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        ToolCard(Icons.Rounded.FolderOpen, "Choose SD destination", if (destinationSet) "Destination permission saved" else "Select a folder on the removable SD card", onChooseDestination, if (destinationSet) "Ready" else null)
        ToolCard(Icons.Rounded.Chat, "Move WhatsApp media", "Moves WhatsApp shared Media where Android permits access", { confirmWhatsApp = true })
        ToolCard(Icons.Rounded.SdStorage, "Move shared storage", "Moves user-accessible shared files; private app data is excluded", { confirmShared = true })

        if (busy || progress.filesTotal > 0) {
            Card {
                Column(Modifier.padding(16.dp)) {
                    Text(if (progress.complete) "Migration finished" else "Migrating…")
                    if (progress.filesTotal > 0) {
                        LinearProgressIndicator(
                            progress = { progress.filesDone.toFloat() / progress.filesTotal.coerceAtLeast(1) },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)
                        )
                    }
                    Text("${progress.filesDone}/${progress.filesTotal} • ${formatBytes(progress.bytesCopied)}")
                    if (progress.currentName.isNotBlank()) Text(progress.currentName, style = MaterialTheme.typography.bodySmall, maxLines = 1)
                    if (progress.message.isNotBlank()) Text(progress.message, style = MaterialTheme.typography.bodySmall)
                }
            }
        }

        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer.copy(.55f))) {
            Column(Modifier.padding(16.dp)) {
                Text("Android boundary", style = MaterialTheme.typography.titleSmall)
                Text(
                    "A normal app cannot relocate another app's private /data/data database, login/session state, or arbitrarily redirect WhatsApp's private storage. This mover handles shared media/files and verifies copies before deleting sources.",
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }
    }
}
