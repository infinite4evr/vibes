package com.example.lumaclean.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun SettingsScreen(initialScheduled: Boolean, onScheduledChanged: (Boolean) -> Unit) {
    var scheduled by remember { mutableStateOf(initialScheduled) }
    Column(Modifier.fillMaxSize().padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        Card {
            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text("Daily cleanup scan")
                    Text("Runs a battery-friendly analysis and notifies you when significant junk is found. It never silently deletes personal files.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Switch(checked = scheduled, onCheckedChange = { scheduled = it; onScheduledChanged(it) })
            }
        }
        Card {
            Column(Modifier.padding(16.dp)) {
                Text("Privacy by design")
                Text("Scanning, hashes, app statistics, and migration are processed locally on-device. No analytics SDK or upload service is included in this starter project.", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
