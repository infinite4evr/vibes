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
