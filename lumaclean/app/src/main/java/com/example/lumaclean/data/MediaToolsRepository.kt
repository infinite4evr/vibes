package com.example.lumaclean.data

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import com.example.lumaclean.model.MediaStats
import com.example.lumaclean.model.OptimizeResult
import com.example.lumaclean.model.PhotoItem
import com.example.lumaclean.model.SimilarPhotoGroup
import java.io.File
import java.io.FileOutputStream
import kotlin.math.max

class MediaToolsRepository(private val context: Context) {
    private val resolver = context.contentResolver

    fun mediaStats(): MediaStats {
        val images = sumCollection(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, screenshotAware = true)
        val videos = sumCollection(MediaStore.Video.Media.EXTERNAL_CONTENT_URI)
        val audio = sumCollection(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI)
        return MediaStats(
            imagesBytes = images.bytes,
            videosBytes = videos.bytes,
            audioBytes = audio.bytes,
            imageCount = images.count,
            videoCount = videos.count,
            audioCount = audio.count,
            screenshotCount = images.screenshots,
            screenshotBytes = images.screenshotBytes
        )
    }

    fun findSimilarPhotos(limit: Int = 400): List<SimilarPhotoGroup> {
        val photos = loadRecentPhotos(limit)
        val hashed = photos.mapNotNull { photo -> dHash(photo.uri)?.let { photo to it } }
        val used = BooleanArray(hashed.size)
        val groups = mutableListOf<SimilarPhotoGroup>()
        val timeWindow = 20L * 60 * 1000

        for (i in hashed.indices) {
            if (used[i]) continue
            val (base, baseHash) = hashed[i]
            val matches = mutableListOf(base)
            for (j in i + 1 until hashed.size) {
                if (used[j]) continue
                val (candidate, candidateHash) = hashed[j]
                if (kotlin.math.abs(base.modified - candidate.modified) > timeWindow) continue
                if (!similarAspect(base, candidate)) continue
                if (java.lang.Long.bitCount(baseHash xor candidateHash) <= 7) {
                    used[j] = true
                    matches += candidate
                }
            }
            if (matches.size > 1) {
                used[i] = true
                groups += SimilarPhotoGroup(matches)
            }
        }
        return groups.sortedByDescending { it.photos.sumOf(PhotoItem::sizeBytes) }
    }

    fun optimize(uris: List<Uri>, quality: Int = 80, maxDimension: Int = 2048): OptimizeResult {
        var created = 0
        var sourceBytes = 0L
        var outputBytes = 0L
        uris.forEachIndexed { index, uri ->
            val sourceSize = runCatching {
                resolver.query(uri, arrayOf(MediaStore.MediaColumns.SIZE), null, null, null)?.use { c ->
                    if (c.moveToFirst()) c.getLong(0) else 0L
                } ?: 0L
            }.getOrDefault(0L)
            val bitmap = decodeScaled(uri, maxDimension) ?: return@forEachIndexed
            val name = "Luma_${System.currentTimeMillis()}_$index.jpg"
            val written = writeOptimized(bitmap, name, quality)
            bitmap.recycle()
            if (written > 0) {
                created++
                sourceBytes += sourceSize
                outputBytes += written
            }
        }
        return OptimizeResult(created, sourceBytes, outputBytes)
    }

    private data class SumResult(
        val count: Int,
        val bytes: Long,
        val screenshots: Int = 0,
        val screenshotBytes: Long = 0
    )

    private fun sumCollection(uri: Uri, screenshotAware: Boolean = false): SumResult {
        val projection = mutableListOf(MediaStore.MediaColumns.SIZE, MediaStore.MediaColumns.DISPLAY_NAME)
        if (Build.VERSION.SDK_INT >= 29) projection += MediaStore.MediaColumns.RELATIVE_PATH
        var count = 0
        var bytes = 0L
        var shots = 0
        var shotBytes = 0L
        runCatching {
            resolver.query(uri, projection.toTypedArray(), null, null, null)?.use { c ->
                val sizeCol = c.getColumnIndexOrThrow(MediaStore.MediaColumns.SIZE)
                val nameCol = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                val pathCol = c.getColumnIndex(MediaStore.MediaColumns.RELATIVE_PATH)
                while (c.moveToNext()) {
                    val size = c.getLong(sizeCol)
                    count++
                    bytes += size
                    if (screenshotAware) {
                        val name = c.getString(nameCol).orEmpty().lowercase()
                        val path = if (pathCol >= 0) c.getString(pathCol).orEmpty().lowercase() else ""
                        if ("screenshot" in name || "screenshot" in path) {
                            shots++
                            shotBytes += size
                        }
                    }
                }
            }
        }
        return SumResult(count, bytes, shots, shotBytes)
    }

    private fun loadRecentPhotos(limit: Int): List<PhotoItem> {
        val uri = MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        val projection = arrayOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.SIZE,
            MediaStore.Images.Media.DATE_MODIFIED,
            MediaStore.Images.Media.WIDTH,
            MediaStore.Images.Media.HEIGHT
        )
        val out = mutableListOf<PhotoItem>()
        runCatching {
            resolver.query(uri, projection, null, null, "${MediaStore.Images.Media.DATE_MODIFIED} DESC")?.use { c ->
                val id = c.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
                val name = c.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME)
                val size = c.getColumnIndexOrThrow(MediaStore.Images.Media.SIZE)
                val modified = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_MODIFIED)
                val width = c.getColumnIndexOrThrow(MediaStore.Images.Media.WIDTH)
                val height = c.getColumnIndexOrThrow(MediaStore.Images.Media.HEIGHT)
                while (c.moveToNext() && out.size < limit) {
                    out += PhotoItem(
                        uri = ContentUris.withAppendedId(uri, c.getLong(id)),
                        name = c.getString(name) ?: "Photo",
                        sizeBytes = c.getLong(size),
                        modified = c.getLong(modified) * 1000L,
                        width = c.getInt(width),
                        height = c.getInt(height)
                    )
                }
            }
        }
        return out
    }

    private fun dHash(uri: Uri): Long? = runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openFileDescriptor(uri, "r")?.use { fd ->
            BitmapFactory.decodeFileDescriptor(fd.fileDescriptor, null, bounds)
        }
        var sample = 1
        val largest = max(bounds.outWidth, bounds.outHeight)
        while (largest / sample > 128) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample.coerceAtLeast(1) }
        val bmp = resolver.openFileDescriptor(uri, "r")?.use { fd ->
            BitmapFactory.decodeFileDescriptor(fd.fileDescriptor, null, options)
        } ?: return@runCatching null
        val scaled = Bitmap.createScaledBitmap(bmp, 9, 8, true)
        if (scaled !== bmp) bmp.recycle()
        var hash = 0L
        var bit = 0
        for (y in 0 until 8) {
            for (x in 0 until 8) {
                val a = scaled.getPixel(x, y)
                val b = scaled.getPixel(x + 1, y)
                val ga = (((a shr 16) and 0xff) * 30 + ((a shr 8) and 0xff) * 59 + (a and 0xff) * 11) / 100
                val gb = (((b shr 16) and 0xff) * 30 + ((b shr 8) and 0xff) * 59 + (b and 0xff) * 11) / 100
                if (ga > gb) hash = hash or (1L shl bit)
                bit++
            }
        }
        scaled.recycle()
        hash
    }.getOrNull()

    private fun similarAspect(a: PhotoItem, b: PhotoItem): Boolean {
        if (a.width <= 0 || a.height <= 0 || b.width <= 0 || b.height <= 0) return true
        val arA = a.width.toDouble() / a.height
        val arB = b.width.toDouble() / b.height
        return kotlin.math.abs(arA - arB) < 0.08
    }

    private fun decodeScaled(uri: Uri, maxDimension: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openFileDescriptor(uri, "r")?.use { fd -> BitmapFactory.decodeFileDescriptor(fd.fileDescriptor, null, bounds) }
        val largest = max(bounds.outWidth, bounds.outHeight)
        var sample = 1
        while (largest / sample > maxDimension * 2) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val decoded = resolver.openFileDescriptor(uri, "r")?.use { fd -> BitmapFactory.decodeFileDescriptor(fd.fileDescriptor, null, options) } ?: return null
        val decodedLargest = max(decoded.width, decoded.height)
        if (decodedLargest <= maxDimension) return decoded
        val scale = maxDimension.toFloat() / decodedLargest
        val resized = Bitmap.createScaledBitmap(decoded, (decoded.width * scale).toInt(), (decoded.height * scale).toInt(), true)
        if (resized !== decoded) decoded.recycle()
        return resized
    }

    private fun writeOptimized(bitmap: Bitmap, name: String, quality: Int): Long {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, name)
                put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
                put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/LumaClean")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return 0
            val bytes = runCatching {
                resolver.openOutputStream(uri)?.use { bitmap.compress(Bitmap.CompressFormat.JPEG, quality, it) }
                resolver.query(uri, arrayOf(MediaStore.Images.Media.SIZE), null, null, null)?.use { c -> if (c.moveToFirst()) c.getLong(0) else 0L } ?: 0L
            }.getOrDefault(0L)
            values.clear(); values.put(MediaStore.Images.Media.IS_PENDING, 0); resolver.update(uri, values, null, null)
            bytes
        } else {
            val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "LumaClean").apply { mkdirs() }
            val out = File(dir, name)
            FileOutputStream(out).use { bitmap.compress(Bitmap.CompressFormat.JPEG, quality, it) }
            MediaScannerConnection.scanFile(context, arrayOf(out.absolutePath), arrayOf("image/jpeg"), null)
            out.length()
        }
    }
}
