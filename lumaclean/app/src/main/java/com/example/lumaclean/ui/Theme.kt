package com.example.lumaclean.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Dark = darkColorScheme(
    primary = Color(0xFF65E6C4),
    onPrimary = Color(0xFF00211A),
    secondary = Color(0xFF8FA8FF),
    tertiary = Color(0xFFFFB87A),
    background = Color(0xFF081018),
    surface = Color(0xFF0E1823),
    surfaceVariant = Color(0xFF152231),
    onBackground = Color(0xFFF1F6FA),
    onSurface = Color(0xFFF1F6FA),
    onSurfaceVariant = Color(0xFFB8C4D1)
)

private val Light = lightColorScheme(
    primary = Color(0xFF006B58),
    secondary = Color(0xFF405A9E),
    tertiary = Color(0xFF8C4A00),
    background = Color(0xFFF7FAFC),
    surface = Color.White,
    surfaceVariant = Color(0xFFE9EFF5),
    onBackground = Color(0xFF111820),
    onSurface = Color(0xFF111820)
)

@Composable
fun LumaCleanTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) Dark else Light,
        typography = MaterialTheme.typography,
        content = content
    )
}
