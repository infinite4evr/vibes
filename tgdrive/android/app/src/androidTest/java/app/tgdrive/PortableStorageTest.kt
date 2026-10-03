package app.tgdrive
import android.content.Context
import android.content.ContextWrapper
import android.os.Environment
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.tgdrive.storage.DataLocation
import app.tgdrive.storage.PortablePreferences
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID
@RunWith(AndroidJUnit4::class)
class PortableStorageTest {
    @Test fun folderCopyReinstallAndTypedSettingsRestore(){
        val app=ApplicationProvider.getApplicationContext<Context>();val id=UUID.randomUUID().toString()
        val private=File(app.cacheDir,"portable-$id").apply{mkdirs()}
        val c=object:ContextWrapper(app){
            override fun getFilesDir()=File(private,"files").apply{mkdirs()}
            override fun getNoBackupFilesDir()=File(private,"state").apply{mkdirs()}
            override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences("portable-$id-$name",mode)
        }
        val first=File(Environment.getExternalStorageDirectory(),"TGDrive-Test-$id-a")
        val second=File(Environment.getExternalStorageDirectory(),"TGDrive-Test-$id-b")
        try{
            val legacy=File(c.filesDir,"tgdrive").apply{mkdirs()};File(legacy,"settings.json").writeText("{\"api_id\":1234,\"api_hash\":\"test-key\"}")
            DataLocation.select(c,first);assertTrue(DataLocation.ready(c))
            c.getSharedPreferences("app",0).edit().putLong("aid",7L).putBoolean("welcomed",true).commit()
            PortablePreferences.save(c)
            val staged=File(DataLocation.state(c),"upload-staging/pending.bin").apply{parentFile!!.mkdirs();writeText("keep staged bytes")}
            File(DataLocation.state(c),"pending-uploads.json").writeText(org.json.JSONArray().put(org.json.JSONObject().put("staged",staged.path)).toString())
            DataLocation.select(c,second)
            assertTrue(File(first,"service/settings.json").exists())
            val moved=org.json.JSONArray(File(DataLocation.state(c),"pending-uploads.json").readText()).getJSONObject(0).getString("staged")
            assertTrue(moved.startsWith(second.path+"/"))
            assertEquals("keep staged bytes",File(moved).readText())
            assertTrue(staged.exists())
            // Simulate removal of app-owned state during uninstall, retaining the external folder.
            File(c.filesDir,"data-location.json").delete()
            c.getSharedPreferences("app",0).edit().clear().commit()
            DataLocation.select(c,second);PortablePreferences.attach(c)
            assertEquals(7L,c.getSharedPreferences("app",0).getLong("aid",0))
            assertTrue(File(DataLocation.service(c),"settings.json").readText().contains("test-key"))
            assertEquals(second.canonicalFile,DataLocation.root(c)!!.canonicalFile)
        }finally{first.deleteRecursively();second.deleteRecursively();private.deleteRecursively()}
    }
    @Test fun folderSelectionRejectsUninstallableAndUnrelatedFolders(){
        val c=ApplicationProvider.getApplicationContext<Context>()
        assertTrue(runCatching{DataLocation.select(c,File(c.getExternalFilesDir(null),"not-portable"))}.isFailure)
        val folder=File(Environment.getExternalStorageDirectory(),"TGDrive-Test-${UUID.randomUUID()}").apply{mkdirs()}
        try{File(folder,"personal.txt").writeText("keep");assertTrue(runCatching{DataLocation.select(c,folder)}.isFailure);assertEquals("keep",File(folder,"personal.txt").readText())}finally{folder.deleteRecursively()}
    }
}
