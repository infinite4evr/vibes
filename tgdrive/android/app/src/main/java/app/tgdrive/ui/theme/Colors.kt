package app.tgdrive.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp

/**
 * The desktop interface's design tokens (tgdrive/web/css/app.css, :root and the dark and
 * high-contrast variants), so the phone app looks like the same product. `mix` is CSS's
 * color-mix(in srgb, a p%, b).
 */
@Immutable
data class TgColors(
    val dark: Boolean,
    val canvas: Color,
    val panel: Color,
    val panel2: Color,
    val paper: Color,
    val ink: Color,
    val ink2: Color,
    val ink3: Color,
    val line: Color,
    val line2: Color,
    val hover: Color,
    val accent: Color,
    val accentInk: Color,
    val accentSoft: Color,
    val accentLine: Color,
    val folder: Color,
    val folderTab: Color,
    val folderSoft: Color,
    val danger: Color,
    val ok: Color,
    val warn: Color,
    val star: Color = Color(0xFFF5B82E),
    val scrim: Color = Color(0x99101319),
) {
    fun kind(kind: String?): Color = when (kind) {
        "photo" -> Color(0xFF23968A)
        "video" -> Color(0xFF7A5AC9)
        "audio" -> Color(0xFFC2527A)
        "voice" -> Color(0xFF4E9A4A)
        "round" -> Color(0xFFB7702E)
        "gif" -> Color(0xFFD0692B)
        else -> Color(0xFF3F6FB5)
    }

    /** Folder colours (the swatches in the folder dialog). */
    fun folderColor(name: String?): Color = FOLDER_COLORS[name] ?: folder

    companion object {
        val FOLDER_COLORS = linkedMapOf(
            "red" to Color(0xFFD9534F), "orange" to Color(0xFFE8833A), "yellow" to Color(0xFFD9A520),
            "green" to Color(0xFF4C9F5A), "teal" to Color(0xFF2F9C93), "blue" to Color(0xFF3B82C4),
            "purple" to Color(0xFF8A63C7), "pink" to Color(0xFFD0659A), "grey" to Color(0xFF8A94A3),
        )
        val DEFAULT_ACCENT = Color(0xFF2A7FC9)

        fun light(accentBase: Color = DEFAULT_ACCENT, highContrast: Boolean = false): TgColors {
            val panel = Color(0xFFFFFFFF)
            val accent = accentBase
            val c = TgColors(
                dark = false,
                canvas = Color(0xFFF1F3F6), panel = panel, panel2 = Color(0xFFF7F8FA), paper = Color(0xFFFFFFFF),
                ink = Color(0xFF161B26), ink2 = Color(0xFF4D5769), ink3 = Color(0xFF848D9D),
                line = Color(0xFFDFE3EA), line2 = Color(0xFFECEFF3), hover = Color(0xFFECEFF4),
                accent = accent, accentInk = if (accent.luminanceApprox() > 0.6f) Color(0xFF0D1520) else Color.White,
                accentSoft = mix(accent, panel, 0.13f), accentLine = mix(accent, panel, 0.38f),
                folder = Color(0xFFE3A73F), folderTab = Color(0xFFC98C26), folderSoft = Color(0xFFF8ECD4),
                danger = Color(0xFFC4413A), ok = Color(0xFF2F8A4A), warn = Color(0xFFB7791F),
            )
            return if (!highContrast) c else c.copy(
                ink = Color.Black, ink2 = Color(0xFF1C2330), ink3 = Color(0xFF39414F), line = Color(0xFF5D6675),
                line2 = Color(0xFF8C95A3), hover = Color(0xFFDDE3EA), canvas = Color(0xFFE9EDF2), panel2 = Color(0xFFF3F5F8),
                accentSoft = mix(accent, panel, 0.22f),
            )
        }

        fun dark(accentBase: Color = DEFAULT_ACCENT, highContrast: Boolean = false): TgColors {
            val panel = if (highContrast) Color(0xFF0B0D11) else Color(0xFF171B23)
            val accent = mix(accentBase, Color.White, 0.70f)
            val c = TgColors(
                dark = true,
                canvas = Color(0xFF101319), panel = panel, panel2 = Color(0xFF1C212B), paper = Color(0xFFD5DBE4),
                ink = Color(0xFFE8EBF1), ink2 = Color(0xFFA8B0BD), ink3 = Color(0xFF737D8E),
                line = Color(0xFF2A303B), line2 = Color(0xFF222833), hover = Color(0xFF232A35),
                accent = accent, accentInk = Color(0xFF0D1520),
                accentSoft = mix(accent, panel, 0.17f), accentLine = mix(accent, panel, 0.38f),
                folder = Color(0xFFD9A040), folderTab = Color(0xFFB9862E), folderSoft = Color(0xFF362E1F),
                danger = Color(0xFFE6665E), ok = Color(0xFF4FB36A), warn = Color(0xFFD9A441),
                scrim = Color(0xB3000000),
            )
            return if (!highContrast) c else c.copy(
                ink = Color.White, ink2 = Color(0xFFE3E7EE), ink3 = Color(0xFFC3CAD6), line = Color(0xFF8D97A8),
                line2 = Color(0xFF5B6474), hover = Color(0xFF2C3441), canvas = Color.Black, panel2 = Color(0xFF12151B),
            )
        }
    }
}

/** CSS color-mix(in srgb, a p, b): p of `a`, the rest `b`. */
fun mix(a: Color, b: Color, p: Float): Color = lerp(b, a, p)

internal fun Color.luminanceApprox(): Float = 0.2126f * red + 0.7152f * green + 0.0722f * blue

/** Colour of a document's extension band (desktop EXT_GROUPS). */
fun extColor(ext: String?): Color {
    val e = ext?.lowercase() ?: return Color(0xFF5B6B82)
    for ((c, list) in EXT_GROUPS) if (e in list) return c
    return Color(0xFF5B6B82)
}

private val EXT_GROUPS: List<Pair<Color, Set<String>>> = listOf(
    Color(0xFFD0453C) to "pdf",
    Color(0xFF2B62B8) to "doc docx odt rtf pages",
    Color(0xFF1F7A44) to "xls xlsx csv ods numbers tsv",
    Color(0xFFD0592A) to "ppt pptx odp key",
    Color(0xFFA8751B) to "zip rar 7z tar gz bz2 xz tgz zst iso dmg",
    Color(0xFF7B4BB3) to "epub mobi azw azw3 fb2 djvu cbz cbr",
    Color(0xFF3C8F3A) to "apk xapk aab exe msi deb rpm appimage",
    Color(0xFF57616F) to "txt md log json xml yml yaml ini srt vtt sub html htm js py c cpp java sh sql",
    Color(0xFFB0417A) to "mp3 m4a flac wav ogg opus aac wma",
    Color(0xFF6B51C7) to "mp4 mkv avi mov webm m4v 3gp ts flv wmv",
    Color(0xFF258F84) to "jpg jpeg png webp heic gif bmp tif tiff svg raw psd ai",
).map { (c, s) -> c to s.split(" ").toSet() }

/** A stable hue per string (desktop `hue()`), for avatars. */
fun hue(s: String): Float {
    var h = 0L
    s.codePoints().forEach { h = (h * 31 + it) and 0xFFFFFFFFL }
    return (h % 360).toFloat()
}
