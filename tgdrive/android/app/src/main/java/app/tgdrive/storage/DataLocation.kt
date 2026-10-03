package app.tgdrive.storage

import android.content.Context
import android.content.Intent
import android.os.Environment
import android.util.AtomicFile
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.util.UUID

/** Only the selected folder pointer lives in uninstallable app storage. */
object DataLocation {
    fun defaultRoot()=File(Environment.getExternalStorageDirectory(),"TG Drive")
    private fun locator(c:Context)=AtomicFile(File(c.filesDir,"data-location.json"))
    fun root(c:Context):File?=try { JSONObject(locator(c).openRead().bufferedReader().use{it.readText()}).optString("path").takeIf{it.isNotBlank()}?.let(::File) }catch(_:Exception){null}
    fun switching(c:Context)=File(c.filesDir,"data-switching").exists()
    fun ready(c:Context)=!switching(c) && root(c)?.let{it.isDirectory && it.canRead() && it.canWrite()}==true
    fun service(c:Context)=File(root(c)?:error("Choose a data folder first."),"service")
    fun state(c:Context)=root(c)?.let{File(it,"android/state").apply{mkdirs()}}?:c.noBackupFilesDir
    fun logs(c:Context)=root(c)?.let{File(it,"android/logs").apply{mkdirs()}}?:File(c.filesDir,"logs").apply{mkdirs()}
    fun existing(f:File)=File(f,"tgdrive-folder.json").isFile || File(f,"service/settings.json").isFile || File(f,"service/accounts").isDirectory
    private fun write(f:AtomicFile,text:String){val out=f.startWrite();try{out.write(text.toByteArray());f.finishWrite(out)}catch(t:Throwable){f.failWrite(out);throw t}}
    fun select(c:Context,chosen:File) {
        val dest=chosen.canonicalFile
        require(dest.path!="/" && dest.path!=Environment.getExternalStorageDirectory().canonicalPath){"Choose a dedicated TG Drive folder."}
        require(listOf("/Android/data", "/Android/obb").none { dest.path.endsWith(it) || dest.path.contains("$it/") }){"Android removes app-specific folders on uninstall. Choose another folder."}
        val old=root(c)?.canonicalFile
        if(old!=null && old!=dest) require(!dest.path.startsWith(old.path+"/") && !old.path.startsWith(dest.path+"/")){"Choose a separate folder, not a parent or child of the current one."}
        check(dest.isDirectory || dest.mkdirs()){ "Could not create this folder. Grant storage access first." }
        val probe=File(dest,".write-${UUID.randomUUID()}");try{probe.writeText("test")}finally{probe.delete()}
        if(!existing(dest) && old!=dest) {
            require(dest.listFiles().orEmpty().isEmpty()){ "Choose an empty folder or an existing TG Drive folder." }
            val stage=File(dest,".import-${UUID.randomUUID()}").apply{mkdirs()}
            try {
                val source=old?:File(c.filesDir,"tgdrive")
                val required=source.walkTopDown().filter{it.isFile}.sumOf{it.length()}
                check(dest.usableSpace>required+64L*1024*1024){"Not enough free space to preserve the current data."}
                if(old!=null) old.copyRecursively(stage,overwrite=false,onError={_,e->throw e})
                else {
                    if(source.exists()) source.copyRecursively(File(stage,"service"),onError={_,e->throw e})
                    if(c.noBackupFilesDir.exists()) c.noBackupFilesDir.copyRecursively(File(stage,"android/state"),onError={_,e->throw e})
                    val logs=File(c.filesDir,"logs")
                    if(logs.exists()) logs.copyRecursively(File(stage,"android/logs"),onError={_,e->throw e})
                }
                // Pending uploads and the offline catalog store absolute paths too.
                // Rewrite only paths belonging to this profile, leaving picked source URIs alone.
                val moves=if(old!=null) listOf(old.path to dest.path) else listOf(
                    c.noBackupFilesDir.canonicalPath to File(dest,"android/state").path,
                    source.canonicalPath to File(dest,"service").path)
                File(stage,"android").walkTopDown().filter{it.isFile && it.extension=="json"}.forEach{file->
                    val raw=file.readText()
                    val json:Any=if(raw.trimStart().startsWith("[")) JSONArray(raw) else JSONObject(raw)
                    rebase(json,moves)
                    file.writeText(json.toString())
                }
                val service=File(stage,"service")
                if(service.exists() && !File(service,".tgdrive-root.json").exists())
                    File(service,".tgdrive-root.json").writeText(JSONObject().put("root",if(old!=null)File(old,"service").path else source.path).toString())
                stage.listFiles().orEmpty().forEach{check(it.renameTo(File(dest,it.name))){"Could not finish the data copy; the original remains safe."}}
            } finally {stage.deleteRecursively()}
        }
        File(dest,"service").mkdirs();File(dest,"downloads").mkdirs()
        write(AtomicFile(File(dest,"tgdrive-folder.json")),JSONObject().put("format",1).toString())
        write(locator(c),JSONObject().put("path",dest.path).toString())
        File(c.filesDir,"data-switching").delete()
    }
    private fun rebase(value:Any,moves:List<Pair<String,String>>):Any {
        when(value){
            is JSONObject->value.keys().asSequence().toList().forEach{value.put(it,rebase(value.get(it),moves))}
            is JSONArray->(0 until value.length()).forEach{value.put(it,rebase(value.get(it),moves))}
            is String->for((from,to) in moves) if(value==from || value.startsWith("$from/")) return to+value.removePrefix(from)
        }
        return value
    }
    fun openChooser(c:Context){
        try { PortablePreferences.save(c) } catch(t:Exception) {
            android.widget.Toast.makeText(c,"Could not save current settings: ${t.message}",android.widget.Toast.LENGTH_LONG).show()
            return
        }
        File(c.filesDir,"data-switching").writeText("switch requested")
        runCatching{c.startService(Intent(c,app.tgdrive.engine.EngineService::class.java).setAction(app.tgdrive.engine.EngineService.ACTION_STOP))}
        c.startActivity(Intent(c,DataLocationActivity::class.java).putExtra("choose",true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({android.os.Process.killProcess(android.os.Process.myPid())},300)
    }
}
