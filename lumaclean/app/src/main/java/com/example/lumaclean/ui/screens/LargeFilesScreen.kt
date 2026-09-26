package com.example.lumaclean.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.lumaclean.model.LargeFile
import com.example.lumaclean.util.formatBytes
import com.example.lumaclean.util.formatDate

@Composable
fun LargeFilesScreen(files: List<LargeFile>, busy: Boolean, onScan: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Large files", style = MaterialTheme.typography.headlineSmall)
            Text("Review files over 100 MB. This screen intentionally does not auto-delete personal media.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(10.dp))
            Button(onClick = onScan, enabled = !busy) { Text(if (busy) "Scanning…" else "Scan large files") }
        }
        items(files, key = { it.uri?.toString() ?: it.path ?: it.name }) { file ->
            Card {
                Column(Modifier.padding(14.dp)) {
                    Text(file.name, fontWeight = FontWeight.Medium, maxLines = 1)
                    Text("${formatBytes(file.sizeBytes)} • ${formatDate(file.modified)}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(file.mimeType ?: "Unknown type", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
        if (files.isEmpty() && !busy) item { Text("Scan to list large files visible through MediaStore.") }
        item { Spacer(Modifier.height(90.dp)) }
    }
}
