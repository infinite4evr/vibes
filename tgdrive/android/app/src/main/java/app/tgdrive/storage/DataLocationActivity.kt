package app.tgdrive.storage

import android.Manifest
import android.app.Activity
import android.app.ActivityManager
import android.content.*
import android.net.Uri
import android.os.*
import android.provider.DocumentsContract
import android.provider.Settings
import android.widget.*
import app.tgdrive.MainActivity
import app.tgdrive.engine.processExitHistory
import java.io.File

/** Plain Android views in their own process: survives a crash while the main UI is initialising. */
class DataLocationActivity:Activity(){
    private var opening=false
    private var busy=false
    private var first=true
    private var received=false
    private val readyReceiver=object:BroadcastReceiver(){override fun onReceive(c:Context?,i:Intent?){received=true;finish()}}
    override fun onCreate(b:Bundle?){
        super.onCreate(b)
        androidx.core.content.ContextCompat.registerReceiver(this,readyReceiver,IntentFilter("$packageName.UI_READY"),androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
    }
    override fun onDestroy(){runCatching{unregisterReceiver(readyReceiver)};super.onDestroy()}
    override fun onResume(){super.onResume()
        if(opening){if(!received)show("TG Drive returned before its main screen finished opening. View startup details below, then retry.");return}
        val choose=intent.getBooleanExtra("choose",false)||DataLocation.switching(this)
        if(first && !choose && permission()){
            first=false
            if(DataLocation.ready(this)){open();return}
            if(DataLocation.existing(DataLocation.defaultRoot())){select(DataLocation.defaultRoot());return}
        }
        first=false;show()
    }
    private fun permission()=if(Build.VERSION.SDK_INT>=30)Environment.isExternalStorageManager() else checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)==android.content.pm.PackageManager.PERMISSION_GRANTED
    private fun show(message:String=""){
        val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(30,35,30,30)}
        fun text(s:String){box.addView(TextView(this).apply{text=s;textSize=16f;setPadding(0,12,0,12)})}
        fun button(s:String,action:()->Unit){box.addView(Button(this).apply{text=s;isEnabled=!busy;setOnClickListener{action()}})}
        text("TG Drive · data folder")
        text(message.ifBlank{"Settings, API credentials, Telegram sign-in sessions, offline files and downloads are kept here. This folder survives uninstalling. Keep it private."})
        text("Current: ${DataLocation.root(this)?.path?:"Not selected"}\nDefault: ${DataLocation.defaultRoot().path}")
        if(!permission())button("Allow storage access"){
            if(Build.VERSION.SDK_INT>=30)startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,Uri.parse("package:$packageName")))
            else requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE,Manifest.permission.READ_EXTERNAL_STORAGE),2)
        }
        button("Use TG Drive folder"){select(DataLocation.defaultRoot())}
        button("Choose another folder"){
            if(!permission()){show("Grant storage access first.");return@button}
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION),3)
        }
        DataLocation.root(this)?.let{root->button("Open selected folder"){select(root)}}
        if(opening)button("Retry opening TG Drive"){opening=false;open()}
        button("Startup details"){
            val reports=app.tgdrive.diag.AppLog.unseenCrashes(this).take(2).joinToString("\n\n"){it.readText().takeLast(12000)}
            val details=reports+"\n\nRecent app log:\n"+app.tgdrive.diag.AppLog.tail(this)+"\n\nAndroid process history:\n"+processExitHistory(this,"")
            val content=TextView(this).apply{text=details.ifBlank{"No crash log was recorded. Try opening again."};setTextIsSelectable(true);setPadding(20,15,20,15)}
            android.app.AlertDialog.Builder(this).setTitle("Startup details").setView(ScrollView(this).apply{addView(content)}).setPositiveButton("Close",null).show()
        }
        setContentView(ScrollView(this).apply{addView(box)})
    }
    private fun select(folder:File){
        if(busy)return
        if(!permission()){show("Grant storage access, then choose a folder.");return}
        busy=true
        show("Preparing the data folder. The original data will be kept.")
        Thread{
            try{
                val am=getSystemService(ActivityManager::class.java)
                val end=System.currentTimeMillis()+35_000
                while(DataLocation.switching(this) && am.runningAppProcesses.orEmpty().any{it.processName=="$packageName:engine"}){
                    check(System.currentTimeMillis()<end){"The service is still closing. Wait a moment and try again."};Thread.sleep(100)
                }
                DataLocation.select(this,folder)
                runOnUiThread{busy=false;open()}
            }catch(t:Throwable){runOnUiThread{busy=false;show(t.message?:t.toString())}}
        }.start()
    }
    private fun open(){
        if(!DataLocation.ready(this)){show("The selected folder is unavailable. Reconnect its storage or choose it again.");return}
        opening=true;show("Opening TG Drive…")
        val target=Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        intent.getParcelableExtra<Intent>("forward")?.let{target.action=it.action;target.clipData=it.clipData;target.putExtras(it);target.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)}
        startActivity(target)
    }
    @Deprecated("Activity callback") override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==3 && resultCode==RESULT_OK){
            try{
                val uri=data?.data?:return
                require(uri.authority=="com.android.externalstorage.documents"){"Choose a folder on internal storage or an SD card."}
                val parts=DocumentsContract.getTreeDocumentId(uri).split(':',limit=2)
                val volume=if(parts[0]=="primary")Environment.getExternalStorageDirectory() else File("/storage/${parts[0]}")
                val folder=File(volume,parts.getOrElse(1){""}).canonicalFile
                require(folder.path.startsWith(volume.canonicalPath+"/")){"Choose a subfolder for TG Drive."}
                select(folder)
            }catch(t:Throwable){show(t.message?:"Could not use that folder.")}
        }
    }
}
