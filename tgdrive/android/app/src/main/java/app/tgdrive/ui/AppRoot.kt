package app.tgdrive.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import app.tgdrive.MainActivity
import app.tgdrive.data.Phase
import app.tgdrive.data.double
import app.tgdrive.data.str
import app.tgdrive.graph
import app.tgdrive.ui.main.MainScreen
import app.tgdrive.ui.onboarding.ApiKeyScreen
import app.tgdrive.ui.onboarding.EngineFailedScreen
import app.tgdrive.ui.onboarding.LockScreen
import app.tgdrive.ui.onboarding.SignInScreen
import app.tgdrive.ui.onboarding.SplashScreen
import app.tgdrive.ui.onboarding.WelcomeScreen
import app.tgdrive.ui.theme.Appearance
import app.tgdrive.ui.theme.TgTheme
import kotlinx.coroutines.delay

@Composable
fun AppRoot(activity: MainActivity) {
    val g = activity.graph
    val state = g.state
    val settings by state.settings.collectAsState()
    val appearance = Appearance(
        theme = settings.str("theme") ?: "system",
        accent = settings.str("accent").orEmpty(),
        contrast = settings.str("contrast") ?: "normal",
        fontScale = settings.double("font_scale").toFloat().takeIf { it > 0 } ?: 1f,
        motion = settings.str("motion") ?: "on",
    )
    TgTheme(appearance) {
        val phase by state.phase.collectAsState()
        val engineState by g.engine.state.collectAsState()
        var seconds by remember { mutableStateOf(0) }
        LaunchedEffect(phase) {
            seconds = 0
            while (phase == Phase.Starting) { delay(1000); seconds++ }
        }
        val report = { app.tgdrive.engine.StartupReport.build(activity, g.engine, (phase as? Phase.Failed)?.error) }
        // TG Drive crashed last time: say so once, and offer to send the report.
        var crashes by remember { mutableStateOf(app.tgdrive.diag.AppLog.unseenCrashes(activity)) }
        if (crashes.isNotEmpty()) app.tgdrive.diag.CrashNotice(crashes) { crashes = emptyList() }
        AnimatedContent(
            targetState = phase::class,
            transitionSpec = { fadeIn(tween(220)) togetherWith fadeOut(tween(160)) },
            modifier = Modifier.fillMaxSize(),
            label = "phase",
        ) { _ ->
            Box(Modifier.fillMaxSize()) {
                when (val p = phase) {
                    Phase.Starting -> SplashScreen(engineState.stage, seconds, report, onRestart = { state.retryEngine() })
                    is Phase.Failed -> EngineFailedScreen(p.error, report, onRetry = { state.retryEngine() }, onSample = { state.chooseStart(true) })
                    Phase.Welcome -> WelcomeScreen(onSignIn = { state.chooseStart(false) }, onSample = { state.chooseStart(true) })
                    Phase.Locked -> LockScreen(state, biometric = null)
                    Phase.NeedsApiKey -> ApiKeyScreen(state, onBack = null)
                    Phase.NeedsLogin -> SignInScreen(state, adding = false, onDone = {}, onBack = null)
                    Phase.Ready -> MainScreen(activity, state)
                }
            }
        }
    }
}
