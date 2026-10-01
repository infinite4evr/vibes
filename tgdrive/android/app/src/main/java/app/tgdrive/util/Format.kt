package app.tgdrive.util

import android.util.Base64
import java.text.NumberFormat
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale
import kotlin.math.floor
import kotlin.math.roundToInt

/** Formatting shared by every screen, matching the desktop interface's (web/js/core.js). */
object Format {
    private val zone: ZoneId get() = ZoneId.systemDefault()

    fun size(bytes: Long?): String {
        var b = (bytes ?: 0L).toDouble()
        if (b <= 0) return "0 B"
        val u = arrayOf("B", "KB", "MB", "GB", "TB", "PB")
        var i = 0
        while (b >= 1024 && i < u.size - 1) { b /= 1024; i++ }
        return if (i == 0) "${b.toLong()} ${u[i]}" else "${if (b < 10) "%.1f".format(Locale.getDefault(), b) else b.roundToInt()} ${u[i]}"
    }

    fun num(n: Long?): String = NumberFormat.getIntegerInstance().format(n ?: 0)
    fun num(n: Int?): String = num(n?.toLong())

    /** 8,424 → 8.4k, 438,046 → 438k, 1,250,000 → 1.2M. */
    fun compact(n: Long?): String {
        val v = n ?: 0
        if (v < 1000) return v.toString()
        val (d, s) = if (v < 1_000_000) 1e3 to "k" else 1e6 to "M"
        val x = v / d
        return (if (x < 100) (floor(x * 10) / 10).let { if (it % 1.0 == 0.0) it.toLong().toString() else "%.1f".format(Locale.getDefault(), it) }
        else floor(x).toLong().toString()) + s
    }

    fun plural(n: Long, one: String, many: String = one + "s") = "${num(n)} ${if (n == 1L) one else many}"
    fun plural(n: Int, one: String, many: String = one + "s") = plural(n.toLong(), one, many)

    private fun local(ts: Long): LocalDateTime = LocalDateTime.ofInstant(Instant.ofEpochSecond(ts), zone)

    private val timeFmt: DateTimeFormatter get() = DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT)
    private val dayMonth: DateTimeFormatter get() = DateTimeFormatter.ofPattern("d MMM", Locale.getDefault())
    private val dayMonthYear: DateTimeFormatter get() = DateTimeFormatter.ofPattern("d MMM yyyy", Locale.getDefault())

    /** "Today 13:05", "Yesterday", "7 May", "7 May 2024" (desktop fmtDate). */
    fun date(ts: Long?): String {
        if (ts == null || ts <= 0) return ""
        val d = local(ts)
        val today = LocalDate.now(zone)
        return when {
            d.toLocalDate() == today -> "Today ${d.format(timeFmt)}"
            d.toLocalDate() == today.minusDays(1) -> "Yesterday"
            d.year == today.year -> d.format(dayMonth)
            else -> d.format(dayMonthYear)
        }
    }

    fun dateLong(ts: Long?): String {
        if (ts == null || ts <= 0) return ""
        return local(ts).format(DateTimeFormatter.ofLocalizedDateTime(FormatStyle.LONG, FormatStyle.SHORT).withZone(zone))
    }

    fun dateTime(ts: Long?): String {
        if (ts == null || ts <= 0) return ""
        return local(ts).format(DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM, FormatStyle.SHORT))
    }

    fun relative(ts: Long?): String {
        if (ts == null || ts <= 0) return "never"
        val s = System.currentTimeMillis() / 1000 - ts
        return when {
            s < 60 -> "just now"
            s < 3600 -> "${s / 60} min ago"
            s < 86400 -> "${s / 3600} h ago"
            s < 86400 * 30 -> "${s / 86400} d ago"
            else -> date(ts)
        }
    }

    /** Section headers when grouping by date (desktop dateGroup). */
    fun dateGroup(ts: Long?): String {
        if (ts == null || ts <= 0) return "Undated"
        val d = local(ts).toLocalDate()
        val today = LocalDate.now(zone)
        return when {
            !d.isBefore(today) -> "Today"
            d == today.minusDays(1) -> "Yesterday"
            !d.isBefore(today.minusDays(6)) -> "Earlier this week"
            d.year == today.year && d.month == today.month -> "Earlier this month"
            else -> d.format(DateTimeFormatter.ofPattern("MMMM yyyy", Locale.getDefault()))
        }
    }

    fun duration(seconds: Double?): String {
        val s = (seconds ?: 0.0).roundToInt()
        val h = s / 3600
        val m = (s % 3600) / 60
        val sec = s % 60
        return if (h > 0) "%d:%02d:%02d".format(h, m, sec) else "%d:%02d".format(m, sec)
    }

    fun eta(seconds: Double): String = when {
        !seconds.isFinite() || seconds <= 0 -> ""
        seconds < 60 -> "${kotlin.math.ceil(seconds).toInt()} s left"
        seconds < 3600 -> "${kotlin.math.ceil(seconds / 60).toInt()} min left"
        else -> "${(seconds / 3600).toInt()} h ${kotlin.math.ceil((seconds % 3600) / 60).toInt()} min left"
    }

    fun initials(name: String?): String {
        val words = (name ?: "").replace(Regex("[^\\p{L}\\p{N}\\s]"), " ").split(Regex("\\s+")).filter { it.isNotBlank() }
        return words.take(2).joinToString("") { it.substring(0, it.offsetByCodePoints(0, 1)).uppercase() }.ifEmpty { "?" }
    }

    // Names cameras and Telegram make up become "Photo · 7 May, 1:50 AM" (desktop friendlyName).
    private val TG_NAME = Regex("^(photo|video|voice|round|audio|animation|file|document|sticker)[_\\- ](\\d{4})-(\\d{2})-(\\d{2})[_ ](\\d{2})-(\\d{2})-(\\d{2})", RegexOption.IGNORE_CASE)
    private val CAM_NAME = Regex("^(?:IMG|VID|PXL|MVIMG|PANO|DSC|Screenshot|Screen[_ ]?Recording|WhatsApp (?:Image|Video|Audio))?[_\\- ]?(\\d{4})-?(\\d{2})-?(\\d{2})[_\\- T]?(?:at )?(\\d{2})[.\\-_]?(\\d{2})[.\\-_]?(\\d{2})?", RegexOption.IGNORE_CASE)
    private val KIND_WORD = mapOf("photo" to "Photo", "video" to "Video", "voice" to "Voice message", "round" to "Round video",
        "audio" to "Audio", "gif" to "GIF", "document" to "File")

    fun friendlyName(name: String?, kind: String?, renamed: Boolean): String? {
        val raw = name ?: return null
        if (raw.isEmpty() || renamed) return null
        val base = raw.replace(Regex("\\.[a-zA-Z0-9]{2,5}$"), "")
        val parts: List<String>
        val m = TG_NAME.find(base)
        parts = if (m != null) m.groupValues.drop(2) else {
            val c = CAM_NAME.find(base) ?: return null
            if (c.range.first != 0 || base.length - c.value.length > 6) return null
            c.groupValues.drop(1)
        }
        val y = parts[0].toIntOrNull() ?: return null
        val mo = parts[1].toIntOrNull() ?: return null
        val d = parts[2].toIntOrNull() ?: return null
        val h = parts.getOrNull(3)?.toIntOrNull() ?: 0
        val mi = parts.getOrNull(4)?.toIntOrNull() ?: 0
        if (y < 1995 || y > 2100 || mo !in 1..12 || d !in 1..31 || h > 23 || mi > 59) return null
        val dt = try { LocalDateTime.of(y, mo, d, h, mi) } catch (_: Exception) { return null }
        val day = dt.format(if (dt.year != LocalDate.now(zone).year) dayMonthYear else dayMonth)
        val label = when {
            base.startsWith("screenshot", true) -> "Screenshot"
            Regex("^screen[_ ]?rec", RegexOption.IGNORE_CASE).containsMatchIn(base) -> "Screen recording"
            else -> KIND_WORD[kind] ?: "File"
        }
        return "$label · $day, ${dt.format(timeFmt)}"
    }

    val KIND_NAME = mapOf("photo" to "Photo", "video" to "Video", "document" to "Document", "audio" to "Audio",
        "voice" to "Voice message", "round" to "Round video", "gif" to "GIF")
    val KIND_PLURAL = listOf("" to "All", "photo" to "Photos", "video" to "Videos", "document" to "Documents",
        "audio" to "Audio", "voice" to "Voice", "round" to "Round videos", "gif" to "GIFs")
    val CHAT_KIND_NAME = mapOf("channel" to "Channel", "supergroup" to "Group", "group" to "Group", "user" to "Private chat",
        "bot" to "Bot", "saved" to "Saved Messages")
    val STREAMABLE = setOf("video", "audio", "voice", "round", "gif")
    val TEXT_EXT = "txt md log json xml yml yaml ini srt vtt csv tsv html htm js ts css py c h cpp java kt go rs rb php sh sql toml cfg conf env".split(" ").toSet()

    // A Telegram "stripped" preview is a JPEG without its fixed header (desktop inlineSrc).
    private val JPG_HEAD: ByteArray by lazy {
        Base64.decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDACgcHiMeGSgjISMtKygwPGRBPDc3PHtYXUlkkYCZlo+AjIqgtObDoKrarYqMyP/L2u71////m8H////6/+b9//j/2wBDASstLTw1PHZBQXb4pYyl+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj/wAARCAAoACgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwA=", Base64.DEFAULT)
    }

    fun inlineJpeg(b64: String?): ByteArray? {
        if (b64.isNullOrEmpty()) return null
        return try {
            val s = Base64.decode(b64, Base64.DEFAULT)
            if (s.size < 3 || s[0].toInt() != 1) return null
            val head = JPG_HEAD
            val out = ByteArray(head.size + s.size - 3 + 2)
            System.arraycopy(head, 0, out, 0, head.size)
            out[164] = s[1]
            out[166] = s[2]
            System.arraycopy(s, 3, out, head.size, s.size - 3)
            out[out.size - 2] = 0xFF.toByte()
            out[out.size - 1] = 0xD9.toByte()
            out
        } catch (_: Exception) {
            null
        }
    }
}
