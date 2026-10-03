package app.tgdrive.storage

import android.Manifest
import android.app.ActivityManager
import android.content.*
import android.net.Uri
import android.os.*
import android.provider.DocumentsContract
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.tgdrive.MainActivity
import app.tgdrive.diag.AppLog
import app.tgdrive.diag.StartupTrail
import app.tgdrive.engine.processExitHistory
import app.tgdrive.ui.components.*
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.TgTheme
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Choosing the data folder, and the startup screen when the main screen can't open. Its own process, so it
 * still opens when the main one crashes: it uses only TG Drive's look (theme and controls), nothing that
 * needs the data folder, the service or the app's state. The data folder is shared storage, which can stop
 * answering: it is only ever looked at on a background thread, so this screen shows whatever happens to it.
 */
class DataLocationActivity:ComponentActivity(){
    // What the screen shows; show() changes it, Compose redraws.
    private var message by mutableStateOf("")
    private var busyState by mutableStateOf(false)
    private var openingState by mutableStateOf(false)
    private var details by mutableStateOf<String?>(null)
    private var tick by mutableIntStateOf(0)
    /** The data folder as last checked (null until a check answers). */
    private var folder by mutableStateOf<Folder?>(null)
    /** A check has waited on the data folder for a while. */
    private var slow by mutableStateOf(false)
    private var opening=false
    private var busy=false
    private var first=true
    private var received=false
    private val main=Handler(Looper.getMainLooper())
    private val io=Executors.newSingleThreadExecutor{r->Thread(r,"tgdrive-folder-check").apply{isDaemon=true}}
    private class Folder(val problem:String?,val defaultExists:Boolean)
    private val readyReceiver=object:BroadcastReceiver(){override fun onReceive(c:Context?,i:Intent?){received=true;finish()}}
    override fun onCreate(b:Bundle?){
        enableEdgeToEdge(statusBarStyle=SystemBarStyle.auto(android.graphics.Color.TRANSPARENT,android.graphics.Color.TRANSPARENT),
            navigationBarStyle=SystemBarStyle.auto(android.graphics.Color.TRANSPARENT,android.graphics.Color.TRANSPARENT))
        super.onCreate(b)
        setContent { TgTheme { Screen() } }
        androidx.core.content.ContextCompat.registerReceiver(this,readyReceiver,IntentFilter("$packageName.UI_READY"),androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
    }
    override fun onDestroy(){runCatching{unregisterReceiver(readyReceiver)};super.onDestroy()}
    override fun onResume(){super.onResume()
        if(opening){if(!received)show("TG Drive returned before its main screen finished opening${mainExit()?.let{" ($it)"}.orEmpty()}. View startup details below, then retry.");return}
        if(first && intent.getBooleanExtra("relaunch",false)){
            // The main screen's old process ends itself as it asks for this: open a fresh one once it's gone.
            first=false;show("Restarting TG Drive…")
            main.postDelayed({open(restarted=true)},800);return
        }
        val choose=intent.getBooleanExtra("choose",false)||DataLocation.switching(this)
        val stuck=intent.getStringExtra(StartupTrail.EXTRA_STUCK)
        val recover=first && (intent.getBooleanExtra("recover",false) || stuck!=null)
        val auto=first && !choose && !recover && permission()
        first=false
        show(when{
            recover && stuck!=null -> "TG Drive stopped responding while starting ($stuck) and was closed after 15 seconds. " +
                "Startup details show where it was stuck. Open it again, or choose another data folder."
            recover -> "TG Drive's last start ended before its main screen opened (${DataLocation.lastLaunch(this)?:"no record of how"}). " +
                "Startup details show more. Open it again, or choose another data folder."
            else -> ""
        })
        checkFolder{f->
            if(!auto) return@checkFolder
            if(f.problem==null) open() else if(f.defaultExists) select(DataLocation.defaultRoot())
        }
    }
    private fun permission()=if(Build.VERSION.SDK_INT>=30)Environment.isExternalStorageManager() else checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)==android.content.pm.PackageManager.PERMISSION_GRANTED
    private fun show(text:String=""){message=text;busyState=busy;openingState=opening;tick++}

    /** Looks at the data folder off the main thread, then runs [then] on it with what was found. */
    private fun checkFolder(then:(Folder)->Unit={}){
        val answered=AtomicBoolean(false)
        main.postDelayed({ if(!answered.get()) slow=true },SLOW_MS)
        io.execute{
            val problem=runCatching{DataLocation.problem(this)}.getOrElse{"TG Drive can't check its data folder: ${it.message}"}
            val f=Folder(problem,runCatching{DataLocation.existing(DataLocation.defaultRoot())}.getOrDefault(false))
            answered.set(true)
            runOnUiThread{
                if(isDestroyed) return@runOnUiThread
                slow=false;folder=f;tick++
                then(f)
            }
        }
    }

    @Composable private fun Screen(){
        val c=Tg.colors
        tick   // re-read the folder and the permission whenever show() runs
        val root=DataLocation.root(this)   // TG Drive's own storage: quick
        val allowed=permission()
        val ready=root!=null && folder?.problem==null && folder!=null
        Column(Modifier.fillMaxSize().background(c.canvas).systemBarsPadding().verticalScroll(rememberScrollState())
            .padding(horizontal=20.dp,vertical=24.dp),verticalArrangement=Arrangement.spacedBy(16.dp)){
            Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)){
                TgLogo(44.dp)
                Column{
                    Text("TG Drive",style=Tg.type.title,color=c.ink)
                    Text("Data folder",style=Tg.type.meta,color=c.ink2)
                }
            }
            if(message.isNotBlank()) Panel(Modifier.fillMaxWidth()){
                Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)){
                    if(busyState || (openingState && message.startsWith("Opening")) || message.startsWith("Restarting")) Spinner()
                    Text(message,style=Tg.type.body,color=c.ink)
                }
            }
            if(slow) Panel(Modifier.fillMaxWidth()){
                Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)){
                    Spinner()
                    Text("The data folder isn't answering. Android's storage may be busy, for example rescanning the folder after " +
                        "a cleaner app removed files from it. Wait a moment, or choose another folder.",style=Tg.type.body,color=c.ink)
                }
            }
            Text("Settings, API credentials, Telegram sign-in sessions, the index and offline files are kept here. "+
                "The folder survives uninstalling: choose it again after reinstalling to continue where you left off. Keep it private.",
                style=Tg.type.body,color=c.ink2)
            Panel(Modifier.fillMaxWidth()){
                Column(verticalArrangement=Arrangement.spacedBy(6.dp)){
                    Text("SELECTED",style=Tg.type.overline,color=c.ink3)
                    Text(root?.path?:"Not selected yet",style=Tg.type.bodyStrong,color=c.ink)
                    if(root?.path!=DataLocation.defaultRoot().path) Text("Default: ${DataLocation.defaultRoot().path}",style=Tg.type.meta,color=c.ink2)
                }
            }
            val full=Modifier.fillMaxWidth()
            Column(verticalArrangement=Arrangement.spacedBy(10.dp)){
                if(!allowed){
                    Text("TG Drive needs access to all files to keep its data in a folder that survives uninstalling.",style=Tg.type.meta,color=c.ink2)
                    TgButton("Allow storage access",{
                        if(Build.VERSION.SDK_INT>=30)startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,Uri.parse("package:$packageName")))
                        else requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE,Manifest.permission.READ_EXTERNAL_STORAGE),2)
                    },full,kind=ButtonKind.Primary,icon=TgIcons.lock)
                }
                if(openingState || ready)
                    TgButton(if(openingState)"Retry opening TG Drive" else "Open TG Drive",{opening=false;open()},full,
                        kind=if(allowed)ButtonKind.Primary else ButtonKind.Secondary,enabled=!busyState,icon=TgIcons.refresh)
                else if(root!=null)
                    TgButton("Open selected folder",{select(root)},full,kind=if(allowed)ButtonKind.Primary else ButtonKind.Secondary,enabled=!busyState,icon=TgIcons.folder)
                if(root?.path!=DataLocation.defaultRoot().path)
                    TgButton("Use the TG Drive folder",{select(DataLocation.defaultRoot())},full,enabled=!busyState,icon=TgIcons.folderFill)
                TgButton("Choose another folder…",{
                    if(!permission()){show("Grant storage access first.");return@TgButton}
                    @Suppress("DEPRECATION")
                    startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION),3)
                },full,enabled=!busyState,icon=TgIcons.folderPlus)
                TgButton("Startup details",{showDetails()},full,kind=ButtonKind.Ghost,icon=TgIcons.info)
            }
        }
        details?.let{text->
            TgDialog("Startup details",{details=null},confirm="Create GitHub issue",onConfirm={createIssue()},dismiss="Close"){
                TgButton("Copy",{copy(text)},small=true,kind=ButtonKind.Ghost)
                Spacer(Modifier.height(8.dp))
                SelectionContainer{Text(text,style=Tg.type.mono,color=c.ink)}
            }
        }
    }

    /** What TG Drive's own storage and Android know first (always there), then the data folder's part, which
     *  can take long, or never come, when the folder doesn't answer. */
    private fun showDetails(){
        details="Collecting…"
        Thread({
            val own=runCatching{ownDetails()}.getOrElse{"Couldn't collect the details: $it"}
            runOnUiThread{details="$own\n\nData folder: checking…"}
            val shared=runCatching{folderDetails()}.getOrElse{"Data folder: couldn't read it ($it)"}
            runOnUiThread{details="$own\n\n$shared"}
        },"tgdrive-startup-details").apply{isDaemon=true}.start()
    }
    private fun ownDetails():String{
        val reports=AppLog.unseenCrashes(this).take(2).joinToString("\n\n"){it.readText().takeLast(12000)}
        val privateLog=File(DataLocation.privateLogs(this),"app.log").takeIf{it.isFile}?.let{f->runCatching{f.readLines().takeLast(120).joinToString("\n")}.getOrNull()}.orEmpty()
        // Android's own record first: it says how the main screen's process ended even when nothing was logged.
        return "Last start: "+(DataLocation.lastLaunch(this)?:"reached the main screen")+
            "\n\nAndroid process history (main screen):\n"+processExitHistory(this,"")+
            "\n\nAndroid process history (service):\n"+processExitHistory(this,":engine")+
            "\n\nStartup steps (kept in TG Drive's own storage):\n"+StartupTrail.tail(this,80).ifBlank{"(none)"}+
            (if(reports.isNotBlank()) "\n\nCrash reports:\n$reports" else "")+
            (if(privateLog.isNotBlank()) "\n\nApp log kept in TG Drive's own storage:\n$privateLog" else "")
    }
    private fun folderDetails():String=
        "Data folder: "+(DataLocation.problem(this)?:"usable from this screen")+"\n\nRecent app log:\n"+AppLog.tail(this,200)

    /** A GitHub issue with how the start went (the issue adds the startup steps: steps and stack frames only). */
    private fun createIssue(){
        app.tgdrive.diag.GitHubIssue.openAsync(this,"Android: TG Drive didn't open its main screen",
            message.ifBlank{"TG Drive didn't open its main screen."},
            "Last start: "+(DataLocation.lastLaunch(this)?:"reached the main screen")+
                "\n\nAndroid process history (main screen):\n"+processExitHistory(this,"",max=4))
    }
    private fun copy(text:String){
        getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("TG Drive startup details",text))
        android.widget.Toast.makeText(this,"Copied",android.widget.Toast.LENGTH_SHORT).show()
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
    private var openedAt=0L
    /** How the main screen's process last ended after this screen opened it, as Android recorded it. */
    private fun mainExit():String?{
        if(Build.VERSION.SDK_INT<30) return null
        return runCatching{
            getSystemService(ActivityManager::class.java).getHistoricalProcessExitReasons(packageName,0,10)
                .firstOrNull{it.processName==packageName && it.timestamp>=openedAt}
                ?.let{i->app.tgdrive.engine.exitReasonName(i.reason)+(i.description?.takeIf{d->d.isNotBlank()}?.let{d->": $d"}.orEmpty())}
        }.getOrNull()
    }
    private fun open(restarted:Boolean=false)=checkFolder{f->
        if(f.problem!=null){show("${f.problem} Reconnect its storage or choose the folder again.");return@checkFolder}
        opening=true;show("Opening TG Drive…")
        openedAt=System.currentTimeMillis()
        DataLocation.launchFinished(this)   // a fresh attempt: MainActivity marks it again
        val target=Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra(MainActivity.EXTRA_FROM_STARTUP,true).putExtra(MainActivity.EXTRA_RESTARTED,restarted)
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
    private companion object { const val SLOW_MS=6_000L }
}
