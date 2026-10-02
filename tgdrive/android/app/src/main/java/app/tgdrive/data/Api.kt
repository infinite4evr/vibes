package app.tgdrive.data

import app.tgdrive.diag.AppLog
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.asExecutor
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import kotlin.coroutines.resumeWithException

/** An error answer from TG Drive's service. [busy]: its index was busy; nothing changed, trying again is safe. */
class ApiException(val status: Int, message: String, val locked: Boolean = false, val busy: Boolean = false) : IOException(message)

val JsonCodec = Json { ignoreUnknownKeys = true; isLenient = true; coerceInputValues = true; explicitNulls = false }

/**
 * TG Drive's HTTP API, exactly as the desktop window uses it. Every request carries the engine's
 * per-launch secret and the X-TGDrive header the service requires for changes.
 */
class Api(private val http: OkHttpClient, private val engine: () -> EngineState) {

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    val base: String get() = "http://127.0.0.1:${engine().port}"
    val mediaBase: String get() = "http://127.0.0.1:${engine().mediaPort.takeIf { it > 0 } ?: engine().port}"
    val token: String get() = engine().token

    // ------------------------------------------------------------------ plumbing
    /**
     * While the service isn't running (it is starting, restarting or was stopped) its port is 0,
     * which OkHttp refuses with an IllegalArgumentException. A screen asking for a thumbnail or
     * stream URL as it draws then crashed the app ("Invalid URL port: 0"). A request gets an
     * [ApiException] its caller already handles; a media URL is [NOT_RUNNING], which simply fails
     * to load until the screen asks again with the service up.
     */
    private fun url(path: String, params: Map<String, Any?> = emptyMap(), media: Boolean = false): HttpUrl {
        val port = engine().port
        if (port !in 1..65535) throw ApiException(503, "TG Drive's service isn't running yet.", busy = true)
        val b = ((if (media) mediaBase else base) + path).toHttpUrl().newBuilder()
        for ((k, v) in params) if (v != null && v != "") b.addQueryParameter(k, v.toString())
        return b.build()
    }

    private fun request(url: HttpUrl) = Request.Builder().url(url)
        .header("x-tgdrive-token", token)
        .header("x-tgdrive", "1")

    suspend fun raw(method: String, path: String, params: Map<String, Any?> = emptyMap(), body: RequestBody? = null,
                    background: Boolean = false): String {
        // A read that found the index busy (a long background write, mostly on slow phones) is simply
        // asked again a moment later, instead of showing an error.
        var attempt = 0
        while (true) {
            try {
                return rawOnce(method, path, params, body, background)
            } catch (e: ApiException) {
                if (!e.busy || method != "GET" || attempt >= 3) throw e
                attempt++
                kotlinx.coroutines.delay(700L * attempt)
            }
        }
    }

    private suspend fun rawOnce(method: String, path: String, params: Map<String, Any?>, body: RequestBody?,
                                background: Boolean): String {
        val rb = request(url(path, params))
        if (background) rb.header("x-tgdrive-bg", "1")
        val needsBody = method in setOf("POST", "PUT", "PATCH")
        rb.method(method, body ?: if (needsBody) "{}".toRequestBody(jsonType) else null)
        // The answer is read, and closed, off the main thread: a big one (a page of files) needs more
        // reads from the socket, and so does closing one that wasn't read to the end (its caller gave
        // up: the screen closed), which Android forbids on the main thread (NetworkOnMainThreadException,
        // a crash when a screen closed just as its answer arrived).
        val t0 = System.nanoTime()
        fun ms() = (System.nanoTime() - t0) / 1_000_000
        try {
            return withContext(Dispatchers.IO) {
                http.newCall(rb.build()).await().use { resp ->
                    val text = resp.body.string()
                    if (!resp.isSuccessful) {
                        val err = error(resp, text)
                        AppLog.w("api", "$method $path → HTTP ${resp.code} in ${ms()} ms: ${err.message}")
                        throw err
                    }
                    AppLog.d("api", "$method $path${if (params.isEmpty()) "" else " $params"} → ${resp.code} in ${ms()} ms, ${text.length} bytes")
                    text
                }
            }
        } catch (e: ApiException) {
            throw e
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            AppLog.w("api", "$method $path failed after ${ms()} ms", e)
            throw e
        }
    }

    private fun error(resp: Response, text: String): ApiException {
        val obj = try { JsonCodec.parseToJsonElement(text).jsonObject } catch (_: Exception) { null }
        val msg = obj?.get("error")?.jsonPrimitive?.contentOrNull
            ?: obj?.get("detail")?.toString()
            ?: text.take(200).ifBlank { "HTTP ${resp.code}" }
        return ApiException(resp.code, msg, locked = resp.code == 423,
            busy = resp.code == 503 && obj?.get("busy")?.jsonPrimitive?.contentOrNull == "true")
    }

    suspend fun <T> get(path: String, s: DeserializationStrategy<T>, params: Map<String, Any?> = emptyMap(), background: Boolean = false): T {
        val text = raw("GET", path, params, background = background)
        return withContext(Dispatchers.Default) { JsonCodec.decodeFromString(s, text) }   // big pages: not on the main thread
    }

    suspend fun json(method: String, path: String, body: JsonElement? = null, params: Map<String, Any?> = emptyMap()): JsonElement {
        val text = raw(method, path, params, body?.toString()?.toRequestBody(jsonType))
        return if (text.isBlank()) JsonNull else withContext(Dispatchers.Default) { JsonCodec.parseToJsonElement(text) }
    }

    private fun a(aid: Long) = "/api/a/$aid"

    private fun items(refs: Collection<FileRef>): JsonArray = buildJsonArray {
        for (r in refs) add(buildJsonArray { add(JsonPrimitive(r.chatId)); add(JsonPrimitive(r.msgId)) })
    }

    // ------------------------------------------------------------------ app
    suspend fun status(): AppStatus = get("/api/status", AppStatus.serializer(), background = true)
    suspend fun setup(apiId: String, apiHash: String) = json("POST", "/api/setup", buildJsonObject { put("api_id", apiId); put("api_hash", apiHash) })
    suspend fun settings(): JsonObject = get("/api/settings", JsonObject.serializer())
    suspend fun patchSettings(changes: JsonObject): JsonObject = json("PATCH", "/api/settings", changes).jsonObject
    suspend fun about(): JsonObject = get("/api/about", JsonObject.serializer())
    suspend fun system(): JsonObject = get("/api/system", JsonObject.serializer())
    suspend fun cpu(): JsonObject = get("/api/cpu", JsonObject.serializer())
    suspend fun logs(lines: Int = 400): String = raw("GET", "/api/logs", mapOf("lines" to lines))
    suspend fun debugLog(which: String = "main", lines: Int = 800): JsonObject =
        get("/api/debuglog", JsonObject.serializer(), mapOf("which" to which, "lines" to lines))
    suspend fun clearLogs(crashes: Boolean) = json("DELETE", "/api/logs", params = mapOf("crashes" to if (crashes) 1 else 0))
    suspend fun crashes(): JsonObject = get("/api/crashes", JsonObject.serializer())
    suspend fun crash(id: String): String = raw("GET", "/api/crashes/$id")
    suspend fun clearCrashes() = json("DELETE", "/api/crashes")
    suspend fun diagnostics(includeNames: Boolean): JsonObject =
        json("POST", "/api/diagnostics", buildJsonObject { put("include_names", includeNames) }).jsonObject
    suspend fun exportSettings(includeApi: Boolean): String = raw("GET", "/api/settings/export", mapOf("include_api" to if (includeApi) 1 else 0))
    suspend fun importSettings(data: JsonElement): JsonObject = json("POST", "/api/settings/import", data).jsonObject
    suspend fun events(after: Long): JsonObject = get("/api/events", JsonObject.serializer(), mapOf("after" to after), background = true)

    // lock
    suspend fun unlock(passcode: String) = json("POST", "/api/lock/unlock", buildJsonObject { put("passcode", passcode) })
    suspend fun setLock(passcode: String?, old: String?) = json("POST", "/api/lock/set", buildJsonObject {
        put("passcode", passcode); put("old", old)
    })
    suspend fun lockNow() = json("POST", "/api/lock/now")
    suspend fun activity() = json("POST", "/api/activity")

    // sign-in
    suspend fun loginStart(phone: String): LoginStart =
        JsonCodec.decodeFromJsonElement(LoginStart.serializer(), json("POST", "/api/login/start", buildJsonObject { put("phone", phone) }))
    suspend fun loginCode(id: String, code: String): LoginStep = JsonCodec.decodeFromJsonElement(LoginStep.serializer(),
        json("POST", "/api/login/code", buildJsonObject { put("login_id", id); put("code", code) }))
    suspend fun loginPassword(id: String, password: String): LoginStep = JsonCodec.decodeFromJsonElement(LoginStep.serializer(),
        json("POST", "/api/login/password", buildJsonObject { put("login_id", id); put("password", password) }))
    suspend fun loginQr(): QrLogin = JsonCodec.decodeFromJsonElement(QrLogin.serializer(), json("POST", "/api/login/qr"))
    suspend fun loginQrStatus(id: String): QrLogin = get("/api/login/qr/$id", QrLogin.serializer())
    suspend fun removeAccount(aid: Long, keepData: Boolean) = json("DELETE", "/api/accounts/$aid", params = mapOf("keep_data" to keepData))

    // ------------------------------------------------------------------ account
    suspend fun accountStatus(aid: Long): AccountStatus = get("${a(aid)}/status", AccountStatus.serializer(), background = true)
    suspend fun chats(aid: Long): List<Chat> = get("${a(aid)}/chats", Wrapped(ListSerializer(Chat.serializer()), "chats"))
    suspend fun dialogFilters(aid: Long): List<DialogFilter> = get("${a(aid)}/dialog_filters", Wrapped(ListSerializer(DialogFilter.serializer()), "filters"))
    suspend fun topics(aid: Long, chatId: Long): List<Topic> = get("${a(aid)}/topics/$chatId", Wrapped(ListSerializer(Topic.serializer()), "topics"))
    suspend fun excludeChat(aid: Long, chatId: Long, excluded: Boolean) =
        json("POST", "${a(aid)}/chats/$chatId/exclude", buildJsonObject { put("excluded", excluded) })
    suspend fun pinChat(aid: Long, chatId: Long, pinned: Boolean) = json("POST", "${a(aid)}/chats/$chatId/pin", buildJsonObject { put("pinned", pinned) })
    suspend fun rescanChat(aid: Long, chatId: Long) = json("POST", "${a(aid)}/chats/$chatId/rescan")
    suspend fun chatsBulk(aid: Long, action: String, chatIds: List<Long> = emptyList(), kind: String? = null) =
        json("POST", "${a(aid)}/chats/bulk", buildJsonObject {
            put("action", action); put("chat_ids", JsonArray(chatIds.map { JsonPrimitive(it) })); if (kind != null) put("kind", kind)
        })
    suspend fun index(aid: Long, action: String) = json("POST", "${a(aid)}/index/$action")

    suspend fun files(aid: Long, params: Map<String, String>): FilePage = get("${a(aid)}/files", FilePage.serializer(), params)
    suspend fun stats(aid: Long, params: Map<String, String>): FileStats = get("${a(aid)}/files/stats", FileStats.serializer(), params)
    suspend fun suggest(aid: Long, q: String): Suggestions = get("${a(aid)}/suggest", Suggestions.serializer(), mapOf("q" to q))
    suspend fun clearHistory(aid: Long, q: String? = null) = json("DELETE", "${a(aid)}/history", params = mapOf("q" to q))

    suspend fun detail(aid: Long, ref: FileRef): FileDetail {
        val el = JsonCodec.parseToJsonElement(raw("GET", "${a(aid)}/files/${ref.chatId}/${ref.msgId}"))
        val note = el.jsonObject["note"]?.jsonPrimitive?.contentOrNull
        val file = JsonCodec.decodeFromJsonElement(FileItem.serializer(), el)
        val extras = JsonCodec.decodeFromJsonElement(FileExtras.serializer(), el).copy(note = note)
        return FileDetail(file, extras)
    }

    suspend fun deleteFiles(aid: Long, refs: Collection<FileRef>): JsonObject =
        json("POST", "${a(aid)}/files/delete", buildJsonObject { put("items", items(refs)) }).jsonObject
    suspend fun forgetFiles(aid: Long, refs: Collection<FileRef>) = json("POST", "${a(aid)}/files/forget", buildJsonObject { put("items", items(refs)) })
    suspend fun place(aid: Long, refs: Collection<FileRef>, folderId: String?) =
        json("POST", "${a(aid)}/files/place", buildJsonObject { put("items", items(refs)); put("folder_id", folderId) })
    suspend fun rename(aid: Long, ref: FileRef, name: String) =
        json("POST", "${a(aid)}/files/${ref.chatId}/${ref.msgId}/rename", buildJsonObject { put("name", name) })
    suspend fun bulkRename(aid: Long, refs: Collection<FileRef>, pattern: String, start: Int): JsonObject =
        json("POST", "${a(aid)}/files/rename", buildJsonObject { put("items", items(refs)); put("pattern", pattern); put("start", start) }).jsonObject
    suspend fun meta(aid: Long, refs: Collection<FileRef>, starred: Boolean? = null, tagsAdd: List<String>? = null,
                     tagsRemove: List<String>? = null, tags: List<String>? = null, note: String? = null) =
        json("POST", "${a(aid)}/files/meta", buildJsonObject {
            put("items", items(refs))
            if (starred != null) put("starred", starred)
            if (tagsAdd != null) put("tags_add", JsonArray(tagsAdd.map { JsonPrimitive(it) }))
            if (tagsRemove != null) put("tags_remove", JsonArray(tagsRemove.map { JsonPrimitive(it) }))
            if (tags != null) put("tags", JsonArray(tags.map { JsonPrimitive(it) }))
            if (note != null) put("note", note)
        })
    suspend fun tags(aid: Long): List<Tag> = get("${a(aid)}/tags", Wrapped(ListSerializer(Tag.serializer()), "tags"))
    suspend fun copyToDrive(aid: Long, refs: Collection<FileRef>, folderId: String?): JsonObject =
        json("POST", "${a(aid)}/files/copy", buildJsonObject { put("items", items(refs)); put("folder_id", folderId) }).jsonObject
    suspend fun send(aid: Long, refs: Collection<FileRef>, chatId: Long, mode: String): JsonObject =
        json("POST", "${a(aid)}/files/send", buildJsonObject { put("items", items(refs)); put("chat_id", chatId); put("mode", mode) }).jsonObject

    suspend fun playback(aid: Long, ref: FileRef): JsonObject = get("${a(aid)}/playback/${ref.chatId}/${ref.msgId}", JsonObject.serializer())
    suspend fun savePlayback(aid: Long, ref: FileRef, pos: Double, dur: Double?, done: Boolean? = null) =
        json("PUT", "${a(aid)}/playback/${ref.chatId}/${ref.msgId}", buildJsonObject {
            put("pos", pos); if (dur != null) put("dur", dur); if (done != null) put("done", done)
        })
    suspend fun clearPlayback(aid: Long, ref: FileRef) = json("DELETE", "${a(aid)}/playback/${ref.chatId}/${ref.msgId}")
    suspend fun context(aid: Long, ref: FileRef, before: Int = 15, after: Int = 15): ChatContext =
        get("${a(aid)}/context/${ref.chatId}/${ref.msgId}", ChatContext.serializer(), mapOf("before" to before, "after" to after))

    // folders
    suspend fun folders(aid: Long): FoldersResponse = get("${a(aid)}/folders", FoldersResponse.serializer())
    suspend fun covers(aid: Long): Map<String, List<Cover>> =
        get("${a(aid)}/folders/covers", Wrapped(MapSerializer(String.serializer(), ListSerializer(Cover.serializer())), "covers"))
    suspend fun createFolder(aid: Long, name: String, parentId: String?, color: String = "", description: String = "",
                             emoji: String = "", rules: JsonElement? = null): Folder =
        JsonCodec.decodeFromJsonElement(Folder.serializer(), json("POST", "${a(aid)}/folders", buildJsonObject {
            put("name", name); put("parent_id", parentId); put("color", color); put("description", description); put("emoji", emoji)
            if (rules != null) put("rules", rules)
        }))
    suspend fun updateFolder(aid: Long, id: String, changes: JsonObject) = json("PATCH", "${a(aid)}/folders/$id", changes)
    suspend fun deleteFolder(aid: Long, id: String): JsonObject = json("DELETE", "${a(aid)}/folders/$id").jsonObject
    suspend fun downloadFolder(aid: Long, id: String, zip: Boolean): JsonElement =
        json("POST", "${a(aid)}/folders/$id/download", buildJsonObject { put("zip", zip) })
    suspend fun applyRules(aid: Long, id: String): JsonObject = json("POST", "${a(aid)}/folders/$id/apply-rules").jsonObject
    suspend fun rulesPreview(aid: Long, q: String, params: JsonObject): JsonObject =
        json("POST", "${a(aid)}/rules/preview", buildJsonObject { put("q", q); put("params", params) }).jsonObject

    suspend fun saveSearch(aid: Long, name: String, q: String, params: JsonObject, id: String? = null): SavedSearch =
        JsonCodec.decodeFromJsonElement(SavedSearch.serializer(), json("POST", "${a(aid)}/saved", buildJsonObject {
            put("name", name); put("q", q); put("params", params); if (id != null) put("id", id)
        }))
    suspend fun deleteSearch(aid: Long, id: String) = json("DELETE", "${a(aid)}/saved/$id")

    suspend fun undo(aid: Long): JsonObject = json("POST", "${a(aid)}/drive/undo").jsonObject
    suspend fun backups(aid: Long): List<Backup> = get("${a(aid)}/drive/backups", Wrapped(ListSerializer(Backup.serializer()), "backups"))
    suspend fun restoreBackup(aid: Long, id: Long) = json("POST", "${a(aid)}/drive/backups/$id/restore")
    suspend fun syncDrive(aid: Long) = json("POST", "${a(aid)}/drive/sync")
    suspend fun exportManifest(aid: Long): String = raw("GET", "${a(aid)}/drive/manifest")
    suspend fun importManifest(aid: Long, manifest: JsonElement, mode: String) =
        json("POST", "${a(aid)}/drive/manifest", manifest, mapOf("mode" to mode))

    // transfers
    suspend fun transfers(aid: Long): TransfersResponse = get("${a(aid)}/transfers", TransfersResponse.serializer(), background = true)
    suspend fun download(aid: Long, refs: Collection<FileRef>, zip: Boolean = false, keepStructure: Boolean = false, name: String? = null): JsonObject =
        json("POST", "${a(aid)}/transfers/download", buildJsonObject {
            put("items", items(refs)); put("zip", zip); put("keep_structure", keepStructure); if (name != null) put("name", name)
        }).jsonObject
    suspend fun transferAction(aid: Long, id: Long, action: String) = json("POST", "${a(aid)}/transfers/$id/$action")
    suspend fun transfersBulk(aid: Long, action: String) = json("POST", "${a(aid)}/transfers/bulk/$action")
    suspend fun removeTransfer(aid: Long, id: Long, deleteFile: Boolean) =
        json("DELETE", "${a(aid)}/transfers/$id", params = mapOf("delete_file" to deleteFile))

    /** Stream a local file into TG Drive (PUT /upload): it is queued for Telegram once fully received. */
    suspend fun upload(aid: Long, name: String, body: RequestBody, folderId: String?, rel: String = "", caption: String = "",
                       chatId: Long? = null): JsonObject {
        val text = raw("PUT", "${a(aid)}/upload", mapOf("name" to name, "folder_id" to folderId, "rel" to rel,
            "caption" to caption, "chat_id" to chatId), body)
        return JsonCodec.parseToJsonElement(text).jsonObject
    }

    // insights
    suspend fun storage(aid: Long): JsonObject = get("${a(aid)}/storage", JsonObject.serializer())
    suspend fun duplicates(aid: Long, mode: String, offset: Int): DuplicatesPage =
        get("${a(aid)}/duplicates", DuplicatesPage.serializer(), mapOf("mode" to mode, "offset" to offset))
    suspend fun activityLog(aid: Long): List<Activity> = get("${a(aid)}/activity", Wrapped(ListSerializer(Activity.serializer()), "activity"))
    suspend fun maintenance(aid: Long, task: String): JsonElement = json("POST", "${a(aid)}/maintenance/$task")
    suspend fun exportCsv(aid: Long, params: Map<String, String>): String = raw("GET", "${a(aid)}/export.csv", params)
    suspend fun subjects(aid: Long): JsonObject = get("${a(aid)}/subjects", JsonObject.serializer())
    suspend fun setSubject(aid: Long, refs: Collection<FileRef>, subject: String?) =
        json("POST", "${a(aid)}/subjects/set", buildJsonObject { put("items", items(refs)); put("subject", subject) })
    suspend fun subjectsToTags(aid: Long, params: JsonObject) = json("POST", "${a(aid)}/subjects/tags", buildJsonObject { put("params", params) })
    suspend fun rebuildSubjects(aid: Long) = json("POST", "${a(aid)}/subjects/rebuild")
    suspend fun timeline(aid: Long, params: Map<String, String>): Timeline = get("${a(aid)}/timeline", Timeline.serializer(), params)

    // ------------------------------------------------------------------ media URLs
    // Built while screens draw, so they must never throw: see [url].
    private fun mediaUrl(path: String, params: Map<String, Any?> = emptyMap()): String =
        try { url(path, params, media = true).toString() } catch (_: ApiException) { NOT_RUNNING }

    /**
     * While the service isn't running, a thumbnail's URL is one nothing listens on but with the same
     * [cacheKey]: a thumbnail seen before still shows from the image cache (the saved screen at start).
     */
    fun thumbUrl(aid: Long, chatId: Long, msgId: Long, v: String = "s"): String =
        mediaUrl("${a(aid)}/thumb/$chatId/$msgId", mapOf("v" to v)).let {
            if (it == NOT_RUNNING) "http://127.0.0.1:1${a(aid)}/thumb/$chatId/$msgId?v=$v" else it
        }

    /**
     * The image caches' key for a thumbnail: its path, without the service's port, which changes
     * every time the service starts (with the port in it, nothing cached outlived a restart).
     * Null for anything else (streams carry a token; they keep their full URL).
     */
    fun cacheKey(url: String): String? =
        THUMB.matchEntire(url)?.groupValues?.get(1)?.let { if (engine().demo) "demo$it" else it }
    fun docThumbUrl(aid: Long, chatId: Long, msgId: Long): String = mediaUrl("${a(aid)}/docthumb/$chatId/$msgId")

    /** A stream the app's own player uses (full access token). */
    fun streamUrl(aid: Long, f: FileItem, download: Boolean = false): String =
        mediaUrl("${a(aid)}/stream/${f.chatId}/${f.msgId}/${encodeName(f.name.ifEmpty { "file" })}",
            mapOf("t" to token, "dl" to if (download) 1 else null))

    /** A stream for other apps (VLC, MX Player …): the media token only plays this kind of URL. */
    fun externalStreamUrl(aid: Long, f: FileItem): String =
        mediaUrl("${a(aid)}/stream/${f.chatId}/${f.msgId}/${encodeName(f.name.ifEmpty { "file" })}",
            mapOf("t" to engine().mediaToken))

    suspend fun saveDocThumb(aid: Long, ref: FileRef, png: ByteArray) =
        raw("PUT", "${a(aid)}/docthumb/${ref.chatId}/${ref.msgId}", body = png.toRequestBody("image/jpeg".toMediaType()))
    suspend fun docThumbFailed(aid: Long, ref: FileRef) = raw("POST", "${a(aid)}/docthumb/${ref.chatId}/${ref.msgId}/failed")

    private fun encodeName(n: String) = java.net.URLEncoder.encode(n, "UTF-8").replace("+", "%20")

    companion object {
        /** A valid URL nothing listens on (connection refused at once), carrying no secret. */
        const val NOT_RUNNING = "http://127.0.0.1:1/not-running"
        private val THUMB = Regex("""^http://127\.0\.0\.1:\d+(/api/a/-?\d+/(?:doc)?thumb/-?\d+/\d+(?:\?[vr]=[^&]*)?)$""")
    }
}

/** Decodes `{"<key>": …}` to the value under key. */
private class Wrapped<T>(private val inner: KSerializer<T>, private val key: String) : DeserializationStrategy<T> {
    override val descriptor = inner.descriptor
    override fun deserialize(decoder: kotlinx.serialization.encoding.Decoder): T {
        val input = decoder as kotlinx.serialization.json.JsonDecoder
        val obj = input.decodeJsonElement().jsonObject
        return input.json.decodeFromJsonElement(inner, obj[key] ?: JsonArray(emptyList()))
    }
}

suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) {
            // Nobody waits any more: close it, on a background thread (closing may read the socket).
            cont.resume(response) { _, r, _ -> Dispatchers.IO.asExecutor().execute { runCatching { r.close() } } }
        }

        override fun onFailure(call: Call, e: IOException) {
            if (!cont.isCancelled) cont.resumeWithException(e)
        }
    })
    cont.invokeOnCancellation { runCatching { cancel() } }
}

fun JsonObject.str(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
fun JsonObject.long(k: String): Long = (this[k] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()?.toLong() ?: 0L
fun JsonObject.double(k: String): Double = (this[k] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull() ?: 0.0
fun JsonObject.bool(k: String, default: Boolean = false): Boolean = (this[k] as? JsonPrimitive)?.contentOrNull?.let {
    it == "true" || it == "1"
} ?: default
fun JsonObject.obj(k: String): JsonObject = (this[k] as? JsonObject) ?: JsonObject(emptyMap())
fun JsonObject.arr(k: String): JsonArray = (this[k] as? JsonArray) ?: JsonArray(emptyList())
fun JsonElement.asObj(): JsonObject = this as? JsonObject ?: JsonObject(emptyMap())

/** What went wrong, for the screen (never blank), after logging it with its stack for diagnosis. */
fun Throwable.explain(where: String): String {
    AppLog.w("error", "$where failed", this)
    return message?.takeIf { it.isNotBlank() } ?: javaClass.simpleName.ifBlank { "Unexpected error" }
}
