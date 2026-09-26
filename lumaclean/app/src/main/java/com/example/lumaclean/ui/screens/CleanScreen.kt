package com.example.lumaclean.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CleaningServices
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.lumaclean.data.SystemActions
import com.example.lumaclean.model.CleanCandidate
import com.example.lumaclean.model.RiskLevel
import com.example.lumaclean.ui.components.PermissionBanner
import com.example.lumaclean.util.formatBytes

@Composable
fun CleanScreen(
    candidates: List<CleanCandidate>,
    busy: Boolean,
    onGrantDeepAccess: () -> Unit,
    onScan: () -> Unit,
    onClean: (Collection<CleanCandidate>) -> Unit
) {
    val selected = remember(candidates) { mutableStateMapOf<String, Boolean>() }
    LaunchedEffect(candidates) {
        candidates.forEach { selected[it.path] = it.risk == RiskLevel.SAFE }
    }
    val chosen = candidates.filter { selected[it.path] == true }
    val bytes = chosen.sumOf { it.sizeBytes }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Junk cleaner", style = MaterialTheme.typography.headlineSmall)
            Text("Safe items are preselected. Review-risk items stay off until you choose them.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (!SystemActions.hasAllFilesAccess()) {
            item {
                PermissionBanner(
                    "Enable deep file scan",
                    "Without All files access, LumaClean only sees its own cache and user-selected/media content. Android blocks other shared files.",
                    "Open special access",
                    onGrantDeepAccess
                )
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = onScan, enabled = !busy, modifier = Modifier.weight(1f)) {
                    Icon(Icons.Rounded.CleaningServices, null); Spacer(Modifier.width(8.dp)); Text(if (busy) "Scanning…" else "Scan")
                }
                FilledTonalButton(onClick = { onClean(chosen) }, enabled = chosen.isNotEmpty() && !busy, modifier = Modifier.weight(1f)) {
                    Text("Clean ${formatBytes(bytes)}")
                }
            }
        }
        items(candidates, key = { it.path }) { item ->
            Card {
                Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = selected[item.path] == true, onCheckedChange = { selected[item.path] = it })
                    Column(Modifier.weight(1f)) {
                        Text(item.name, fontWeight = FontWeight.Medium, maxLines = 1)
                        Text(item.kind.label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        Text(formatBytes(item.sizeBytes))
                        if (item.risk == RiskLevel.REVIEW) Text("Review", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
                    }
                }
            }
        }
        if (candidates.isEmpty() && !busy) item { Text("Run a scan to find cleanable files.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        item { Spacer(Modifier.height(90.dp)) }
    }
}
