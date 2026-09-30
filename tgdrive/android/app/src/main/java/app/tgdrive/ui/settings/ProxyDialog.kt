package app.tgdrive.ui.settings

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.bool
import app.tgdrive.data.str
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.components.TgDialog
import app.tgdrive.ui.components.TgSwitch
import app.tgdrive.ui.components.TgTextField
import app.tgdrive.ui.theme.Tg
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Proxy for networks where Telegram is blocked or slow (SOCKS5/4, HTTP, MTProto). */
@Composable
fun ProxyDialog(state: AppState, onClose: () -> Unit) {
    val s = state.settings.value
    val scope = rememberCoroutineScope()
    var enabled by remember { mutableStateOf(s.bool("proxy_enabled")) }
    var type by remember { mutableStateOf(s.str("proxy_type") ?: "socks5") }
    var host by remember { mutableStateOf(s.str("proxy_host").orEmpty()) }
    var port by remember { mutableStateOf(s.str("proxy_port") ?: "1080") }
    var user by remember { mutableStateOf(s.str("proxy_user").orEmpty()) }
    var pass by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    TgDialog("Connection settings", onClose, confirm = "Save", busy = busy, onConfirm = {
        busy = true
        scope.launch {
            try {
                state.api.patchSettings(buildJsonObject {
                    put("proxy_enabled", enabled); put("proxy_type", type); put("proxy_host", host.trim())
                    put("proxy_port", port.toIntOrNull() ?: 1080); put("proxy_user", user.trim())
                    if (type == "mtproto") put("proxy_pass", pass) else put("proxy_pass", pass)
                })
                state.refreshStatus()
                onClose()
            } catch (e: Exception) {
                error = e.message
            } finally { busy = false }
        }
    }) {
        Text("Use a proxy if Telegram is blocked or slow on your network.", style = Tg.type.body, color = Tg.colors.ink2)
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Use a proxy", style = Tg.type.bodyStrong, color = Tg.colors.ink, modifier = Modifier.weight(1f))
            TgSwitch(enabled, { enabled = it })
        }
        Spacer(Modifier.height(10.dp))
        Row {
            for ((k, l) in listOf("socks5" to "SOCKS5", "socks4" to "SOCKS4", "http" to "HTTP", "mtproto" to "MTProto")) {
                TgChip(l, selected = type == k, onClick = { type = k })
                Spacer(Modifier.width(6.dp))
            }
        }
        Spacer(Modifier.height(12.dp))
        TgTextField(host, { host = it }, label = "Server", placeholder = "proxy.example.com")
        Spacer(Modifier.height(10.dp))
        TgTextField(port, { port = it.filter(Char::isDigit) }, label = "Port", keyboardType = KeyboardType.Number)
        if (type != "mtproto") {
            Spacer(Modifier.height(10.dp))
            TgTextField(user, { user = it }, label = "Username")
        }
        Spacer(Modifier.height(10.dp))
        TgTextField(pass, { pass = it }, label = if (type == "mtproto") "Secret" else "Password", password = true,
            placeholder = if (s.bool("proxy_pass_set")) "Saved" else "")
        if (error != null) Text(error!!, style = Tg.type.label, color = Tg.colors.danger, modifier = Modifier.padding(top = 10.dp))
    }
}
