package com.example.lumaclean.ui

import android.app.Application
import android.net.Uri
import android.os.Environment
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.example.lumaclean.data.*
import com.example.lumaclean.model.*
import com.example.lumaclean.worker.ScanWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.TimeUnit

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val storageRepo = StorageRepository(app)
    private val junkScanner = JunkScanner(app)
    private val duplicateScanner = DuplicateScanner()
    private val largeScanner = LargeFileScanner(app)
    private val appRepo = AppRepository(app)
    private val mover = MoveEngine(app)
    private val mediaTools = MediaToolsRepository(app)
    private val prefs = Preferences(app)

    private val _storage = MutableStateFlow(StorageSnapshot())
    val storage: StateFlow<StorageSnapshot> = _storage.asStateFlow()

    private val _junk = MutableStateFlow<List<CleanCandidate>>(emptyList())
    val junk: StateFlow<List<CleanCandidate>> = _junk.asStateFlow()

    private val _duplicates = MutableStateFlow<List<DuplicateGroup>>(emptyList())
    val duplicates: StateFlow<List<DuplicateGroup>> = _duplicates.asStateFlow()

    private val _largeFiles = MutableStateFlow<List<LargeFile>>(emptyList())
    val largeFiles: StateFlow<List<LargeFile>> = _largeFiles.asStateFlow()

    private val _apps = MutableStateFlow<List<InstalledAppInfo>>(emptyList())
    val apps: StateFlow<List<InstalledAppInfo>> = _apps.asStateFlow()

    private val _mediaStats = MutableStateFlow(MediaStats())
    val mediaStats: StateFlow<MediaStats> = _mediaStats.asStateFlow()

    private val _similarPhotos = MutableStateFlow<List<SimilarPhotoGroup>>(emptyList())
    val similarPhotos: StateFlow<List<SimilarPhotoGroup>> = _similarPhotos.asStateFlow()

    private val _optimizeResult = MutableStateFlow<OptimizeResult?>(null)
    val optimizeResult: StateFlow<OptimizeResult?> = _optimizeResult.asStateFlow()

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    private val _status = MutableStateFlow("")
    val status: StateFlow<String> = _status.asStateFlow()

    private val _migration = MutableStateFlow(MigrationProgress())
    val migration: StateFlow<MigrationProgress> = _migration.asStateFlow()

    val sdTreeUri: Uri? get() = prefs.sdTreeUri
    val scheduledScan: Boolean get() = prefs.scheduledScan
    val hasUsageAccess: Boolean get() = appRepo.hasUsageAccess()

    init { refreshStorage() }

    fun refreshStorage() = viewModelScope.launch(Dispatchers.IO) {
        _storage.value = storageRepo.snapshot()
    }

    fun scanJunk() = runBusy("Scanning junk…") {
        _junk.value = junkScanner.scan()
        _status.value = "Found ${_junk.value.size} items to review"
    }

    fun cleanSelected(items: Collection<CleanCandidate>) = runBusy("Cleaning selected items…") {
        val (count, bytes) = junkScanner.delete(items)
        prefs.lastReclaimedBytes = bytes
        _junk.value = junkScanner.scan()
        _storage.value = storageRepo.snapshot()
        _status.value = "Removed $count items"
    }

    fun scanDuplicates() = runBusy("Hashing possible duplicates…") {
        _duplicates.value = duplicateScanner.scan()
        _status.value = "Found ${_duplicates.value.size} duplicate groups"
    }

    fun deleteDuplicateExtras(groups: Collection<DuplicateGroup>) = runBusy("Deleting duplicate copies…") {
        val (count, bytes) = duplicateScanner.deleteExtras(groups)
        prefs.lastReclaimedBytes = bytes
        _duplicates.value = duplicateScanner.scan()
        _storage.value = storageRepo.snapshot()
        _status.value = "Removed $count duplicate files"
    }

    fun loadLargeFiles() = runBusy("Finding large media and files…") {
        _largeFiles.value = largeScanner.query()
        _status.value = "Found ${_largeFiles.value.size} files over 100 MB"
    }

    fun analyzeMedia() = runBusy("Analyzing gallery…") {
        _mediaStats.value = mediaTools.mediaStats()
        _status.value = "Media analysis complete"
    }

    fun findSimilarPhotos() = runBusy("Comparing recent photos…") {
        _similarPhotos.value = mediaTools.findSimilarPhotos()
        _status.value = "Found ${_similarPhotos.value.size} similar-photo groups"
    }

    fun optimizePhotos(uris: List<Uri>) = runBusy("Optimizing selected photos…") {
        _optimizeResult.value = mediaTools.optimize(uris)
        _status.value = "Created ${_optimizeResult.value?.created ?: 0} optimized photos"
    }

    fun loadApps() = runBusy("Loading app storage usage…") {
        _apps.value = appRepo.loadApps()
        _status.value = if (appRepo.hasUsageAccess()) "App usage loaded" else "Grant Usage Access for cache sizes and last-used dates"
    }

    fun rememberSdTree(uri: Uri) {
        prefs.sdTreeUri = uri
        _status.value = "SD-card destination saved"
    }

    fun migrateWhatsApp() = migrateSource(resolveWhatsAppSource(), "WhatsApp media")

    fun migrateSharedStorage() {
        val root = Environment.getExternalStorageDirectory()
        migrateSource(root, "shared storage")
    }

    private fun migrateSource(source: File?, label: String) {
        val tree = prefs.sdTreeUri
        if (tree == null) {
            _status.value = "Choose an SD-card destination first"
            return
        }
        if (source == null || !source.exists()) {
            _status.value = "$label folder was not found on this device"
            return
        }
        viewModelScope.launch {
            _busy.value = true
            _status.value = "Moving $label…"
            val result = withContext(Dispatchers.IO) {
                mover.migrate(source, tree, deleteSource = true) { progress -> _migration.value = progress }
            }
            _migration.value = _migration.value.copy(complete = true, message = "Moved ${result.copied}, skipped ${result.skipped}, failed ${result.failed}")
            _status.value = _migration.value.message
            _storage.value = withContext(Dispatchers.IO) { storageRepo.snapshot() }
            _busy.value = false
        }
    }

    fun setScheduledScan(enabled: Boolean) {
        prefs.scheduledScan = enabled
        val manager = WorkManager.getInstance(getApplication())
        if (enabled) {
            val constraints = Constraints.Builder()
                .setRequiresBatteryNotLow(true)
                .setRequiredNetworkType(NetworkType.NOT_REQUIRED)
                .build()
            val request = PeriodicWorkRequestBuilder<ScanWorker>(1, TimeUnit.DAYS)
                .setConstraints(constraints)
                .build()
            manager.enqueueUniquePeriodicWork("cleanup-scan", ExistingPeriodicWorkPolicy.UPDATE, request)
        } else {
            manager.cancelUniqueWork("cleanup-scan")
        }
    }

    private fun resolveWhatsAppSource(): File? {
        val root = Environment.getExternalStorageDirectory()
        return listOf(
            File(root, "Android/media/com.whatsapp/WhatsApp/Media"),
            File(root, "Android/media/com.whatsapp.w4b/WhatsApp Business/Media"),
            File(root, "WhatsApp/Media")
        ).firstOrNull { it.exists() }
    }

    private fun runBusy(initial: String, block: suspend () -> Unit) {
        viewModelScope.launch {
            _busy.value = true
            _status.value = initial
            runCatching { withContext(Dispatchers.IO) { block() } }
                .onFailure { _status.value = it.message ?: "Operation failed" }
            _busy.value = false
        }
    }
}
