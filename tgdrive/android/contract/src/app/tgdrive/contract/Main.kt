package app.tgdrive.contract

import app.tgdrive.data.Api
import app.tgdrive.data.FileItem
import app.tgdrive.data.Folder
import app.tgdrive.data.JsonCodec
import app.tgdrive.data.arr
import app.tgdrive.data.str
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit
import kotlin.system.exitProcess

/**
 * Every call the Android app makes, through the app's own Api.kt and models, against a running
 * TG Drive service with the sample account. Prints one line per call; exits 1 if any failed.
 *
 *   contract <port> <media_port> <token> <media_token> [demo]
 */
private val failures = ArrayList<String>()
private var passed = 0

private suspend fun <T> check(name: String, block: suspend () -> T): T? = try {
    val r = block()
    passed++
    println("ok    $name")
    r
} catch (e: Throwable) {
    failures += "$name: ${e.javaClass.simpleName}: ${e.message}"
    println("FAIL  $name: ${e.javaClass.simpleName}: ${e.message?.take(300)}")
    null
}

private fun expect(cond: Boolean, what: String) { if (!cond) throw AssertionError(what) }

fun main(args: Array<String>): Unit = runBlocking {
    val (port, media, token, mediaToken) = args
    // The sample account's made-up Telegram has previews of photos but not the full-size pictures.
    val demo = args.getOrNull(4) == "demo"
    val http = OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS).build()
    // As AppGraph.mediaHttp (pictures, streams, PDF pages): the secret on every request to the service.
    val mediaHttp = http.newBuilder().addInterceptor { c -> c.proceed(c.request().newBuilder().header("x-tgdrive-token", token).build()) }.build()
    val engine = EngineState(port.toInt(), media.toInt(), token, mediaToken)
    val api = Api(http) { engine }

    // ---------------------------------------------------------------- start-up (AppState.bootstrap)
    val st = check("status") { api.status() } ?: run { println("service not answering"); exitProcess(1) }
    val aid = st.accounts.firstOrNull()?.id ?: run { println("no account (start the service with the sample data)"); exitProcess(1) }
    check("status has the sample account ready") { expect(st.apiConfigured && !st.locked, "api_configured/locked: $st") }
    check("settings") { expect(api.settings().containsKey("theme"), "no theme") }
    check("patchSettings(view=list, back to grid)") {
        api.patchSettings(buildJsonObject { put("view", "list") })
        api.patchSettings(buildJsonObject { put("view", "grid") })
    }
    check("patchSettings(font_scale=1.1 as a Double)") { api.patchSettings(buildJsonObject { put("font_scale", 1.1) }) }
    check("patchSettings(slideshow_seconds=5 as an Int)") { api.patchSettings(buildJsonObject { put("slideshow_seconds", 5) }) }
    check("accountStatus") { api.accountStatus(aid) }
    val folders = check("folders") { api.folders(aid) }
    check("covers") { api.covers(aid) }
    val chats = check("chats") { api.chats(aid) }.orEmpty()
    check("dialogFilters") { api.dialogFilters(aid) }
    check("tags") { api.tags(aid) }
    check("subjects") { api.subjects(aid) }
    check("transfers") { api.transfers(aid) }
    check("events") { api.events(0) }
    check("activity (keep-alive)") { api.activity() }
    check("stream-events (live updates, first event)") {
        val req = Request.Builder().url("${api.base}/api/stream-events?aid=$aid&after=0").header("x-tgdrive-token", token)
            .header("x-tgdrive-bg", "1").build()
        http.newBuilder().readTimeout(15, TimeUnit.SECONDS).build().newCall(req).execute().use { r ->
            expect(r.isSuccessful, "HTTP ${r.code}")
            val first = r.body.source().readUtf8Line()
            expect(first != null && (first.startsWith("event:") || first.startsWith(":") || first.startsWith("data:") || first.startsWith("retry")), "first line: $first")
        }
    }

    // ---------------------------------------------------------------- lists (BrowseModel.viewParams)
    val drive = folders?.drive?.channelId
    val base = mapOf("sort" to "date", "order" to "desc", "limit" to "90", "copies" to "hide")
    val views = linkedMapOf(
        "My Drive" to (if (drive != null) mapOf("chat_ids" to drive.toString(), "filed" to "0") else emptyMap()),
        "All files" to emptyMap(),
        "Starred" to mapOf("starred" to "1"),
        "Recent" to mapOf("recent" to "1", "sort" to "recent"),
        "Continue watching" to mapOf("in_progress" to "1", "sort" to "played"),
        "search polity" to mapOf("q" to "polity", "sort" to "relevance"),
        "search typo seires" to mapOf("q" to "seires", "sort" to "relevance"),
        "search Hindi" to mapOf("q" to "संविधान", "sort" to "relevance"),
        "search operators" to mapOf("q" to "type:video size>1mb"),
        "kind tab photos" to mapOf("kinds" to "photo"),
        "filters (size, date, source)" to mapOf("size_min" to "1mb", "date_from" to "30d", "chat_kinds" to "channel", "has_caption" to "1"),
        "every copy shown" to mapOf("copies" to "show"),
    )
    for (f in folders?.folders.orEmpty().take(4)) views["folder ${f.name}"] = mapOf("folder_id" to f.id)
    for (c in chats.take(3)) views["chat ${c.title}"] = mapOf("chat_ids" to c.id.toString())
    for (s in folders?.saved.orEmpty().take(2)) views["saved ${s.name}"] = s.params.mapValues { (it.value as? JsonPrimitive)?.content ?: "" } + ("q" to s.q)
    var sample: List<FileItem> = emptyList()
    for ((name, p) in views) {
        val params = base + p
        check("files: $name") {
            val page = api.files(aid, params)
            if (sample.size < page.items.size) sample = page.items
            if (page.next != null) api.files(aid, params + ("cursor" to page.next!!))
        }
        check("stats: $name") { api.stats(aid, params - "sort" - "order" - "limit") }
    }
    // The type tabs above a list: every type with files gets one (Documents, Audio … not only Photos and Videos).
    check("stats: every type counted") {
        val st = api.stats(aid, mapOf("copies" to "hide"))
        println("      kind counts: ${st.kindCounts}")
        for (k in listOf("photo", "video", "document", "audio"))
            require((st.kindCounts[k] ?: 0L) > 0L) { "no count for $k: ${st.kindCounts}" }
    }
    for (sort in listOf("name:asc", "size:desc", "chat:asc", "duration:desc", "type:asc", "ext:asc", "date:asc")) {
        val (s, o) = sort.split(":")
        check("files sorted $sort") { api.files(aid, base + mapOf("sort" to s, "order" to o)) }
    }
    check("suggest (empty)") { api.suggest(aid, "") }
    check("suggest pol") { api.suggest(aid, "pol") }
    check("timeline") { api.timeline(aid, mapOf("kinds" to "photo,video", "copies" to "hide")) }
    check("photos of one month") {
        val t = api.timeline(aid, mapOf("kinds" to "photo,video"))
        val m = t.months.firstOrNull() ?: return@check
        api.files(aid, mapOf("kinds" to "photo,video", "date_from" to m.ym, "date_to" to m.ym, "sort" to "date", "order" to "desc", "limit" to "500"))
    }

    // ---------------------------------------------------------------- one file (viewer, details, menu)
    expect(sample.isNotEmpty(), "no files in the sample account")
    val f = sample.first()
    val pdf = sample.firstOrNull { it.isPdf } ?: api.files(aid, mapOf("q" to "ext:pdf")).items.firstOrNull()
    val photo = api.files(aid, mapOf("kinds" to "photo", "limit" to "5")).items.firstOrNull()
    val video = api.files(aid, mapOf("kinds" to "video", "limit" to "5")).items.firstOrNull()
    check("detail") { api.detail(aid, f.ref) }
    check("context (Show in chat)") { api.context(aid, f.ref) }
    check("playback") { api.playback(aid, (video ?: f).ref) }
    check("savePlayback + clear") { val v = video ?: f; api.savePlayback(aid, v.ref, 12.5, v.duration); api.clearPlayback(aid, v.ref) }
    for ((label, url) in listOfNotNull(
        photo?.let { "thumb s" to api.thumbUrl(aid, it.chatId, it.msgId, "s") },
        photo?.let { "thumb b" to api.thumbUrl(aid, it.chatId, it.msgId, "b") },
        photo?.let { "photo full size (viewer)" to api.thumbUrl(aid, it.chatId, it.msgId, "full") },
        video?.let { "stream video" to api.streamUrl(aid, it) },
        video?.let { "external stream (media token)" to api.externalStreamUrl(aid, it) },
        pdf?.let { "stream pdf" to api.streamUrl(aid, it) },
    )) {
        check("GET $label") {
            mediaHttp.newCall(Request.Builder().url(url).header("Range", "bytes=0-1023").build()).execute().use { r ->
                val demoFull = demo && label.startsWith("photo full") && r.code == 400
                expect(r.code == 200 || r.code == 206 || demoFull, "HTTP ${r.code} for $url")
            }
        }
    }
    if (pdf != null) {
        check("docthumb state") {
            mediaHttp.newCall(Request.Builder().url(api.docThumbUrl(aid, pdf.chatId, pdf.msgId)).build()).execute().use { r ->
                expect(r.code == 200 || r.code == 204, "HTTP ${r.code}")
            }
        }
        check("saveDocThumb (JPEG)") {
            val jpeg = java.util.Base64.getDecoder().decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
            api.saveDocThumb(aid, pdf.ref, jpeg)
        }
    }

    // ---------------------------------------------------------------- organising (menus)
    val two = sample.take(2)
    val refs = two.map { it.ref }
    check("star / unstar") { api.meta(aid, refs, starred = true); api.meta(aid, refs, starred = false) }
    check("tags add / remove") { api.meta(aid, refs, tagsAdd = listOf("contract")); api.meta(aid, refs, tagsRemove = listOf("contract")) }
    check("note save / clear") { api.meta(aid, listOf(f.ref), note = "hello"); api.meta(aid, listOf(f.ref), note = "") }
    check("rename / back") { api.rename(aid, f.ref, "Renamed by contract.pdf"); api.rename(aid, f.ref, "") }
    check("undo") { api.undo(aid) }
    val created: Folder? = check("createFolder") { api.createFolder(aid, "Contract folder", null) }
    if (created != null) {
        check("updateFolder look") { api.updateFolder(aid, created.id, buildJsonObject { put("color", "green"); put("emoji", "📚"); put("description", "x") }) }
        check("rename folder") { api.updateFolder(aid, created.id, buildJsonObject { put("name", "Contract folder 2") }) }
        check("place files in folder") { api.place(aid, refs, created.id) }
        check("files in the new folder") { expect(api.files(aid, mapOf("folder_id" to created.id)).items.size == refs.size, "not filed") }
        check("place back out") { api.place(aid, refs, null) }
        check("rulesPreview") { api.rulesPreview(aid, "polity", buildJsonObject { put("kinds", "document") }) }
        check("rule: auto-file + apply") {
            api.updateFolder(aid, created.id, buildJsonObject {
                put("rules", buildJsonObject { put("mode", "auto"); put("q", "polity"); put("params", buildJsonObject { }) })
            })
            api.applyRules(aid, created.id)
        }
        check("rule removed") { api.updateFolder(aid, created.id, buildJsonObject { put("rules", kotlinx.serialization.json.JsonNull) }) }
        check("downloadFolder") { api.downloadFolder(aid, created.id, zip = false) }
        check("deleteFolder") { api.deleteFolder(aid, created.id) }
    }
    check("smart folder create + list + delete") {
        val rules = buildJsonObject { put("mode", "smart"); put("q", "polity"); put("params", buildJsonObject { put("kinds", "document") }) }
        val sf = api.createFolder(aid, "Contract smart", null, rules = rules)
        expect(sf.smart, "not smart: $sf")
        api.folders(aid)
        api.deleteFolder(aid, sf.id)
    }
    check("bulkRename + undo") { api.bulkRename(aid, refs, "{n:02} {name}", 1); api.undo(aid) }
    check("saveSearch + delete") {
        val s = api.saveSearch(aid, "Contract search", "polity", buildJsonObject { put("kinds", "document") })
        api.deleteSearch(aid, s.id)
    }
    check("setSubject + clear") {
        val subs = api.subjects(aid).arr("subjects")
        val id = (subs.firstOrNull() as? JsonObject)?.str("id") ?: return@check
        api.setSubject(aid, listOf(f.ref), id); api.setSubject(aid, listOf(f.ref), null)
    }
    check("copyToDrive") { api.copyToDrive(aid, listOf(f.ref), null) }
    chats.firstOrNull()?.let { c ->
        check("pinChat on / off") { api.pinChat(aid, c.id, true); api.pinChat(aid, c.id, false) }
        check("send to chat (copy)") { api.send(aid, listOf(f.ref), c.id, "copy") }
    }
    check("clearHistory") { api.clearHistory(aid) }

    // ---------------------------------------------------------------- transfers
    val dl = check("download") { api.download(aid, listOf(f.ref)) }
    val tid = dl?.arr("ids")?.firstOrNull()?.let { (it as JsonPrimitive).content.toLong() }
    check("transfers after download") { api.transfers(aid) }
    if (tid != null) check("pause / resume / cancel / remove") {
        runCatching { api.transferAction(aid, tid, "pause") }
        runCatching { api.transferAction(aid, tid, "resume") }
        runCatching { api.transferAction(aid, tid, "cancel") }
        api.removeTransfer(aid, tid, false)
    }
    check("download zip") { api.download(aid, refs, zip = true, keepStructure = true, name = "Contract") }
    check("transfersBulk clear") { api.transfersBulk(aid, "clear") }
    check("upload a small file") {
        val body = "hello from the contract test".toByteArray().toRequestBody("text/plain".toMediaType())
        api.upload(aid, "contract.txt", body, null)
    }

    // ---------------------------------------------------------------- pages
    check("storage") { val s = api.storage(aid); expect(s.containsKey("by_kind"), "shape") }
    check("duplicates exact") { api.duplicates(aid, "exact", 0) }
    check("duplicates similar") { api.duplicates(aid, "similar", 0) }
    check("activityLog") { api.activityLog(aid) }
    check("index resync") { api.index(aid, "resync") }
    check("index pause / resume") { api.index(aid, "pause"); api.index(aid, "resume") }
    chats.firstOrNull()?.let { c -> check("topics") { api.topics(aid, c.id) } }
    check("maintenance stats") { api.maintenance(aid, "stats") }
    check("maintenance integrity") { api.maintenance(aid, "integrity") }
    check("backups") { api.backups(aid) }
    check("syncDrive") { api.syncDrive(aid) }
    check("exportManifest + import (merge)") { val m = api.exportManifest(aid); api.importManifest(aid, JsonCodec.parseToJsonElement(m), "merge") }
    check("exportCsv") { api.exportCsv(aid, mapOf("q" to "polity")) }
    check("about") { api.about() }
    check("cpu") { api.cpu(); api.cpu() }
    check("logs") { api.logs(50) }
    check("crashes") { api.crashes() }
    check("exportSettings + import") { val s = api.exportSettings(false); api.importSettings(JsonCodec.parseToJsonElement(s)) }
    check("diagnostics") { api.diagnostics(false) }
    check("lock set / lock now / unlock / remove") {
        api.setLock("4321", null)
        api.lockNow()
        api.unlock("4321")
        api.setLock(null, "4321")
    }

    println()
    println("$passed passed, ${failures.size} failed")
    failures.forEach { println("  - $it") }
    exitProcess(if (failures.isEmpty()) 0 else 1)
}
