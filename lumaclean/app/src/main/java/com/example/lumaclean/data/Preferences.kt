package com.example.lumaclean.data

import android.content.Context
import android.net.Uri

class Preferences(context: Context) {
    private val prefs = context.getSharedPreferences("lumaclean", Context.MODE_PRIVATE)

    var sdTreeUri: Uri?
        get() = prefs.getString("sd_tree_uri", null)?.let(Uri::parse)
        set(value) { prefs.edit().putString("sd_tree_uri", value?.toString()).apply() }

    var scheduledScan: Boolean
        get() = prefs.getBoolean("scheduled_scan", false)
        set(value) { prefs.edit().putBoolean("scheduled_scan", value).apply() }

    var lastReclaimedBytes: Long
        get() = prefs.getLong("last_reclaimed", 0L)
        set(value) { prefs.edit().putLong("last_reclaimed", value).apply() }
}
