package com.example.lumaclean.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.lumaclean.model.StorageSnapshot
import com.example.lumaclean.ui.components.HeroStorageCard
import com.example.lumaclean.ui.components.ToolCard
import com.example.lumaclean.util.formatBytes

enum class ToolRoute { CLEAN, DUPLICATES, LARGE, MEDIA, APPS, MOVE, SETTINGS }

@Composable
fun HomeScreen(storage: StorageSnapshot, onTool: (ToolRoute) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text("Good morning", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Your phone, lighter.", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.height(14.dp))
            HeroStorageCard(storage.usedBytes, storage.totalBytes, storage.usedFraction) { onTool(ToolRoute.CLEAN) }
        }
        item { Text("Smart tools", style = MaterialTheme.typography.titleMedium) }
        item { ToolCard(Icons.Rounded.AutoAwesome, "Junk cleaner", "Temporary files, thumbnails, old installers", { onTool(ToolRoute.CLEAN) }) }
        item { ToolCard(Icons.Rounded.ContentCopy, "Duplicate finder", "SHA-256 exact duplicate detection", { onTool(ToolRoute.DUPLICATES) }) }
        item { ToolCard(Icons.Rounded.VideoFile, "Large files", "Review media and files over 100 MB", { onTool(ToolRoute.LARGE) }) }
        item { ToolCard(Icons.Rounded.PhotoLibrary, "Media lab", "Similar photos, screenshots and photo optimization", { onTool(ToolRoute.MEDIA) }) }
        item { ToolCard(Icons.Rounded.Apps, "App manager", "Cache sizes, last-used dates, uninstall", { onTool(ToolRoute.APPS) }) }
        item { ToolCard(Icons.Rounded.SdStorage, "Move to SD card", "Merge shared storage and WhatsApp media", { onTool(ToolRoute.MOVE) }) }
        if (storage.removableTotalBytes > 0) {
            item {
                ToolCard(
                    Icons.Rounded.SdCard,
                    "SD card",
                    "${formatBytes(storage.removableFreeBytes)} free of ${formatBytes(storage.removableTotalBytes)}",
                    { onTool(ToolRoute.MOVE) },
                    "Detected"
                )
            }
        }
        item { Spacer(Modifier.height(84.dp)) }
    }
}
