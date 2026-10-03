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
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.auto(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.auto(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)
        val location = app.tgdrive.storage.DataLocation
        val crashed = location.launchFailed(this)
        if (!location.ready(this) || crashed) {
            // The startup screen runs in its own process: it still opens when this one can't.
            startActivity(Intent(this,app.tgdrive.storage.DataLocationActivity::class.java).putExtra("forward",intent).putExtra("recover",crashed))
            finish(); return
        }
        location.launchStarted(this)   // until the main screen is up (AppRoot)
        try { app.tgdrive.storage.PortablePreferences.attach(applicationContext); graph } catch(t:Throwable) {
            location.launchFinished(this)   // this screen is the answer; don't send the next launch to the startup screen
            val text=android.widget.TextView(this).apply { this.text="TG Drive could not start.\n\n${t.message}\n\nOpen TG Drive again to choose a data folder or view startup details."; setPadding(30,40,30,30); setTextIsSelectable(true) }
            val box=android.widget.LinearLayout(this).apply { orientation=android.widget.LinearLayout.VERTICAL; addView(text); addView(android.widget.Button(this@MainActivity).apply { this.text="Choose data folder"; setOnClickListener { app.tgdrive.storage.DataLocation.openChooser(this@MainActivity) } }) }
            setContentView(box)
            app.tgdrive.diag.AppLog.e("startup","Main screen initialization failed",t)
            return
        }
        app.tgdrive.engine.BackgroundSync.schedule(this)
        ProcessLifecycleOwner.get().lifecycle.addObserver(appVisibility)
        handle(intent)
        setContent { AppRoot(this) }
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
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

    override fun onDestroy() {
        ProcessLifecycleOwner.get().lifecycle.removeObserver(appVisibility)
        super.onDestroy()
    }

    /** While the app is on screen the engine stays up; a minute after it leaves, the engine may stop. */
    private val appVisibility = object : DefaultLifecycleObserver {
        override fun onStart(owner: LifecycleOwner) {
            val g = graph
            if (g.state.needsWelcome()) return   // nothing runs until the first-run choice
            g.engine.hold("ui", true)             // starts the engine if it isn't running
            if (g.engine.keepRunning) g.engine.hold("keep", true)
            g.scope.launch(kotlinx.coroutines.Dispatchers.IO) {
                val pending = runCatching { app.tgdrive.engine.UploadJournal(this@MainActivity).list().any { it.demo == g.engine.demo && it.error.isEmpty() } }.getOrDefault(false)
                if (pending) withContext(kotlinx.coroutines.Dispatchers.Main) {
                    runCatching { ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, app.tgdrive.engine.UploadService::class.java)) }
                        .onFailure { app.tgdrive.diag.AppLog.w("upload", "Pending uploads can be retried in Recovery", it) }
                }
            }
        }

        override fun onStop(owner: LifecycleOwner) {
            graph.engine.hold("ui", false)
        }
    }

    companion object {
        const val EXTRA_OPEN_PATH = "open_path"
        const val EXTRA_OPEN_PLAYER = "open_player"
        const val EXTRA_OPEN_SCREEN = "open_screen"
    }
}
