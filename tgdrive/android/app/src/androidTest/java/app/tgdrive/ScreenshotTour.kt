package app.tgdrive

import android.graphics.Bitmap
import android.os.Environment
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Walks through the app on the sample account and saves a screenshot of each screen (CI keeps
 * them, so every change to the interface can be looked at).
 */
@RunWith(AndroidJUnit4::class)
class ScreenshotTour {
    private val dir = File(InstrumentationRegistry.getInstrumentation().targetContext.getExternalFilesDir(Environment.DIRECTORY_PICTURES), "tour")

    private fun shot(name: String) {
        Thread.sleep(1500)
        val bmp: Bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot() ?: return
        dir.mkdirs()
        File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test
    fun tour() {
        val app = ApplicationProvider.getApplicationContext<TGDriveApp>()
        app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
        app.getSharedPreferences("engine", 0).edit().putBoolean("demo", true).commit()
        ActivityScenario.launch(MainActivity::class.java).use {
            runBlocking { withTimeout(240_000) { app.graph.engine.state.first { it.ready || it.phase == EngineState.Phase.Failed } } }
            Thread.sleep(4000)
            shot("01-home")
        }
    }
}
