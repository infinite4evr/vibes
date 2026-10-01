package app.tgdrive.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

private val backSheet = PathParser().parsePathString(
    "M104 174a36 36 0 0 1 36-36h66a36 36 0 0 1 25.5 10.5L253 170h119a36 36 0 0 1 36 36v134a44 44 0 0 1-44 44H148a44 44 0 0 1-44-44z").toPath()
private val front = PathParser().parsePathString(
    "M104 234a34 34 0 0 1 34-34h236a34 34 0 0 1 34 34v106a44 44 0 0 1-44 44H148a44 44 0 0 1-44-44z").toPath()
private val wing = PathParser().parsePathString("M186 296 336 238 256 314z").toPath()
private val wing2 = PathParser().parsePathString("M256 314 336 238 306 356z").toPath()
private val wing3 = PathParser().parsePathString("M256 314 306 356 262 338 250 360z").toPath()

/** TG Drive's mark (tgdrive/web/icon.svg): the gradient tile, the folder and the paper plane. */
@Composable
fun TgLogo(size: Dp = 64.dp, modifier: Modifier = Modifier) {
    Canvas(modifier.size(size)) {
        val s = this.size.minDimension / 464f
        scale(s, s, pivot = Offset.Zero) {
            translate(-24f, -20f) {
                drawRoundRect(
                    Brush.linearGradient(listOf(Color(0xFF38B6FF), Color(0xFF3D7BF5), Color(0xFF5A4FE0)),
                        start = Offset(70f, 20f), end = Offset(442f, 484f)),
                    topLeft = Offset(24f, 20f), size = Size(464f, 464f), cornerRadius = CornerRadius(106f))
                drawRoundRect(
                    Brush.verticalGradient(0f to Color.White.copy(alpha = .28f), .5f to Color.Transparent, startY = 20f, endY = 484f),
                    topLeft = Offset(24f, 20f), size = Size(464f, 464f), cornerRadius = CornerRadius(106f))
                translate(0f, -4f) {
                    drawPath(backSheet, Color.White.copy(alpha = .5f))
                    drawPath(front, Brush.verticalGradient(listOf(Color.White, Color(0xFFE9F0FF)), startY = 200f, endY = 384f))
                    drawPath(wing, Brush.linearGradient(listOf(Color(0xFF3FA9FF), Color(0xFF3A6FF0)), start = Offset(186f, 238f), end = Offset(336f, 314f)))
                    drawPath(wing2, Color(0xFF2553D6))
                    drawPath(wing3, Color(0xFF1B3FAE))
                }
            }
        }
    }
}
