package app.tgdrive.ui.theme

import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** One part of a desktop icon: an SVG path drawn with the icon's stroke, or filled. */
class P(val d: String, val fill: Boolean = false, val width: Float? = null)

/** A desktop line icon (24×24, 1.8 stroke, round caps), turned into an ImageVector on first use. */
class TgIcon(val name: String, private val parts: List<P>) {
    private val cache = HashMap<Float, ImageVector>(2)

    fun vector(stroke: Float = 1.8f): ImageVector = cache.getOrPut(stroke) {
        val b = ImageVector.Builder(name = name, defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f)
        for (p in parts) {
            val nodes = addPathNodes(p.d)
            if (p.fill) {
                b.addPath(nodes, fill = SolidColor(Color.Black))
            } else {
                b.addPath(nodes, stroke = SolidColor(Color.Black), strokeLineWidth = p.width ?: stroke,
                    strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round)
            }
        }
        b.build()
    }

    /** The same shape filled (stars, pins): used where the desktop sets `fill: currentColor`. */
    fun filled(): ImageVector = cache.getOrPut(-1f) {
        val b = ImageVector.Builder(name = "$name-filled", defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f)
        for (p in parts) b.addPath(addPathNodes(p.d), fill = SolidColor(Color.Black), stroke = SolidColor(Color.Black),
            strokeLineWidth = 1.8f, strokeLineJoin = StrokeJoin.Round, strokeLineCap = StrokeCap.Round)
        b.build()
    }
}

@Composable
fun TgIconView(icon: TgIcon, modifier: Modifier = Modifier, tint: Color = Tg.colors.ink2, size: Dp = 20.dp,
               stroke: Float = 1.8f, filled: Boolean = false, contentDescription: String? = null) {
    Icon(if (filled) icon.filled() else icon.vector(stroke), contentDescription, modifier.size(size), tint = tint)
}
