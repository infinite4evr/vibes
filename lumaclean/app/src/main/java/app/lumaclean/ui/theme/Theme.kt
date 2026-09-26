package app.lumaclean.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import app.lumaclean.data.Accent
import app.lumaclean.data.AppSettings
import app.lumaclean.data.FileCategory
import app.lumaclean.data.ThemeMode

@Immutable
data class ExtraColors(
    val success: Color,
    val warning: Color,
    val danger: Color,
    val categories: Map<FileCategory, Color>,
    val apps: Color,
    val system: Color,
    val free: Color,
)

val LocalExtraColors = staticCompositionLocalOf {
    ExtraColors(Color.Green, Color.Yellow, Color.Red, emptyMap(), Color.Blue, Color.Gray, Color.LightGray)
}

private fun extraColors(dark: Boolean, scheme: ColorScheme) = ExtraColors(
    success = if (dark) Color(0xFF6DD58C) else Color(0xFF1B8A4B),
    warning = if (dark) Color(0xFFFFC266) else Color(0xFFB26A00),
    danger = scheme.error,
    categories = mapOf(
        FileCategory.IMAGES to Color(0xFF4C8DF6),
        FileCategory.VIDEOS to Color(0xFFE8618C),
        FileCategory.AUDIO to Color(0xFFF2A93B),
        FileCategory.DOCUMENTS to Color(0xFF2FA87A),
        FileCategory.APKS to Color(0xFF8E6CEF),
        FileCategory.ARCHIVES to Color(0xFF26A9C2),
        FileCategory.OTHER to Color(0xFF8C939D),
    ),
    apps = Color(0xFF5C6BC0),
    system = if (dark) Color(0xFF5E6570) else Color(0xFFB9C0CA),
    free = scheme.surfaceContainerHighest,
)

private fun scheme(accent: Accent, dark: Boolean): ColorScheme = when (accent) {
    Accent.OCEAN -> if (dark) darkColorScheme(
        primary = Color(0xFF99CBFF), onPrimary = Color(0xFF003355), primaryContainer = Color(0xFF004A78),
        onPrimaryContainer = Color(0xFFCFE5FF), secondary = Color(0xFFB9C8DA), onSecondary = Color(0xFF243140),
        secondaryContainer = Color(0xFF3A4857), onSecondaryContainer = Color(0xFFD5E4F7), tertiary = Color(0xFF82D5C8),
        onTertiary = Color(0xFF003731), tertiaryContainer = Color(0xFF005048), onTertiaryContainer = Color(0xFF9EF2E4),
        background = Color(0xFF111318), surface = Color(0xFF111318),
    ) else lightColorScheme(
        primary = Color(0xFF00629D), onPrimary = Color.White, primaryContainer = Color(0xFFCFE5FF),
        onPrimaryContainer = Color(0xFF001D34), secondary = Color(0xFF526070), onSecondary = Color.White,
        secondaryContainer = Color(0xFFD5E4F7), onSecondaryContainer = Color(0xFF0F1D2A), tertiary = Color(0xFF006A60),
        onTertiary = Color.White, tertiaryContainer = Color(0xFF9EF2E4), onTertiaryContainer = Color(0xFF00201C),
        background = Color(0xFFF8F9FC), surface = Color(0xFFF8F9FC),
    )
    Accent.EMERALD -> if (dark) darkColorScheme(
        primary = Color(0xFF79DA9E), onPrimary = Color(0xFF00391E), primaryContainer = Color(0xFF00522E),
        onPrimaryContainer = Color(0xFF95F7B9), secondary = Color(0xFFB6CCB8), onSecondary = Color(0xFF223527),
        secondaryContainer = Color(0xFF384B3C), onSecondaryContainer = Color(0xFFD2E8D4), tertiary = Color(0xFFA2CEDA),
        onTertiary = Color(0xFF033640), tertiaryContainer = Color(0xFF214C57), onTertiaryContainer = Color(0xFFBEEAF6),
        background = Color(0xFF101411), surface = Color(0xFF101411),
    ) else lightColorScheme(
        primary = Color(0xFF006D3F), onPrimary = Color.White, primaryContainer = Color(0xFF95F7B9),
        onPrimaryContainer = Color(0xFF00210F), secondary = Color(0xFF4F6353), onSecondary = Color.White,
        secondaryContainer = Color(0xFFD2E8D4), onSecondaryContainer = Color(0xFF0D1F13), tertiary = Color(0xFF3A646F),
        onTertiary = Color.White, tertiaryContainer = Color(0xFFBEEAF6), onTertiaryContainer = Color(0xFF001F26),
        background = Color(0xFFF6FBF4), surface = Color(0xFFF6FBF4),
    )
    Accent.VIOLET -> if (dark) darkColorScheme(
        primary = Color(0xFFD0BCFF), onPrimary = Color(0xFF381E72), primaryContainer = Color(0xFF4F378B),
        onPrimaryContainer = Color(0xFFEADDFF), secondary = Color(0xFFCCC2DC), onSecondary = Color(0xFF332D41),
        secondaryContainer = Color(0xFF4A4458), onSecondaryContainer = Color(0xFFE8DEF8), tertiary = Color(0xFFEFB8C8),
        onTertiary = Color(0xFF492532), tertiaryContainer = Color(0xFF633B48), onTertiaryContainer = Color(0xFFFFD8E4),
        background = Color(0xFF141218), surface = Color(0xFF141218),
    ) else lightColorScheme(
        primary = Color(0xFF6750A4), onPrimary = Color.White, primaryContainer = Color(0xFFEADDFF),
        onPrimaryContainer = Color(0xFF21005D), secondary = Color(0xFF625B71), onSecondary = Color.White,
        secondaryContainer = Color(0xFFE8DEF8), onSecondaryContainer = Color(0xFF1D192B), tertiary = Color(0xFF7D5260),
        onTertiary = Color.White, tertiaryContainer = Color(0xFFFFD8E4), onTertiaryContainer = Color(0xFF31111D),
        background = Color(0xFFFEF7FF), surface = Color(0xFFFEF7FF),
    )
    Accent.SUNSET -> if (dark) darkColorScheme(
        primary = Color(0xFFFFB68B), onPrimary = Color(0xFF532200), primaryContainer = Color(0xFF763300),
        onPrimaryContainer = Color(0xFFFFDBC8), secondary = Color(0xFFE6BEAB), onSecondary = Color(0xFF432B1D),
        secondaryContainer = Color(0xFF5D4132), onSecondaryContainer = Color(0xFFFFDBC8), tertiary = Color(0xFFCEC991),
        onTertiary = Color(0xFF343207), tertiaryContainer = Color(0xFF4B4819), onTertiaryContainer = Color(0xFFEAE5AB),
        background = Color(0xFF19120D), surface = Color(0xFF19120D),
    ) else lightColorScheme(
        primary = Color(0xFF9A4600), onPrimary = Color.White, primaryContainer = Color(0xFFFFDBC8),
        onPrimaryContainer = Color(0xFF321300), secondary = Color(0xFF765848), onSecondary = Color.White,
        secondaryContainer = Color(0xFFFFDBC8), onSecondaryContainer = Color(0xFF2B160A), tertiary = Color(0xFF636032),
        onTertiary = Color.White, tertiaryContainer = Color(0xFFEAE5AB), onTertiaryContainer = Color(0xFF1E1C00),
        background = Color(0xFFFFF8F5), surface = Color(0xFFFFF8F5),
    )
}

private val base = Typography()

private val LumaTypography = Typography(
    displaySmall = base.displaySmall.copy(fontWeight = FontWeight.SemiBold),
    headlineLarge = base.headlineLarge.copy(fontWeight = FontWeight.SemiBold),
    headlineMedium = base.headlineMedium.copy(fontWeight = FontWeight.SemiBold),
    headlineSmall = base.headlineSmall.copy(fontWeight = FontWeight.SemiBold),
    titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold),
    titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
    titleSmall = base.titleSmall.copy(fontWeight = FontWeight.SemiBold),
    labelLarge = base.labelLarge.copy(fontWeight = FontWeight.SemiBold),
)

private val LumaShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(32.dp),
)

/** Big numbers on dashboards: tabular so live values don't jitter. */
val NumberStyle = TextStyle(fontSize = 40.sp, fontWeight = FontWeight.SemiBold, fontFeatureSettings = "tnum")

@Composable
fun LumaTheme(settings: AppSettings, content: @Composable () -> Unit) {
    val dark = when (settings.themeMode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    val context = LocalContext.current
    val colors = if (settings.dynamicColor && Build.VERSION.SDK_INT >= 31) {
        if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
    } else scheme(settings.accent, dark)

    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as? Activity)?.window ?: return@SideEffect
            val controller = WindowCompat.getInsetsController(window, view)
            controller.isAppearanceLightStatusBars = !dark
            controller.isAppearanceLightNavigationBars = !dark
        }
    }

    CompositionLocalProvider(LocalExtraColors provides extraColors(dark, colors)) {
        MaterialTheme(colorScheme = colors, typography = LumaTypography, shapes = LumaShapes, content = content)
    }
}

/** A swatch for the accent picker in settings. */
fun accentSwatch(accent: Accent): Color = scheme(accent, false).primary
