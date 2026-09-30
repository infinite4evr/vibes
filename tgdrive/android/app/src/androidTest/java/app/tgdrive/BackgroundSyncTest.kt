package app.tgdrive

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
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

    @Test
    fun syncsWithTheAppClosedAndStopsAfterwards() = runBlocking {
        app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
        app.getSharedPreferences("engine", 0).edit().putBoolean("demo", true).commit()
        // Start from a stopped service (as when the app has been closed for a while).
        engine.stop()
        withTimeoutOrNull(40_000) { engine.state.first { it.phase == EngineState.Phase.Stopped || it.phase == EngineState.Phase.Failed } }
        Thread.sleep(2000)
        val before = BackgroundSync.last(app).at

        BackgroundSync.syncNow(app)
        val s = withTimeout(240_000) { engine.state.first { it.ready || it.phase == EngineState.Phase.Failed } }
        assertEquals("the sync didn't get the service running: ${s.error}", EngineState.Phase.Ready, s.phase)

        // It finishes, and says what it found.
        val until = System.currentTimeMillis() + BackgroundSync.BUDGET_MS + 60_000
        var last = BackgroundSync.last(app)
        while ((last.at == before || last.running) && System.currentTimeMillis() < until) {
            Thread.sleep(1000)
            last = BackgroundSync.last(app)
        }
        assertTrue("the sync didn't finish", last.at != before && !last.running)
        assertTrue("the sync failed: ${last.result}", last.ok)
        assertTrue("unexpected result: ${last.result}", last.result.startsWith("Up to date") || last.result.contains("new file"))

        // Then the service stops by itself: nothing keeps running on the battery.
        val stopped = withTimeoutOrNull(60_000) { engine.state.first { it.phase == EngineState.Phase.Stopped } }
        assertTrue("the service kept running after the sync (${engine.state.value.phase})", stopped != null)
    }
}
