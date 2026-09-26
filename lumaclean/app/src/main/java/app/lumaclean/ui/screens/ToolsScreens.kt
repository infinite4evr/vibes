package app.lumaclean.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridItemSpanScope
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Android
import androidx.compose.material.icons.rounded.BatteryChargingFull
import androidx.compose.material.icons.rounded.BatteryFull
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.CleaningServices
import androidx.compose.material.icons.rounded.Compress
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.DataUsage
import androidx.compose.material.icons.rounded.DeleteSweep
import androidx.compose.material.icons.rounded.DeveloperBoard
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.HourglassEmpty
import androidx.compose.material.icons.rounded.Loop
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.Movie
import androidx.compose.material.icons.rounded.PhoneAndroid
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material.icons.rounded.Screenshot
import androidx.compose.material.icons.rounded.SignalCellularAlt
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material.icons.rounded.Straighten
import androidx.compose.material.icons.rounded.Thermostat
import androidx.compose.material.icons.rounded.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.DAY_MS
import app.lumaclean.core.UiMessage
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatDuration
import app.lumaclean.core.percent
import app.lumaclean.core.startSafely
import app.lumaclean.data.FileCategory
import app.lumaclean.data.FileQuery
import app.lumaclean.data.InfoSection
import app.lumaclean.ui.components.IconBadge
import app.lumaclean.ui.components.KeyValue
import app.lumaclean.ui.components.LineChart
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaGrid
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.RingGauge
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.SectionHeader
import app.lumaclean.ui.components.StatTile
import app.lumaclean.ui.nav.Route
import app.lumaclean.ui.nav.Tab
import app.lumaclean.ui.theme.LocalExtraColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.Locale

private val fullSpan: LazyGridItemSpanScope.() -> GridItemSpan = { GridItemSpan(maxLineSpan) }

private data class Tool(val title: String, val subtitle: String, val icon: ImageVector, val open: () -> Unit)

@Composable
fun ToolsScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val settings by c.settings.flow.collectAsStateWithLifecycle()
    val sections = listOf(
        "Cleaning" to listOf(
            Tool("Smart Clean", "Junk, caches, leftovers", Icons.Rounded.CleaningServices) { nav.select(Tab.CLEAN) },
            Tool("Duplicates", "Exact copies of files", Icons.Rounded.ContentCopy) { nav.open(Route.Duplicates) },
            Tool("Large files", "Over ${settings.largeFileMb} MB", Icons.Rounded.Straighten) {
                nav.open(Route.Files(FileQuery.Large(settings.largeFileMb * 1_000_000L)))
            },
            Tool("Old downloads", "Not touched in months", Icons.Rounded.Download) {
                nav.open(Route.Files(FileQuery.OldDownloads(settings.oldDownloadDays)))
            },
            Tool("Installer files", "APKs you may not need", Icons.Rounded.Android) {
                nav.open(Route.Files(FileQuery.Category(FileCategory.APKS)))
            },
            Tool("Recycle bin", "Restore deleted files", Icons.Rounded.DeleteSweep) { nav.open(Route.RecycleBin) },
        ),
        "Photos & media" to listOf(
            Tool("Similar photos", "Bursts and near-copies", Icons.Rounded.PhotoLibrary) { nav.open(Route.Similar) },
            Tool("Screenshots", "Review and clear", Icons.Rounded.Screenshot) { nav.open(Route.Files(FileQuery.Screenshots)) },
            Tool("Compress photos", "Same photos, less space", Icons.Rounded.Compress) { nav.open(Route.Compress) },
            Tool("Large videos", "Videos over 20 MB", Icons.Rounded.Movie) { nav.open(Route.Files(FileQuery.LargeVideos)) },
            Tool("Chat media", "WhatsApp, Telegram, Signal", Icons.Rounded.Forum) { nav.open(Route.ChatMedia) },
        ),
        "Phone" to listOf(
            Tool("Free up RAM", "Stop background apps", Icons.Rounded.Memory) { nav.open(Route.Ram) },
            Tool("Battery", "Health, charging, history", Icons.Rounded.BatteryFull) { nav.open(Route.Battery) },
            Tool("Screen time & data", "Per-app usage", Icons.Rounded.DataUsage) { nav.open(Route.AppUsage) },
            Tool("Unused apps", "Apps you never open", Icons.Rounded.HourglassEmpty) { nav.open(Route.UnusedApps) },
            Tool("Device info", "Hardware and system", Icons.Rounded.PhoneAndroid) { nav.open(Route.Device) },
            Tool("Network", "Connection details", Icons.Rounded.Wifi) { nav.open(Route.Network) },
        ),
    )
    ScreenScaffold(title = "Tools") { padding ->
        LumaGrid(padding, minCell = 168.dp) {
            sections.forEach { (title, tools) ->
                item(span = fullSpan) { SectionHeader(title) }
                tools.forEach { t ->
                    item {
                        LumaCard(onClick = t.open, contentPadding = PaddingValues(16.dp), modifier = Modifier.height(132.dp)) {
                            IconBadge(t.icon, MaterialTheme.colorScheme.primary)
                            Spacer(Modifier.weight(1f))
                            Text(t.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(t.subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun RamScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val memory by remember { c.system.memoryFlow(1000) }.collectAsStateWithLifecycle(null)
    var result by remember { mutableStateOf<Pair<Int, Long>?>(null) }
    val extra = LocalExtraColors.current

    ScreenScaffold(title = "Memory", onBack = { nav.back() }) { padding ->
        LumaList(padding) {
            item {
                LumaCard {
                    val m = memory
                    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                        val f = m?.usedFraction ?: 0f
                        RingGauge(f, Modifier.size(200.dp), color = if (f > 0.85f) extra.warning else MaterialTheme.colorScheme.primary, stroke = 16.dp) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text(f.percent(), fontSize = 44.sp, style = MaterialTheme.typography.displaySmall)
                                Text("in use", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        Spacer(Modifier.height(16.dp))
                        if (m != null) {
                            Text("${m.available.formatBytes()} free of ${m.total.formatBytes()}", style = MaterialTheme.typography.titleMedium)
                            if (m.low) Text("Android reports memory is running low", color = extra.warning, style = MaterialTheme.typography.bodySmall)
                        }
                        Spacer(Modifier.height(16.dp))
                        Button(onClick = {
                            c.operations.run("Freeing up memory") {
                                report(null, "Asking background apps to stop…", force = true)
                                val r = c.system.freeRam()
                                result = r
                                UiMessage(if (r.second > 0) "${r.second.formatBytes()} of memory freed" else "Memory was already in good shape")
                            }
                        }, modifier = Modifier.fillMaxWidth()) { Text("Free up RAM") }
                    }
                }
            }
            result?.let { (apps, freed) ->
                item {
                    LumaCard(color = MaterialTheme.colorScheme.primaryContainer) {
                        Text("Done", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
                        Text(
                            "Asked $apps apps to stop working in the background. ${if (freed > 0) "${freed.formatBytes()} became available." else "Nothing needed stopping."}",
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                    }
                }
            }
            item {
                LumaCard {
                    Text("How this works", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Android already manages memory well and closes apps when it needs room. Stopping background apps helps " +
                            "most right before a game or heavy app. It never touches the app on screen, music that's playing or your " +
                            "keyboard, and apps may start again on their own. No app can do more than this without root.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
fun BatteryScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val battery by remember { c.system.batteryFlow(1000) }.collectAsStateWithLifecycle(null)
    val log by c.batteryLog.points.collectAsStateWithLifecycle()
    var range by rememberSaveable { mutableIntStateOf(1) }
    val extra = LocalExtraColors.current

    ScreenScaffold(title = "Battery", onBack = { nav.back() }) { padding ->
        LumaGrid(padding, minCell = 160.dp) {
            val b = battery
            item(span = fullSpan) {
                LumaCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RingGauge((b?.level ?: 0) / 100f, Modifier.size(128.dp), color = if ((b?.level ?: 100) <= 15) extra.danger else extra.success, stroke = 12.dp) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                if (b?.charging == true) Icon(Icons.Rounded.Bolt, null, tint = extra.success)
                                Text(b?.let { "${it.level}%" } ?: "—", fontSize = 32.sp, style = MaterialTheme.typography.headlineMedium)
                            }
                        }
                        Spacer(Modifier.width(20.dp))
                        Column(Modifier.weight(1f)) {
                            Text(b?.statusText ?: "Reading…", style = MaterialTheme.typography.titleLarge)
                            b?.timeToFullMs?.let { Text("Full in ${it.formatDuration()}", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                            b?.powerW?.let { w ->
                                Text(
                                    String.format(Locale.US, "%s %.1f W", if (b.charging) "Charging at" else "Using", w),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
            if (b != null) {
                item { StatTile(Icons.Rounded.Favorite, "Health", b.health.label, tint = if (b.health.good) extra.success else extra.danger) }
                item {
                    StatTile(
                        Icons.Rounded.Thermostat, "Temperature", String.format(Locale.US, "%.1f°C", b.tempC),
                        detail = when {
                            b.tempC >= 45 -> "Too hot"
                            b.tempC >= 38 -> "Warm"
                            else -> "Normal"
                        },
                        tint = if (b.tempC >= 45) extra.danger else if (b.tempC >= 38) extra.warning else extra.success,
                    )
                }
                item { StatTile(Icons.Rounded.Bolt, "Voltage", String.format(Locale.US, "%.2f V", b.voltageMv / 1000f)) }
                item { StatTile(Icons.Rounded.Speed, "Current", b.currentMa?.let { "$it mA" } ?: "Not reported", detail = "Positive while charging") }
                item { StatTile(Icons.Rounded.BatteryChargingFull, "Capacity (estimate)", b.capacityMah?.let { "$it mAh" } ?: "Not reported") }
                item { StatTile(Icons.Rounded.Loop, "Charge cycles", b.cycleCount?.toString() ?: "Not reported") }
                item { StatTile(Icons.Rounded.DeveloperBoard, "Technology", b.technology) }
            }
            item(span = fullSpan) {
                LumaCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Battery level", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            FilterChip(selected = range == 1, onClick = { range = 1 }, label = { Text("24 h") })
                            FilterChip(selected = range == 7, onClick = { range = 7 }, label = { Text("7 days") })
                        }
                    }
                    val from = System.currentTimeMillis() - range * DAY_MS
                    val pts = log.filter { it.time >= from }
                    Spacer(Modifier.height(12.dp))
                    if (pts.size < 2) {
                        Text(
                            "LumaClean records the battery every 15 minutes in the background. The chart fills in over the next few hours.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        LineChart(pts.map { it.time to it.level.toFloat() }, 0f, 100f, color = extra.success, fromTime = from)
                        Spacer(Modifier.height(16.dp))
                        Text("Temperature", style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.height(8.dp))
                        val maxT = (pts.maxOf { it.tempC } + 5).coerceAtLeast(45f)
                        LineChart(pts.map { it.time to it.tempC }, 15f, maxT, color = extra.warning, fromTime = from)
                    }
                }
            }
            item(span = fullSpan) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.horizontalScroll(rememberScrollState())) {
                    OutlinedButton(onClick = { context.startSafely(Intent(Intent.ACTION_POWER_USAGE_SUMMARY)) }) { Text("Battery use by app") }
                    OutlinedButton(onClick = { context.startSafely(Intent(Settings.ACTION_BATTERY_SAVER_SETTINGS)) }) { Text("Battery saver") }
                }
            }
            item(span = fullSpan) {
                LumaCard {
                    Text("Make your battery last longer", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    listOf(
                        "Heat is the biggest enemy. Avoid charging under a pillow or in a hot car.",
                        "Keeping the charge between 20% and 80% slows wear. Many phones offer an \"adaptive\" or \"protect battery\" option.",
                        "Overnight charging is fine when adaptive charging is on.",
                        "Fast charging is safe, but it warms the phone more.",
                    ).forEach { tip ->
                        Text("• $tip", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(vertical = 3.dp))
                    }
                }
            }
        }
    }
}

@Composable
fun DeviceScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val cpu by remember { c.system.cpuFlow() }.collectAsStateWithLifecycle(emptyList())
    val sections by produceState<List<InfoSection>?>(null) {
        value = withContext(Dispatchers.IO) { c.system.deviceSections(c.storage.primary()) }
    }

    ScreenScaffold(
        title = "Device info",
        onBack = { nav.back() },
        actions = {
            IconButton(onClick = {
                val text = sections.orEmpty().joinToString("\n\n") { s -> s.title + "\n" + s.rows.joinToString("\n") { "${it.first}: ${it.second}" } }
                context.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("Device info", text))
                c.message("Device report copied")
            }) { Icon(Icons.Rounded.ContentCopy, "Copy report") }
        },
    ) { padding ->
        LumaGrid(padding, minCell = 360.dp) {
            item(span = fullSpan) {
                LumaCard(color = MaterialTheme.colorScheme.primaryContainer) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconBadge(Icons.Rounded.PhoneAndroid, MaterialTheme.colorScheme.primary, size = 56.dp)
                        Spacer(Modifier.width(16.dp))
                        Column {
                            Text(
                                "${android.os.Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${android.os.Build.MODEL}",
                                style = MaterialTheme.typography.titleLarge,
                                color = MaterialTheme.colorScheme.onPrimaryContainer,
                            )
                            Text(
                                "${androidVersionName(android.os.Build.VERSION.SDK_INT)} · patch ${android.os.Build.VERSION.SECURITY_PATCH}",
                                color = MaterialTheme.colorScheme.onPrimaryContainer,
                            )
                        }
                    }
                }
            }
            if (cpu.isNotEmpty()) {
                item(span = fullSpan) {
                    LumaCard {
                        Text("Processor, live", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(8.dp))
                        cpu.chunked(4).forEach { row ->
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                row.forEach { (core, mhz) ->
                                    Column(Modifier.weight(1f).padding(vertical = 4.dp)) {
                                        Text("Core $core", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        Text(mhz?.let { "$it MHz" } ?: "Sleeping", style = MaterialTheme.typography.titleSmall)
                                    }
                                }
                                repeat(4 - row.size) { Spacer(Modifier.weight(1f)) }
                            }
                        }
                    }
                }
            }
            val list = sections
            if (list == null) {
                item(span = fullSpan) { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            } else {
                list.forEach { s ->
                    item {
                        LumaCard {
                            Text(s.title, style = MaterialTheme.typography.titleMedium)
                            Spacer(Modifier.height(6.dp))
                            s.rows.forEach { (k, v) -> KeyValue(k, v) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun NetworkScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val net by remember { c.system.networkFlow() }.collectAsStateWithLifecycle(null)
    val totals by produceState<List<Pair<String, Long?>>?>(null, perms.usage) {
        if (perms.usage) value = withContext(Dispatchers.IO) {
            val now = System.currentTimeMillis()
            val today = java.util.Calendar.getInstance().apply {
                set(java.util.Calendar.HOUR_OF_DAY, 0); set(java.util.Calendar.MINUTE, 0); set(java.util.Calendar.SECOND, 0)
            }.timeInMillis
            listOf(
                "Wi-Fi today" to c.apps.deviceTotal(android.net.ConnectivityManager.TYPE_WIFI, today, now),
                "Mobile today" to c.apps.deviceTotal(android.net.ConnectivityManager.TYPE_MOBILE, today, now),
                "Wi-Fi, 30 days" to c.apps.deviceTotal(android.net.ConnectivityManager.TYPE_WIFI, now - 30 * DAY_MS, now),
                "Mobile, 30 days" to c.apps.deviceTotal(android.net.ConnectivityManager.TYPE_MOBILE, now - 30 * DAY_MS, now),
            )
        }
    }

    ScreenScaffold(title = "Network", onBack = { nav.back() }) { padding ->
        LumaList(padding) {
            val n = net
            item {
                LumaCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconBadge(
                            if (n?.type == "Mobile data") Icons.Rounded.SignalCellularAlt else Icons.Rounded.Wifi,
                            if (n?.connected == true) LocalExtraColors.current.success else MaterialTheme.colorScheme.outline,
                            size = 56.dp,
                        )
                        Spacer(Modifier.width(16.dp))
                        Column {
                            Text(n?.type ?: "Checking…", style = MaterialTheme.typography.titleLarge)
                            if (n != null && n.connected) {
                                Text(
                                    listOfNotNull(
                                        if (n.validated) "Internet works" else "No internet",
                                        if (n.metered) "metered" else "unmetered",
                                        if (n.vpn) "VPN on" else null,
                                    ).joinToString(" · "),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
            if (n != null && n.connected) {
                item {
                    LumaCard {
                        Text("Connection", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(6.dp))
                        n.wifiLevel?.let { KeyValue("Signal", listOf("Very weak", "Weak", "Fair", "Good", "Excellent")[it.coerceIn(0, 4)] + " (${n.wifiRssi} dBm)") }
                        n.wifiLinkMbps?.let { KeyValue("Link speed", "$it Mbps") }
                        n.wifiFrequencyMhz?.let { KeyValue("Band", if (it > 5900) "6 GHz" else if (it > 4900) "5 GHz" else "2.4 GHz") }
                        n.downKbps?.let { KeyValue("Estimated download", "${it / 1000} Mbps") }
                        n.upKbps?.let { KeyValue("Estimated upload", "${it / 1000} Mbps") }
                        n.iface?.let { KeyValue("Interface", it) }
                        if (n.addresses.isNotEmpty()) KeyValue("IP addresses", n.addresses.joinToString("\n"))
                        if (n.dns.isNotEmpty()) KeyValue("DNS servers", n.dns.joinToString("\n"))
                    }
                }
            }
            item {
                LumaCard {
                    Text("Data used", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    if (!perms.usage) {
                        Text("Allow usage access to see how much data you've used.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        totals?.forEach { (k, v) -> KeyValue(k, v?.formatBytes() ?: "Not available") } ?: LinearProgressIndicator(Modifier.fillMaxWidth())
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(onClick = { nav.open(Route.AppUsage) }) { Text("Data by app") }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { context.startSafely(Intent(Settings.ACTION_WIFI_SETTINGS)) }) { Text("Wi-Fi settings") }
                    OutlinedButton(onClick = { context.startSafely(Intent(Settings.ACTION_WIRELESS_SETTINGS)) }) { Text("Network settings") }
                }
            }
        }
    }
}

