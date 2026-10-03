package app.tgdrive

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.tgdrive.data.*
import app.tgdrive.diag.ProblemReport
import app.tgdrive.engine.*
import app.tgdrive.storage.DataLocation
import app.tgdrive.ui.browse.BrowseModel
import app.tgdrive.ui.nav.View
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.BeforeClass
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.zip.ZipFile

/** Android integration faults at the HTTP boundary; real disk, API decoding and coroutines.
 * UI-to-engine journeys are in RecoveryJourneys. */
@RunWith(AndroidJUnit4::class)
class ReliabilityTest {
    companion object {
        private lateinit var app: TGDriveApp
        @JvmStatic @BeforeClass fun start() = runBlocking {
            app=ApplicationProvider.getApplicationContext()
            if(!DataLocation.ready(app)) DataLocation.select(app,DataLocation.defaultRoot())
            app.graph.engine.start(true)
            assertTrue(withTimeout(240_000) { app.graph.engine.state.first { it.ready || it.phase==EngineState.Phase.Failed } }.ready)
        }
    }
    private fun context(): Context=object:ContextWrapper(app) {
        val root=File(app.cacheDir,"reliability-${UUID.randomUUID()}").apply{mkdirs()}
        override fun getFilesDir()=root
        override fun getNoBackupFilesDir()=root
        override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences("${root.name}-$name",mode)
    }
    private val status="""{"api_configured":true,"accounts":[{"id":1},{"id":2}]}"""
    private fun client(answer:(okhttp3.Request)->String)=OkHttpClient.Builder().addInterceptor { chain ->
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK")
            .body(answer(chain.request()).toResponseBody("application/json".toMediaType())).build()
    }.build()
    private suspend fun until(check:()->Boolean)=withTimeout(8000) { while(!check()) delay(20) }
    private fun fallback(path:String)=when {
        path=="/api/status" -> status
        path.endsWith("/tags") -> """{"tags":[]}"""
        path.endsWith("/subjects") -> """{"subjects":[]}"""
        else -> "{}"
    }
    @Test fun delayedAccountCannotReplaceNewAccountOrCache():Unit=runBlocking {
        val arrived=CountDownLatch(1);val release=CountDownLatch(1)
        val http=client { req -> when(req.url.encodedPath) {
            "/api/a/1/tags" -> { arrived.countDown();release.await(8,TimeUnit.SECONDS);"""{"tags":[{"tag":"old"}]}""" }
            "/api/a/2/tags" -> """{"tags":[{"tag":"new"}]}"""
            else -> fallback(req.url.encodedPath)
        } }
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        try { withContext(Dispatchers.Main) {
            val state=AppState(context(),Api(http){app.graph.engine.state.value},app.graph.engine,http,scope)
            delay(100);state.bootstrap();until { state.phase.value==Phase.Ready }
            assertTrue(withContext(Dispatchers.IO){arrived.await(5,TimeUnit.SECONDS)})
            state.selectAccount(2);until { state.tags.value.any { it.tag=="new" } }
            release.countDown();delay(250)
            assertEquals(listOf("new"),state.tags.value.map{it.tag})
            assertEquals(2L,state.cache.snapshot!!.aid)
            assertEquals(listOf("new"),state.cache.snapshot!!.tags.map{it.tag})
        } } finally { release.countDown();scope.cancel();http.dispatcher.executorService.shutdown() }
    }
    @Test fun reloadDuringPaginationCanLoadMoreAgain():Unit=runBlocking {
        val arrived=CountDownLatch(1);val release=CountDownLatch(1);val pages=AtomicInteger()
        val http=client { req ->
            if(req.url.encodedPath.endsWith("/files")) {
                if(req.url.queryParameter("cursor")!=null) {
                    if(pages.incrementAndGet()==1) { arrived.countDown();release.await(8,TimeUnit.SECONDS) }
                    """{"items":[{"chat_id":1,"msg_id":2,"name":"second"}]}"""
                } else """{"items":[{"chat_id":1,"msg_id":1,"name":"first"}],"next":"page-2"}"""
            } else fallback(req.url.encodedPath)
        }
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        try { withContext(Dispatchers.Main) {
            val state=AppState(context(),Api(http){app.graph.engine.state.value},app.graph.engine,http,scope)
            delay(100);state.selectAccount(1,false)
            val model=BrowseModel(state,View.All,scope);model.reload();until{!model.loading};model.loadMore()
            assertTrue(withContext(Dispatchers.IO){arrived.await(5,TimeUnit.SECONDS)})
            model.reload();assertFalse(model.loadingMore);release.countDown()
            until{!model.loading};model.loadMore();until{!model.loadingMore}
            assertEquals(listOf(1L,2L),model.items.map{it.msgId});assertNull(model.moreError)
        } } finally { release.countDown();scope.cancel();http.dispatcher.executorService.shutdown() }
    }
    @Test fun stalledStatusHasOverallDeadline():Unit=runBlocking {
        val release=CountDownLatch(1);val http=client { release.await(35,TimeUnit.SECONDS);status }
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        try { withContext(Dispatchers.Main) {
            val state=AppState(context(),Api(http){app.graph.engine.state.value},app.graph.engine,http,scope)
            delay(100);val start=android.os.SystemClock.elapsedRealtime();state.bootstrap()
            withTimeout(29_000){state.phase.first{it is Phase.Failed}}
            assertTrue(android.os.SystemClock.elapsedRealtime()-start<29_000)
        } } finally { release.countDown();scope.cancel();http.dispatcher.executorService.shutdown() }
    }
    @Test fun lockedBootstrapCannotRecreateSavedScreen():Unit=runBlocking {
        val ctx=context();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        val http=client { req -> if(req.url.encodedPath=="/api/status") """{"api_configured":true,"lock_set":true,"accounts":[{"id":1}]}""" else fallback(req.url.encodedPath) }
        try { withContext(Dispatchers.Main) {
            val state=AppState(ctx,Api(http){app.graph.engine.state.value},app.graph.engine,http,scope)
            delay(100);state.cache.start(AppStatus(apiConfigured=true,accounts=listOf(Account(1))),1,true)
            delay(2200);assertTrue(File(ctx.noBackupFilesDir,"startup-cache.json").exists())
            state.bootstrap();until{state.phase.value==Phase.Ready};delay(2300)
            assertNull(state.cache.snapshot);assertFalse(File(ctx.noBackupFilesDir,"startup-cache.json").exists())
        } } finally { scope.cancel() }
    }
    @Test fun cacheKeysSeparateLiteralDelimiters() {
        assertNotEquals(StartupCache.key(1,mapOf("q" to "a&tag=b")),StartupCache.key(1,mapOf("q" to "a","tag" to "b")))
        assertNotEquals(StartupCache.key(1,mapOf("q" to "x+y")),StartupCache.key(1,mapOf("q" to "x y")))
    }
    @Test fun journalSurvivesReopeningAndConcurrentWriters():Unit=runBlocking {
        val ctx=context()
        coroutineScope { repeat(30){i->launch(Dispatchers.IO){UploadJournal(ctx).put(UploadJournal.Entry("job-$i",1,"content://test/$i","$i.txt",null,"",null,"",error="interrupted"))}} }
        assertEquals(30,UploadJournal(ctx).list().size);UploadJournal(ctx).remove("job-2");assertEquals(29,UploadJournal(ctx).list().size)
    }
    @Test fun syncNeverMarksPausedErrorOrUnknownAsUpToDate() {
        assertTrue(BackgroundSync.indexComplete(listOf(1L to IndexStatus(phase="idle"))))
        assertFalse(BackgroundSync.indexComplete(listOf(1L to IndexStatus(phase=""))))
        assertFalse(BackgroundSync.indexComplete(listOf(1L to IndexStatus(phase="indexing"))))
        for(index in listOf(IndexStatus(phase="paused"),IndexStatus(phase="error"),IndexStatus(phase="idle",error="disconnected")))
            assertTrue(runCatching{BackgroundSync.indexComplete(listOf(1L to index))}.isFailure)
    }
    @Test fun reportZipOmitsNamesByDefaultAndHonoursOptIn():Unit=runBlocking {
        val text="PRIVATE-FILENAME-and-chat-and-query"
        fun content(f:File)=ZipFile(f).use{z->z.entries().asSequence().joinToString{z.getInputStream(it).bufferedReader().use{r->r.readText()}}}
        assertFalse(content(ProblemReport.build(app,app.graph.engine,text)).contains(text))
        assertTrue(content(ProblemReport.build(app,app.graph.engine,text,true)).contains(text))
    }
}
