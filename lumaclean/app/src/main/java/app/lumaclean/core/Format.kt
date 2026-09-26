package app.lumaclean.core

import android.text.format.DateUtils
import java.text.DateFormat
import java.text.NumberFormat
import java.util.Date
import java.util.Locale

/** Sizes in SI units, the way Android's own Settings shows them. */
fun Long.formatBytes(): String {
    val b = coerceAtLeast(0)
    if (b < 1000) return "$b B"
    val units = arrayOf("KB", "MB", "GB", "TB")
    var v = b / 1000.0
    var i = 0
    while (v >= 1000 && i < units.lastIndex) {
        v /= 1000
        i++
    }
    val pattern = when {
        v >= 100 -> "%.0f %s"
        v >= 10 -> "%.1f %s"
        else -> "%.2f %s"
    }
    return String.format(Locale.getDefault(), pattern, v, units[i])
}

fun Int.formatCount(): String = NumberFormat.getIntegerInstance().format(this)

fun Long.formatCount(): String = NumberFormat.getIntegerInstance().format(this)

fun Long.relativeTime(): String =
    if (this <= 0) "never"
    else DateUtils.getRelativeTimeSpanString(this, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString()

fun Long.formatDate(): String =
    if (this <= 0) "—" else DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(this))

fun Long.formatDateTime(): String =
    if (this <= 0) "—" else DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(this))

fun Long.formatDuration(): String {
    val totalMin = this / 60_000
    val h = totalMin / 60
    val m = totalMin % 60
    return when {
        h >= 24 -> "${h / 24}d ${h % 24}h"
        h > 0 -> "${h}h ${m}m"
        m > 0 -> "${m}m"
        this > 0 -> "<1m"
        else -> "0m"
    }
}

fun Float.percent(): String = "${(this * 100).toInt()}%"

const val DAY_MS = 24L * 60 * 60 * 1000

fun daysAgo(days: Int): Long = System.currentTimeMillis() - days * DAY_MS
