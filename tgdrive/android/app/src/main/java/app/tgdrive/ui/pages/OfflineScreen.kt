package app.tgdrive.ui.pages

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.tgdrive.data.*
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.engine.UploadJournal
import app.tgdrive.engine.UploadService
import app.tgdrive.ui.actions.Platform
import app.tgdrive.ui.components.*
import app.tgdrive.ui.theme.Tg
import app.tgdrive.util.Format
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import kotlinx.serialization.json.*
import java.io.File

@Composable
fun OfflineScreen(state: AppState, onMenu: () -> Unit, onBack: (() -> Unit)? = null) {
    val ctx = LocalContext.current
    val aid by state.aid.collectAsState()
    val scope = rememberCoroutineScope()
    var data by remember(aid) { mutableStateOf<JsonObject?>(null) }
    var error by remember(aid) { mutableStateOf<String?>(null) }
    var pending by remember { mutableStateOf(emptyList<UploadJournal.Entry>()) }
    var remove by remember { mutableStateOf<JsonObject?>(null) }
    val journal = remember { UploadJournal(ctx) }
    val catalog = remember(aid,state.demo) { File(app.tgdrive.storage.DataLocation.state(ctx),"offline-${state.demo}-$aid.json") }
    suspend fun load() {
        try {
            pending = withContext(Dispatchers.IO) { journal.list() }.filter { it.aid == aid && it.demo == state.demo }
            val next = state.api.json("GET","/api/a/$aid/recovery").jsonObject
            data = next; error = null
            withContext(Dispatchers.IO) {
                val f = android.util.AtomicFile(catalog); val out = f.startWrite()
                try { out.write(next.toString().toByteArray()); f.finishWrite(out) } catch(e: Throwable) { f.failWrite(out); throw e }
            }
        } catch(e: kotlinx.coroutines.CancellationException) { throw e
        } catch(e: Exception) {
            error = "Showing saved information. ${e.message.orEmpty()}"
            if (data == null) data = withContext(Dispatchers.IO) { runCatching { JsonCodec.parseToJsonElement(android.util.AtomicFile(catalog).openRead().bufferedReader().use { it.readText() }).jsonObject }.getOrNull() }
        }
    }
    fun action(path: String, method: String = "POST") { scope.launch {
        try { state.api.json(method,"/api/a/$aid/$path"); load() }
        catch(e: Exception) { state.failed("Recovery action", e) }
    } }
    LaunchedEffect(aid) { while (true) { load(); delay(4000) } }
    val o = data?.get("offline")?.jsonObject
    val files = o?.get("items")?.jsonArray.orEmpty().map { it.jsonObject }
    val issues = data?.get("issues")?.jsonArray.orEmpty().map { it.jsonObject }
    Column(Modifier.fillMaxSize()) {
        PageBar("Offline & recovery", onMenu, onBack)
        LazyColumn(Modifier.weight(1f), contentPadding=PaddingValues(16.dp), verticalArrangement=Arrangement.spacedBy(12.dp)) {
            item { Text("Pinned copies stay on this phone. Cache cleanup never removes them.", color=Tg.colors.ink2) }
            error?.let { item { Text(it, color=Tg.colors.ink2) } }
            item { TgButton("Refresh", { scope.launch { load() } }) }
            item { Text("Storage and data limits", style=Tg.type.subheading, color=Tg.colors.ink) }
            item { Text("${Format.size(o?.long("ready_bytes") ?: 0)} ready / ${Format.size(o?.long("reserved_bytes") ?: 0)} reserved. Limits below apply per account.", color=Tg.colors.ink2) }
            for ((key,label) in listOf("offline_limit_mb" to "Offline files (MB)", "automatic_download_daily_mb" to "Automatic downloads per day (MB)", "thumb_cache_mb" to "Thumbnail cache (MB)", "stream_cache_mb" to "Streaming cache (MB)", "upload_staging_limit_mb" to "Phone upload staging (MB, all accounts)")) {
                item(key) {
                    var value by remember(key) { mutableStateOf(state.setting(key).orEmpty()) }
                    TgTextField(value, { value=it }, label=label)
                    TgButton("Save $label", {
                        val n=value.toIntOrNull()
                        if (n == null || n !in (if (key in setOf("thumb_cache_mb","upload_staging_limit_mb")) 1 else 0)..200000) state.message("Enter a valid whole MB limit.")
                        else state.setSetting(key,n)
                    }, small=true)
                }
            }
            item { Text("Manual pins and retries use data immediately. Automatic folder additions obey the daily budget. Limits reserve space for incomplete pins too.", color=Tg.colors.ink2) }
            item { Text("Recovery", style=Tg.type.subheading, color=Tg.colors.ink) }
            item {
                val last=BackgroundSync.last(ctx)
                Text(last.result.ifBlank { "No background sync result yet." }, color=Tg.colors.ink2)
                TgButton("Retry background sync", { BackgroundSync.syncNow(ctx) }, small=true)
            }
            items(issues) { i ->
                Text(i.str("title").orEmpty(), color=Tg.colors.ink)
                Text(i.str("detail").orEmpty(), color=Tg.colors.ink2)
                TgButton("Retry", { action("recovery/${i.str("kind")}/${android.net.Uri.encode(i.str("id"))}") }, small=true)
            }
            items(pending, key={it.id}) { e ->
                Text(e.name, color=Tg.colors.ink)
                Text(e.error.ifBlank { "Waiting for phone-to-engine handoff" }, color=Tg.colors.ink2)
                TgButton("Retry pending uploads", { UploadService.retry(ctx) }, small=true)
                if(e.error.isNotEmpty()) TgButton("Remove pending upload", { scope.launch { withContext(Dispatchers.IO) {
                    journal.remove(e.id); if(e.staged.isNotEmpty()) File(e.staged).delete()
                }; load() } }, small=true)
            }
            item { Text("Pinned folders", style=Tg.type.subheading, color=Tg.colors.ink) }
            items(o?.get("folders")?.jsonArray.orEmpty()) { f ->
                val id=f.jsonObject.str("id").orEmpty()
                Text(state.folders.value.folders.firstOrNull { it.id==id }?.name ?: id, color=Tg.colors.ink)
                TgButton("Stop automatic downloads", { action("offline/folders/${android.net.Uri.encode(id)}","DELETE") }, small=true)
            }
            item { Text("Offline files", style=Tg.type.subheading, color=Tg.colors.ink)
                Text("Use Keep available offline in a file or folder menu.",color=Tg.colors.ink2) }
            items(files) { f ->
                Text(f.str("name").orEmpty(),color=Tg.colors.ink)
                Text("${f.str("status")} · ${Format.size(f.long("done"))} / ${Format.size(f.long("size"))}",color=Tg.colors.ink2)
                if(f.str("status")=="ready") TgButton("Open offline copy", {
                    val path=f.str("local_path").orEmpty()
                    if(!Platform.openFile(ctx,path,null)) state.message("No app could open this file.")
                },small=true)
                TgButton("Remove offline copy",{remove=f},small=true)
            }
        }
    }
    remove?.let { f -> TgDialog("Remove offline copy?", {remove=null}, confirm="Remove", onConfirm={
        action("offline/${f.long("chat_id")}/${f.long("msg_id")}","DELETE"); remove=null
    }) { Text("The original remains in Telegram.",color=Tg.colors.ink2) } }
}
