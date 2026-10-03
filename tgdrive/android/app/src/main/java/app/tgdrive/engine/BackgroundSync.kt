package app.tgdrive.engine

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.tgdrive.diag.AppLog
import app.tgdrive.graph
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.TimeUnit

/**
 * Background sync: every so often, TG Drive checks your chats for new files and indexes them while
 * the app is closed, so search and folders are up to date when you open it.
 *
 * Made to cost little battery: Android's job scheduler decides the moment (it batches with other
 * apps, waits out Doze, needs a network and a battery that isn't low; optionally Wi-Fi or charging),
 * the service runs without a notification and without its CPU-heavy jobs (meaning index, subjects,
 * duplicates: they catch up when the app is opened), and it stops as soon as the chats are checked,
 * at most [BUDGET_MS] later. Settings → This phone turns it off or changes how often.
 */
object BackgroundSync {
    private const val WORK = "tgdrive-sync"
    private const val WORK_NOW = "tgdrive-sync-now"
    const val BUDGET_MS = 8 * 60_000L          // WorkManager allows 10 minutes
    val INTERVALS = listOf(30, 60, 180, 360, 720)   // minutes

    private fun prefs(c: Context) = c.getSharedPreferences("sync", Context.MODE_PRIVATE)

    fun enabled(c: Context) = prefs(c).getBoolean("enabled", true)
    fun minutes(c: Context) = prefs(c).getInt("minutes", 60).let { if (it in INTERVALS) it else 60 }
    fun wifiOnly(c: Context) = prefs(c).getBoolean("wifi_only", false)
    fun chargingOnly(c: Context) = prefs(c).getBoolean("charging_only", false)

    /** The last run: when it ended (ms, 0 = never), what it found, and whether one is running now. */
    data class Last(val at: Long, val result: String, val ok: Boolean, val running: Boolean)

    fun last(c: Context): Last = prefs(c).let {
        val runningSince = it.getLong("running_since", 0)
        Last(it.getLong("last_at", 0), it.getString("last_result", "") ?: "", it.getBoolean("last_ok", true),
            runningSince > 0 && System.currentTimeMillis() - runningSince < BUDGET_MS + 120_000)
    }

    fun update(c: Context, enabled: Boolean = enabled(c), minutes: Int = minutes(c), wifiOnly: Boolean = wifiOnly(c),
               chargingOnly: Boolean = chargingOnly(c)) {
        prefs(c).edit().putBoolean("enabled", enabled).putInt("minutes", minutes).putBoolean("wifi_only", wifiOnly)
            .putBoolean("charging_only", chargingOnly).apply()
        schedule(c, replace = true)
    }

    private fun constraints(c: Context) = Constraints.Builder()
        .setRequiredNetworkType(if (wifiOnly(c)) NetworkType.UNMETERED else NetworkType.CONNECTED)
        .setRequiresBatteryNotLow(true)
        .setRequiresCharging(chargingOnly(c))
        .build()

    /** Keep the schedule matching the settings (at every start of the app, and when they change). */
    fun schedule(c: Context, replace: Boolean = false) {
        runCatching {
            val wm = WorkManager.getInstance(c)
            if (!enabled(c)) {
                wm.cancelUniqueWork(WORK)
                return
            }
            val min = minutes(c).toLong()
            val req = PeriodicWorkRequestBuilder<SyncWorker>(min, TimeUnit.MINUTES, (min / 4).coerceAtLeast(5), TimeUnit.MINUTES)
                .setConstraints(constraints(c))
                .setInitialDelay(min, TimeUnit.MINUTES)   // not right away: the app has just been used
                .build()
            wm.enqueueUniquePeriodicWork(WORK, if (replace) ExistingPeriodicWorkPolicy.UPDATE else ExistingPeriodicWorkPolicy.KEEP, req)
        }.onFailure { AppLog.w("sync", "couldn't schedule the background sync", it) }
    }

    internal fun indexComplete(states: List<Pair<Long, app.tgdrive.data.IndexStatus>>): Boolean {
        val failed = states.firstOrNull { (_, index) -> index.phase == "error" || !index.error.isNullOrBlank() }
        if (failed != null) error("Account ${failed.first}: ${failed.second.error ?: "indexing failed"}")
        if (states.any { it.second.phase == "paused" }) error("Indexing is paused. Resume indexing to complete sync.")
        return states.isNotEmpty() && states.all { it.second.phase == "idle" }
    }

    /** Settings → Sync now (still waits for a network). */
    fun syncNow(c: Context) {
        val req = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(c).enqueueUniqueWork(WORK_NOW, ExistingWorkPolicy.KEEP, req)
    }

    internal fun started(c: Context) = prefs(c).edit().putLong("running_since", System.currentTimeMillis()).apply()

    internal fun finished(c: Context, result: String, ok: Boolean) = prefs(c).edit()
        .putLong("running_since", 0).putLong("last_at", System.currentTimeMillis())
        .putString("last_result", result).putBoolean("last_ok", ok).apply()
}

/** One background sync: bind the service, have every account check its chats, wait until indexed. */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val c = applicationContext
        val g = c.graph
        val t0 = System.currentTimeMillis()
        BackgroundSync.started(c)
        AppLog.i("sync", "background sync starting (attempt ${runAttemptCount + 1}; ${BatteryLimits.status(c).describe()})")
        val conn = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, service: IBinder?) {}
            override fun onServiceDisconnected(name: ComponentName?) {}
        }
        var bound = false
        return try { kotlinx.coroutines.withTimeout(BackgroundSync.BUDGET_MS) {
            val intent = Intent(c, EngineService::class.java).putExtra(EngineService.EXTRA_DEMO, g.engine.demo)
            val boundAt = System.currentTimeMillis()
            bound = c.bindService(intent, conn, Context.BIND_AUTO_CREATE)
            if (!bound) throw IllegalStateException("Android didn't let the background sync reach TG Drive's service")
            // A failure recorded before this sync (an earlier run of the app) says nothing about this start.
            val s = withTimeoutOrNull(150_000) {
                g.engine.state.first { it.ready || (it.phase == EngineState.Phase.Failed && it.updatedAt >= boundAt) }
            } ?: throw IllegalStateException("TG Drive's service didn't start in time (${g.engine.state.value.phase})")
            if (!s.ready) throw IllegalStateException(s.error ?: "TG Drive's service didn't start")

            val st = g.api.status()
            if (st.locked) {
                // A locked TG Drive shows nothing, not even its accounts, until the passcode is entered.
                BackgroundSync.finished(c, "Locked with the app passcode: syncs after you unlock TG Drive", true)
                return@withTimeout Result.success()
            }
            val accounts = st.accounts.filter { it.status != "logged_out" }
            if (accounts.isEmpty()) {
                BackgroundSync.finished(c, "Not signed in: nothing to sync", true)
                return@withTimeout Result.success()
            }
            val before = HashMap<Long, Long>()
            for (a in accounts) {
                // Signed-in accounts connect to Telegram first (a few seconds).
                withTimeoutOrNull(60_000) {
                    while (g.api.accountStatus(a.id).account?.status != "online") delay(1000)
                    true
                } ?: error("Account ${a.id}: could not connect to Telegram")
                before[a.id] = g.api.accountStatus(a.id).index.files
                g.api.index(a.id, "resync")
            }
            // Until every account has checked its chats (it says "idle" again), within the budget.
            delay(5000)
            var done = false
            while (!done && System.currentTimeMillis() - t0 < BackgroundSync.BUDGET_MS && !isStopped) {
                val states = accounts.map { it.id to g.api.accountStatus(it.id).index }
                done = BackgroundSync.indexComplete(states)
                if (!done) delay(4000)
            }
            val added = accounts.sumOf { (g.api.accountStatus(it.id).index.files - (before[it.id] ?: 0)).coerceAtLeast(0) }
            val secs = (System.currentTimeMillis() - t0) / 1000
            val text = when {
                !done -> "Stopped after ${secs / 60} min (continues next time)" + if (added > 0) " · $added new files" else ""
                added > 0 -> "$added new ${if (added == 1L) "file" else "files"} · took ${secs}s"
                else -> "Up to date · took ${secs}s"
            }
            AppLog.i("sync", "background sync done: $text")
            BackgroundSync.finished(c, text, done)
            Result.success()
        } } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
            BackgroundSync.finished(c, "Sync time limit reached; some accounts may be incomplete. Retry in Recovery.", false)
            Result.success()
        } catch (e: kotlinx.coroutines.CancellationException) {
            AppLog.i("sync", "background sync stopped by Android")
            BackgroundSync.finished(c, "Stopped by Android (continues next time)", false)
            throw e
        } catch (e: Exception) {
            AppLog.w("sync", "background sync failed", e)
            BackgroundSync.finished(c, e.message ?: e.javaClass.simpleName, false)
            // Periodic runs just try again next time; don't hammer the battery with retries.
            Result.success()
        } finally {
            if (bound) runCatching { c.unbindService(conn) }
        }
    }

}
