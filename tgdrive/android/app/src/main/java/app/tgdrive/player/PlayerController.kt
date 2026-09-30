package app.tgdrive.player

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import app.tgdrive.data.AppState
import app.tgdrive.data.FileItem
import app.tgdrive.util.Format
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * The interface's handle on the background player (desktop: the mini player with a queue and
 * playback speed, remembered). Talks to [PlayerService] through a Media3 controller.
 */
@Stable
class PlayerController private constructor(private val ctx: Context) {
    private var controller: MediaController? = null
    private val files = HashMap<String, FileItem>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var ticker: Job? = null
    private val prefs = ctx.getSharedPreferences("player", Context.MODE_PRIVATE)

    var current by mutableStateOf<FileItem?>(null)
        private set
    var playing by mutableStateOf(false)
        private set
    var buffering by mutableStateOf(false)
        private set
    var position by mutableLongStateOf(0L)
        private set
    var duration by mutableLongStateOf(0L)
        private set
    var speed by mutableFloatStateOf(prefs.getFloat("speed", 1f))
        private set
    var queueSize by mutableStateOf(0)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    private val listener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) = sync(player)
    }

    private fun connect(then: (MediaController) -> Unit) {
        controller?.let { return then(it) }
        val token = SessionToken(ctx, ComponentName(ctx, PlayerService::class.java))
        val future = MediaController.Builder(ctx, token).buildAsync()
        future.addListener({
            val c = runCatching { future.get() }.getOrNull() ?: return@addListener
            controller = c
            c.addListener(listener)
            sync(c)
            then(c)
        }, ContextCompat.getMainExecutor(ctx))
    }

    private fun sync(p: Player) {
        current = p.currentMediaItem?.mediaId?.let { files[it] }
        playing = p.isPlaying
        buffering = p.playbackState == Player.STATE_BUFFERING
        position = p.currentPosition.coerceAtLeast(0)
        duration = p.duration.takeIf { it > 0 } ?: ((current?.duration ?: 0.0) * 1000).toLong()
        queueSize = p.mediaItemCount
        error = p.playerError?.let { "Couldn't play this: ${it.errorCodeName}" }
        if (playing && ticker?.isActive != true) {
            ticker = scope.launch {
                while (isActive) {
                    delay(500)
                    controller?.let { position = it.currentPosition.coerceAtLeast(0) }
                }
            }
        } else if (!playing) ticker?.cancel()
    }

    /** Play `start` and queue the rest of `list` after it (songs and voice notes of a folder or search). */
    fun playList(state: AppState, list: List<FileItem>, start: FileItem) {
        val aid = state.aid.value
        val token = state.api.token
        val items = list.map { f ->
            val id = PlayerService.mediaId(aid, f.ref)
            files[id] = f
            MediaItem.Builder()
                .setMediaId(id)
                .setUri(state.api.streamUrl(aid, f))
                .setMimeType(f.mime)
                .setMediaMetadata(MediaMetadata.Builder()
                    .setTitle(f.audioTitle ?: f.displayName)
                    .setArtist(f.performer ?: f.chatTitle)
                    .setAlbumTitle(f.chatTitle)
                    .setArtworkUri(if (f.hasThumb) Uri.parse(state.api.thumbUrl(aid, f.chatId, f.msgId, "b") + "&t=$token") else null)
                    .build())
                .build()
        }
        val startIndex = list.indexOfFirst { it.key == start.key }.coerceAtLeast(0)
        val resume = if (!start.watched && start.playPos > 5) (start.playPos * 1000).toLong() else 0L
        connect { c ->
            c.setMediaItems(items, startIndex, resume)
            c.playbackParameters = PlaybackParameters(speed)
            c.prepare()
            c.play()
        }
    }

    fun toggle() = connect { if (it.isPlaying) it.pause() else { if (it.playbackState == Player.STATE_ENDED) it.seekTo(0); it.play() } }
    fun seekTo(ms: Long) = connect { it.seekTo(ms) }
    fun skip(seconds: Int) = connect { it.seekTo((it.currentPosition + seconds * 1000L).coerceAtLeast(0)) }
    fun next() = connect { if (it.hasNextMediaItem()) it.seekToNextMediaItem() }
    fun previous() = connect { if (it.currentPosition > 3000 || !it.hasPreviousMediaItem()) it.seekTo(0) else it.seekToPreviousMediaItem() }
    fun stop() = connect { it.stop(); it.clearMediaItems(); current = null }

    fun setSpeed(s: Float) {
        speed = s
        prefs.edit().putFloat("speed", s).apply()
        connect { it.playbackParameters = PlaybackParameters(s) }
    }

    fun pauseForVideo() = controller?.let { if (it.isPlaying) it.pause() }

    val positionLabel: String get() = Format.duration(position / 1000.0)
    val durationLabel: String get() = if (duration > 0) Format.duration(duration / 1000.0) else "–:––"

    companion object {
        @Volatile private var instance: PlayerController? = null
        fun get(ctx: Context): PlayerController = instance ?: synchronized(this) {
            instance ?: PlayerController(ctx.applicationContext).also { instance = it }
        }
        val SPEEDS = listOf(0.75f, 1f, 1.25f, 1.5f, 1.75f, 2f)
    }
}
