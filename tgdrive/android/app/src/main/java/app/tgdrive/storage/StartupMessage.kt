package app.tgdrive.storage

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.tgdrive.ui.components.*
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgTheme

/** A full screen for when TG Drive can't open normally, in its own look. Needs nothing but the theme. */
@Composable
fun StartupMessage(title: String, text: String, actions: List<Pair<String, () -> Unit>>) = TgTheme {
    val c = Tg.colors
    Column(Modifier.fillMaxSize().background(c.canvas).systemBarsPadding().verticalScroll(rememberScrollState())
        .padding(horizontal = 20.dp, vertical = 24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            TgLogo(44.dp)
            Text(title, style = Tg.type.title, color = c.ink)
        }
        Panel(Modifier.fillMaxWidth()) { SelectionContainer { Text(text, style = Tg.type.body, color = c.ink) } }
        actions.forEachIndexed { i, (label, action) ->
            TgButton(label, action, Modifier.fillMaxWidth(), kind = if (i == 0) ButtonKind.Primary else ButtonKind.Secondary)
        }
    }
}
