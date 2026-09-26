package app.lumaclean.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class ThemeMode(val label: String) { SYSTEM("System"), LIGHT("Light"), DARK("Dark") }

enum class Accent(val label: String) { OCEAN("Ocean"), EMERALD("Emerald"), VIOLET("Violet"), SUNSET("Sunset") }

enum class StartTab(val label: String) { HOME("Home"), CLEAN("Clean"), STORAGE("Storage"), APPS("Apps"), TOOLS("Tools") }

data class AppSettings(
    val themeMode: ThemeMode = ThemeMode.SYSTEM,
    val dynamicColor: Boolean = true,
    val accent: Accent = Accent.OCEAN,
    val startTab: StartTab = StartTab.HOME,
    val oldDownloadDays: Int = 90,
    val largeFileMb: Int = 100,
    val showHidden: Boolean = false,
    val useRecycleBin: Boolean = true,
    val recycleDays: Int = 30,
    val weeklyCheckup: Boolean = true,
    val storageAlerts: Boolean = true,
    val batteryAlerts: Boolean = true,
    val onboarded: Boolean = false,
    val lastCleanAt: Long = 0,
    val lastCleanBytes: Long = 0,
)

class SettingsRepository(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val _flow = MutableStateFlow(read())
    val flow: StateFlow<AppSettings> = _flow.asStateFlow()
    val current: AppSettings get() = _flow.value

    @Synchronized
    fun update(block: (AppSettings) -> AppSettings) {
        val next = block(_flow.value)
        if (next == _flow.value) return
        write(next)
        _flow.value = next
    }

    private fun read(): AppSettings {
        val d = AppSettings()
        return AppSettings(
            themeMode = enumOr(prefs.getString("themeMode", null), d.themeMode),
            dynamicColor = prefs.getBoolean("dynamicColor", d.dynamicColor),
            accent = enumOr(prefs.getString("accent", null), d.accent),
            startTab = enumOr(prefs.getString("startTab", null), d.startTab),
            oldDownloadDays = prefs.getInt("oldDownloadDays", d.oldDownloadDays),
            largeFileMb = prefs.getInt("largeFileMb", d.largeFileMb),
            showHidden = prefs.getBoolean("showHidden", d.showHidden),
            useRecycleBin = prefs.getBoolean("useRecycleBin", d.useRecycleBin),
            recycleDays = prefs.getInt("recycleDays", d.recycleDays),
            weeklyCheckup = prefs.getBoolean("weeklyCheckup", d.weeklyCheckup),
            storageAlerts = prefs.getBoolean("storageAlerts", d.storageAlerts),
            batteryAlerts = prefs.getBoolean("batteryAlerts", d.batteryAlerts),
            onboarded = prefs.getBoolean("onboarded", d.onboarded),
            lastCleanAt = prefs.getLong("lastCleanAt", d.lastCleanAt),
            lastCleanBytes = prefs.getLong("lastCleanBytes", d.lastCleanBytes),
        )
    }

    private fun write(s: AppSettings) {
        prefs.edit()
            .putString("themeMode", s.themeMode.name)
            .putBoolean("dynamicColor", s.dynamicColor)
            .putString("accent", s.accent.name)
            .putString("startTab", s.startTab.name)
            .putInt("oldDownloadDays", s.oldDownloadDays)
            .putInt("largeFileMb", s.largeFileMb)
            .putBoolean("showHidden", s.showHidden)
            .putBoolean("useRecycleBin", s.useRecycleBin)
            .putInt("recycleDays", s.recycleDays)
            .putBoolean("weeklyCheckup", s.weeklyCheckup)
            .putBoolean("storageAlerts", s.storageAlerts)
            .putBoolean("batteryAlerts", s.batteryAlerts)
            .putBoolean("onboarded", s.onboarded)
            .putLong("lastCleanAt", s.lastCleanAt)
            .putLong("lastCleanBytes", s.lastCleanBytes)
            .apply()
    }

    private inline fun <reified E : Enum<E>> enumOr(name: String?, fallback: E): E =
        name?.let { n -> enumValues<E>().firstOrNull { it.name == n } } ?: fallback

    /** Small key/value flags for alerts etc. that aren't user settings. */
    fun stamp(key: String): Long = prefs.getLong("stamp_$key", 0)

    fun setStamp(key: String, value: Long = System.currentTimeMillis()) {
        prefs.edit().putLong("stamp_$key", value).apply()
    }
}
