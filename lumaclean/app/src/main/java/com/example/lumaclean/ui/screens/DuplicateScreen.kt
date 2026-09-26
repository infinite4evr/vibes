package com.example.lumaclean.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.lumaclean.model.DuplicateGroup
import com.example.lumaclean.util.formatBytes

@Composable
fun DuplicateScreen(
    groups: List<DuplicateGroup>,
    busy: Boolean,
    onScan: () -> Unit,
    onDeleteExtras: (Collection<DuplicateGroup>) -> Unit
) {
    var confirm by remember { mutableStateOf(false) }
    if (confirm) AlertDialog(
        onDismissRequest = { confirm = false },
        title = { Text("Delete duplicate copies?") },
        text = { Text("LumaClean will keep the newest file in each exact-match group and permanently delete the other copies.") },
        confirmButton = { TextButton(onClick = { confirm = false; onDeleteExtras(groups) }) { Text("Delete extras") } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } }
    )

    val reclaim = groups.sumOf { it.reclaimableBytes }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Duplicate finder", style = MaterialTheme.typography.headlineSmall)
            Text("Exact duplicates are confirmed with SHA-256, not just file names.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = onScan, enabled = !busy, modifier = Modifier.weight(1f)) { Text(if (busy) "Scanning…" else "Find duplicates") }
                FilledTonalButton(onClick = { confirm = true }, enabled = groups.isNotEmpty() && !busy, modifier = Modifier.weight(1f)) { Text("Free ${formatBytes(reclaim)}") }
            }
        }
        items(groups, key = { it.fingerprint }) { group ->
            Card {
                Column(Modifier.padding(14.dp)) {
                    Text("${group.files.size} identical files", fontWeight = FontWeight.SemiBold)
                    Text("Recoverable ${formatBytes(group.reclaimableBytes)}", color = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.height(8.dp))
                    group.files.take(4).forEachIndexed { index, file ->
                        Text(if (index == 0) "Keep • ${file.name}" else "Copy • ${file.name}", style = MaterialTheme.typography.bodySmall, maxLines = 1)
                    }
                    if (group.files.size > 4) Text("+ ${group.files.size - 4} more", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
        if (groups.isEmpty() && !busy) item { Text("Run a duplicate scan. Deep file access is required for a complete device scan.") }
        item { Spacer(Modifier.height(90.dp)) }
    }
}
