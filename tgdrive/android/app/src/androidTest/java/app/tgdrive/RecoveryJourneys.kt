package app.tgdrive

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import app.tgdrive.data.*
import app.tgdrive.diag.ReportPreview
import app.tgdrive.engine.*
import app.tgdrive.storage.DataLocation
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

/** Real screens -> service -> disk against the sample Telegram transport. */
@RunWith(AndroidJUnit4::class)
class RecoveryJourneys:UiDriver() {
    @Before fun start() {
        if(!DataLocation.ready(app)) DataLocation.select(app,DataLocation.defaultRoot())
        app.getSharedPreferences("app",0).edit().putBoolean("welcomed",true).commit()
        runBlocking { g.engine.start(true);withTimeout(240_000){g.engine.state.first{it.ready}} }
        ActivityScenario.launch(MainActivity::class.java)
        eventually("app ready",60_000){g.state.phase.value==Phase.Ready}
    }
    @Test fun selectedDataFolderAndChangeActionAreVisible() {
        open("settings/data")
        need(By.text("DATA FOLDER"),"persistent storage section")   // section titles are shown in capitals
        need(By.text(DataLocation.root(app)!!.path),"current data location")
        need(By.text("Change data folder"),"folder selection action")
    }
    @Test fun pinFromMenuThenRemoveCopyKeepsOriginal() {
        val f=runBlocking{g.api.files(1,mapOf("q" to "Fundamental Rights","limit" to "30")).items.first{it.size in 1..1000000}}
        search("Fundamental Rights");val y=need(label(f.displayName),"file").visibleBounds.centerY()
        tapAt(device.findObjects(By.desc("File options")).filter{it.visibleBounds.centerY()<=y+40}.maxByOrNull{it.visibleBounds.centerY()}!!)
        sheetTap("Keep available offline")
        // Whichever row's menu opened, its file is the one pinned: follow that one through the journey.
        var pinned:JsonObject?=null
        eventually("an offline copy completes",60_000){
            pinned=g.api.json("GET","/api/a/1/offline").jsonObject["items"]!!.jsonArray.map{it.jsonObject}.firstOrNull{it.str("status")=="ready"}
            pinned!=null
        }
        val item=pinned!!
        open("offline");need(By.text("Offline & recovery"),"offline screen");scrollTo(By.text("Open offline copy"),"downloaded copy")
        val path=File(item.str("local_path")!!);assertEquals(item.long("size"),path.length())
        assertNotNull(androidx.core.content.FileProvider.getUriForFile(app,"${app.packageName}.files",path))
        tap("Remove offline copy");need(By.text("Remove offline copy?"),"confirmation");tap("Remove")
        eventually("local copy removed"){!path.exists()}
        assertTrue(runBlocking{g.api.files(1,mapOf("q" to item.str("name")!!.substringBeforeLast('.'))).items.any{it.msgId==item.long("msg_id")}})
    }
    @Test fun interruptedStagedUploadCanBeRetriedFromRecovery() {
        val id=UUID.randomUUID().toString();val dir=File(DataLocation.state(app),"upload-staging").apply{mkdirs()}
        val file=File(dir,"$id.bin").apply{writeText("durable test upload")}
        UploadJournal(app).put(UploadJournal.Entry(id,1,"content://expired/test","recover-$id.txt",null,"",null,"",file.path,"Interrupted before handoff",true))
        open("offline");scrollTo(By.text("Retry pending uploads"),"pending upload");tap("Retry pending uploads")
        eventually("handoff acknowledged",60_000){UploadJournal(app).list().none{it.id==id}}
        assertFalse(file.exists())
        assertTrue(runBlocking{g.api.json("GET","/api/a/1/transfers").toString().contains("recover-$id.txt")})
    }
    @Test fun privacyPreviewDefaultsOffAndCancelDoesNotShare() {
        val scenario=ActivityScenario.launch(MainActivity::class.java)
        scenario.onActivity{a->g.scope.launch{ReportPreview.show(a,g.engine,"private-file.pdf secret query")}}
        need(By.text("Preview problem report"),"preview")
        assertFalse(need(By.text("Include filenames, chat names and search terms"),"privacy choice").isChecked)
        need(By.textContains("Personal text omitted"),"redacted preview",30_000)
        tapAt(find(By.text("CANCEL"),100)?:need(By.text("Cancel"),"cancel"))
        assertEquals(app.packageName,device.currentPackageName);assertNull(find(By.text("Preview problem report"),500));scenario.close()
    }
}
