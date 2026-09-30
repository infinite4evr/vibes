package app.tgdrive

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.tgdrive.data.await
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Request
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import org.junit.runner.RunWith

/**
 * TG Drive's Python service running inside the app on a real Android runtime, with the made-up
 * account: the parts that differ from a computer (FTS5 as an SQLite extension, OpenSSL for
 * Telegram's encryption, numpy from Chaquopy, the pure-Python stand-ins) all have to work.
 */
@RunWith(AndroidJUnit4::class)
class EngineTest {
    companion object {
        private lateinit var g: AppGraph
        private const val AID = 1L

        @JvmStatic
        @BeforeClass
        fun startEngine() = runBlocking {
            val app = ApplicationProvider.getApplicationContext<TGDriveApp>()
            app.getSharedPreferences("app", 0).edit().putBoolean("welcomed", true).commit()
            g = app.graph
            g.engine.start(demo = true)
            val s = withTimeout(240_000) {
                g.engine.state.first { it.ready || it.phase == EngineState.Phase.Failed }
            }
            assertEquals("engine failed: ${s.error}", EngineState.Phase.Ready, s.phase)
        }
    }

    @Test
    fun runtimeHasEverythingItNeeds() {
        val s = g.engine.state.value
        assertEquals("FTS5 comes from the app's SQLite extension", "extension", s.fts5)
        assertEquals("Telegram encryption runs in OpenSSL", "openssl", s.crypto)
        assertTrue("numpy loads (meaning search)", s.numpy)
    }

    /** The screens call the API from the main thread: big answers (a page of files, a month of
     *  photos, the folders) must still load (they failed with NetworkOnMainThreadException). */
    @Test
    fun bigPagesLoadFromTheMainThread() = runBlocking {
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) {
            val page = g.api.files(AID, mapOf("limit" to "90", "sort" to "date", "order" to "desc", "copies" to "hide"))
            assertTrue(page.items.size >= 90)
            assertTrue(g.api.folders(AID).folders.isNotEmpty())
            val m = g.api.timeline(AID, mapOf("kinds" to "photo,video")).months.first()
            g.api.files(AID, mapOf("kinds" to "photo,video", "date_from" to m.ym, "date_to" to m.ym, "limit" to "500"))
            g.api.storage(AID)
        }
    }

    @Test
    fun sampleAccountIsThere() = runBlocking {
        val st = g.api.status()
        assertTrue(st.apiConfigured)
        assertEquals(1, st.accounts.size)
        val page = g.api.files(AID, mapOf("limit" to "50"))
        assertTrue(page.items.size >= 50)
        assertTrue(g.api.folders(AID).folders.any { it.name == "Study" })
    }

    @Test
    fun smartSearchWorksOnAndroid() = runBlocking {
        val typo = g.api.files(AID, mapOf("q" to "seires", "sort" to "relevance"))
        assertEquals("typo correction (numpy matcher instead of rapidfuzz)", "series", typo.corrected)
        assertTrue(typo.items.any { it.name.contains("Series") })
        val hindi = g.api.files(AID, mapOf("q" to "संविधान"))
        assertTrue("Devanagari search", hindi.items.any { it.name.contains("संविधान") })
        val joined = g.api.files(AID, mapOf("q" to "test series", "sort" to "relevance"))
        assertTrue("joined words (FTS5 trigram and keywords)", joined.items.any { it.name.contains("TestSeries") })
        val ops = g.api.files(AID, mapOf("q" to "type:video size>100mb"))
        assertTrue(ops.items.isNotEmpty() && ops.items.all { it.kind == "video" && it.size > 100L * 1024 * 1024 })
    }

    @Test
    fun streamsWithRanges() = runBlocking {
        val pdf = g.api.files(AID, mapOf("q" to "\"Fundamental Rights\" ext:pdf")).items.first()
        val req = Request.Builder().url(g.api.streamUrl(AID, pdf)).header("Range", "bytes=0-7").build()
        g.mediaHttp.newCall(req).await().use { r ->
            assertEquals(206, r.code)
            assertEquals("%PDF-1.", r.body.string().take(7))
        }
        val photo = g.api.files(AID, mapOf("kinds" to "photo", "limit" to "1")).items.first()
        g.mediaHttp.newCall(Request.Builder().url(g.api.thumbUrl(AID, photo.chatId, photo.msgId)).build()).await().use { r ->
            assertEquals(200, r.code)
            assertTrue(r.body.bytes().size > 100)
        }
    }

    @Test
    fun organisingIsSaved() = runBlocking {
        val f = g.api.files(AID, mapOf("limit" to "1")).items.first()
        g.api.meta(AID, listOf(f.ref), starred = true, tagsAdd = listOf("android"))
        val again = g.api.detail(AID, f.ref).file
        assertTrue(again.starred && "android" in again.tags)
        val folder = g.api.createFolder(AID, "From Android", null, color = "teal", emoji = "📱")
        g.api.place(AID, listOf(f.ref), folder.id)
        assertEquals(folder.id, g.api.detail(AID, f.ref).file.folderId)
    }
}
