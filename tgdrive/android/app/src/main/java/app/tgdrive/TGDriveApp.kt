package app.tgdrive

import android.app.Application
import android.os.Build
import android.os.Process
import app.tgdrive.data.Api
import app.tgdrive.data.AppState
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
import okhttp3.OkHttpClient
import okio.Path.Companion.toOkioPath
import java.util.concurrent.TimeUnit

class TGDriveApp : Application(), SingletonImageLoader.Factory {

    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        // The engine process (TG Drive's Python service) needs none of the interface's objects.
        if (processName().endsWith(":engine")) return
        EngineService.createChannels(this)
        graph = AppGraph(this)
    }

    override fun newImageLoader(context: PlatformContext): ImageLoader = ImageLoader.Builder(context)
        .components { add(OkHttpNetworkFetcherFactory(callFactory = { graph.mediaHttp })) }
        .memoryCache { MemoryCache.Builder().maxSizePercent(context, 0.2).build() }
        // Thumbnails are cached by TG Drive's service already; a small disk cache still makes
        // scrolling back instant after the service restarts.
        .diskCache { DiskCache.Builder().directory(cacheDir.resolve("images").toOkioPath()).maxSizeBytes(128L * 1024 * 1024).build() }
        .crossfade(180)
        .build()

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
