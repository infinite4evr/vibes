package app.tgdrive

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import app.tgdrive.ui.AppRoot
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {

    /** Files shared from another app, waiting for the user to pick where they go. */
    val incomingShare = MutableStateFlow<List<Uri>>(emptyList())
    val openPlayer = MutableStateFlow(false)
    /** A screen to show (from a notification: "transfers" …; see MainScreen's screenNamed). */
    val openScreen = MutableStateFlow<String?>(null)

    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        // Every step until the first screen shows is written down at once and watched: a hang opens the
        // startup screen with where it was stuck, instead of the launcher icon staying with nothing said.
        val trail = app.tgdrive.diag.StartupTrail
        trail.begin(this, "Main screen: opening")
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.auto(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.auto(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)
        val location = app.tgdrive.storage.DataLocation
        val crashed = location.launchFailed(this)
        trail.begin(this, "Main screen: checking the data folder")
        val problem = location.problem(this)
        if (problem != null && intent.getBooleanExtra(EXTRA_FROM_STARTUP, false)) {
            // The startup screen (its own process) has just found the folder usable, this process can't use
            // it: never send the person back there in a loop. A process started before storage access was
            // granted can keep its old view of storage: start a fresh one once, then say what is wrong.
            app.tgdrive.diag.AppLog.w("startup", "main screen can't use the data folder: $problem")
            if (!intent.getBooleanExtra(EXTRA_RESTARTED, false)) {
                trail.done(this, "Main screen can't use the data folder ($problem): restarting its process")
                startActivity(Intent(this, app.tgdrive.storage.DataLocationActivity::class.java).putExtra("relaunch", true)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
                finish()
                android.os.Process.killProcess(android.os.Process.myPid())   // the start above is already with Android
                return
            }
            trail.done(this, "Main screen can't use the data folder: $problem")
            startupProblem(problem)
            return
        }
        if (problem != null || crashed) {
            trail.done(this, if (crashed) "The last start never reached the main screen: opening the startup screen"
                else "Opening the startup screen: $problem")
            // The startup screen runs in its own process: it still opens when this one can't.
            startActivity(Intent(this,app.tgdrive.storage.DataLocationActivity::class.java).putExtra("forward",intent).putExtra("recover",crashed))
            finish(); return
        }
        location.launchStarted(this)   // until the main screen is up (AppRoot)
        if (BuildConfig.DEBUG && intent.getBooleanExtra(EXTRA_TEST_HANG, false)) {
            // Emulator tests only (debuggable builds): a launch whose main thread never comes back.
            trail.begin(this, "Main screen: a test launch that hangs")
            Thread.sleep(60_000)
        }
        trail.begin(this, "Main screen: loading the app's state")
        try { app.tgdrive.storage.PortablePreferences.attach(applicationContext); graph } catch(t:Throwable) {
            location.launchFinished(this)   // this screen is the answer; don't send the next launch to the startup screen
            trail.done(this, "Main screen couldn't start: $t")
            setContent { app.tgdrive.storage.StartupMessage("TG Drive could not start",
                "${t.message}\n\nChoose the data folder again, or open TG Drive again to see its startup details.",
                listOf("Choose data folder" to { app.tgdrive.storage.DataLocation.openChooser(this) })) }
            app.tgdrive.diag.AppLog.e("startup","Main screen initialization failed",t)
            return
        }
        if (app.tgdrive.storage.PortablePreferences.damagedNotice())
            android.widget.Toast.makeText(this, "The phone settings saved in TG Drive's data folder were damaged. " +
                "TG Drive kept this phone's own settings.", android.widget.Toast.LENGTH_LONG).show()
        app.tgdrive.engine.BackgroundSync.schedule(this)
        watchVisibility(applicationContext)
        handle(intent)
        trail.begin(this, "Main screen: drawing the first screen")   // until AppRoot is composed
        setContent { AppRoot(this) }
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    /** The reason, and the ways out (nothing here may depend on the data folder). */
    private fun startupProblem(problem: String) {
        val actions = mutableListOf<Pair<String, () -> Unit>>("Choose data folder" to { app.tgdrive.storage.DataLocation.openChooser(this) })
        if (Build.VERSION.SDK_INT >= 30) actions += "All-files access settings" to {
            runCatching { startActivity(Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName"))) }
            Unit
        }
        setContent { app.tgdrive.storage.StartupMessage("TG Drive can't open its data folder",
            "$problem\n\nChoose the folder again, or allow all-files access for TG Drive in Android's settings.", actions) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        when (intent?.action) {
            Intent.ACTION_SEND -> IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)?.let {
                incomingShare.value = listOf(it)
            }
            Intent.ACTION_SEND_MULTIPLE -> IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)?.let {
                incomingShare.value = it
            }
        }
        if (intent?.getBooleanExtra(EXTRA_OPEN_PLAYER, false) == true) openPlayer.value = true
        intent?.getStringExtra(EXTRA_OPEN_SCREEN)?.let { openScreen.value = it }
    }

    /** While the app is on screen the engine stays up; a minute after it leaves, the engine may stop. */
    private class AppVisibility(private val context: android.content.Context) : DefaultLifecycleObserver {
        override fun onStart(owner: LifecycleOwner) {
            val g = context.graph
            if (g.state.needsWelcome()) return   // nothing runs until the first-run choice
            g.engine.hold("ui", true)             // starts the engine if it isn't running
            if (g.engine.keepRunning) g.engine.hold("keep", true)
            g.scope.launch(kotlinx.coroutines.Dispatchers.IO) {
                val pending = runCatching { app.tgdrive.engine.UploadJournal(context).list().any { it.demo == g.engine.demo && it.error.isEmpty() } }.getOrDefault(false)
                if (pending) withContext(kotlinx.coroutines.Dispatchers.Main) {
                    runCatching { ContextCompat.startForegroundService(context, Intent(context, app.tgdrive.engine.UploadService::class.java)) }
                        .onFailure { app.tgdrive.diag.AppLog.w("upload", "Pending uploads can be retried in Recovery", it) }
                }
            }
        }

        override fun onStop(owner: LifecycleOwner) {
            context.graph.engine.hold("ui", false)
        }
    }

    companion object {
        /** Watched once per process and never unregistered: Android reports the app leaving the screen
         *  0.7 s after the last activity stops, often after that activity is already destroyed, and a
         *  per-activity observer removed in onDestroy would miss it. The "ui" hold then stayed on for
         *  good and the service never stopped (also after a background sync). */
        private var visibilityWatched = false
        private fun watchVisibility(context: android.content.Context) {
            if (visibilityWatched) return
            visibilityWatched = true
            ProcessLifecycleOwner.get().lifecycle.addObserver(AppVisibility(context))
        }

        /** Opened by the startup screen, which has just checked the data folder. */
        const val EXTRA_FROM_STARTUP = "from_startup"
        /** ... in a main-screen process started fresh for it. */
        const val EXTRA_RESTARTED = "restarted"
        const val EXTRA_OPEN_PATH = "open_path"
        const val EXTRA_OPEN_PLAYER = "open_player"
        const val EXTRA_OPEN_SCREEN = "open_screen"
        /** Debuggable builds only: the launch hangs (the emulator tests check the startup watchdog with it). */
        const val EXTRA_TEST_HANG = "test_hang"
    }
}
