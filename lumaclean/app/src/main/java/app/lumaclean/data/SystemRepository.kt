package app.lumaclean.data

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ApplicationInfo
import android.hardware.Sensor
import android.hardware.SensorManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.SystemClock
import android.util.DisplayMetrics
import android.view.WindowManager
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatDuration
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.Dispatchers
import java.io.File
import java.util.Locale
import java.util.TimeZone
import kotlin.math.abs
import kotlin.math.roundToInt

data class MemoryInfo(val total: Long, val available: Long, val threshold: Long, val low: Boolean) {
    val used: Long get() = (total - available).coerceAtLeast(0)
    val usedFraction: Float get() = if (total <= 0) 0f else used.toFloat() / total
}

enum class BatteryHealth(val label: String, val good: Boolean) {
    GOOD("Good", true), OVERHEAT("Overheating", false), DEAD("Dead", false), OVER_VOLTAGE("Over voltage", false),
    FAILURE("Failure", false), COLD("Too cold", false), UNKNOWN("Unknown", true),
}

data class BatteryInfo(
    val level: Int,
    val charging: Boolean,
    val full: Boolean,
    val plugged: String?,
    val health: BatteryHealth,
    val tempC: Float,
    val voltageMv: Int,
    val technology: String,
    val currentMa: Int?,
    val capacityMah: Int?,
    val cycleCount: Int?,
    val timeToFullMs: Long?,
) {
    val powerW: Float? get() = currentMa?.let { abs(it) * voltageMv / 1_000_000f }
    val statusText: String
        get() = when {
            full -> "Fully charged"
            charging -> "Charging" + (plugged?.let { " · $it" } ?: "")
            else -> "On battery"
        }
}

data class InfoSection(val title: String, val rows: List<Pair<String, String>>)

data class NetworkInfo(
    val connected: Boolean,
    val type: String,
    val validated: Boolean,
    val metered: Boolean,
    val vpn: Boolean,
    val downKbps: Int?,
    val upKbps: Int?,
    val addresses: List<String>,
    val dns: List<String>,
    val iface: String?,
    val wifiRssi: Int?,
    val wifiLevel: Int?,
    val wifiLinkMbps: Int?,
    val wifiFrequencyMhz: Int?,
)

class SystemRepository(private val context: Context) {
    private val am = context.getSystemService(ActivityManager::class.java)

    fun memory(): MemoryInfo {
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        return MemoryInfo(mi.totalMem, mi.availMem, mi.threshold, mi.lowMemory)
    }

    fun memoryFlow(periodMs: Long = 2000): Flow<MemoryInfo> = flow {
        while (true) {
            emit(memory())
            delay(periodMs)
        }
    }.distinctUntilChanged().flowOn(Dispatchers.IO)

    /**
     * Asks Android to end the cached background processes of user apps. It can't touch
     * what's on screen, playing music or otherwise in use, and apps may start again later.
     */
    suspend fun freeRam(): Pair<Int, Long> {
        val before = memory().available
        val pm = context.packageManager
        @Suppress("DEPRECATION")
        val targets = pm.getInstalledApplications(0).filter {
            it.flags and ApplicationInfo.FLAG_SYSTEM == 0 && it.packageName != context.packageName
        }
        targets.forEach { runCatching { am.killBackgroundProcesses(it.packageName) } }
        delay(1500)
        val after = memory().available
        return targets.size to (after - before).coerceAtLeast(0)
    }

    fun battery(): BatteryInfo? {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val bm = context.getSystemService(BatteryManager::class.java)
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100).coerceAtLeast(1)
        val pct = if (level >= 0) level * 100 / scale else bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING
        val full = status == BatteryManager.BATTERY_STATUS_FULL
        val plugged = when (intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0)) {
            BatteryManager.BATTERY_PLUGGED_AC -> "Wall charger"
            BatteryManager.BATTERY_PLUGGED_USB -> "USB"
            BatteryManager.BATTERY_PLUGGED_WIRELESS -> "Wireless"
            0 -> null
            else -> "Dock"
        }
        val health = when (intent.getIntExtra(BatteryManager.EXTRA_HEALTH, 0)) {
            BatteryManager.BATTERY_HEALTH_GOOD -> BatteryHealth.GOOD
            BatteryManager.BATTERY_HEALTH_OVERHEAT -> BatteryHealth.OVERHEAT
            BatteryManager.BATTERY_HEALTH_DEAD -> BatteryHealth.DEAD
            BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE -> BatteryHealth.OVER_VOLTAGE
            BatteryManager.BATTERY_HEALTH_UNSPECIFIED_FAILURE -> BatteryHealth.FAILURE
            BatteryManager.BATTERY_HEALTH_COLD -> BatteryHealth.COLD
            else -> BatteryHealth.UNKNOWN
        }
        val rawCurrent = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW)
        val currentMa = if (rawCurrent == Int.MIN_VALUE || rawCurrent == 0) null else {
            // most phones report µA, a few report mA
            val ma = if (abs(rawCurrent) > 20_000) rawCurrent / 1000 else rawCurrent
            // normalise the sign: positive while charging
            if (charging && ma < 0 || !charging && ma > 0) -ma else ma
        }
        val counter = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER)
        val capacity = if (counter > 0 && pct in 5..100) (counter / 1000.0 / (pct / 100.0)).roundToInt() else null
        val cycles = intent.getIntExtra("android.os.extra.CYCLE_COUNT", -1).takeIf { it >= 0 }
        val toFull = if (Build.VERSION.SDK_INT >= 28 && charging) bm.computeChargeTimeRemaining().takeIf { it > 0 } else null
        return BatteryInfo(
            level = pct,
            charging = charging,
            full = full,
            plugged = plugged,
            health = health,
            tempC = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10f,
            voltageMv = intent.getIntExtra(BatteryManager.EXTRA_VOLTAGE, 0),
            technology = intent.getStringExtra(BatteryManager.EXTRA_TECHNOLOGY)?.takeIf { it.isNotBlank() } ?: "Unknown",
            currentMa = currentMa,
            capacityMah = capacity,
            cycleCount = cycles,
            timeToFullMs = toFull,
        )
    }

    fun batteryFlow(periodMs: Long = 2000): Flow<BatteryInfo?> = flow {
        while (true) {
            emit(battery())
            delay(periodMs)
        }
    }.distinctUntilChanged().flowOn(Dispatchers.IO)

    fun cpuFrequencies(): List<Pair<Int, Int?>> {
        val cores = Runtime.getRuntime().availableProcessors()
        return (0 until cores).map { i ->
            val khz = readInt("/sys/devices/system/cpu/cpu$i/cpufreq/scaling_cur_freq")
            i to khz?.let { it / 1000 }
        }
    }

    fun cpuFlow(): Flow<List<Pair<Int, Int?>>> = flow {
        while (true) {
            emit(cpuFrequencies())
            delay(1000)
        }
    }.flowOn(Dispatchers.IO)

    private fun readInt(path: String): Int? = runCatching { File(path).readText().trim().toInt() }.getOrNull()

    @Suppress("DEPRECATION")
    fun deviceSections(storage: VolumeInfo): List<InfoSection> {
        val mem = memory()
        val sections = ArrayList<InfoSection>()
        sections += InfoSection(
            "Device",
            listOf(
                "Model" to "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}",
                "Codename" to Build.DEVICE,
                "Brand" to Build.BRAND.replaceFirstChar { it.uppercase() },
                "Board" to Build.BOARD,
                "Hardware" to Build.HARDWARE,
            ),
        )
        sections += InfoSection(
            "System",
            listOfNotNull(
                "Android version" to "${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
                "Security patch" to Build.VERSION.SECURITY_PATCH,
                "Build" to Build.DISPLAY,
                "Kernel" to (System.getProperty("os.version") ?: "—"),
                "Bootloader" to Build.BOOTLOADER,
                "Java VM" to "ART ${System.getProperty("java.vm.version") ?: ""}".trim(),
                "Uptime" to SystemClock.elapsedRealtime().formatDuration(),
                "Language" to Locale.getDefault().displayName,
                "Time zone" to TimeZone.getDefault().id,
            ),
        )
        val maxFreq = (0 until Runtime.getRuntime().availableProcessors())
            .mapNotNull { readInt("/sys/devices/system/cpu/cpu$it/cpufreq/cpuinfo_max_freq") }
            .maxOrNull()
        sections += InfoSection(
            "Processor",
            listOfNotNull(
                if (Build.VERSION.SDK_INT >= 31) "Chip" to "${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}".trim() else null,
                "Cores" to Runtime.getRuntime().availableProcessors().toString(),
                maxFreq?.let { "Top speed" to String.format(Locale.US, "%.2f GHz", it / 1_000_000f) },
                "Instruction sets" to Build.SUPPORTED_ABIS.joinToString(", "),
            ),
        )
        sections += InfoSection(
            "Memory & storage",
            listOf(
                "RAM" to mem.total.formatBytes(),
                "RAM available" to mem.available.formatBytes(),
                "Storage" to storage.total.formatBytes(),
                "Storage free" to storage.free.formatBytes(),
            ),
        )
        sections += displaySection()
        cameraSection()?.let { sections += it }
        val sensors = context.getSystemService(SensorManager::class.java)?.getSensorList(Sensor.TYPE_ALL).orEmpty()
        sections += InfoSection("Sensors (${sensors.size})", sensors.map { it.name to it.vendor })
        return sections
    }

    @Suppress("DEPRECATION")
    private fun displaySection(): InfoSection {
        val wm = context.getSystemService(WindowManager::class.java)
        val metrics = DisplayMetrics()
        wm.defaultDisplay.getRealMetrics(metrics)
        val refresh = wm.defaultDisplay.refreshRate
        val inchesW = metrics.widthPixels / metrics.xdpi
        val inchesH = metrics.heightPixels / metrics.ydpi
        val diag = kotlin.math.sqrt(inchesW * inchesW + inchesH * inchesH)
        val modes = if (Build.VERSION.SDK_INT >= 23) wm.defaultDisplay.supportedModes.map { it.refreshRate.roundToInt() }.distinct().sorted() else emptyList()
        return InfoSection(
            "Display",
            listOf(
                "Resolution" to "${metrics.widthPixels} × ${metrics.heightPixels}",
                "Density" to "${metrics.densityDpi} dpi",
                "Size" to String.format(Locale.US, "%.1f\"", diag),
                "Refresh rate" to "${refresh.roundToInt()} Hz" + if (modes.size > 1) " (supports ${modes.joinToString("/")} Hz)" else "",
            ),
        )
    }

    private fun cameraSection(): InfoSection? = runCatching {
        val cm = context.getSystemService(CameraManager::class.java)
        val rows = cm.cameraIdList.mapNotNull { id ->
            val ch = cm.getCameraCharacteristics(id)
            val facing = when (ch.get(CameraCharacteristics.LENS_FACING)) {
                CameraCharacteristics.LENS_FACING_FRONT -> "Front"
                CameraCharacteristics.LENS_FACING_BACK -> "Back"
                else -> "External"
            }
            val px = ch.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE) ?: return@mapNotNull null
            val mp = px.width * px.height / 1_000_000f
            "$facing camera $id" to String.format(Locale.US, "%.1f MP · %d × %d", mp, px.width, px.height)
        }
        if (rows.isEmpty()) null else InfoSection("Cameras", rows)
    }.getOrNull()

    fun network(): NetworkInfo {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val net = cm.activeNetwork
        val caps = net?.let { cm.getNetworkCapabilities(it) }
        val link = net?.let { cm.getLinkProperties(it) }
        val type = when {
            caps == null -> "Offline"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Mobile data"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_BLUETOOTH) -> "Bluetooth"
            else -> "Connected"
        }
        var rssi: Int? = null
        var linkMbps: Int? = null
        var freq: Int? = null
        if (caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true) {
            val info: WifiInfo? = if (Build.VERSION.SDK_INT >= 29) caps.transportInfo as? WifiInfo else null
            @Suppress("DEPRECATION")
            val wi = info ?: runCatching { context.applicationContext.getSystemService(WifiManager::class.java).connectionInfo }.getOrNull()
            if (wi != null) {
                rssi = wi.rssi.takeIf { it > -127 && it < 0 }
                linkMbps = wi.linkSpeed.takeIf { it > 0 }
                freq = wi.frequency.takeIf { it > 0 }
            }
        }
        @Suppress("DEPRECATION")
        val level = rssi?.let { WifiManager.calculateSignalLevel(it, 5) }
        return NetworkInfo(
            connected = caps != null,
            type = type,
            validated = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true,
            metered = caps != null && !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED),
            vpn = caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true,
            downKbps = caps?.linkDownstreamBandwidthKbps?.takeIf { it > 0 },
            upKbps = caps?.linkUpstreamBandwidthKbps?.takeIf { it > 0 },
            addresses = link?.linkAddresses?.map { it.address.hostAddress ?: "" }?.filter { it.isNotBlank() }.orEmpty(),
            dns = link?.dnsServers?.mapNotNull { it.hostAddress }.orEmpty(),
            iface = link?.interfaceName,
            wifiRssi = rssi,
            wifiLevel = level,
            wifiLinkMbps = linkMbps,
            wifiFrequencyMhz = freq,
        )
    }

    fun networkFlow(): Flow<NetworkInfo> = flow {
        while (true) {
            emit(network())
            delay(3000)
        }
    }.distinctUntilChanged().flowOn(Dispatchers.IO)
}
