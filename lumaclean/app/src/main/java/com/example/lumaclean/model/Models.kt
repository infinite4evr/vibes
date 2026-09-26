package com.example.lumaclean.model

import android.net.Uri

enum class JunkKind(val label: String) {
    APP_CACHE("LumaClean cache"),
    TEMP_FILE("Temporary files"),
    THUMBNAIL("Thumbnails"),
    OLD_APK("Old APK installers"),
    EMPTY_FOLDER("Empty folders"),
    LOG_FILE("Log files"),
    ZERO_BYTE("Zero-byte files")
}

enum class RiskLevel { SAFE, REVIEW }

data class CleanCandidate(
    val path: String,
    val name: String,
    val sizeBytes: Long,
    val kind: JunkKind,
    val risk: RiskLevel,
    val lastModified: Long,
    val isDirectory: Boolean = false
)

data class DuplicateFile(
    val path: String,
    val name: String,
    val sizeBytes: Long,
    val lastModified: Long
)

data class DuplicateGroup(
    val fingerprint: String,
    val files: List<DuplicateFile>
) {
    val reclaimableBytes: Long
        get() = if (files.size < 2) 0 else files.drop(1).sumOf { it.sizeBytes }
}

data class LargeFile(
    val uri: Uri? = null,
    val path: String?,
    val name: String,
    val sizeBytes: Long,
    val modified: Long,
    val mimeType: String?
)

data class InstalledAppInfo(
    val packageName: String,
    val label: String,
    val versionName: String,
    val cacheBytes: Long,
    val dataBytes: Long,
    val appBytes: Long,
    val lastUsed: Long,
    val systemApp: Boolean
) {
    val totalBytes: Long get() = cacheBytes + dataBytes + appBytes
}

data class StorageSnapshot(
    val totalBytes: Long = 0,
    val freeBytes: Long = 0,
    val removableTotalBytes: Long = 0,
    val removableFreeBytes: Long = 0
) {
    val usedBytes: Long get() = (totalBytes - freeBytes).coerceAtLeast(0)
    val usedFraction: Float get() = if (totalBytes <= 0) 0f else usedBytes.toFloat() / totalBytes
}

data class MigrationProgress(
    val currentName: String = "",
    val filesDone: Int = 0,
    val filesTotal: Int = 0,
    val bytesCopied: Long = 0,
    val complete: Boolean = false,
    val message: String = ""
)

data class MigrationResult(
    val copied: Int,
    val skipped: Int,
    val renamed: Int,
    val failed: Int,
    val bytesMoved: Long
)

data class MediaStats(
    val imagesBytes: Long = 0,
    val videosBytes: Long = 0,
    val audioBytes: Long = 0,
    val imageCount: Int = 0,
    val videoCount: Int = 0,
    val audioCount: Int = 0,
    val screenshotCount: Int = 0,
    val screenshotBytes: Long = 0
)

data class PhotoItem(
    val uri: Uri,
    val name: String,
    val sizeBytes: Long,
    val modified: Long,
    val width: Int,
    val height: Int
)

data class SimilarPhotoGroup(
    val photos: List<PhotoItem>
)

data class OptimizeResult(
    val created: Int,
    val sourceBytes: Long,
    val outputBytes: Long
) {
    val savedBytes: Long get() = (sourceBytes - outputBytes).coerceAtLeast(0)
}
