package app.lumaclean

import android.app.Application
import app.lumaclean.core.Operations
import app.lumaclean.core.PermissionState
import app.lumaclean.core.Task
import app.lumaclean.core.UiMessage
import app.lumaclean.core.formatBytes
import app.lumaclean.data.AppsRepository
import app.lumaclean.data.BatteryLogStore
import app.lumaclean.data.DuplicateEngine
import app.lumaclean.data.ExclusionStore
import app.lumaclean.data.FileIndexRepository
import app.lumaclean.data.FileOps
import app.lumaclean.data.HistoryStore
import app.lumaclean.data.JunkEngine
import app.lumaclean.data.JunkItem
import app.lumaclean.data.MediaRepository
import app.lumaclean.data.RecycleBin
import app.lumaclean.data.SettingsRepository
import app.lumaclean.data.SimilarGroup
import app.lumaclean.data.StorageRepository
import app.lumaclean.data.SystemRepository
import app.lumaclean.work.Notifier
import app.lumaclean.work.Scheduler
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.request.crossfade
import coil3.video.VideoFrameDecoder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.io.File

class LumaApp : Application(), SingletonImageLoader.Factory {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        Notifier.createChannels(this)
        Scheduler.apply(this, container.settings.current)
        container.scope.launch {
            container.settings.flow
                .map { Triple(it.weeklyCheckup, it.storageAlerts, it.batteryAlerts) }
                .distinctUntilChanged()
                .drop(1)
                .collect { Scheduler.apply(this@LumaApp, container.settings.current) }
        }
        container.scope.launch(Dispatchers.IO) { container.bin.reconcile() }
    }

    override fun newImageLoader(context: PlatformContext): ImageLoader =
        ImageLoader.Builder(context)
            .components { add(VideoFrameDecoder.Factory()) }
            .crossfade(true)
            .build()
}

data class FileClip(val paths: List<String>, val move: Boolean)

/** Everything long-lived: repositories, background tasks and the message bus. */
class AppContainer(val app: Application) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val messages = MutableSharedFlow<UiMessage>(extraBufferCapacity = 16)

    val settings = SettingsRepository(app)
    val history = HistoryStore(app)
    val exclusions = ExclusionStore(app)
    val batteryLog = BatteryLogStore(app)
    val perms = PermissionState(app)
    val index = FileIndexRepository()
    val storage = StorageRepository(app)
    val bin = RecycleBin(app, index.binDirName)
    val files = FileOps(app, index, bin)
    val junk = JunkEngine(app, index, exclusions, settings, storage)
    val duplicates = DuplicateEngine(index, exclusions)
    val apps = AppsRepository(app)
    val system = SystemRepository(app)
    val media = MediaRepository(app)
    val operations = Operations(scope, messages)
    val clipboard = MutableStateFlow<FileClip?>(null)

    val junkTask = Task(scope) { junk.scan(this) }
    val indexTask = Task(scope) { index.get(this) }
    val duplicatesTask = Task(scope) { duplicates.scan(this) }
    val appsTask = Task(scope) { apps.load(this) }
    val similarTask = Task(scope) { media.findSimilar(this) }

    @Volatile
    var usageDays = 7
    val usageTask = Task(scope) { apps.usage(usageDays, this) }

    fun message(text: String) {
        messages.tryEmit(UiMessage(text))
    }

    /** Rebuilds the storage index from scratch (the refresh button on storage screens). */
    fun refreshIndex() {
        index.invalidate()
        indexTask.restart()
    }

    /** Deletes [paths] (to the recycle bin unless [permanent] or the bin is off) and updates every result list. */
    fun deleteFiles(paths: Collection<String>, permanent: Boolean = false, what: String = "files") {
        if (paths.isEmpty()) return
        val toBin = !permanent && settings.current.useRecycleBin
        operations.run(if (toBin) "Moving to recycle bin" else "Deleting") {
            val r = files.remove(paths, toBin, this)
            forgetPaths(paths.filterNot { File(it).exists() }.toSet())
            if (!toBin) history.add("Deleted $what", r.done, r.bytes)
            val failed = if (r.failed > 0) " · ${r.failed} couldn't be removed" else ""
            if (toBin) {
                UiMessage("${r.done} moved to recycle bin$failed", "Undo") { restore(r.binIds) }
            } else {
                UiMessage("Deleted ${r.done} · ${r.bytes.formatBytes()} freed$failed")
            }
        }
    }

    fun cleanJunk(items: List<JunkItem>) {
        if (items.isEmpty()) return
        operations.run("Cleaning") {
            val (result, freed) = junk.clean(items, this, files)
            forgetPaths(items.map { it.path }.filterNot { File(it).exists() }.toSet())
            history.add("Smart Clean", result.done, freed)
            settings.update { it.copy(lastCleanAt = System.currentTimeMillis(), lastCleanBytes = freed) }
            UiMessage("Freed ${freed.formatBytes()} · ${result.done} items removed")
        }
    }

    fun restore(ids: List<String>) {
        if (ids.isEmpty()) return
        operations.run("Restoring") {
            val n = files.restore(ids)
            UiMessage("Restored $n ${if (n == 1) "item" else "items"}")
        }
    }

    /** Drops deleted paths from every finished result so screens update without a rescan. */
    fun forgetPaths(removed: Set<String>) {
        if (removed.isEmpty()) return
        junkTask.update { it.without(removed) }
        duplicatesTask.update { groups ->
            groups.map { g -> g.copy(files = g.files.filter { it.path !in removed }) }.filter { it.files.size > 1 }
        }
        similarTask.update { groups ->
            groups.mapNotNull { g ->
                val left = g.photos.filter { it.path !in removed }
                if (left.size < 2) null
                else SimilarGroup(left, if (g.best in left) g.best else left.maxBy { it.pixels })
            }
        }
    }
}
