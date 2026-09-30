package app.tgdrive.diag

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.tgdrive.graph
import app.tgdrive.ui.actions.Platform
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgDialog
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcons
import kotlinx.coroutines.launch
import java.io.File

/**
 * "Send a problem report": makes the .zip (logs, crash reports, the phone and the service's
 * state) and opens the share sheet. Returns (what failed, if known) -> Unit, and whether it is busy.
 */
@Composable
fun rememberSendReport(): Pair<(String?) -> Unit, Boolean> {
    val ctx = LocalContext.current
    var busy by remember { mutableStateOf(false) }
    val send: (String?) -> Unit = { error ->
        if (!busy) {
            busy = true
            // The app's scope, not the screen's: a menu that closes as it starts this must not cancel it.
            ctx.graph.scope.launch {
                try {
                    ProblemReport.share(ctx, ctx.graph.engine, error)
                } catch (e: Exception) {
                    AppLog.e("report", "couldn't make the problem report", e)
                    ctx.graph.state.message("Couldn't make the report: ${e.message ?: e.javaClass.simpleName}", error = true)
                } finally { busy = false }
            }
        }
    }
    return send to busy
}

/** What exactly went wrong behind an error message, to read, copy or send. */
@Composable
fun ErrorDetailsDialog(message: String, detail: String?, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val (send, busy) = rememberSendReport()
    val full = message + (detail?.let { "\n\n$it" } ?: "")
    TgDialog("What went wrong", onClose, confirm = "Send report", onConfirm = { send(full) }, dismiss = "Close", busy = busy) {
        Text(message, style = Tg.type.bodyStrong, color = Tg.colors.ink)
        if (detail != null) {
            Spacer(Modifier.height(10.dp))
            SelectionContainer { Text(detail, style = Tg.type.mono.copy(fontSize = 11.sp), color = Tg.colors.ink2, maxLines = 60) }
        }
        Spacer(Modifier.height(12.dp))
        Text("“Send report” makes a file with TG Drive's logs to send to whoever helps you fix this. It has no passwords, keys or messages.",
            style = Tg.type.meta, color = Tg.colors.ink3)
        Spacer(Modifier.height(8.dp))
        TgButton("Copy", { Platform.copy(ctx, "TG Drive error", full) }, kind = ButtonKind.Ghost, small = true, icon = TgIcons.copy)
    }
}

/** After a crash: say so on the next start and offer to send the report (once per crash). */
@Composable
fun CrashNotice(crashes: List<File>, onClose: () -> Unit) {
    val (send, busy) = rememberSendReport()
    val first = remember(crashes) { runCatching { crashes.first().readText() }.getOrDefault("") }
    TgDialog("TG Drive closed unexpectedly", { AppLog.markSeen(crashes); onClose() }, confirm = "Send report",
        onConfirm = { send(first.take(3000)) ; AppLog.markSeen(crashes); onClose() }, dismiss = "Not now", busy = busy) {
        Text("Last time, TG Drive stopped because of an error. A report was saved on this phone; sending it helps get this fixed.",
            style = Tg.type.body, color = Tg.colors.ink2)
        Spacer(Modifier.height(10.dp))
        SelectionContainer {
            Text(first.lineSequence().take(14).joinToString("\n"), style = Tg.type.mono.copy(fontSize = 11.sp), color = Tg.colors.ink3)
        }
    }
}

/** A row of buttons for error screens: send the report. */
@Composable
fun ReportButton(error: String?, small: Boolean = true) {
    val (send, busy) = rememberSendReport()
    Row {
        TgButton("Send report", { send(error) }, small = small, icon = TgIcons.bug, busy = busy)
        Spacer(Modifier.width(1.dp))
    }
}
