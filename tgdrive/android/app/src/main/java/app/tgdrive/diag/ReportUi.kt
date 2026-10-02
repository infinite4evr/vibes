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

/** Opens a new GitHub issue about [error] (see [GitHubIssue]). */
fun createIssue(context: android.content.Context, error: String?, detail: String? = null, prefix: String = "Android") =
    GitHubIssue.openAsync(context, GitHubIssue.titleFor(prefix, error), error, detail)

/** What exactly went wrong behind an error message, to read, copy, report as a GitHub issue or send. */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun ErrorDetailsDialog(message: String, detail: String?, action: String? = null, onAction: (() -> Unit)? = null, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val (send, busy) = rememberSendReport()
    val full = message + (detail?.let { "\n\n$it" } ?: "")
    TgDialog("What went wrong", onClose, confirm = "Create GitHub issue", onConfirm = { createIssue(ctx, message, detail) }, dismiss = "Close") {
        Text(message, style = Tg.type.bodyStrong, color = Tg.colors.ink)
        Spacer(Modifier.height(8.dp))
        Text("“Create GitHub issue” opens a new issue on TG Drive's GitHub with this error and the end of the logs; you see it " +
            "before sending. “Send report” makes a file with all the logs. Neither has passwords, keys or messages.",
            style = Tg.type.meta, color = Tg.colors.ink3)
        Spacer(Modifier.height(8.dp))
        // The actions before the (long) stack, so they're on screen without scrolling.
        androidx.compose.foundation.layout.FlowRow(horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(8.dp)) {
            if (action != null && onAction != null) TgButton(action, { onClose(); onAction() }, kind = ButtonKind.Secondary, small = true)
            TgButton("Send report", { send(full) }, kind = ButtonKind.Secondary, small = true, icon = TgIcons.bug, busy = busy)
            TgButton("Copy", { Platform.copy(ctx, "TG Drive error", full) }, kind = ButtonKind.Ghost, small = true, icon = TgIcons.copy)
        }
        if (detail != null) {
            Spacer(Modifier.height(10.dp))
            SelectionContainer { Text(detail, style = Tg.type.mono.copy(fontSize = 11.sp), color = Tg.colors.ink2, maxLines = 60) }
        }
    }
}

/**
 * An error shown on a screen (a PDF that didn't open, a video that won't play …) also opens the error
 * dialog, with "Create GitHub issue", by itself: once per distinct error, closable.
 */
@Composable
fun AutoErrorDialog(message: String?, detail: String? = null) {
    if (message.isNullOrBlank()) return
    var open by remember(message, detail) { mutableStateOf(true) }
    if (open) ErrorDetailsDialog(message, detail) { open = false }
}

/** After a crash: say so on the next start and offer to send the report (once per crash). */
@Composable
fun CrashNotice(crashes: List<File>, onClose: () -> Unit) {
    val (send, busy) = rememberSendReport()
    val first = remember(crashes) { runCatching { crashes.first().readText() }.getOrDefault("") }
    val ctx = LocalContext.current
    val cause = remember(first) { first.lineSequence().drop(3).firstOrNull { it.isNotBlank() }?.trim() }
    TgDialog("TG Drive closed unexpectedly", { AppLog.markSeen(crashes); onClose() }, confirm = "Create GitHub issue",
        onConfirm = { createIssue(ctx, cause ?: "TG Drive closed unexpectedly", first, prefix = "Android crash"); AppLog.markSeen(crashes); onClose() },
        dismiss = "Not now") {
        Text("Last time, TG Drive stopped because of an error. A report was saved on this phone; reporting it helps get this fixed.",
            style = Tg.type.body, color = Tg.colors.ink2)
        Spacer(Modifier.height(10.dp))
        SelectionContainer {
            Text(first.lineSequence().take(14).joinToString("\n"), style = Tg.type.mono.copy(fontSize = 11.sp), color = Tg.colors.ink3)
        }
        Spacer(Modifier.height(10.dp))
        TgButton("Send report", { send(first.take(3000)) }, kind = ButtonKind.Secondary, small = true, icon = TgIcons.bug, busy = busy)
    }
}

/** The buttons for error screens: a GitHub issue about [error], and the full problem report. */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun ReportButton(error: String?, small: Boolean = true) {
    val ctx = LocalContext.current
    val (send, busy) = rememberSendReport()
    androidx.compose.foundation.layout.FlowRow(horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(8.dp),
        verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(8.dp)) {
        TgButton("Create GitHub issue", { createIssue(ctx, error ?: "A problem in TG Drive") }, small = small,
            kind = ButtonKind.Primary, icon = TgIcons.external)
        TgButton("Send report", { send(error) }, small = small, icon = TgIcons.bug, busy = busy)
    }
}
