package app.tgdrive.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import app.tgdrive.R

val Inter = FontFamily(
    Font(R.font.inter_regular, FontWeight.Normal),
    Font(R.font.inter_medium, FontWeight.Medium),
    Font(R.font.inter_semibold, FontWeight.SemiBold),
    Font(R.font.inter_bold, FontWeight.Bold),
)

/** Inter with the desktop's features: tabular numbers, the flat-top "1" (ss03) and open digits (cv11). */
private const val FEATURES = "tnum, cv11, ss03, calt"

private fun style(size: Float, weight: FontWeight, line: Float, tracking: Float = -0.006f) = TextStyle(
    fontFamily = Inter, fontWeight = weight, fontSize = size.sp, lineHeight = line.sp,
    letterSpacing = tracking.em, fontFeatureSettings = FEATURES,
)

/** The desktop type scale (app.css), a touch larger where phones need it. */
@Immutable
data class TgType(
    val display: TextStyle = style(26f, FontWeight.Bold, 32f, -0.02f),
    val title: TextStyle = style(22f, FontWeight.Bold, 28f, -0.02f),
    val heading: TextStyle = style(17f, FontWeight.SemiBold, 23f, -0.015f),
    val subheading: TextStyle = style(15f, FontWeight.SemiBold, 20f, -0.01f),
    val body: TextStyle = style(14.5f, FontWeight.Normal, 21f),
    val bodyStrong: TextStyle = style(14.5f, FontWeight.Medium, 21f),
    val label: TextStyle = style(13.5f, FontWeight.Medium, 18f),
    val cardName: TextStyle = style(13.5f, FontWeight.SemiBold, 17.5f),
    val meta: TextStyle = style(12.5f, FontWeight.Normal, 17f),
    val caption: TextStyle = style(11.5f, FontWeight.Medium, 15f),
    val overline: TextStyle = style(11.5f, FontWeight.SemiBold, 15f, 0.06f),
    val button: TextStyle = style(14f, FontWeight.Medium, 18f),
    val mono: TextStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 12.5.sp, lineHeight = 18.sp),
)

object TgShape {
    val card = RoundedCornerShape(12.dp)
    val control = RoundedCornerShape(9.dp)
    val chip = RoundedCornerShape(13.dp)
    val sheet = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp)
    val dialog = RoundedCornerShape(16.dp)
    val pill = RoundedCornerShape(50)
    val small = RoundedCornerShape(6.dp)
}

val LocalTgColors = staticCompositionLocalOf { TgColors.light() }
val LocalTgType = staticCompositionLocalOf { TgType() }

object Tg {
    val colors: TgColors
        @Composable @ReadOnlyComposable get() = LocalTgColors.current
    val type: TgType
        @Composable @ReadOnlyComposable get() = LocalTgType.current
}

/** Appearance settings, shared with the desktop app's (Settings → Appearance). */
data class Appearance(
    val theme: String = "system",       // system | light | dark
    val accent: String = "",            // "" or #rrggbb
    val contrast: String = "normal",    // normal | high
    val fontScale: Float = 1f,
    val motion: String = "on",
)

@Composable
fun TgTheme(appearance: Appearance = Appearance(), content: @Composable () -> Unit) {
    val dark = when (appearance.theme) {
        "dark" -> true
        "light" -> false
        else -> isSystemInDarkTheme()
    }
    val accent = parseHex(appearance.accent) ?: TgColors.DEFAULT_ACCENT
    val high = appearance.contrast == "high"
    val colors = remember(dark, accent, high) { if (dark) TgColors.dark(accent, high) else TgColors.light(accent, high) }
    val type = remember { TgType() }
    val density = LocalDensity.current
    val scaled = remember(density, appearance.fontScale) {
        Density(density.density, density.fontScale * appearance.fontScale.coerceIn(0.85f, 1.3f))
    }
    CompositionLocalProvider(LocalTgColors provides colors, LocalTgType provides type, LocalDensity provides scaled) {
        MaterialTheme(
            colorScheme = materialScheme(colors),
            typography = materialTypography(type),
            shapes = Shapes(
                extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(9.dp),
                medium = RoundedCornerShape(12.dp), large = RoundedCornerShape(16.dp), extraLarge = RoundedCornerShape(20.dp),
            ),
            content = content,
        )
    }
}

private fun materialScheme(c: TgColors): ColorScheme {
    val base = if (c.dark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = c.accent, onPrimary = c.accentInk, primaryContainer = c.accentSoft, onPrimaryContainer = c.accent,
        secondary = c.ink2, onSecondary = c.panel, secondaryContainer = c.hover, onSecondaryContainer = c.ink,
        tertiary = c.folder, onTertiary = Color.White,
        background = c.canvas, onBackground = c.ink, surface = c.panel, onSurface = c.ink,
        surfaceVariant = c.panel2, onSurfaceVariant = c.ink2, surfaceTint = Color.Transparent,
        surfaceContainerLowest = c.panel, surfaceContainerLow = c.panel, surfaceContainer = c.panel,
        surfaceContainerHigh = c.panel, surfaceContainerHighest = c.panel2, surfaceBright = c.panel, surfaceDim = c.canvas,
        inverseSurface = c.ink, inverseOnSurface = c.panel, inversePrimary = c.accentSoft,
        outline = c.line, outlineVariant = c.line2, error = c.danger, onError = Color.White,
        errorContainer = mix(c.danger, c.panel, 0.14f), onErrorContainer = c.danger, scrim = Color.Black,
    )
}

private fun materialTypography(t: TgType) = Typography(
    displayLarge = t.display, displayMedium = t.display, displaySmall = t.display,
    headlineLarge = t.title, headlineMedium = t.title, headlineSmall = t.heading,
    titleLarge = t.heading, titleMedium = t.subheading, titleSmall = t.label,
    bodyLarge = t.body, bodyMedium = t.body, bodySmall = t.meta,
    labelLarge = t.button, labelMedium = t.label, labelSmall = t.caption,
)

fun parseHex(s: String?): Color? {
    val h = s?.trim()?.removePrefix("#") ?: return null
    if (h.length != 6) return null
    return h.toLongOrNull(16)?.let { Color(0xFF000000 or it) }
}
