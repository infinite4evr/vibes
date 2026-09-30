package app.tgdrive.engine

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File

/**
 * The interface's side of the engine: starts it, keeps it alive while the app is in use, and
 * follows its state (announced by [EngineService] through a file and a package-local broadcast).
 */
class EngineClient(private val context: Context) {
    private val prefs = context.getSharedPreferences("engine", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(checked(EngineState.read(context)))
    val state: StateFlow<EngineState> = _state.asStateFlow()

    /** "Try it with sample data" (the desktop's --demo): a made-up account instead of Telegram. */
    var demo: Boolean
        get() = prefs.getBoolean("demo", false)
        private set(v) { prefs.edit().putBoolean("demo", v).apply() }

    init {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) = refresh()
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(EngineService.BROADCAST_STATE),
            ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    fun refresh() {
        _state.value = checked(EngineState.read(context))
    }

    /** The state file outlives a crashed engine process: a Ready state whose process is gone is Stopped. */
    private fun checked(s: EngineState): EngineState =
        if ((s.phase == EngineState.Phase.Ready || s.phase == EngineState.Phase.Starting) && s.pid > 0 && !File("/proc/${s.pid}").exists())
            s.copy(phase = EngineState.Phase.Stopped) else s

    fun start(demo: Boolean = this.demo) {
        this.demo = demo
        send(EngineService.ACTION_START)
    }

    fun hold(reason: String, on: Boolean) {
        val i = Intent(context, EngineService::class.java).setAction(EngineService.ACTION_HOLD)
            .putExtra(EngineService.EXTRA_REASON, reason).putExtra(EngineService.EXTRA_ON, on).putExtra(EngineService.EXTRA_DEMO, demo)
        if (_state.value.ready) {
            // Already running (a foreground service): a plain message, allowed even from the background.
            runCatching { context.startService(i) }.onFailure { if (on) send(i) }
            return
        }
        if (on) send(i)   // letting go never needs to start anything
    }

    fun stop() {
        if (_state.value.phase == EngineState.Phase.Stopped) return
        runCatching { context.startService(Intent(context, EngineService::class.java).setAction(EngineService.ACTION_STOP)) }
    }

    /** Switch between the real account(s) and the sample data (a fresh engine process either way). */
    suspend fun restart(demo: Boolean) {
        stop()
        withTimeoutOrNull(30_000) { state.first { it.phase == EngineState.Phase.Stopped || it.phase == EngineState.Phase.Failed } }
        // The old process ends itself right after saying so; give it a moment to be gone.
        withTimeoutOrNull(5_000) {
            while (File("/proc/${_state.value.pid}").exists() && _state.value.pid > 0) kotlinx.coroutines.delay(100)
        }
        start(demo)
    }

    private fun send(action: String) = send(Intent(context, EngineService::class.java).setAction(action).putExtra(EngineService.EXTRA_DEMO, demo))

    private fun send(i: Intent) {
        try {
            ContextCompat.startForegroundService(context, i)
        } catch (e: Exception) {
            // Android 12+ refuses to start foreground services from the background; the app retries
            // when it comes back to the foreground.
            Log.w("TGDrive", "couldn't reach the engine: $e")
        }
    }
}
