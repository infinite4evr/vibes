package app.tgdrive.storage
import android.content.Context
import android.content.SharedPreferences
import android.os.Handler
import android.os.Looper
import android.util.AtomicFile
import app.tgdrive.diag.AppLog
import app.tgdrive.diag.StartupTrail
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Portable preferences retain exact types (a Long account id must never become an Int). */
object PortablePreferences {
    private val names=listOf("app","engine","sync","player")
    private val listeners=ArrayList<SharedPreferences.OnSharedPreferenceChangeListener>()
    /** Preference files this process restored from (and keeps current). */
    private val attached=HashSet<String>()
    private val writer=Executors.newSingleThreadExecutor { r -> Thread(r,"portable-preferences").apply { isDaemon=true } }
    private val pending=AtomicBoolean(false)
    private fun file(c:Context)=DataLocation.root(c)?.let{AtomicFile(File(it,"android/preferences.json"))}

    /** The saved file was unreadable at [attach] (it was set aside; this phone's own settings were kept), not said yet. */
    @Volatile private var damaged=false
    /** Whether to tell the person the saved file was damaged: true once, then false. */
    fun damagedNotice():Boolean { val d=damaged; damaged=false; return d }

    /** Restores this phone's preferences from the selected folder, then keeps that copy current.
     *  Safe to call again (a process that started before the folder was chosen attaches later). */
    @Synchronized fun attach(app:Context){
        val f=file(app)?:return
        if(f.baseFile.path in attached) return
        val saved=if(f.baseFile.exists()) read(app,f) else null
        if(saved!=null) {
            for((name,values) in saved) {
                val edit=app.getSharedPreferences(name,0).edit().clear()
                for((key,v) in values) when(v){
                    is Boolean->edit.putBoolean(key,v); is Long->edit.putLong(key,v); is Int->edit.putInt(key,v)
                    is Float->edit.putFloat(key,v); is Set<*>->edit.putStringSet(key,v.map{it.toString()}.toSet())
                    else->edit.putString(key,v.toString())
                }
                check(edit.commit()){ "Could not restore phone preferences." }
            }
        } else if(File(DataLocation.service(app),"accounts").isDirectory) app.getSharedPreferences("app",0).edit().putBoolean("welcomed",true).commit()
        for(name in names){
            val listener=SharedPreferences.OnSharedPreferenceChangeListener{_,_->saveSoon(app)}
            listeners+=listener;app.getSharedPreferences(name,0).registerOnSharedPreferenceChangeListener(listener)
        }
        attached+=f.baseFile.path
        // Brings the folder's copy up to date (a fresh one replaces a damaged file), off the main thread.
        saveSoon(app)
    }

    /**
     * Every value of the saved file, read completely before any is restored (half a restore would be worse than
     * none), or null when it can't be read: then it is set aside as preferences.json.damaged and this phone's
     * own settings are kept. A damaged file (cut short by a full disk, a cleaner app, an editor) must never
     * stop TG Drive from opening, at every launch, until someone finds and deletes it.
     */
    private fun read(app:Context,f:AtomicFile):Map<String,Map<String,Any>>? = try {
        val all=JSONObject(f.openRead().bufferedReader().use{it.readText()})
        names.associateWith{name->
            val values=all.optJSONObject(name)?:JSONObject()
            values.keys().asSequence().toList().associateWith<String,Any>{key->
                val v=values.getJSONObject(key)
                when(v.getString("type")){
                    "boolean"->v.getBoolean("value"); "long"->v.getLong("value"); "int"->v.getInt("value")
                    "float"->v.getDouble("value").toFloat()
                    "set"->v.getJSONArray("value").let{a->(0 until a.length()).map{a.getString(it)}.toSet()}
                    else->v.getString("value")
                }
            }
        }
    } catch(e:Exception) {
        val aside=File(f.baseFile.path+".damaged")
        aside.delete()
        val kept=f.baseFile.renameTo(aside)
        damaged=true
        AppLog.w("storage","The phone settings saved in the data folder can't be read; " +
            (if(kept) "set aside as ${aside.name}" else "left as they are")+", and this phone's own settings are kept",e)
        StartupTrail.note(app,"Phone settings file damaged (${e.javaClass.simpleName}); kept this phone's own settings")
        null
    }

    /** Preference changes arrive on the main thread: write them off it, a burst of changes as one write. */
    private fun saveSoon(c:Context){
        if(!pending.compareAndSet(false,true)) return
        writer.execute {
            pending.set(false)
            runCatching{save(c)}.onFailure{
                app.tgdrive.diag.AppLog.w("storage","Could not save phone preferences",it)
                Handler(Looper.getMainLooper()).post { android.widget.Toast.makeText(c,"Could not save phone settings. Check the data folder.",android.widget.Toast.LENGTH_LONG).show() }
            }
        }
    }

    @Synchronized fun save(c:Context){
        val f=file(c)?:return
        val all=JSONObject()
        for(name in names){val values=JSONObject();c.getSharedPreferences(name,0).all.forEach{(k,v)->
            val type=when(v){is Boolean->"boolean";is Long->"long";is Int->"int";is Float->"float";is Set<*>->"set";else->"string"}
            values.put(k,JSONObject().put("type",type).put("value",if(v is Set<*>) JSONArray(v.toList()) else v))
        };all.put(name,values)}
        f.baseFile.parentFile?.mkdirs()
        val out=f.startWrite();try{out.write(all.toString().toByteArray());f.finishWrite(out)}catch(t:Throwable){f.failWrite(out);throw t}
    }
}
