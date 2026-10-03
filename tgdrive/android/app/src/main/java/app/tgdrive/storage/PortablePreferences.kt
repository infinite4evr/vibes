package app.tgdrive.storage
import android.content.Context
import android.content.SharedPreferences
import android.os.Handler
import android.os.Looper
import android.util.AtomicFile
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

    /** Restores this phone's preferences from the selected folder, then keeps that copy current.
     *  Safe to call again (a process that started before the folder was chosen attaches later). */
    @Synchronized fun attach(app:Context){
        val f=file(app)?:return
        if(f.baseFile.path in attached) return
        if(f.baseFile.exists()) {
            val all=JSONObject(f.openRead().bufferedReader().use{it.readText()})
            for(name in names) {
                val values=all.optJSONObject(name)?:JSONObject();val edit=app.getSharedPreferences(name,0).edit().clear()
                for(key in values.keys()) {val v=values.getJSONObject(key);when(v.getString("type")){
                    "boolean"->edit.putBoolean(key,v.getBoolean("value"));"long"->edit.putLong(key,v.getLong("value"))
                    "int"->edit.putInt(key,v.getInt("value"));"float"->edit.putFloat(key,v.getDouble("value").toFloat())
                    "set"->{val a=v.getJSONArray("value");edit.putStringSet(key,(0 until a.length()).map{a.getString(it)}.toSet())}
                    else->edit.putString(key,v.getString("value"))
                }};check(edit.commit()){ "Could not restore phone preferences." }
            }
        } else if(File(DataLocation.service(app),"accounts").isDirectory) app.getSharedPreferences("app",0).edit().putBoolean("welcomed",true).commit()
        for(name in names){
            val listener=SharedPreferences.OnSharedPreferenceChangeListener{_,_->saveSoon(app)}
            listeners+=listener;app.getSharedPreferences(name,0).registerOnSharedPreferenceChangeListener(listener)
        }
        save(app)
        attached+=f.baseFile.path
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
