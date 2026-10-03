package app.tgdrive

import android.app.Application
import android.os.Build
import android.os.Process
import app.tgdrive.data.Api
import app.tgdrive.data.AppState
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.engine.EngineClient
import app.tgdrive.engine.EngineService
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.disk.DiskCache
import coil3.memory.MemoryCache
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.crossfade
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import app.tgdrive.diag.AppLog
import okhttp3.OkHttpClient
import okio.Path.Companion.toOkioPath
import java.util.concurrent.TimeUnit

class TGDriveApp : Application(), SingletonImageLoader.Factory, androidx.work.Configuration.Provider {

    /** Preferences come from the selected data folder first (a no-op once restored; retried after a failure). */
    val graph: AppGraph by lazy {
        if (app.tgdrive.storage.DataLocation.ready(this)) app.tgdrive.storage.PortablePreferences.attach(this)
        AppGraph(this)
    }

    /** "app" (the interface), "engine" (TG Drive's Python service) or "crash" (the crash screen). */
    private val process: String by lazy {
        val p = processName()
        when {
            p.endsWith(":bootstrap") -> "bootstrap"
            p.endsWith(":engine") -> "engine"
            p.endsWith(":crash") -> "crash"
            else -> "app"
        }
    }

    override fun attachBaseContext(base: android.content.Context) {
        super.attachBaseContext(base)
        // As early as possible: before the libraries' content providers start, so a crash anywhere
        // (even while the app is still starting) reaches the crash screen instead of closing the app.
        AppLog.installCrashHandler(this, process)
    }

    override fun onCreate() {
        super.onCreate()
        AppLog.init(this, process)
        // The engine process (TG Drive's Python service) and the crash screen need none of the interface's objects.
        if (process != "app") return
        try {
            EngineService.createChannels(this)
            if (app.tgdrive.storage.DataLocation.ready(this)) {
                app.tgdrive.storage.DataLocation.prepare(this)
                app.tgdrive.storage.PortablePreferences.attach(this)
            }
        } catch(t: Throwable) { AppLog.e("startup","Could not load the selected data folder",t) }   // shown by MainActivity
    }

    /** WorkManager (background sync) lives in this process only, never in the engine's. */
    override val workManagerConfiguration: androidx.work.Configuration
        get() = androidx.work.Configuration.Builder().setDefaultProcessName(packageName).build()

    override fun newImageLoader(context: PlatformContext): ImageLoader = ImageLoader.Builder(context)
        .components {
            add(OkHttpNetworkFetcherFactory(callFactory = { graph.mediaHttp }))
            add(stableThumbKeys)
        }
        .memoryCache { MemoryCache.Builder().maxSizePercent(context, 0.2).build() }
        // Thumbnails are cached by TG Drive's service already; a small disk cache still makes
        // scrolling back instant after the service restarts.
        .diskCache { DiskCache.Builder().directory((app.tgdrive.storage.DataLocation.root(this)?.resolve("android/images") ?: cacheDir.resolve("images")).toOkioPath()).maxSizeBytes(128L * 1024 * 1024).build() }
        .crossfade(180)
        .build()

    /** Thumbnails are cached under their path, not their URL (see [app.tgdrive.data.Api.cacheKey]). */
    private val stableThumbKeys = object : coil3.intercept.Interceptor {
        override suspend fun intercept(chain: coil3.intercept.Interceptor.Chain): coil3.request.ImageResult {
            val req = chain.request
            val path = (req.data as? String)?.let { graph.api.cacheKey(it) } ?: return chain.proceed()
            // The sample data's account ids aren't Telegram's: never mix their thumbnails.
            val key = if (graph.engine.demo) "demo$path" else path
            return chain.withRequest(req.newBuilder().memoryCacheKey("$key#${chain.size}").diskCacheKey(key).build()).proceed()
        }
    }

    private fun processName(): String = if (Build.VERSION.SDK_INT >= 28) getProcessName() else
        runCatching { java.io.File("/proc/${Process.myPid()}/cmdline").readText().trim('\u0000') }.getOrDefault(packageName)
}

/** The objects the interface shares (one per app process). */
class AppGraph(val app: TGDriveApp) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    val engine = EngineClient(app)

    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(0, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    /** For pictures and streams: carries the engine's secret on every request to it. */
    val mediaHttp: OkHttpClient = http.newBuilder()
        .readTimeout(60, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val req = chain.request()
            val s = engine.state.value
            if (req.url.host == "127.0.0.1" && s.token.isNotEmpty())
                chain.proceed(req.newBuilder().header("x-tgdrive-token", s.token).build())
            else chain.proceed(req)
        }
        .build()

    val api = Api(http) { engine.state.value }
    val state = AppState(app, api, engine, http, scope)
}

val android.content.Context.graph: AppGraph get() = (applicationContext as TGDriveApp).graph
