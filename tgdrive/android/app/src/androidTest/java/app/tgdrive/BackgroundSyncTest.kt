package app.tgdrive

import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The background sync with the app closed, on the sample account: Android's job scheduler runs it,
 * it starts TG Drive's service only by binding to it (no notification), checks the chats, records
 * what it found, and the service stops right after (nothing left running on the battery).
 */
@RunWith(AndroidJUnit4::class)
class BackgroundSyncTest {
    private val app = ApplicationProvider.getApplicationContext<TGDriveApp>()
    private val engine get() = app.graph.engine

    /** The sample account, and a stopped service (as when the app has been closed for a while). */
    private suspend fun stoppedService() {
        app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
        app.getSharedPreferences("engine", 0).edit().putBoolean("demo", true).commit()
        // An earlier test's screen counts as open until Android says it stopped (0.7 s late): the app would
        // rightly start a service stopped under it again.
        Thread.sleep(2500)
        repeat(3) {
            engine.stop()
            withTimeoutOrNull(40_000) { engine.state.first { it.phase == EngineState.Phase.Stopped || it.phase == EngineState.Phase.Failed } }
            withTimeoutOrNull(10_000) { while (engine.state.value.ready) kotlinx.coroutines.delay(200) }
            Thread.sleep(3000)
            val s = engine.state.value
            if (!s.ready && s.phase != EngineState.Phase.Starting) return
        }
        throw AssertionError("the service kept starting again (${engine.state.value.phase})")
    }

    /** Until the sync that started after [before] has ended. */
    private fun syncEnded(before: Long): BackgroundSync.Last {
        val until = System.currentTimeMillis() + BackgroundSync.BUDGET_MS + 60_000
        var last = BackgroundSync.last(app)
        while ((last.at == before || last.running) && System.currentTimeMillis() < until) {
            Thread.sleep(1000)
            last = BackgroundSync.last(app)
        }
        return last
    }

    @Test
    fun syncsWithTheAppClosedAndStopsAfterwards() = runBlocking {
        stoppedService()
        val before = BackgroundSync.last(app).at

        BackgroundSync.syncNow(app)
        // The state left by an earlier run can say "failed" (the test runner force-stops the app between
        // tests): wait for the service this sync starts.
        val s = withTimeoutOrNull(240_000) { engine.state.first { it.ready } }
        assertTrue("the sync didn't get the service running: ${engine.state.value.phase} ${engine.state.value.error ?: ""}", s != null)

        // It finishes, and says what it found.
        val last = syncEnded(before)
        assertTrue("the sync didn't finish", last.at != before && !last.running)
        assertTrue("the sync failed: ${last.result}", last.ok)
        assertTrue("unexpected result: ${last.result}", last.result.startsWith("Up to date") || last.result.contains("new file"))

        // Then the service stops by itself: nothing keeps running on the battery.
        val stopped = withTimeoutOrNull(60_000) { engine.state.first { it.phase == EngineState.Phase.Stopped } }
        assertTrue("the service kept running after the sync (${engine.state.value.phase})", stopped != null)
    }

    /**
     * The app opened while a background sync has the service running in its quiet background mode
     * (no notification, heavy jobs held): the main screen shows, and when the sync lets go the service
     * keeps running for the app on screen.
     */
    @Test
    fun openingTheAppDuringASyncShowsTheMainScreen() = runBlocking {
        stoppedService()
        val before = BackgroundSync.last(app).at
        BackgroundSync.syncNow(app)
        val s = withTimeoutOrNull(120_000) { engine.state.first { it.phase == EngineState.Phase.Starting || it.ready } }
        assertTrue("the sync didn't start the service: ${engine.state.value.phase}", s != null)

        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        ActivityScenario.launch(MainActivity::class.java).use {
            withTimeoutOrNull(120_000) { engine.state.first { it.ready } }
            removeLeftoverPasscode(app.graph)
            assertNotNull("the main screen didn't show while a background sync ran",
                device.wait(Until.findObject(By.text("Search everything…")), 90_000))
            val last = syncEnded(before)
            assertTrue("the sync didn't finish", last.at != before && !last.running)
            Thread.sleep(8000)
            assertTrue("the service stopped under the open app when the sync let go (${engine.state.value.phase})",
                engine.state.value.ready)
            assertNotNull("the main screen went away after the sync", device.findObject(By.text("Search everything…")))
        }
    }
}
