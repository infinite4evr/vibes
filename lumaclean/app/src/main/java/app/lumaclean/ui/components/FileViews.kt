@file:OptIn(ExperimentalFoundationApi::class)

package app.lumaclean.ui.components

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.InsertDriveFile
import androidx.compose.material.icons.rounded.Android
import androidx.compose.material.icons.rounded.AudioFile
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.FolderZip
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Insights
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Movie
import androidx.compose.material.icons.rounded.PlayCircle
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.lumaclean.core.Perms
import app.lumaclean.core.startSafely
import app.lumaclean.data.FileCategory
import app.lumaclean.data.FileTypes
import app.lumaclean.ui.theme.LocalExtraColors
import coil3.compose.AsyncImage
import java.io.File

fun categoryIcon(category: FileCategory): ImageVector = when (category) {
    FileCategory.IMAGES -> Icons.Rounded.Image
    FileCategory.VIDEOS -> Icons.Rounded.Movie
    FileCategory.AUDIO -> Icons.Rounded.AudioFile
    FileCategory.DOCUMENTS -> Icons.Rounded.Description
    FileCategory.APKS -> Icons.Rounded.Android
    FileCategory.ARCHIVES -> Icons.Rounded.FolderZip
    FileCategory.OTHER -> Icons.AutoMirrored.Rounded.InsertDriveFile
}

@Composable
fun categoryColor(category: FileCategory): Color = LocalExtraColors.current.categories[category] ?: MaterialTheme.colorScheme.primary

/** A thumbnail for photos and videos, a coloured type icon for everything else. */
@Composable
fun FileThumb(path: String, isDir: Boolean = false, modifier: Modifier = Modifier, size: Dp = 44.dp) {
    val name = path.substringAfterLast('/')
    val category = FileTypes.category(name)
    val shape = RoundedCornerShape(12.dp)
    if (isDir) {
        Box(
            modifier.size(size).clip(shape).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Rounded.Folder, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(size * 0.55f)) }
        return
    }
    val color = categoryColor(category)
    Box(modifier.size(size).clip(shape).background(color.copy(alpha = 0.14f)), contentAlignment = Alignment.Center) {
        Icon(categoryIcon(category), null, tint = color, modifier = Modifier.size(size * 0.5f))
        if (category == FileCategory.IMAGES || category == FileCategory.VIDEOS) {
            AsyncImage(model = File(path), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
    }
}

/** A square gallery cell with a selection tick. */
@Composable
fun MediaCell(
    model: Any,
    selected: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
    isVideo: Boolean = false,
    badge: String? = null,
) {
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier
            .aspectRatio(1f)
            .clip(shape)
            .background(MaterialTheme.colorScheme.surfaceContainerHighest)
            .then(if (selected) Modifier.border(3.dp, MaterialTheme.colorScheme.primary, shape) else Modifier)
            .combinedClickable(onClick = onClick, onLongClick = onLongClick),
    ) {
        AsyncImage(model = model, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        if (isVideo) {
            Icon(Icons.Rounded.PlayCircle, null, tint = Color.White, modifier = Modifier.align(Alignment.Center).size(32.dp))
        }
        if (badge != null) {
            Text(
                badge,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onPrimary,
                modifier = Modifier.align(Alignment.TopStart).padding(6.dp)
                    .clip(RoundedCornerShape(6.dp)).background(MaterialTheme.colorScheme.primary)
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            )
        }
        if (label != null) {
            Text(
                label,
                style = MaterialTheme.typography.labelSmall,
                color = Color.White,
                modifier = Modifier.align(Alignment.BottomStart).fillMaxWidth()
                    .background(Color.Black.copy(alpha = 0.45f)).padding(horizontal = 6.dp, vertical = 3.dp),
                maxLines = 1,
            )
        }
        if (selected) {
            Box(
                Modifier.align(Alignment.TopEnd).padding(6.dp).size(24.dp).clip(CircleShape).background(Color.White),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Rounded.CheckCircle, "Selected", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(24.dp))
            }
        }
    }
}

fun contentUri(path: String): Any = File(path)

@Composable
fun FilesPermissionCard(modifier: Modifier = Modifier, reason: String = "to find junk, duplicates and big files") {
    val context = LocalContext.current
    val container = LocalContainer.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { container.perms.refresh() }
    LumaCard(modifier, color = MaterialTheme.colorScheme.tertiaryContainer) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBadge(Icons.Rounded.Lock, MaterialTheme.colorScheme.tertiary)
            Spacer(Modifier.width(14.dp))
            Text("Allow access to files", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onTertiaryContainer)
        }
        Spacer(Modifier.height(8.dp))
        Text(
            "LumaClean needs file access $reason. Everything is checked on your phone: the app has no internet access at all.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onTertiaryContainer,
        )
        Spacer(Modifier.height(12.dp))
        Button(onClick = {
            if (Perms.needsSettingsForFiles) context.startSafely(Perms.allFilesIntent(context), Perms.allFilesFallbackIntent())
            else launcher.launch(Perms.legacyStorage)
        }) { Text("Allow access") }
    }
}

@Composable
fun UsagePermissionCard(reason: String, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    LumaCard(modifier, color = MaterialTheme.colorScheme.secondaryContainer) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBadge(Icons.Rounded.Insights, MaterialTheme.colorScheme.secondary)
            Spacer(Modifier.width(14.dp))
            Text("Allow usage access", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSecondaryContainer)
        }
        Spacer(Modifier.height(8.dp))
        Text(
            "Android keeps $reason behind \"Usage access\". Find LumaClean in the list and switch it on.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSecondaryContainer,
        )
        Spacer(Modifier.height(8.dp))
        TextButton(onClick = { context.startSafely(Perms.usageIntent(context)) }) { Text("Open settings") }
    }
}

fun fileUri(path: String): Uri = Uri.fromFile(File(path))
