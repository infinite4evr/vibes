package app.tgdrive.data

import android.content.Context
import app.tgdrive.diag.AppLog
import app.tgdrive.engine.EngineClient
import app.tgdrive.engine.EngineState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/** Where the app stands, which decides the first screen. */
sealed interface Phase {
    data object Starting : Phase                         // the engine is starting
    data class Failed(val error: String) : Phase          // the engine couldn't start
    data object Welcome : Phase                          // first run: sample data or your own account
    data object Locked : Phase                           // app lock
    data object NeedsApiKey : Phase                      // my.telegram.org app key
    data object NeedsLogin : Phase                       // no account signed in
    data object Ready : Phase
}

/** A message at the bottom of the screen; an error can carry details (what exactly failed) to show and report. */
data class UiMessage(val text: String, val error: Boolean = false, val action: String? = null, val onAction: (() -> Unit)? = null,
                     val detail: String? = null)

/**
 * The shared state of the interface (the desktop window's `S`): the service's status and settings,
 * the chosen account and its live status, folders, chats, tags … kept current by the service's
 * live event stream, exactly as the desktop window does.
 */
class AppState(
    context: Context,
    val api: Api,
    val engine: EngineClient,
    http: OkHttpClient,
    private val scope: CoroutineScope,
) {
    private val prefs = context.getSharedPreferences("app", Context.MODE_PRIVATE)
    private val streamHttp = http.newBuilder().readTimeout(40, TimeUnit.SECONDS).build()

    /** The last screen's data, shown at once on the next start while the service starts (see [StartupCache]). */
    val cache = StartupCache(context, scope)

    private val _phase = MutableStateFlow<Phase>(Phase.Starting)

    /** The service is starting again under an open screen (shown as a small bar, not the start screen). */
    private val _reconnecting = MutableStateFlow(false)
    val reconnecting: StateFlow<Boolean> = _reconnecting.asStateFlow()
    val phase: StateFlow<Phase> = _phase.asStateFlow()

    private val _status = MutableStateFlow<AppStatus?>(null)
    val status: StateFlow<AppStatus?> = _status.asStateFlow()

    private val _settings = MutableStateFlow(JsonObject(emptyMap()))
    val settings: StateFlow<JsonObject> = _settings.asStateFlow()

    private val _aid = MutableStateFlow(prefs.getLong("aid", 0L))
    val aid: StateFlow<Long> = _aid.asStateFlow()

    private val _account = MutableStateFlow<AccountStatus?>(null)
    val account: StateFlow<AccountStatus?> = _account.asStateFlow()

    /**
     * The top bar's transfers badge: active transfers and their progress. The account status comes
     * every second while indexing; this changes only when the badge does, so the bar isn't redrawn.
     */
    val transferBadge: StateFlow<Pair<Int, Float?>> = _account
        .map { a -> (a?.transfers?.active ?: 0) to a?.transfers?.let { if (it.size > 0) it.done.toFloat() / it.size else null } }
        .distinctUntilChanged()
        .stateIn(scope, SharingStarted.Eagerly, 0 to null)

    private val _folders = MutableStateFlow(FoldersResponse())
    val folders: StateFlow<FoldersResponse> = _folders.asStateFlow()

    private val _chats = MutableStateFlow<List<Chat>>(emptyList())
    val chats: StateFlow<List<Chat>> = _chats.asStateFlow()

    private val _filters = MutableStateFlow<List<DialogFilter>>(emptyList())
    val dialogFilters: StateFlow<List<DialogFilter>> = _filters.asStateFlow()

    private val _tags = MutableStateFlow<List<Tag>>(emptyList())
    val tags: StateFlow<List<Tag>> = _tags.asStateFlow()

    private val _subjects = MutableStateFlow<List<Subject>>(emptyList())
    val subjects: StateFlow<List<Subject>> = _subjects.asStateFlow()

    private val _transfers = MutableStateFlow(TransfersResponse())
    val transfers: StateFlow<TransfersResponse> = _transfers.asStateFlow()

    /** Something changed files in the lists (new files arrived, an action finished): lists reload. */
    private val _changes = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val changes: SharedFlow<String> = _changes.asSharedFlow()

    private val _messages = MutableSharedFlow<UiMessage>(extraBufferCapacity = 8)
    val messages: SharedFlow<UiMessage> = _messages.asSharedFlow()

    private var live: Job? = null
    private var lastEvent = 0L
    private var welcomed: Boolean
        get() = prefs.getBoolean("welcomed", false)
        set(v) { prefs.edit().putBoolean("welcomed", v).apply() }

    /** The service became ready while no screen was showing (the background sync woke this process). */
    private var bootstrapWhenVisible = false

    private fun appVisible() = androidx.lifecycle.ProcessLifecycleOwner.get().lifecycle.currentState
        .isAtLeast(androidx.lifecycle.Lifecycle.State.STARTED)

    init {
        scope.launch {
            engine.state.collect { s -> onEngine(s) }
        }
        scope.launch { cache.load()?.let { showCached(it) } }
        // Load everything (and follow live updates) only once someone is looking.
        scope.launch {
            androidx.lifecycle.ProcessLifecycleOwner.get().lifecycle.currentStateFlow.collect {
                if (it.isAtLeast(androidx.lifecycle.Lifecycle.State.STARTED) && bootstrapWhenVisible) {
                    bootstrapWhenVisible = false
                    if (engine.state.value.ready) bootstrap()
                }
            }
        }
        // "Detailed debug logging" (Settings → About & diagnostics) also makes the app's own log detailed.
        scope.launch { settings.collect { AppLog.verbose = it.bool("debug_logging") } }
        scope.launch { phase.collect { AppLog.i("app", "now: ${it.javaClass.simpleName}${(it as? Phase.Failed)?.let { f -> " (${f.error})" } ?: ""}") } }
    }

    val demo: Boolean get() = engine.state.value.demo

    // ------------------------------------------------------------------ engine
    private var lastEngine: EngineState? = null
    private var accountGeneration = 0L
    private var bootJob: Job? = null

    private suspend fun onEngine(s: EngineState) {
        val prev = lastEngine
        lastEngine = s
        when (s.phase) {
            EngineState.Phase.Ready -> if (prev?.ready != true || prev.startedAt != s.startedAt) {
                if (appVisible()) bootstrap() else bootstrapWhenVisible = true
            }
            EngineState.Phase.Failed -> { accountGeneration++; bootJob?.cancel(); stopLive(); _reconnecting.value = false; _phase.value = Phase.Failed(s.error ?: "TG Drive's service didn't start.") }
            else -> {
                accountGeneration++
                bootJob?.cancel()
                stopLive()
                when {
                    !welcomed -> _phase.value = Phase.Welcome
                    // The service stopped while the app was away (it does after a minute, to save
                    // battery) and starts again now: keep the screen as it was, just say so.
                    _phase.value == Phase.Ready -> _reconnecting.value = true
                    _phase.value !is Phase.Failed -> _phase.value = Phase.Starting
                }
            }
        }
    }

    /** First screen: sample data or your own account. */
    fun chooseStart(demo: Boolean) {
        welcomed = true
        _phase.value = Phase.Starting
        scope.launch {
            if (engine.state.value.ready && engine.state.value.demo != demo) engine.restart(demo) else engine.start(demo)
            // The app is on screen: keep the service running (MainActivity does this on every later start).
            engine.hold("ui", true)
        }
    }

    fun needsWelcome(): Boolean = !welcomed

    fun retryEngine() {
        _phase.value = Phase.Starting
        bootFailedSince = 0
        // A service that runs but doesn't answer needs a fresh process, not just a start.
        scope.launch { if (engine.state.value.ready) engine.restart(engine.demo) else engine.start() }
    }

    /** Since when the running service hasn't answered (0: it answers). */
    private var bootFailedSince = 0L

    suspend fun switchMode(demo: Boolean) {
        _phase.value = Phase.Starting
        stopLive()
        engine.restart(demo)
    }

    /**
     * Open straight onto what the main screen showed last time, instead of the start screen, while
     * the service starts: the "Connecting" bar says so, and [bootstrap] replaces it all once the
     * service answers. Only when nothing newer is known yet and nothing has to come first (the
     * first-run choice, a passcode, signing in).
     */
    private fun showCached(c: StartupCache.Snapshot) {
        if (_phase.value != Phase.Starting || !welcomed || c.demo != engine.demo) return
        val st = c.status
        if (st.locked || st.lockSet || !st.apiConfigured || st.accounts.none { it.id == c.aid }) return
        AppLog.i("app", "showing the saved screen while the service starts (${c.pages.size} list(s))")
        _status.value = st
        _settings.value = st.settings
        _aid.value = c.aid
        _account.value = c.account
        _folders.value = c.folders
        _chats.value = c.chats
        _filters.value = c.filters
        _tags.value = c.tags
        _subjects.value = c.subjects
        _reconnecting.value = true
        _phase.value = Phase.Ready
    }

    // ------------------------------------------------------------------ bootstrap
    fun bootstrap() {
        accountGeneration++
        bootJob?.cancel()
        bootJob = scope.launch {
            try {
                val st = kotlinx.coroutines.withTimeout(25_000) {
                    while (true) {
                        try { return@withTimeout api.status() }
                        catch (e: kotlinx.coroutines.TimeoutCancellationException) { kotlinx.coroutines.currentCoroutineContext().ensureActive(); delay(800) }
                        catch (e: kotlinx.coroutines.CancellationException) { throw e }
                        catch (e: Exception) { if (!engine.state.value.ready) throw e; delay(800) }
                    }
                    @Suppress("UNREACHABLE_CODE")
                    error("No status")
                }
                _status.value = st
                _settings.value = st.settings
                val cacheable = !st.locked && !st.lockSet && st.apiConfigured && st.accounts.isNotEmpty()
                if (!cacheable) cache.clear()
                _phase.value = when {
                    st.locked -> Phase.Locked
                    !st.apiConfigured -> Phase.NeedsApiKey
                    st.accounts.isEmpty() -> Phase.NeedsLogin
                    else -> {
                        val chosen = st.accounts.firstOrNull { it.id == _aid.value } ?: st.accounts.first()
                        if (cacheable) cache.start(st, chosen.id, engine.demo)
                        selectAccount(chosen.id, announce = false)
                        Phase.Ready
                    }
                }
                if (_phase.value == Phase.Ready) startLive()
                if (_reconnecting.value) { _reconnecting.value = false; _changes.tryEmit("reconnected") }
            } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                _reconnecting.value = false
                _phase.value = Phase.Failed("TG Drive's service did not answer within 25 seconds. Try again.")
            } catch (e: kotlinx.coroutines.CancellationException) { throw e
            } catch (e: Exception) {
                _reconnecting.value = false
                _phase.value = Phase.Failed("TG Drive's service did not answer: ${e.message}")
            }
        }
    }

    fun selectAccount(id: Long, announce: Boolean = true) {
        if (_aid.value != id) {
            accountGeneration++
            _tags.value = emptyList(); _subjects.value = emptyList(); _filters.value = emptyList()
            _transfers.value = TransfersResponse()
            _aid.value = id
            prefs.edit().putLong("aid", id).apply()
            _account.value = null
            _folders.value = FoldersResponse()
            _chats.value = emptyList()
            _status.value?.let { if (cache.snapshot != null) cache.start(it, id, engine.demo) }
        }
        reloadAll()
        if (announce) { startLive(); _changes.tryEmit("account") }
    }

    fun reloadAll() {
        scope.launch { loadFolders() }
        scope.launch { loadChats() }
        scope.launch { loadTags() }
        scope.launch { loadSubjects() }
        scope.launch { loadTransfers() }
        scope.launch { loadAccount() }
    }

    private suspend fun <T> accountLoad(fetch: suspend (Long) -> T, apply: (T) -> Unit) {
        val id = _aid.value
        val revision = accountGeneration
        try {
            val result = fetch(id)
            if (id == _aid.value && revision == accountGeneration) apply(result)
        } catch (e: kotlinx.coroutines.CancellationException) { throw e
        } catch (e: Exception) {
            if (id == _aid.value && revision == accountGeneration) {
                if (e is ApiException && e.locked) onLocked() else e.explain("loading")
            }
        }
    }
    private suspend fun loadAccount() = accountLoad({ api.accountStatus(it) }) { a ->
        _account.value = a; cache.update { it.copy(account = a) }
    }
    suspend fun loadFolders() = accountLoad({ api.folders(it) }) { f ->
        _folders.value = f; cache.update { it.copy(folders = f) }
    }
    suspend fun loadChats() = accountLoad({ id -> api.chats(id) to api.dialogFilters(id) }) { (chats, filters) ->
        _chats.value = chats; _filters.value = filters
        cache.update { it.copy(chats = chats, filters = filters) }
    }
    suspend fun loadTags() = accountLoad({ api.tags(it) }) { tags ->
        _tags.value = tags; cache.update { it.copy(tags = tags) }
    }
    suspend fun loadSubjects() = accountLoad({ api.subjects(it) }) { obj ->
        val list = obj["subjects"]?.let { JsonCodec.decodeFromJsonElement(kotlinx.serialization.builtins.ListSerializer(Subject.serializer()), it) }
        _subjects.value = if (obj.bool("enabled", true)) list.orEmpty() else emptyList()
        cache.update { it.copy(subjects = _subjects.value) }
    }
    suspend fun loadTransfers() = accountLoad({ api.transfers(it) }) { _transfers.value = it }

    suspend fun refreshStatus() = safely {
        val st = api.status()
        _status.value = st
        _settings.value = st.settings
        if (st.lockSet || st.locked) cache.clear() else cache.update { it.copy(status = st.copy(mediaToken = "")) }
    }

    /** Change settings (shared with the desktop app's Settings), applied at once. */
    fun setSetting(key: String, value: Any?) {
        val v = when (value) {
            null -> kotlinx.serialization.json.JsonNull
            is Boolean -> JsonPrimitive(value)
            is Number -> JsonPrimitive(value)
            is kotlinx.serialization.json.JsonElement -> value
            else -> JsonPrimitive(value.toString())
        }
        _settings.value = JsonObject(_settings.value + (key to v))
        scope.launch {
            try {
                val res = api.patchSettings(buildJsonObject { put(key, v) })
                res["settings"]?.let { _settings.value = it.jsonObject }
                cache.update { it.copy(status = it.status.copy(settings = _settings.value)) }
            } catch (e: Exception) {
                failed("Couldn't change that setting.", e)
                refreshStatus()
            }
        }
    }

    fun setting(key: String): String? = (_settings.value[key] as? JsonPrimitive)?.contentOrNull

    /** Choices kept on this phone only (like the desktop window's own preferences): folder order, last tab … */
    private val _local = MutableStateFlow(prefs.all.filterKeys { it.startsWith("pref.") }
        .mapKeys { it.key.removePrefix("pref.") }.mapValues { it.value.toString() })
    val local: StateFlow<Map<String, String>> = _local.asStateFlow()

    fun pref(key: String): String? = _local.value[key]

    fun setPref(key: String, value: String?) {
        _local.value = if (value == null) _local.value - key else _local.value + (key to value)
        prefs.edit().apply { if (value == null) remove("pref.$key") else putString("pref.$key", value) }.apply()
    }

    fun changed(what: String = "files") {
        _changes.tryEmit(what)
    }

    private var newFilesJob: Job? = null
    private var lastNewFiles = 0L

    /**
     * New files arrived (they come one by one while a chat is indexed): lists refresh at most every
     * [NEW_FILES_EVERY] ms, not once per file: a list reloading every second is jumpy and costs battery.
     */
    private fun newFilesArrived() {
        if (newFilesJob?.isActive == true) return
        val wait = (NEW_FILES_EVERY - (System.currentTimeMillis() - lastNewFiles)).coerceAtLeast(0)
        newFilesJob = scope.launch {
            delay(wait)
            lastNewFiles = System.currentTimeMillis()
            changed("new")
        }
    }

    fun message(text: String, error: Boolean = false, action: String? = null, onAction: (() -> Unit)? = null, detail: String? = null) {
        if (error) AppLog.w("message", text + (detail?.let { "\n$it" } ?: "")) else AppLog.d("message", text)
        _messages.tryEmit(UiMessage(text, error, action, onAction, detail))
    }

    /** Say that something failed: the reason on screen, the full story in the log and behind "Details". */
    fun failed(what: String, e: Throwable) {
        val reason = e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName.ifBlank { "Unexpected error" }
        message(reason, error = true, detail = "$what failed:\n${AppLog.stack(e).take(4000)}")
    }

    fun onLocked() {
        accountGeneration++
        cache.clear()
        _phase.value = Phase.Locked
        stopLive()
    }

    fun onUnlocked() = bootstrap()

    private suspend fun safely(block: suspend () -> Unit) {
        try {
            block()
        } catch (e: ApiException) {
            if (e.locked) onLocked() else e.explain("loading")
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            e.explain("loading")
        }
    }

    // ------------------------------------------------------------------ live updates
    private fun stopLive() {
        live?.cancel()
        live = null
    }

    /** The service's server-sent events: account status once a second when it changes, and events. */
    private fun startLive() {
        stopLive()
        val aid = _aid.value
        live = scope.launch(Dispatchers.IO) {
            var failures = 0
            while (isActive) {
                try {
                    val url = "${api.base}/api/stream-events?aid=$aid&after=$lastEvent"
                    val req = Request.Builder().url(url).header("x-tgdrive-token", api.token).header("x-tgdrive-bg", "1").build()
                    streamHttp.newCall(req).execute().use { resp ->
                        if (resp.code == 423) { withContext(Dispatchers.Main) { onLocked() }; return@launch }
                        if (!resp.isSuccessful) throw java.io.IOException("HTTP ${resp.code}")
                        failures = 0
                        val src = resp.body.source()
                        var event = ""
                        val data = StringBuilder()
                        while (isActive) {
                            val line = src.readUtf8Line() ?: break
                            when {
                                line.startsWith("event:") -> event = line.substring(6).trim()
                                line.startsWith("data:") -> data.append(line.substring(5).trim())
                                line.isEmpty() -> {
                                    if (data.isNotEmpty()) {
                                        val payload = data.toString()
                                        withContext(Dispatchers.Main) { onLive(event, payload) }
                                    }
                                    event = ""
                                    data.clear()
                                }
                            }
                        }
                    }
                } catch (e: Exception) {
                    if (!isActive) break
                    failures++
                }
                delay(if (failures > 3) 5000 else 1500)
                if (!engine.state.value.ready) break
            }
        }
    }

    private var loadedChatsAt = 0L

    private fun onLive(event: String, payload: String) {
        val obj = try { JsonCodec.parseToJsonElement(payload).jsonObject } catch (_: Exception) { return }
        when (event) {
            "status" -> {
                if (obj.bool("locked")) { onLocked(); return }
                if (obj.containsKey("none")) return
                val before = _account.value
                val st = try { JsonCodec.decodeFromJsonElement(AccountStatus.serializer(), obj) } catch (_: Exception) { return }
                _account.value = st
                if (before?.transfers?.active != st.transfers.active) scope.launch { loadTransfers() }
                val indexing = st.index.phase !in setOf("idle", "paused")
                val now = System.currentTimeMillis()
                if (indexing && now - loadedChatsAt > 20_000) { loadedChatsAt = now; scope.launch { loadChats() } }
                if (before != null && before.index.phase !in setOf("idle", "paused") && !indexing) scope.launch { loadChats() }
                if (before != null && before.drive.channelId != st.drive.channelId) scope.launch { loadFolders() }
                if (before != null && before.search.str("state") != "ready" && st.search.str("state") == "ready") {
                    message("Search upgrade finished: smart matching is on.")
                    changed("search")
                }
            }
            "events" -> {
                val first = lastEvent == 0L
                lastEvent = obj.long("last")
                if (first) return
                val events = obj["events"]?.let {
                    JsonCodec.decodeFromJsonElement(kotlinx.serialization.builtins.ListSerializer(ServerEvent.serializer()), it)
                }.orEmpty()
                var newFiles = false
                for (ev in events) {
                    when (ev.kind) {
                        "new_file" -> newFiles = true
                        "connection" -> if (ev.account == _aid.value) {
                            val online = ev.online == true
                            message(if (online) "Connected to Telegram again." else "Lost the connection to Telegram. Reconnecting…", error = !online)
                        }
                        "notify" -> if (ev.account == _aid.value) {
                            scope.launch { loadTransfers() }
                            changed("transfer")
                        }
                        "search_ready" -> changed("search")
                    }
                }
                if (newFiles) newFilesArrived()
            }
        }
    }
}

private const val NEW_FILES_EVERY = 15_000L
