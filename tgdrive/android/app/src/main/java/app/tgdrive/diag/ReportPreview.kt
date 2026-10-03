package app.tgdrive.diag

import android.app.AlertDialog
import android.content.Context
import android.widget.*
import app.tgdrive.engine.EngineClient
import kotlinx.coroutines.*
import java.io.File
import java.util.zip.ZipFile

object ReportPreview {
    suspend fun show(context: Context, engine: EngineClient?, error: String?) = withContext(Dispatchers.Main) {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        val box=LinearLayout(context).apply { orientation=LinearLayout.VERTICAL; setPadding(24,12,24,12) }
        val include=CheckBox(context).apply { text="Include filenames, chat names and search terms"; isChecked=false }
        val note=TextView(context).apply { text="Off removes free-form log messages. Review the pages below before sharing." }
        val preview=TextView(context).apply { setTextIsSelectable(true); textSize=11f }
        val scroll=ScrollView(context).apply { addView(preview) }
        val controls=LinearLayout(context)
        val previous=Button(context).apply { text="Previous page" }
        val next=Button(context).apply { text="Next page" }
        controls.addView(previous); controls.addView(next)
        box.addView(include); box.addView(note); box.addView(scroll,LinearLayout.LayoutParams(-1,600)); box.addView(controls)
        var zip: File?=null
        var contents=""
        var page=0
        var generation=0
        val size=10000
        fun render() { val start=(page*size).coerceAtMost(contents.length); preview.text="Page ${page+1} of ${((contents.length+size-1)/size).coerceAtLeast(1)}\n\n"+contents.substring(start,(start+size).coerceAtMost(contents.length)); previous.isEnabled=page>0; next.isEnabled=(page+1)*size<contents.length }
        val dialog=AlertDialog.Builder(context).setTitle("Preview problem report").setView(box)
            .setNegativeButton("Cancel",null).setPositiveButton("Share report",null).create()
        fun prepare() {
            val current=++generation
            zip=null; preview.text="Preparing preview…"; dialog.getButton(AlertDialog.BUTTON_POSITIVE)?.isEnabled=false
            val names=include.isChecked
            scope.launch {
                try {
                    val result=ProblemReport.build(context,engine,error,names)
                    val text=withContext(Dispatchers.IO) { ZipFile(result).use { z -> z.entries().asSequence().joinToString("\n\n") { e -> "--- ${e.name} ---\n"+z.getInputStream(e).bufferedReader().use { it.readText() } } } }
                    if(current==generation) { zip=result; contents=text; page=0; render(); dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled=true }
                } catch(e: Exception) { if(current==generation) preview.text="Could not prepare report: ${e.message}" }
            }
        }
        dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener { zip?.let { ProblemReport.shareFile(context,it); dialog.dismiss() } }; prepare() }
        dialog.setOnDismissListener { scope.cancel() }
        previous.setOnClickListener { page--; render() }; next.setOnClickListener { page++; render() }
        include.setOnCheckedChangeListener { _,_ -> prepare() }
        dialog.show()
    }
}
