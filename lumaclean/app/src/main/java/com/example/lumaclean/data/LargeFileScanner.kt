package com.example.lumaclean.data

import android.content.ContentUris
import android.content.Context
import android.os.Build
import android.provider.MediaStore
import com.example.lumaclean.model.LargeFile

class LargeFileScanner(private val context: Context) {
    fun query(minBytes: Long = 100L * 1024 * 1024): List<LargeFile> {
        val resolver = context.contentResolver
        val collection = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL)
        } else {
            MediaStore.Files.getContentUri("external")
        }
        val projection = arrayOf(
            MediaStore.Files.FileColumns._ID,
            MediaStore.Files.FileColumns.DISPLAY_NAME,
            MediaStore.Files.FileColumns.SIZE,
            MediaStore.Files.FileColumns.DATE_MODIFIED,
            MediaStore.Files.FileColumns.MIME_TYPE
        )
        val selection = "${MediaStore.Files.FileColumns.SIZE} >= ?"
        val args = arrayOf(minBytes.toString())
        val order = "${MediaStore.Files.FileColumns.SIZE} DESC"
        val out = mutableListOf<LargeFile>()
        runCatching {
            resolver.query(collection, projection, selection, args, order)?.use { c ->
                val idCol = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns._ID)
                val nameCol = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DISPLAY_NAME)
                val sizeCol = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.SIZE)
                val dateCol = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DATE_MODIFIED)
                val mimeCol = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.MIME_TYPE)
                while (c.moveToNext()) {
                    val id = c.getLong(idCol)
                    out += LargeFile(
                        uri = ContentUris.withAppendedId(collection, id),
                        path = null,
                        name = c.getString(nameCol) ?: "Unnamed",
                        sizeBytes = c.getLong(sizeCol),
                        modified = c.getLong(dateCol) * 1000L,
                        mimeType = c.getString(mimeCol)
                    )
                }
            }
        }
        return out
    }
}
