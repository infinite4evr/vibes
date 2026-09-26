package com.example.lumaclean.data

import android.content.Context
import android.os.Environment
import android.os.StatFs
import com.example.lumaclean.model.StorageSnapshot
import java.io.File

class StorageRepository(private val context: Context) {
    fun snapshot(): StorageSnapshot {
        val internal = StatFs(Environment.getExternalStorageDirectory().absolutePath)
        val removable = context.getExternalFilesDirs(null)
            .firstOrNull { it != null && Environment.isExternalStorageRemovable(it) }
            ?.let { volumeRoot(it) }
            ?.takeIf { it.exists() }
            ?.let { StatFs(it.absolutePath) }

        return StorageSnapshot(
            totalBytes = internal.totalBytes,
            freeBytes = internal.availableBytes,
            removableTotalBytes = removable?.totalBytes ?: 0L,
            removableFreeBytes = removable?.availableBytes ?: 0L
        )
    }

    private fun volumeRoot(file: File): File {
        var current = file
        repeat(4) { current.parentFile?.let { current = it } }
        return current
    }
}
