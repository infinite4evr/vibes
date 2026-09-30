package app.tgdrive.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgShape
import app.tgdrive.ui.theme.hue
import app.tgdrive.ui.theme.mix
import app.tgdrive.util.Format

enum class ButtonKind { Primary, Secondary, Ghost, Danger, DangerSolid }

/** The desktop's .btn: 9 dp corners, a hairline border, medium weight. */
@Composable
fun TgButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    kind: ButtonKind = ButtonKind.Secondary,
    icon: TgIcon? = null,
    enabled: Boolean = true,
    busy: Boolean = false,
    small: Boolean = false,
) {
    val c = Tg.colors
    val (bg, fg, border) = when (kind) {
        ButtonKind.Primary -> Triple(c.accent, c.accentInk, c.accent)
        ButtonKind.Secondary -> Triple(c.panel, c.ink, c.line)
        ButtonKind.Ghost -> Triple(Color.Transparent, c.ink, Color.Transparent)
        ButtonKind.Danger -> Triple(c.panel, c.danger, c.line)
        ButtonKind.DangerSolid -> Triple(c.danger, Color.White, c.danger)
    }
    val h = if (small) 34.dp else 42.dp
    Row(
        modifier
            .heightIn(min = h)
            .alpha(if (enabled) 1f else .5f)
            .clip(TgShape.control)
            .background(bg)
            .border(1.dp, border, TgShape.control)
            .clickable(enabled = enabled && !busy, role = Role.Button, onClick = onClick)
            .padding(horizontal = if (small) 12.dp else 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(16.dp), color = fg, strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp))
        } else if (icon != null) {
            TgIconView(icon, tint = fg, size = if (small) 16.dp else 18.dp)
            Spacer(Modifier.width(8.dp))
        }
        Text(text, style = if (small) Tg.type.label else Tg.type.button, color = fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** The desktop's .icon-btn: a quiet square button that highlights when pressed or active. */
@Composable
fun IconBtn(icon: TgIcon, onClick: () -> Unit, modifier: Modifier = Modifier, contentDescription: String? = null,
            active: Boolean = false, tint: Color? = null, size: Dp = 40.dp, iconSize: Dp = 22.dp, enabled: Boolean = true,
            filled: Boolean = false) {
    val c = Tg.colors
    Box(
        modifier
            .size(size)
            .clip(RoundedCornerShape(10.dp))
            .background(if (active) c.accentSoft else Color.Transparent)
            .clickable(enabled = enabled, role = Role.Button, onClickLabel = contentDescription, onClick = onClick)
            .alpha(if (enabled) 1f else .4f),
        contentAlignment = Alignment.Center,
    ) {
        TgIconView(icon, tint = tint ?: if (active) c.accent else c.ink2, size = iconSize, filled = filled,
            contentDescription = contentDescription)
    }
}

/** The desktop's .chip (filters, tags). */
@Composable
fun TgChip(text: String, modifier: Modifier = Modifier, selected: Boolean = false, icon: TgIcon? = null,
           leading: (@Composable () -> Unit)? = null, onClose: (() -> Unit)? = null, onClick: (() -> Unit)? = null) {
    val c = Tg.colors
    Row(
        modifier
            .height(32.dp)
            .clip(TgShape.chip)
            .background(if (selected) c.accentSoft else c.panel2)
            .border(1.dp, if (selected) c.accentLine else c.line, TgShape.chip)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(start = 12.dp, end = if (onClose != null) 4.dp else 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        leading?.invoke()
        if (icon != null) TgIconView(icon, tint = if (selected) c.accent else c.ink2, size = 15.dp)
        Text(text, style = Tg.type.label, color = if (selected) c.accent else c.ink, maxLines = 1)
        if (onClose != null) {
            Box(Modifier.size(24.dp).clip(CircleShape).clickable(onClick = onClose), contentAlignment = Alignment.Center) {
                TgIconView(app.tgdrive.ui.theme.TgIcons.close, tint = c.ink3, size = 14.dp)
            }
        }
    }
}

/** A single-line or multi-line field with the desktop's look (9 dp corners, accent focus ring). */
@Composable
fun TgTextField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    label: String? = null,
    leading: TgIcon? = null,
    trailing: (@Composable () -> Unit)? = null,
    singleLine: Boolean = true,
    minLines: Int = 1,
    password: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
    imeAction: ImeAction = ImeAction.Done,
    onDone: (() -> Unit)? = null,
    error: String? = null,
    enabled: Boolean = true,
    textStyle: TextStyle = Tg.type.body,
    height: Dp = 46.dp,
) {
    val c = Tg.colors
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    Column(modifier) {
        if (label != null) {
            Text(label, style = Tg.type.label, color = c.ink2, modifier = Modifier.padding(bottom = 6.dp))
        }
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            enabled = enabled,
            singleLine = singleLine,
            minLines = minLines,
            textStyle = textStyle.copy(color = c.ink),
            cursorBrush = SolidColor(c.accent),
            visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = keyboardType, imeAction = imeAction),
            keyboardActions = KeyboardActions(onDone = { onDone?.invoke() }, onGo = { onDone?.invoke() }, onSearch = { onDone?.invoke() },
                onSend = { onDone?.invoke() }),
            interactionSource = interaction,
            modifier = Modifier.fillMaxWidth(),
            decorationBox = { inner ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .defaultMinSize(minHeight = height)
                        .clip(TgShape.control)
                        .background(c.panel)
                        .border(if (focused || error != null) 2.dp else 1.dp,
                            when { error != null -> c.danger; focused -> c.accent; else -> c.line }, TgShape.control)
                        .padding(horizontal = 12.dp, vertical = if (singleLine) 0.dp else 10.dp),
                    verticalAlignment = if (singleLine) Alignment.CenterVertically else Alignment.Top,
                ) {
                    if (leading != null) {
                        TgIconView(leading, tint = c.ink3, size = 18.dp)
                        Spacer(Modifier.width(10.dp))
                    }
                    Box(Modifier.weight(1f), contentAlignment = if (singleLine) Alignment.CenterStart else Alignment.TopStart) {
                        if (value.isEmpty() && placeholder.isNotEmpty()) {
                            Text(placeholder, style = textStyle, color = c.ink3, maxLines = if (singleLine) 1 else 3,
                                overflow = TextOverflow.Ellipsis)
                        }
                        inner()
                    }
                    trailing?.invoke()
                }
            },
        )
        if (error != null) {
            Text(error, style = Tg.type.meta, color = c.danger, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

/** Desktop toggle: accent track when on. */
@Composable
fun TgSwitch(checked: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true) {
    val c = Tg.colors
    Switch(
        checked = checked, onCheckedChange = onChange, enabled = enabled,
        colors = SwitchDefaults.colors(
            checkedThumbColor = Color.White, checkedTrackColor = c.accent, checkedBorderColor = c.accent,
            uncheckedThumbColor = Color.White, uncheckedTrackColor = mix(c.ink3, c.panel, .45f), uncheckedBorderColor = Color.Transparent,
        ),
        thumbContent = null,
    )
}

/** Tabs with counts (desktop: All 285 · Photos 85 …), scrolled horizontally. */
@Composable
fun CountTab(text: String, count: Long?, selected: Boolean, onClick: () -> Unit, dot: Color? = null) {
    val c = Tg.colors
    Column(
        Modifier
            .clip(RoundedCornerShape(8.dp))
            .clickable(role = Role.Tab, onClick = onClick)
            .padding(horizontal = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(Modifier.height(42.dp), verticalAlignment = Alignment.CenterVertically) {
            if (dot != null) {
                Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp)).background(dot))
                Spacer(Modifier.width(7.dp))
            }
            Text(text, style = Tg.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold),
                color = if (selected) c.accent else c.ink2)
            if (count != null) {
                Spacer(Modifier.width(6.dp))
                Text(Format.compact(count), style = Tg.type.meta, color = if (selected) c.accent else c.ink3)
            }
        }
        Box(Modifier.height(3.dp).fillMaxWidth().clip(RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp))
            .background(if (selected) c.accent else Color.Transparent))
    }
}

/** "FOLDERS 4" style section header. */
@Composable
fun SectionHeader(text: String, count: Long? = null, modifier: Modifier = Modifier, trailing: (@Composable RowScope.() -> Unit)? = null) {
    val c = Tg.colors
    Row(modifier.fillMaxWidth().heightIn(min = 36.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text.uppercase(), style = Tg.type.overline, color = c.ink3)
        if (count != null) {
            Spacer(Modifier.width(8.dp))
            Text(Format.compact(count), style = Tg.type.caption, color = c.ink3)
        }
        Spacer(Modifier.weight(1f))
        trailing?.invoke(this)
    }
}

@Composable
fun Spinner(size: Dp = 22.dp, color: Color = Tg.colors.accent, stroke: Dp = 2.2.dp) =
    CircularProgressIndicator(Modifier.size(size), color = color, strokeWidth = stroke, trackColor = Color.Transparent)

@Composable
fun ThinProgress(fraction: Float?, modifier: Modifier = Modifier, color: Color = Tg.colors.accent) {
    val c = Tg.colors
    if (fraction == null) LinearProgressIndicator(modifier.height(3.dp).clip(RoundedCornerShape(2.dp)), color = color, trackColor = c.line2)
    else LinearProgressIndicator(progress = { fraction.coerceIn(0f, 1f) }, modifier = modifier.height(4.dp).clip(RoundedCornerShape(2.dp)),
        color = color, trackColor = c.line2, drawStopIndicator = {}, gapSize = 0.dp)
}

/** Shimmer for things still loading (desktop .skel). */
@Composable
fun Modifier.shimmer(shape: androidx.compose.ui.graphics.Shape = RoundedCornerShape(6.dp)): Modifier {
    val c = Tg.colors
    val t = rememberInfiniteTransition(label = "shimmer")
    val x by t.animateFloat(0f, 1f, infiniteRepeatable(tween(1200, easing = LinearEasing), RepeatMode.Restart), label = "x")
    return this.clip(shape).background(
        Brush.linearGradient(listOf(c.hover, c.panel2, c.hover), start = androidx.compose.ui.geometry.Offset(x * 1200f - 600f, 0f),
            end = androidx.compose.ui.geometry.Offset(x * 1200f, 0f)))
}

/** Nothing to show: an icon, a sentence and, where it helps, a way forward. */
@Composable
fun EmptyState(icon: TgIcon, title: String, text: String? = null, modifier: Modifier = Modifier,
               action: String? = null, onAction: (() -> Unit)? = null, secondary: String? = null, onSecondary: (() -> Unit)? = null) {
    val c = Tg.colors
    Column(modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.size(64.dp).clip(RoundedCornerShape(18.dp)).background(c.panel2).border(1.dp, c.line2, RoundedCornerShape(18.dp)),
            contentAlignment = Alignment.Center) {
            TgIconView(icon, tint = c.ink3, size = 28.dp, stroke = 1.6f)
        }
        Spacer(Modifier.height(16.dp))
        Text(title, style = Tg.type.subheading, color = c.ink, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        if (text != null) {
            Spacer(Modifier.height(6.dp))
            Text(text, style = Tg.type.body, color = c.ink2, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
        if (action != null && onAction != null) {
            Spacer(Modifier.height(18.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                TgButton(action, onAction, kind = ButtonKind.Primary)
                if (secondary != null && onSecondary != null) TgButton(secondary, onSecondary)
            }
        }
    }
}

/** A person or chat: initials on a colour of their own. */
@Composable
fun Avatar(name: String?, size: Dp = 36.dp, modifier: Modifier = Modifier) {
    val h = hue(name ?: "?")
    val bg = Color.hsl(h, .55f, if (Tg.colors.dark) .32f else .88f)
    val fg = Color.hsl(h, .55f, if (Tg.colors.dark) .82f else .36f)
    Box(modifier.size(size).clip(CircleShape).background(bg), contentAlignment = Alignment.Center) {
        Text(Format.initials(name), style = Tg.type.label.copy(fontSize = (size.value * .38f).sp), color = fg)
    }
}

/** A white panel with the desktop's hairline border. */
@Composable
fun Panel(modifier: Modifier = Modifier, padding: PaddingValues = PaddingValues(16.dp), onClick: (() -> Unit)? = null,
          content: @Composable () -> Unit) {
    val c = Tg.colors
    Surface(
        modifier = modifier.then(if (onClick != null) Modifier.clip(TgShape.card).clickable(onClick = onClick) else Modifier),
        shape = TgShape.card, color = c.panel, border = BorderStroke(1.dp, c.line),
    ) {
        Box(Modifier.padding(padding)) { content() }
    }
}

@Composable
fun Divider(modifier: Modifier = Modifier, color: Color = Tg.colors.line2) =
    Box(modifier.fillMaxWidth().height(1.dp).background(color))

/** A row in a list of settings or actions. */
@Composable
fun ListRow(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    icon: TgIcon? = null,
    iconTint: Color? = null,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    danger: Boolean = false,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
) {
    val c = Tg.colors
    Row(
        modifier
            .fillMaxWidth()
            .then(if (onClick != null || onLongClick != null) Modifier.combinedClickableCompat(onClick, onLongClick) else Modifier)
            .heightIn(min = 52.dp)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (leading != null) { leading(); Spacer(Modifier.width(14.dp)) }
        else if (icon != null) {
            TgIconView(icon, tint = iconTint ?: if (danger) c.danger else c.ink2, size = 21.dp)
            Spacer(Modifier.width(16.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = Tg.type.bodyStrong, color = if (danger) c.danger else c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) Text(subtitle, style = Tg.type.meta, color = c.ink3, maxLines = 3, overflow = TextOverflow.Ellipsis)
        }
        if (trailing != null) { Spacer(Modifier.width(12.dp)); trailing() }
    }
}

fun Modifier.combinedClickableCompat(onClick: (() -> Unit)?, onLongClick: (() -> Unit)?): Modifier =
    this.combinedClickable(onClick = onClick ?: {}, onLongClick = onLongClick)
