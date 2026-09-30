package app.tgdrive.ui.main

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.tgdrive.MainActivity
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.ui.components.ListRow
import app.tgdrive.ui.theme.Tg

/** Temporary shell (replaced by the full interface): proves the engine answers on the device. */
@Composable
fun MainScreen(activity: MainActivity, state: AppState) {
    val aid by state.aid.collectAsState()
    var files by remember { mutableStateOf<List<FileItem>>(emptyList()) }
    var err by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(aid) {
        try { files = state.api.files(aid, mapOf("limit" to "40")).items } catch (e: Exception) { err = e.message }
    }
    Column(Modifier.fillMaxSize().background(Tg.colors.canvas).systemBarsPadding()) {
        Text("All files", style = Tg.type.title, color = Tg.colors.ink, modifier = Modifier.padding(16.dp))
        if (err != null) Text(err!!, color = Tg.colors.danger)
        LazyColumn { items(files) { ListRow(it.displayName, subtitle = it.chatTitle) } }
    }
}
