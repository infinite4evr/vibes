package com.example.lumaclean.util

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

fun formatBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = arrayOf("KB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var i = -1
    do {
        value /= 1024.0
        i++
    } while (value >= 1024 && i < units.lastIndex)
    return if (value >= 100) "%.0f %s".format(value, units[i])
    else "%.1f %s".format(value, units[i])
}

fun formatDate(epochMillis: Long): String {
    if (epochMillis <= 0) return "Never"
    return SimpleDateFormat("dd MMM yyyy", Locale.getDefault()).format(Date(epochMillis))
}
