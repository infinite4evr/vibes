package app.lumaclean.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatCount

/**
 * Confirms a delete. When the recycle bin is on, offers skipping it to free the space now.
 * [onConfirm] receives true for a permanent delete.
 */
@Composable
fun DeleteConfirm(count: Int, bytes: Long, onConfirm: (permanent: Boolean) -> Unit, onDismiss: () -> Unit) {
    val c = LocalContainer.current
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    var permanent by remember { mutableStateOf(!settings.useRecycleBin) }
    val what = if (count == 1) "this item" else "${count.formatCount()} items"
    ConfirmDialog(
        title = "Delete $what?",
        text = if (permanent) "${bytes.formatBytes()} will be deleted for good. This can't be undone."
        else "They go to the recycle bin, where you can restore them for ${settings.recycleDays} days. Space is freed when the bin is emptied.",
        confirmLabel = if (permanent) "Delete" else "Move to bin",
        onConfirm = { onConfirm(permanent) },
        onDismiss = onDismiss,
        extra = {
            if (settings.useRecycleBin) {
                Row(
                    Modifier.fillMaxWidth().clickable { permanent = !permanent },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(checked = permanent, onCheckedChange = { permanent = it })
                    Text("Delete for good and free ${bytes.formatBytes()} now", style = MaterialTheme.typography.bodyMedium)
                }
            }
        },
    )
}

@Composable
fun TextInputDialog(
    title: String,
    initial: String,
    confirmLabel: String,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
    label: String = "Name",
) {
    val dot = initial.lastIndexOf('.')
    var value by remember {
        mutableStateOf(TextFieldValue(initial, TextRange(0, if (dot > 0) dot else initial.length)))
    }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                label = { Text(label) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        },
        confirmButton = {
            Button(onClick = { onConfirm(value.text); onDismiss() }, enabled = value.text.isNotBlank()) { Text(confirmLabel) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
