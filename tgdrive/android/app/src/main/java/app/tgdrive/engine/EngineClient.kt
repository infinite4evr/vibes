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
import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.os.Build
import android.os.Handler
import android.os.Looper

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

    /** Settings → This phone → Keep running: the service stays up (indexing, live updates) while the app is closed. */
    var keepRunning: Boolean
        get() = prefs.getBoolean("keep", false)
        set(v) {
            prefs.edit().putBoolean("keep", v).apply()
            hold("keep", v)
        }

    /** The interface is on screen (it wants the service running). */
    @Volatile private var visible = false
    private var restarts = 0
    @Volatile private var requestedAt = 0L
    private val watch = Handler(Looper.getMainLooper())

    init {
        watch.postDelayed(::watchdog, WATCH_MS)
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) = refresh()
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(EngineService.BROADCAST_STATE),
            ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    fun refresh() {
        _state.value = checked(EngineState.read(context))
    }

    /** The state file outlives a crashed engine process: a Ready or Starting state whose process is
     *  gone (or whose pid now belongs to another process) is Stopped. */
    private fun checked(s: EngineState): EngineState =
        if ((s.phase == EngineState.Phase.Ready || s.phase == EngineState.Phase.Starting) && !alive(s.pid))
            s.copy(phase = EngineState.Phase.Stopped) else s

    private fun alive(pid: Int): Boolean = pid > 0 &&
        runCatching { File("/proc/$pid/cmdline").readText().trim('\u0000').endsWith(":engine") }.getOrDefault(false)

    /**
     * Every couple of seconds: a service process that died without saying so (killed by Android,
     * a native crash) is noticed, explained and, while the app is on screen, started again once;
     * the interface never waits on a service that is gone.
     */
    private fun watchdog() {
        watch.postDelayed(::watchdog, WATCH_MS)
        val file = EngineState.read(context)
        val shown = _state.value
        val gone = (file.phase == EngineState.Phase.Ready || file.phase == EngineState.Phase.Starting) && !alive(file.pid)
        if (!gone) {
            refresh()
            // Stopped while the app is on screen (a start that never reached the service): start it.
            val now = System.currentTimeMillis()
            if (file.phase == EngineState.Phase.Stopped && shown.phase != EngineState.Phase.Failed && visible && now - requestedAt > 8000) {
                requestedAt = now
                send(EngineService.ACTION_START)
            }
            return
        }
        val why = exitReason(file.pid)
        Log.w("TGDrive", "the service process ${file.pid} is gone ($why) while ${file.phase}")
        if (visible && restarts < 1 && file.phase == EngineState.Phase.Ready) {
            restarts++
            EngineState.write(context, file.copy(phase = EngineState.Phase.Stopped))
            start()
            return
        }
        val msg = if (file.phase == EngineState.Phase.Starting) "TG Drive's service stopped while starting (${file.stage.ifBlank { "early" }})."
        else "TG Drive's service stopped unexpectedly."
        val failed = file.copy(phase = EngineState.Phase.Failed, error = if (why.isNotBlank()) "$msg\n$why" else msg)
        EngineState.write(context, failed)
        _state.value = failed
    }

    /** Why Android ended the service's process, if it recorded that (Android 11+). */
    fun exitReason(pid: Int = 0): String {
        if (Build.VERSION.SDK_INT < 30) return ""
        return runCatching {
            val am = context.getSystemService(ActivityManager::class.java)
            val infos = am.getHistoricalProcessExitReasons(context.packageName, 0, 10)
                .filter { it.processName.endsWith(":engine") && (pid <= 0 || it.pid == pid) }
            infos.firstOrNull()?.let { i -> "${reasonName(i.reason)}${i.description?.let { ": $it" } ?: ""} (status ${i.status})" }.orEmpty()
        }.getOrDefault("")
    }

    /** The last few ways the service's process ended, for the details on the error screen. */
    fun exitHistory(): String {
        if (Build.VERSION.SDK_INT < 30) return "(needs Android 11)"
        return runCatching {
            val am = context.getSystemService(ActivityManager::class.java)
            am.getHistoricalProcessExitReasons(context.packageName, 0, 8).filter { it.processName.endsWith(":engine") }.joinToString("\n") { i ->
                "${java.time.Instant.ofEpochMilli(i.timestamp)} pid ${i.pid}: ${reasonName(i.reason)} ${i.description.orEmpty()} status ${i.status} importance ${i.importance}"
            }.ifBlank { "(none)" }
        }.getOrDefault("(unavailable)")
    }

    private fun reasonName(r: Int): String = when (r) {
        ApplicationExitInfo.REASON_CRASH -> "crashed"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "crashed in native code"
        ApplicationExitInfo.REASON_ANR -> "stopped responding"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "ended by Android (low memory)"
        ApplicationExitInfo.REASON_EXIT_SELF -> "ended itself"
        ApplicationExitInfo.REASON_SIGNALED -> "killed by a signal"
        ApplicationExitInfo.REASON_USER_REQUESTED -> "stopped by the user"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "ended by Android (too much CPU or memory)"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "failed to initialise"
        ApplicationExitInfo.REASON_PERMISSION_CHANGE -> "ended after a permission change"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "ended because something it needs died"
        else -> "ended (reason $r)"
    }

    fun start(demo: Boolean = this.demo) {
        this.demo = demo
        requestedAt = System.currentTimeMillis()
        send(EngineService.ACTION_START)
    }

    fun hold(reason: String, on: Boolean) {
        if (reason == "ui") { visible = on; if (on) { restarts = 0; requestedAt = System.currentTimeMillis() } }
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

    private companion object { const val WATCH_MS = 2000L }

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
