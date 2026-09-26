package app.lumaclean.data

import android.content.ContentUris
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import android.provider.MediaStore
import androidx.exifinterface.media.ExifInterface
import app.lumaclean.core.Progress
import app.lumaclean.core.formatBytes
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File
import java.io.FileOutputStream
import kotlin.math.abs
import kotlin.math.max

data class Photo(
    val id: Long,
    val uri: Uri,
    val path: String?,
    val name: String,
    val size: Long,
    val taken: Long,
    val width: Int,
    val height: Int,
) {
    val pixels: Long get() = width.toLong() * height
}

data class SimilarGroup(val photos: List<Photo>, val best: Photo) {
    val reclaimable: Long get() = photos.filter { it != best }.sumOf { it.size }
}

enum class CompressLevel(val label: String, val quality: Int, val maxSide: Int, val hint: String) {
    HIGH("High quality", 90, 3072, "Hardly any visible difference"),
    BALANCED("Balanced", 82, 2560, "Best size-to-quality ratio"),
    SMALL("Smallest", 72, 1920, "Great for sharing and old photos"),
}

data class CompressResult(val done: Int, val skipped: Int, val before: Long, val after: Long) {
    val saved: Long get() = (before - after).coerceAtLeast(0)
}

class MediaRepository(private val context: Context) {
    private val resolver = context.contentResolver
    private val imagesUri = MediaStore.Images.Media.EXTERNAL_CONTENT_URI

    @Suppress("DEPRECATION")
    fun photos(minBytes: Long = 0, limit: Int = Int.MAX_VALUE, jpegOnly: Boolean = false): List<Photo> {
        val projection = arrayOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DATA,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.SIZE,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Images.Media.DATE_MODIFIED,
            MediaStore.Images.Media.WIDTH,
            MediaStore.Images.Media.HEIGHT,
            MediaStore.Images.Media.MIME_TYPE,
        )
        val selection = buildString {
            append("${MediaStore.Images.Media.SIZE} >= ?")
            if (jpegOnly) append(" AND ${MediaStore.Images.Media.MIME_TYPE} = 'image/jpeg'")
        }
        val out = ArrayList<Photo>()
        runCatching {
            resolver.query(imagesUri, projection, selection, arrayOf(minBytes.toString()), "${MediaStore.Images.Media.DATE_MODIFIED} DESC")?.use { c ->
                val id = c.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
                val data = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATA)
                val name = c.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME)
                val size = c.getColumnIndexOrThrow(MediaStore.Images.Media.SIZE)
                val taken = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_TAKEN)
                val modified = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_MODIFIED)
                val w = c.getColumnIndexOrThrow(MediaStore.Images.Media.WIDTH)
                val h = c.getColumnIndexOrThrow(MediaStore.Images.Media.HEIGHT)
                while (c.moveToNext() && out.size < limit) {
                    val rowId = c.getLong(id)
                    val t = c.getLong(taken).takeIf { it > 0 } ?: (c.getLong(modified) * 1000)
                    out += Photo(
                        id = rowId,
                        uri = ContentUris.withAppendedId(imagesUri, rowId),
                        path = c.getString(data),
                        name = c.getString(name) ?: "Photo",
                        size = c.getLong(size),
                        taken = t,
                        width = c.getInt(w),
                        height = c.getInt(h),
                    )
                }
            }
        }
        return out
    }

    /**
     * Bursts and near-identical shots: photos taken within a few minutes of each other whose
     * 64-bit difference hashes differ in only a few bits. The sharpest, largest one is kept.
     */
    suspend fun findSimilar(progress: Progress, limit: Int = 3000): List<SimilarGroup> {
        val ctx = currentCoroutineContext()
        progress.report(null, "Loading your photos…", force = true)
        val photos = photos(limit = limit).filter { it.path?.contains("/.") != true }.sortedBy { it.taken }
        val hashes = LongArray(photos.size)
        val ok = BooleanArray(photos.size)
        photos.forEachIndexed { i, p ->
            ctx.ensureActive()
            progress.report(0.9f * i / photos.size.coerceAtLeast(1), "Looking at photo ${i + 1} of ${photos.size}")
            dHash(p.uri)?.let { hashes[i] = it; ok[i] = true }
        }
        progress.report(0.95f, "Grouping similar shots…", force = true)
        val window = 5 * 60_000L
        val used = BooleanArray(photos.size)
        val groups = ArrayList<SimilarGroup>()
        for (i in photos.indices) {
            if (used[i] || !ok[i]) continue
            val members = arrayListOf(photos[i])
            var j = i + 1
            while (j < photos.size && photos[j].taken - photos[i].taken <= window) {
                if (!used[j] && ok[j] && java.lang.Long.bitCount(hashes[i] xor hashes[j]) <= 8 && sameShape(photos[i], photos[j])) {
                    used[j] = true
                    members += photos[j]
                }
                j++
            }
            if (members.size > 1) {
                used[i] = true
                val best = members.maxWith(compareBy<Photo>({ it.pixels }, { it.size }))
                groups += SimilarGroup(members, best)
            }
        }
        return groups.sortedByDescending { it.taken() }
    }

    private fun SimilarGroup.taken() = photos.maxOf { it.taken }

    private fun sameShape(a: Photo, b: Photo): Boolean {
        if (a.width <= 0 || a.height <= 0 || b.width <= 0 || b.height <= 0) return true
        return abs(a.width.toDouble() / a.height - b.width.toDouble() / b.height) < 0.05
    }

    private fun dHash(uri: Uri): Long? = runCatching {
        val bmp = decodeSampled(uri, 64) ?: return@runCatching null
        val scaled = Bitmap.createScaledBitmap(bmp, 9, 8, true)
        if (scaled !== bmp) bmp.recycle()
        var hash = 0L
        var bit = 0
        for (y in 0 until 8) {
            for (x in 0 until 8) {
                if (luma(scaled.getPixel(x, y)) > luma(scaled.getPixel(x + 1, y))) hash = hash or (1L shl bit)
                bit++
            }
        }
        scaled.recycle()
        hash
    }.getOrNull()

    private fun luma(c: Int) = ((c shr 16) and 0xff) * 299 + ((c shr 8) and 0xff) * 587 + (c and 0xff) * 114

    private fun decodeSampled(uri: Uri, target: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0) return null
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= target) sample *= 2
        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        return resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
    }

    /**
     * Re-encodes large JPEGs. Keeps the date, location and camera details. With [replace] the
     * smaller file takes the original's place; otherwise a copy lands next to it. Files that
     * wouldn't get meaningfully smaller are left alone.
     */
    suspend fun compress(items: List<Photo>, level: CompressLevel, replace: Boolean, progress: Progress): CompressResult {
        val ctx = currentCoroutineContext()
        var done = 0
        var skipped = 0
        var before = 0L
        var after = 0L
        val touched = ArrayList<String>()
        items.forEachIndexed { i, photo ->
            ctx.ensureActive()
            progress.report(i / items.size.toFloat(), "Compressing ${photo.name} · saved ${(before - after).coerceAtLeast(0).formatBytes()}")
            val src = photo.path?.let(::File)
            if (src == null || !src.canRead()) {
                skipped++
                return@forEachIndexed
            }
            val tmp = File(context.cacheDir, "compress_${photo.id}.jpg")
            val ok = runCatching { encode(src, tmp, level) }.getOrDefault(false)
            if (!ok || tmp.length() <= 0 || tmp.length() > src.length() * 0.9) {
                tmp.delete()
                skipped++
                return@forEachIndexed
            }
            val originalTime = src.lastModified()
            val originalSize = src.length()
            val target = if (replace) src else uniqueFile(src.parentFile!!, src.nameWithoutExtension + "_small.jpg")
            val moved = runCatching { tmp.copyTo(target, overwrite = true); true }.getOrDefault(false)
            tmp.delete()
            if (!moved) {
                skipped++
                return@forEachIndexed
            }
            target.setLastModified(originalTime)
            before += originalSize
            after += target.length()
            done++
            touched += target.absolutePath
        }
        runCatching { android.media.MediaScannerConnection.scanFile(context, touched.toTypedArray(), null, null) }
        return CompressResult(done, skipped, before, after)
    }

    private fun encode(src: File, dest: File, level: CompressLevel): Boolean {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(src.absolutePath, bounds)
        if (bounds.outWidth <= 0) return false
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= level.maxSide) sample *= 2
        var bmp = BitmapFactory.decodeFile(src.absolutePath, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return false

        val exif = runCatching { ExifInterface(src.absolutePath) }.getOrNull()
        val largest = max(bmp.width, bmp.height)
        if (largest > level.maxSide) {
            val s = level.maxSide.toFloat() / largest
            val scaled = Bitmap.createScaledBitmap(bmp, (bmp.width * s).toInt(), (bmp.height * s).toInt(), true)
            if (scaled !== bmp) bmp.recycle()
            bmp = scaled
        }
        val rotation = when (exif?.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
        if (rotation != 0f) {
            val rotated = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, Matrix().apply { postRotate(rotation) }, true)
            if (rotated !== bmp) bmp.recycle()
            bmp = rotated
        }
        FileOutputStream(dest).use { bmp.compress(Bitmap.CompressFormat.JPEG, level.quality, it) }
        bmp.recycle()

        if (exif != null) runCatching {
            val out = ExifInterface(dest.absolutePath)
            keptTags.forEach { tag -> exif.getAttribute(tag)?.let { out.setAttribute(tag, it) } }
            out.setAttribute(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL.toString())
            out.saveAttributes()
        }
        return true
    }

    private val keptTags = listOf(
        ExifInterface.TAG_DATETIME, ExifInterface.TAG_DATETIME_ORIGINAL, ExifInterface.TAG_DATETIME_DIGITIZED,
        ExifInterface.TAG_OFFSET_TIME, ExifInterface.TAG_OFFSET_TIME_ORIGINAL,
        ExifInterface.TAG_GPS_LATITUDE, ExifInterface.TAG_GPS_LATITUDE_REF, ExifInterface.TAG_GPS_LONGITUDE,
        ExifInterface.TAG_GPS_LONGITUDE_REF, ExifInterface.TAG_GPS_ALTITUDE, ExifInterface.TAG_GPS_ALTITUDE_REF,
        ExifInterface.TAG_GPS_TIMESTAMP, ExifInterface.TAG_GPS_DATESTAMP,
        ExifInterface.TAG_MAKE, ExifInterface.TAG_MODEL, ExifInterface.TAG_F_NUMBER, ExifInterface.TAG_EXPOSURE_TIME,
        ExifInterface.TAG_PHOTOGRAPHIC_SENSITIVITY, ExifInterface.TAG_FOCAL_LENGTH, ExifInterface.TAG_IMAGE_DESCRIPTION,
    )
}
