package app.lumaclean

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import app.lumaclean.ui.LumaRoot
import kotlinx.coroutines.flow.MutableStateFlow

class MainActivity : ComponentActivity() {
    /** A screen requested by a shortcut or notification, consumed by the UI once shown. */
    private val pendingRoute = MutableStateFlow<String?>(null)

    private val container get() = (application as LumaApp).container

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        pendingRoute.value = intent?.getStringExtra(EXTRA_ROUTE)
        setContent { LumaRoot(container, pendingRoute) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra(EXTRA_ROUTE)?.let { pendingRoute.value = it }
    }

    override fun onResume() {
        super.onResume()
        container.perms.refresh()
    }

    companion object {
        const val EXTRA_ROUTE = "route"
    }
}
