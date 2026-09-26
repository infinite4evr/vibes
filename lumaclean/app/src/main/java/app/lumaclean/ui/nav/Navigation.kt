package app.lumaclean.ui.nav

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Apps
import androidx.compose.material.icons.outlined.CleaningServices
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.Handyman
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.rounded.Apps
import androidx.compose.material.icons.rounded.CleaningServices
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.Handyman
import androidx.compose.material.icons.rounded.Home
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.graphics.vector.ImageVector
import app.lumaclean.data.FileQuery

enum class Tab(val label: String, val icon: ImageVector, val selectedIcon: ImageVector) {
    HOME("Home", Icons.Outlined.Home, Icons.Rounded.Home),
    CLEAN("Clean", Icons.Outlined.CleaningServices, Icons.Rounded.CleaningServices),
    STORAGE("Storage", Icons.Outlined.Folder, Icons.Rounded.Folder),
    APPS("Apps", Icons.Outlined.Apps, Icons.Rounded.Apps),
    TOOLS("Tools", Icons.Outlined.Handyman, Icons.Rounded.Handyman),
}

/** Screens pushed on top of a tab. The tab roots themselves aren't routes. */
sealed interface Route {
    data class Browser(val path: String) : Route
    data class Files(val query: FileQuery) : Route
    data class AppDetail(val packageName: String) : Route
    data object Duplicates : Route
    data object AppUsage : Route
    data object UnusedApps : Route
    data object Ram : Route
    data object Battery : Route
    data object Device : Route
    data object Network : Route
    data object Similar : Route
    data object Compress : Route
    data object ChatMedia : Route
    data object RecycleBin : Route
    data object Settings : Route
    data object History : Route
    data object Exclusions : Route
    data object Permissions : Route
    data object Search : Route
}

class Navigator(start: Tab) {
    var tab by mutableStateOf(start)
        private set
    private val stacks: Map<Tab, SnapshotStateList<Route>> = Tab.entries.associateWith { mutableStateListOf() }

    fun stack(t: Tab = tab): List<Route> = stacks.getValue(t)

    val current: Route? get() = stacks.getValue(tab).lastOrNull()

    val canGoBack: Boolean get() = stacks.getValue(tab).isNotEmpty() || tab != Tab.HOME

    fun open(route: Route) {
        val s = stacks.getValue(tab)
        if (s.lastOrNull() != route) s.add(route)
    }

    /** Opens [route] on [inTab], on top of that tab's root (used by shortcuts and notifications). */
    fun jump(inTab: Tab, route: Route? = null) {
        tab = inTab
        val s = stacks.getValue(inTab)
        s.clear()
        route?.let { s.add(it) }
    }

    fun select(t: Tab) {
        if (t == tab) stacks.getValue(t).clear() else tab = t
    }

    fun back(): Boolean {
        val s = stacks.getValue(tab)
        return when {
            s.isNotEmpty() -> {
                s.removeAt(s.lastIndex)
                true
            }
            tab != Tab.HOME -> {
                tab = Tab.HOME
                true
            }
            else -> false
        }
    }
}
