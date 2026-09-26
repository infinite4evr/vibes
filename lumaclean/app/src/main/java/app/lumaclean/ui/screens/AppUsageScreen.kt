@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package app.lumaclean.ui.screens

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.lumaclean.core.TaskState
import app.lumaclean.core.formatBytes
import app.lumaclean.core.formatDuration
import app.lumaclean.ui.components.AppIcon
import app.lumaclean.ui.components.BarChart
import app.lumaclean.ui.components.ErrorCard
import app.lumaclean.ui.components.ItemRow
import app.lumaclean.ui.components.LocalContainer
import app.lumaclean.ui.components.LocalNavigator
import app.lumaclean.ui.components.LumaCard
import app.lumaclean.ui.components.LumaList
import app.lumaclean.ui.components.Meter
import app.lumaclean.ui.components.ScreenScaffold
import app.lumaclean.ui.components.TaskProgressCard
import app.lumaclean.ui.components.UsagePermissionCard
import app.lumaclean.ui.nav.Route
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun AppUsageScreen() {
    val c = LocalContainer.current
    val nav = LocalNavigator.current
    val perms by c.perms.state.collectAsStateWithLifecycle()
    val state by c.usageTask.state.collectAsStateWithLifecycle()
    var days by rememberSaveable { mutableIntStateOf(c.usageDays) }
    var tab by rememberSaveable { mutableIntStateOf(0) }

    LaunchedEffect(perms.usage, days) {
        if (!perms.usage) return@LaunchedEffect
        if (c.usageDays != days || state.value == null) {
            c.usageDays = days
            c.usageTask.restart()
        }
    }
    val report = state.value?.takeIf { it.days == days }

    ScreenScaffold(title = "Screen time & data", onBack = { nav.back() }) { padding ->
        LumaList(padding, spacing = 4.dp) {
            if (!perms.usage) {
                item { UsagePermissionCard("screen time and data usage") }
                return@LumaList
            }
            item {
                Column {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(1 to "Today", 7 to "7 days", 30 to "30 days").forEach { (d, label) ->
                            FilterChip(selected = days == d, onClick = { days = d }, label = { Text(label) })
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    SingleChoiceSegmentedButtonRow {
                        listOf("Screen time", "Data").forEachIndexed { i, label ->
                            SegmentedButton(
                                selected = tab == i,
                                onClick = { tab = i },
                                shape = SegmentedButtonDefaults.itemShape(i, 2),
                            ) { Text(label) }
                        }
                    }
                }
            }
            when (val s = state) {
                is TaskState.Running -> item { TaskProgressCard(s, "Reading usage", onCancel = { c.usageTask.cancel() }) }
                is TaskState.Failed -> item { ErrorCard(s.message) { c.usageTask.restart() } }
                else -> {}
            }
            val r = report ?: return@LumaList
            if (tab == 0) {
                item {
                    LumaCard {
                        Text("Screen time", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(r.totalScreenMs.formatDuration(), style = MaterialTheme.typography.displaySmall)
                        if (r.days > 1) {
                            Text("${(r.totalScreenMs / r.days).formatDuration()} a day on average", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Spacer(Modifier.height(16.dp))
                            val shown = r.dailyScreenMs.takeLast(if (r.days > 7) 14 else 7)
                            val fmt = SimpleDateFormat(if (shown.size > 7) "d" else "EEE", Locale.getDefault())
                            BarChart(shown.map { it.second.toFloat() }, shown.map { fmt.format(Date(it.first)) })
                        }
                    }
                }
                val apps = r.apps.filter { it.foregroundMs >= 60_000 }.sortedByDescending { it.foregroundMs }
                val max = apps.firstOrNull()?.foregroundMs?.toFloat() ?: 1f
                items(apps, key = { "s" + it.packageName }) { u ->
                    Column {
                        ItemRow(
                            title = u.label,
                            subtitle = u.foregroundMs.formatDuration(),
                            leading = { AppIcon(u.packageName) },
                            onClick = { if (c.apps.isInstalled(u.packageName)) nav.open(Route.AppDetail(u.packageName)) },
                        )
                        Meter(u.foregroundMs / max, MaterialTheme.colorScheme.primary, Modifier.padding(start = 66.dp, end = 12.dp), height = 3.dp)
                    }
                }
            } else {
                item {
                    LumaCard {
                        Text("Data used", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text((r.totalWifi + r.totalMobile).formatBytes(), style = MaterialTheme.typography.displaySmall)
                        Text(
                            "Wi-Fi ${r.totalWifi.formatBytes()} · Mobile ${if (r.mobileAvailable) r.totalMobile.formatBytes() else "not available"}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                val apps = r.apps.filter { it.wifiBytes + it.mobileBytes > 100_000 }.sortedByDescending { it.wifiBytes + it.mobileBytes }
                val max = apps.firstOrNull()?.let { (it.wifiBytes + it.mobileBytes).toFloat() } ?: 1f
                items(apps, key = { "d" + it.packageName }) { u ->
                    Column {
                        ItemRow(
                            title = u.label,
                            subtitle = "Wi-Fi ${u.wifiBytes.formatBytes()} · Mobile ${u.mobileBytes.formatBytes()}",
                            leading = { AppIcon(u.packageName) },
                            trailing = { Text((u.wifiBytes + u.mobileBytes).formatBytes(), style = MaterialTheme.typography.labelLarge) },
                            onClick = { if (c.apps.isInstalled(u.packageName)) nav.open(Route.AppDetail(u.packageName)) },
                        )
                        Meter((u.wifiBytes + u.mobileBytes) / max, MaterialTheme.colorScheme.tertiary, Modifier.padding(start = 66.dp, end = 12.dp), height = 3.dp)
                    }
                }
            }
        }
    }
}
