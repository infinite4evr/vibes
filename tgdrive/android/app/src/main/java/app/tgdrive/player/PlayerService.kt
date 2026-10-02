package app.tgdrive.player

import android.app.PendingIntent
import android.content.Intent
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import app.tgdrive.MainActivity
import app.tgdrive.data.FileRef
import app.tgdrive.graph
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * The background player (the desktop's mini player): songs, voice notes and lectures keep playing
 * with the screen off, with lock-screen and headset controls, a queue and playback speed. Streams
 * come from TG Drive's service, which is kept running while something plays; where each file
 * stopped is saved to TG Drive (Continue watching, resume).
 */
class PlayerService : MediaSessionService() {
    private var session: MediaSession? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var saver: Job? = null

    override fun onCreate() {
        super.onCreate()
        val http = DefaultHttpDataSource.Factory().setAllowCrossProtocolRedirects(false)
            .setConnectTimeoutMs(15_000).setReadTimeoutMs(60_000)
        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(), true)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .setSeekBackIncrementMs(10_000)
            .setSeekForwardIncrementMs(30_000)
            .build()
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                graph.engine.hold("playback", isPlaying || player.playbackState == Player.STATE_BUFFERING)
                if (isPlaying) startSaving(player) else savePosition(player)
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                savePosition(player, previous = true)
            }

            override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                // Said in the app's error dialog (with "Create GitHub issue") when it is open.
                val title = player.currentMediaItem?.mediaMetadata?.title ?: "a track"
                graph.state.message("Couldn't play $title: ${error.errorCodeName.removePrefix("ERROR_CODE_").lowercase().replace('_', ' ')}",
                    error = true, detail = app.tgdrive.diag.AppLog.stack(error).take(4000))
                // Skip a track that can't be played instead of stopping (desktop 2.4 behaviour).
                if (player.hasNextMediaItem()) {
                    player.seekToNextMediaItem()
                    player.prepare()
                    player.play()
                }
            }
        })
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_OPEN_PLAYER, true)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        session = MediaSession.Builder(this, player).setSessionActivity(open).build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        val p = session?.player
        if (p == null || !p.playWhenReady || p.mediaItemCount == 0) stopSelf()
    }

    override fun onDestroy() {
        session?.player?.let { savePosition(it); it.release() }
        session?.release()
        session = null
        graph.engine.hold("playback", false)
        scope.cancel()
        super.onDestroy()
    }

    private fun startSaving(player: Player) {
        saver?.cancel()
        saver = scope.launch {
            while (isActive) {
                delay(10_000)
                savePosition(player)
            }
        }
    }

    private var lastSaved: Pair<String, Long>? = null

    /** Where playback is, saved to TG Drive (the same place the desktop's player saves it). */
    private fun savePosition(player: Player, previous: Boolean = false) {
        val item = (if (previous) null else player.currentMediaItem) ?: player.currentMediaItem ?: return
        val (aid, ref) = parseId(item.mediaId) ?: return
        val pos = player.currentPosition / 1000.0
        val dur = player.duration.takeIf { it > 0 }?.div(1000.0)
        if (pos < 3) return
        val key = item.mediaId to (pos.toLong() / 5)
        if (lastSaved == key) return
        lastSaved = key
        val done = dur != null && pos > dur * 0.95
        scope.launch { runCatching { graph.api.savePlayback(aid, ref, pos, dur, if (done) true else null) } }
    }

    companion object {
        fun mediaId(aid: Long, ref: FileRef) = "$aid:${ref.chatId}:${ref.msgId}"
        fun parseId(id: String): Pair<Long, FileRef>? {
            val p = id.split(":")
            if (p.size != 3) return null
            return (p[0].toLongOrNull() ?: return null) to FileRef(p[1].toLongOrNull() ?: return null, p[2].toLongOrNull() ?: return null)
        }
    }
}
