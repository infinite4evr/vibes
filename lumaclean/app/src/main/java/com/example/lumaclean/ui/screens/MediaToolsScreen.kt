package com.example.lumaclean.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AutoFixHigh
import androidx.compose.material.icons.rounded.Collections
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.lumaclean.model.MediaStats
import com.example.lumaclean.model.OptimizeResult
import com.example.lumaclean.model.SimilarPhotoGroup
import com.example.lumaclean.ui.components.ToolCard
import com.example.lumaclean.util.formatBytes

@Composable
fun MediaToolsScreen(
    stats: MediaStats,
    similar: List<SimilarPhotoGroup>,
    optimizeResult: OptimizeResult?,
    busy: Boolean,
    onAnalyze: () -> Unit,
    onSimilar: () -> Unit,
    onPickPhotos: () -> Unit
) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Media lab", style = MaterialTheme.typography.headlineSmall)
            Text("Gallery cleanup without auto-deleting personal photos.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item { ToolCard(Icons.Rounded.Collections, "Analyze media", "Images, video, audio and screenshot storage", onAnalyze) }
        item { ToolCard(Icons.Rounded.PhotoLibrary, "Find similar photos", "Perceptual hash scan of recent photos (beta)", onSimilar) }
        item { ToolCard(Icons.Rounded.AutoFixHigh, "Optimize photos", "Choose photos and create smaller JPEG copies", onPickPhotos) }
        item {
            Card {
                Column(Modifier.padding(16.dp)) {
                    Text("Storage breakdown", fontWeight = FontWeight.SemiBold)
                    Text("Images: ${formatBytes(stats.imagesBytes)} • ${stats.imageCount}")
                    Text("Videos: ${formatBytes(stats.videosBytes)} • ${stats.videoCount}")
                    Text("Audio: ${formatBytes(stats.audioBytes)} • ${stats.audioCount}")
                    Text("Screenshots: ${formatBytes(stats.screenshotBytes)} • ${stats.screenshotCount}")
                }
            }
        }
        optimizeResult?.let { result ->
            item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(.5f))) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Optimization complete", fontWeight = FontWeight.SemiBold)
                        Text("Created ${result.created} optimized copies • saved about ${formatBytes(result.savedBytes)}")
                        Text("Originals were kept.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        if (similar.isNotEmpty()) item { Text("Similar-photo groups", style = MaterialTheme.typography.titleMedium) }
        items(similar) { group ->
            Card {
                Column(Modifier.padding(14.dp)) {
                    Text("${group.photos.size} visually similar photos", fontWeight = FontWeight.SemiBold)
                    Text("${formatBytes(group.photos.sumOf { it.sizeBytes })} total", color = MaterialTheme.colorScheme.primary)
                    group.photos.take(3).forEach { Text(it.name, style = MaterialTheme.typography.bodySmall, maxLines = 1) }
                }
            }
        }
        if (busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        item { Spacer(Modifier.height(90.dp)) }
    }
}
