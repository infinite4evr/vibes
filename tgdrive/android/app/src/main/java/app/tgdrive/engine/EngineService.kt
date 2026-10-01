package app.tgdrive.engine

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.Environment
import android.os.IBinder
import android.os.Process
import android.util.Base64
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.tgdrive.MainActivity
import app.tgdrive.R
import app.tgdrive.diag.AppLog
import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import kotlinx.serialization.json.buildJsonObject
import java.io.File
import java.security.SecureRandom
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/**
 * TG Drive's service (the desktop app's Python server: Telegram, index, search, streaming,
 * transfers) running in its own process, as on the desktop, so the interface never waits on it
 * and a crash in it can't take the interface down.
 *
 * It runs as a foreground service while the app is open, while something needs it (transfers,
 * the background player, "keep running" in Settings), and stops a minute after nothing does:
 * like the desktop app, TG Drive doesn't sit in the background using battery for nothing.
 *
 * The background sync ([SyncWorker]) binds to it instead of starting it: no notification, the
 * CPU-heavy jobs held, and it ends as soon as the sync lets go (unless the app opened meanwhile).
 */
class EngineService : Service() {

    private val exec = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "tgdrive-engine") }
    private var poll: ScheduledFuture<*>? = null
    private val holds = HashSet<String>()
    private var idleSince = 0L
    private var lastEvent = 0L
    private var state = EngineState()
    private var shuttingDown = false
    /** Started (by the app: a foreground service), not only bound by the background sync. */
    private var started = false
    private var foreground = false
    /** Python runs in background mode (started for a sync: CPU-heavy jobs held). */
    private var backgroundMode = false
    private val json = Json { ignoreUnknownKeys = true }

    override fun onBind(intent: Intent?): IBinder {
        val demo = intent?.getBooleanExtra(EXTRA_DEMO, false) ?: false
        exec.execute {
            AppLog.i("engine", "background sync bound (running: ${state.phase})")
            holds += HOLD_SYNC
            idleSince = 0
            if (state.phase == EngineState.Phase.Stopped) start(demo, background = !started)
        }
        return Binder()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        exec.execute {
            holds -= HOLD_SYNC
            idleSince = 0
            AppLog.i("engine", "background sync let go (started by the app: $started)")
            if (!started) shutdown()   // only the sync wanted it: stop now, nothing waits a minute
        }
        return false
    }

    override fun onCreate() {
        super.onCreate()
        createChannels(this)
        // Anything that escapes in this process ends it: say so first, so the app shows the error
        // instead of waiting for a service that is gone.
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            runCatching {
                AppLog.e("engine", "the service crashed", e)
                trace("crashed: ${e.stackTraceToString().take(4000)}")
                publish(state.copy(phase = EngineState.Phase.Failed, error = "TG Drive's service crashed: $e", pid = Process.myPid()))
            }
            previous?.uncaughtException(t, e)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        goForeground(getString(if (state.ready) R.string.engine_ready else R.string.engine_starting))
        val action = intent?.action ?: ACTION_START
        val demo = intent?.getBooleanExtra(EXTRA_DEMO, false) ?: false
        exec.execute {
            if (action != ACTION_STOP) started = true
            if (backgroundMode && action != ACTION_STOP && state.ready) {
                // The app opened during a background sync: everything runs normally again.
                runCatching { mobile().callAttr("set_background", false) }
                backgroundMode = false
            }
            when (action) {
                ACTION_START -> start(demo)
                ACTION_HOLD -> {
                    val reason = intent?.getStringExtra(EXTRA_REASON) ?: "ui"
                    val on = intent?.getBooleanExtra(EXTRA_ON, true) != false
                    if (on) holds += reason else holds -= reason
                    AppLog.d("engine", "hold $reason=$on → $holds")
                    idleSince = 0
                    if (state.phase == EngineState.Phase.Stopped) {
                        if (on) start(demo) else stopEverything()   // letting go of a stopped service: nothing to start
                    }
                }
                ACTION_STOP -> shutdown()
            }
        }
        return START_NOT_STICKY
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        // Android 15+ limits data-sync services to 6 hours a day: save everything and stop.
        exec.execute { shutdown() }
    }

    // ------------------------------------------------------------------ lifecycle
    private fun start(demo: Boolean, background: Boolean = false) {
        if (state.phase == EngineState.Phase.Ready || state.phase == EngineState.Phase.Starting) return
        if (shuttingDown) {
            // This process ends in a moment (Python can't start again in it): starting now would be cut off
            // half-way and look like a crash. The app's watchdog, or Android re-creating a bound service,
            // starts a fresh process instead.
            AppLog.i("engine", "start asked while stopping: left to a fresh process")
            return
        }
        startLog().delete()
        stage(EngineState(phase = EngineState.Phase.Starting, demo = demo, pid = Process.myPid()), "Preparing")
        try {
            stage(state, "Loading search (full-text index)")
            System.loadLibrary("tgfts5")
            stage(state, if (Python.isStarted()) "Starting Python" else "Unpacking Python (first start takes longer)")
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            val token = secret()
            val mediaToken = secret()
            stage(state, "Unpacking the meaning model")
            val model = modelDir()
            val opts = buildJsonObject {
                put("data_dir", File(filesDir, "tgdrive").absolutePath)
                put("download_dir", downloadDir().absolutePath)
                put("model_dir", model?.absolutePath ?: "")
                put("fts5_library", "libtgfts5.so")
                put("token", token)
                put("media_token", mediaToken)
                put("demo", demo)
                put("background", background)
            }
            backgroundMode = background
            stage(state, if (demo) "Starting TG Drive with sample data" else "Starting TG Drive")
            val out = mobile().callAttr("start", opts.toString()).toString()
            val info = json.parseToJsonElement(out).jsonObject
            trace("started: $out")
            publish(EngineState(
                phase = EngineState.Phase.Ready, port = info.int("port"), mediaPort = info.int("media_port"),
                token = token, mediaToken = mediaToken, demo = demo, pid = Process.myPid(),
                startedAt = System.currentTimeMillis(), crypto = info.str("crypto"), fts5 = info.str("fts5"),
                numpy = info["numpy"]?.jsonPrimitive?.boolean ?: false, version = info.str("version"),
                updatedAt = System.currentTimeMillis(),
            ))
            lastEvent = 0
            idleSince = 0
            poll = exec.scheduleWithFixedDelay({ tick() }, 2, 3, TimeUnit.SECONDS)
            updateNotification(getString(R.string.engine_ready), null)
        } catch (e: Throwable) {
            AppLog.e("engine", "the service didn't start (at “${state.stage}”)", e)
            trace("failed at “${state.stage}”: ${e.stackTraceToString().take(6000)}")
            val msg = (e as? PyException)?.message ?: e.toString()
            val last = msg.lineSequence().lastOrNull { it.isNotBlank() } ?: msg
            publish(state.copy(phase = EngineState.Phase.Failed, error = "$last\n(while: ${state.stage})"))
            // Python can't be restarted inside a process: end this one, the app starts a fresh one to retry.
            stopEverything()
        }
    }

    /** Say what the service is doing now (the app shows it under the spinner, and keeps a log of it). */
    private fun stage(s: EngineState, what: String) {
        trace(what)
        publish(s.copy(stage = what, updatedAt = System.currentTimeMillis()))
    }

    private fun startLog() = File(filesDir, START_LOG)

    private fun trace(line: String) {
        AppLog.i("engine", line.take(2000))
        runCatching { startLog().appendText("${java.time.Instant.now()} [${Process.myPid()}] $line\n") }
    }

    private fun tick() {
        if (shuttingDown || !state.ready) return
        try {
            val act = json.parseToJsonElement(mobile().callAttr("activity").toString()).jsonObject
            val running = act.int("running")
            if (act.long("events") != lastEvent) postEvents()
            val text = when {
                running > 0 -> resources.getQuantityString(R.plurals.engine_transfers, running, running) +
                    speedSuffix(act.long("speed"))
                act.str("indexing").isNotEmpty() -> getString(R.string.engine_indexing, act.str("indexing"))
                else -> getString(R.string.engine_ready)
            }
            val progress = if (running > 0 && act.long("size") > 0) (act.long("done") * 100 / act.long("size")).toInt() else null
            updateNotification(text, progress)
            val busy = holds.isNotEmpty() || running > 0
            val now = System.currentTimeMillis()
            if (busy) idleSince = 0
            else if (idleSince == 0L) idleSince = now
            else if (now - idleSince > IDLE_STOP_MS) shutdown()
        } catch (e: Throwable) {
            AppLog.w("engine", "status check failed", e)
        }
    }

    private fun postEvents() {
        val res = json.parseToJsonElement(mobile().callAttr("events_since", lastEvent).toString()).jsonObject
        lastEvent = res.long("last")
        if (!NotificationManagerCompat.from(this).areNotificationsEnabled()) return
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        for (ev in res["events"]?.jsonArray ?: return) {
            val e = ev.jsonObject
            if (e.str("kind") != "notify") continue
            val n = NotificationCompat.Builder(this, CHANNEL_DONE)
                .setSmallIcon(R.drawable.ic_stat_tgdrive)
                .setContentTitle(e.str("title"))
                .setContentText(e.str("body"))
                .setAutoCancel(true)
                .setContentIntent(openApp(this, e.str("path")))
                .build()
            NotificationManagerCompat.from(this).notify(e.int("id") % 100_000 + 1000, n)
        }
    }

    private fun shutdown() {
        if (shuttingDown) return
        AppLog.i("engine", "stopping (holds: $holds)")
        shuttingDown = true
        poll?.cancel(false)
        if (state.phase == EngineState.Phase.Ready || state.phase == EngineState.Phase.Starting) {
            updateNotification(getString(R.string.engine_stopping), null)
            try {
                mobile().callAttr("stop", 20.0)
            } catch (e: Throwable) {
                AppLog.w("engine", "stop failed", e)
            }
        }
        publish(EngineState(phase = EngineState.Phase.Stopped, demo = state.demo))
        stopEverything()
    }

    private fun stopEverything() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
        // Python keeps threads and state for the life of the process: end it so the next start is clean.
        exec.schedule({ Process.killProcess(Process.myPid()) }, 300, TimeUnit.MILLISECONDS)
    }

    private fun publish(s: EngineState) {
        state = s
        EngineState.write(this, s)
        sendBroadcast(Intent(BROADCAST_STATE).setPackage(packageName))
    }

    // ------------------------------------------------------------------ paths
    /** The phone's Download/TG Drive where Android lets apps write there directly (11+, or with the
     *  storage permission before that), else this app's own folder on the shared storage. */
    private fun downloadDir(): File {
        val pub = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "TG Drive")
        val allowed = Build.VERSION.SDK_INT >= 30 ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        if (allowed && writable(pub)) return pub
        val own = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: filesDir, "TG Drive")
        own.mkdirs()
        return own
    }

    private fun writable(dir: File): Boolean = try {
        dir.mkdirs()
        val probe = File(dir, ".tgdrive-probe")
        probe.writeText("")
        probe.delete()
        true
    } catch (_: Exception) {
        false
    }

    /** The meaning-search model ships as assets; Python needs real files, copied once per version. */
    private fun modelDir(): File? {
        val dir = File(filesDir, "model")
        return try {
            val names = assets.list("model")?.toList().orEmpty()
            if (names.isEmpty()) return null
            dir.mkdirs()
            for (n in names) {
                val target = File(dir, n)
                val size = assets.openFd("model/$n").use { it.length }
                if (target.length() != size) {
                    assets.open("model/$n").use { input -> target.outputStream().use { input.copyTo(it) } }
                }
            }
            dir
        } catch (e: Exception) {
            // Compressed asset (openFd fails): copy if missing.
            try {
                dir.mkdirs()
                for (n in assets.list("model").orEmpty()) {
                    val target = File(dir, n)
                    if (!target.exists()) assets.open("model/$n").use { i -> target.outputStream().use { i.copyTo(it) } }
                }
                dir
            } catch (e2: Exception) {
                AppLog.w("engine", "meaning model unavailable", e2)
                null
            }
        }
    }

    // ------------------------------------------------------------------ notification
    private fun goForeground(text: String) {
        val n = baseNotification(text, null)
        try {
            ServiceCompat.startForeground(this, NOTIFY_ID, n,
                if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
            foreground = true
        } catch (e: Exception) {
            // Android refused (15+: data-sync services have a daily time limit, reset when the app is opened;
            // 12+: not from the background). Serve anyway while the app is open; never crash over a notification.
            foreground = false
            AppLog.w("engine", "couldn't run as a foreground service; running without it", e)
        }
    }

    private fun updateNotification(text: String, progress: Int?) {
        if (!foreground) return   // bound by the background sync only: no notification
        if (shuttingDown && text != getString(R.string.engine_stopping)) return
        try {
            NotificationManagerCompat.from(this).notify(NOTIFY_ID, baseNotification(text, progress))
        } catch (_: SecurityException) {
        }
    }

    private fun baseNotification(text: String, progress: Int?): Notification {
        val stop = PendingIntent.getService(this, 1, Intent(this, EngineService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, CHANNEL_ENGINE)
            .setSmallIcon(R.drawable.ic_stat_tgdrive)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setShowWhen(false)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(openApp(this, null))
            .addAction(0, getString(R.string.engine_stop), stop)
            .apply { if (progress != null) setProgress(100, progress.coerceIn(0, 100), false) }
            .build()
    }

    private fun speedSuffix(bps: Long): String =
        if (bps <= 0) "" else " · " + app.tgdrive.util.Format.size(bps) + "/s"

    companion object {
        private const val TAG = "TGDriveEngine"
        const val ACTION_START = "app.tgdrive.engine.START"
        const val ACTION_HOLD = "app.tgdrive.engine.HOLD"
        const val ACTION_STOP = "app.tgdrive.engine.STOP"
        const val EXTRA_DEMO = "demo"
        const val EXTRA_REASON = "reason"
        const val EXTRA_ON = "on"
        const val BROADCAST_STATE = "app.tgdrive.engine.STATE"
        const val CHANNEL_ENGINE = "engine"
        const val CHANNEL_DONE = "transfers"
        private const val NOTIFY_ID = 1
        private const val IDLE_STOP_MS = 60_000L
        const val HOLD_SYNC = "sync"
        /** How the last start went, step by step (Settings → About and the error screen show it). */
        const val START_LOG = "engine-start.log"

        private fun mobile() = Python.getInstance().getModule("tgdrive.mobile")

        private fun secret(): String {
            val b = ByteArray(24)
            SecureRandom().nextBytes(b)
            return Base64.encodeToString(b, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        }

        fun createChannels(context: Context) {
            if (Build.VERSION.SDK_INT < 26) return
            val nm = context.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CHANNEL_ENGINE, context.getString(R.string.channel_engine),
                NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(false) })
            nm.createNotificationChannel(NotificationChannel(CHANNEL_DONE, context.getString(R.string.channel_transfers),
                NotificationManager.IMPORTANCE_DEFAULT))
        }

        /** Opens TG Drive on [screen] (see MainScreen's screenNamed), e.g. "transfers". */
        fun openScreen(context: Context, screen: String): PendingIntent {
            val i = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(MainActivity.EXTRA_OPEN_SCREEN, screen)
            return PendingIntent.getActivity(context, screen.hashCode(), i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }

        fun openApp(context: Context, path: String?): PendingIntent {
            val i = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            if (path != null) i.putExtra(MainActivity.EXTRA_OPEN_PATH, path)
            return PendingIntent.getActivity(context, path?.hashCode() ?: 0, i,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }
    }
}

private fun JsonObject.str(k: String): String = this[k]?.jsonPrimitive?.content ?: ""
private fun JsonObject.int(k: String): Int = this[k]?.jsonPrimitive?.int ?: 0
private fun JsonObject.long(k: String): Long = this[k]?.jsonPrimitive?.long ?: 0L
