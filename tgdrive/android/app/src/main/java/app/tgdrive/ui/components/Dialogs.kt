package app.tgdrive.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgShape

/** A dialog in the desktop's style: a title, content and right-aligned buttons. */
@Composable
fun TgDialog(
    title: String,
    onDismiss: () -> Unit,
    confirm: String? = null,
    onConfirm: (() -> Unit)? = null,
    dismiss: String? = "Cancel",
    danger: Boolean = false,
    confirmEnabled: Boolean = true,
    busy: Boolean = false,
    scroll: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = Tg.colors
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.padding(20.dp).widthIn(max = 520.dp).fillMaxWidth(), shape = TgShape.dialog, color = c.panel,
            shadowElevation = 12.dp) {
            Column(Modifier.padding(start = 22.dp, end = 22.dp, top = 20.dp, bottom = 16.dp)) {
                Text(title, style = Tg.type.heading, color = c.ink)
                Spacer(Modifier.height(12.dp))
                // The content takes what is left and scrolls: the buttons stay on screen however long it is
                // (small phones, landscape, large text).
                Column(Modifier.weight(1f, fill = false).heightIn(max = 520.dp)
                    .then(if (scroll) Modifier.verticalScroll(rememberScrollState()) else Modifier), content = content)
                Spacer(Modifier.height(18.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End)) {
                    if (dismiss != null) TgButton(dismiss, onDismiss, kind = ButtonKind.Ghost)
                    if (confirm != null && onConfirm != null) {
                        TgButton(confirm, onConfirm, kind = if (danger) ButtonKind.DangerSolid else ButtonKind.Primary,
                            enabled = confirmEnabled, busy = busy)
                    }
                }
            }
        }
    }
}

@Composable
fun ConfirmDialog(title: String, text: String, confirm: String, onConfirm: () -> Unit, onDismiss: () -> Unit, danger: Boolean = false) =
    TgDialog(title, onDismiss, confirm, { onConfirm(); onDismiss() }, danger = danger) {
        Text(text, style = Tg.type.body, color = Tg.colors.ink2)
    }

/** Bottom sheet with the desktop's panel look (actions, pickers, details on phones). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TgSheet(onDismiss: () -> Unit, skipPartial: Boolean = true, content: @Composable ColumnScope.() -> Unit) {
    val c = Tg.colors
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = skipPartial),
        containerColor = c.panel,
        shape = TgShape.sheet,
        dragHandle = {
            Box(Modifier.padding(top = 10.dp, bottom = 6.dp).size(36.dp, 4.dp).clip(RoundedCornerShape(2.dp)).background(c.line))
        },
        scrimColor = c.scrim,
    ) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(bottom = 8.dp), content = content)
    }
}

/** One action in a sheet or menu. */
@Composable
fun SheetAction(icon: TgIcon, text: String, onClick: () -> Unit, subtitle: String? = null, danger: Boolean = false,
                trailing: (@Composable () -> Unit)? = null, enabled: Boolean = true) {
    val c = Tg.colors
    Row(
        Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).heightIn(min = 52.dp).padding(horizontal = 20.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TgIconView(icon, tint = when { danger -> c.danger; !enabled -> c.ink3; else -> c.ink2 }, size = 22.dp)
        Spacer(Modifier.width(18.dp))
        Column(Modifier.weight(1f)) {
            Text(text, style = Tg.type.bodyStrong, color = when { danger -> c.danger; !enabled -> c.ink3; else -> c.ink },
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) Text(subtitle, style = Tg.type.meta, color = c.ink3, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        trailing?.invoke()
    }
}

@Composable
fun SheetTitle(title: String, subtitle: String? = null, leading: (@Composable () -> Unit)? = null) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 4.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        if (leading != null) { leading(); Spacer(Modifier.width(14.dp)) }
        Column(Modifier.weight(1f)) {
            Text(title, style = Tg.type.subheading, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) Text(subtitle, style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
    Divider()
    Spacer(Modifier.height(4.dp))
}

/** Radio-style choice list for dialogs (sort orders, types, themes). */
@Composable
fun ChoiceRow(text: String, selected: Boolean, onClick: () -> Unit, subtitle: String? = null) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick).padding(vertical = 10.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(20.dp).border(2.dp, if (selected) c.accent else c.ink3, CircleShape), contentAlignment = Alignment.Center) {
            if (selected) Box(Modifier.size(10.dp).clip(CircleShape).background(c.accent))
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(text, style = Tg.type.body, color = c.ink)
            if (subtitle != null) Text(subtitle, style = Tg.type.meta, color = c.ink3)
        }
    }
}
