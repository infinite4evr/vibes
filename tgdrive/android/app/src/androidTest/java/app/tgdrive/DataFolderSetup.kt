package app.tgdrive

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.tgdrive.storage.DataLocation
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Chooses the default data folder, as a person does on the first start, before the emulator journeys run. */
@RunWith(AndroidJUnit4::class)
class DataFolderSetup {
    @Test fun selectDefaultDataFolder() {
        val app = ApplicationProvider.getApplicationContext<Context>()
        if (!DataLocation.ready(app)) DataLocation.select(app, DataLocation.defaultRoot())
        assertTrue(DataLocation.ready(app))
        assertTrue("gallery apps must skip TG Drive's own files",
            java.io.File(DataLocation.root(app), "service/.nomedia").exists() && java.io.File(DataLocation.root(app), "android/.nomedia").exists())
    }
}
