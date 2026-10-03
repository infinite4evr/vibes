package app.tgdrive.storage
import android.content.Context
import android.content.SharedPreferences
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Portable preferences retain exact types (a Long account id must never become an Int). */
object PortablePreferences {
    private val names=listOf("app","engine","sync","player")
    private val listeners=ArrayList<SharedPreferences.OnSharedPreferenceChangeListener>()
    private fun file(c:Context)=DataLocation.root(c)?.let{AtomicFile(File(it,"android/preferences.json"))}
    fun attach(c:Context){
        val f=file(c)?:return
        if(f.baseFile.exists()) {
            val all=JSONObject(f.openRead().bufferedReader().use{it.readText()})
            for(name in names) {
                val values=all.optJSONObject(name)?:JSONObject();val edit=c.getSharedPreferences(name,0).edit().clear()
                for(key in values.keys()) {val v=values.getJSONObject(key);when(v.getString("type")){
                    "boolean"->edit.putBoolean(key,v.getBoolean("value"));"long"->edit.putLong(key,v.getLong("value"))
                    "int"->edit.putInt(key,v.getInt("value"));"float"->edit.putFloat(key,v.getDouble("value").toFloat())
                    "set"->{val a=v.getJSONArray("value");edit.putStringSet(key,(0 until a.length()).map{a.getString(it)}.toSet())}
                    else->edit.putString(key,v.getString("value"))
                }};check(edit.commit()){ "Could not restore phone preferences." }
            }
        } else if(File(DataLocation.service(c),"accounts").isDirectory) c.getSharedPreferences("app",0).edit().putBoolean("welcomed",true).commit()
        for(name in names){val listener=SharedPreferences.OnSharedPreferenceChangeListener{_,_->runCatching{save(c)}.onFailure{app.tgdrive.diag.AppLog.w("storage","Could not save phone preferences",it);android.widget.Toast.makeText(c,"Could not save phone settings. Check the data folder.",android.widget.Toast.LENGTH_LONG).show()}};listeners+=listener;c.getSharedPreferences(name,0).registerOnSharedPreferenceChangeListener(listener)}
        save(c)
    }
    @Synchronized fun save(c:Context){
        val f=file(c)?:return
        val all=JSONObject()
        for(name in names){val values=JSONObject();c.getSharedPreferences(name,0).all.forEach{(k,v)->
            val type=when(v){is Boolean->"boolean";is Long->"long";is Int->"int";is Float->"float";is Set<*>->"set";else->"string"}
            values.put(k,JSONObject().put("type",type).put("value",if(v is Set<*>) JSONArray(v.toList()) else v))
        };all.put(name,values)}
        val out=f.startWrite();try{out.write(all.toString().toByteArray());f.finishWrite(out)}catch(t:Throwable){f.failWrite(out);throw t}
    }
}
