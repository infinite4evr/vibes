package app.tgdrive.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.vector.PathParser

/**
 * The sign-in QR code, drawn from the SVG TG Drive's service makes with segno: one path of
 * horizontal runs (`M x y h n m …`) stroked one module wide.
 */
@Composable
fun QrImage(svg: String, modifier: Modifier = Modifier) {
    val parsed = remember(svg) {
        val d = Regex("""class="qrline"[^>]*\sd="([^"]+)"""").find(svg)?.groupValues?.get(1)
        val width = Regex("""width="(\d+(?:\.\d+)?)"""").find(svg)?.groupValues?.get(1)?.toFloatOrNull()
        val scale = Regex("""scale\((\d+(?:\.\d+)?)\)""").find(svg)?.groupValues?.get(1)?.toFloatOrNull() ?: 1f
        if (d == null || width == null) null else PathParser().parsePathString(d).toPath() to width / scale
    }
    Canvas(modifier) {
        val (path, modules) = parsed ?: return@Canvas
        val k = size.minDimension / modules
        scale(k, k, pivot = androidx.compose.ui.geometry.Offset.Zero) {
            drawPath(path, Color(0xFF1C2331), style = Stroke(width = 1f))
        }
    }
}
