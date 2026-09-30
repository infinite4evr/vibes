package app.tgdrive.ui.settings

import android.content.Intent
import android.net.Uri
import android.provider.Settings as AndroidSettings
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.tgdrive.BuildConfig
import app.tgdrive.data.AppState
import app.tgdrive.data.explain
import app.tgdrive.data.JsonCodec
import app.tgdrive.data.arr
import app.tgdrive.data.bool
import app.tgdrive.data.long
import app.tgdrive.data.obj
import app.tgdrive.data.str
import app.tgdrive.graph
import app.tgdrive.ui.actions.Platform
import app.tgdrive.ui.components.Avatar
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.ConfirmDialog
import app.tgdrive.ui.components.Divider
import app.tgdrive.ui.components.IconBtn
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgChip
import app.tgdrive.ui.components.TgDialog
import app.tgdrive.ui.components.TgSwitch
import app.tgdrive.ui.components.TgTextField
import app.tgdrive.ui.pages.PageBar
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.TgShape
import app.tgdrive.ui.theme.parseHex
import app.tgdrive.engine.BackgroundSync
import app.tgdrive.engine.BatteryLimits
import app.tgdrive.util.Format
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

private data class Section(val id: String, val label: String, val icon: TgIcon, val help: String)

private val SECTIONS = listOf(
    Section("general", "General", TgIcons.settings, "View, duplicates, notifications, background work"),
    Section("appearance", "Appearance", TgIcons.palette, "Theme, accent colour, text size"),
    Section("search", "Search", TgIcons.search, "Smart matching, meaning, synonyms"),
    Section("subjects", "Subjects", TgIcons.book, "Automatic subjects and your own"),
    Section("photos", "Photos", TgIcons.image, "Slideshow"),
    Section("downloads", "Downloads & uploads", TgIcons.download, "Parallel transfers, upload as media"),
    Section("streaming", "Streaming", TgIcons.play, "Cache, prefetch, autoplay"),
    Section("indexing", "Indexing", TgIcons.database, "What gets indexed and how often"),
    Section("network", "Network & proxy", TgIcons.external, "SOCKS, HTTP or MTProto proxy"),
    Section("telegram", "Telegram API", TgIcons.telegram, "API ID and hash"),
    Section("accounts", "Accounts", TgIcons.user, "Switch, add, sign out"),
    Section("security", "Security", TgIcons.lock, "App passcode"),
    Section("phone", "This phone", TgIcons.disk, "Background sync, battery, storage"),
    Section("data", "Data & maintenance", TgIcons.database, "Index tools, folder backups, settings backup"),
    Section("about", "About & diagnostics", TgIcons.info, "Version, logs, crash reports"),
)

private val ACCENTS = listOf("", "#2a7fc9", "#4f63d8", "#7a4fd0", "#c2418f", "#d2463b", "#e07a1f", "#b88a00", "#2f8f4e", "#128b86", "#4b5563")

/** Settings (desktop pages.js settings): the same settings, shared with the desktop app, in phone-sized sections. */
@Composable
fun SettingsScreen(state: AppState, section: String?, onMenu: () -> Unit, onAccounts: () -> Unit) {
    val c = Tg.colors
    var current by rememberSaveable { mutableStateOf(section) }
    var find by rememberSaveable { mutableStateOf("") }
    BackHandler(enabled = current != null) { current = null }
    LaunchedEffect(Unit) { state.refreshStatus() }

    AnimatedContent(current, transitionSpec = {
        (if (targetState != null) slideInHorizontally { it / 5 } + fadeIn(tween(180)) else fadeIn(tween(160))) togetherWith fadeOut(tween(100))
    }, label = "settings") { sec ->
        Column(Modifier.fillMaxSize().background(c.canvas)) {
            val s = SECTIONS.firstOrNull { it.id == sec }
            if (s == null) {
                PageBar("Settings", onMenu)
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 96.dp)) {
                    TgTextField(find, { find = it }, Modifier.padding(horizontal = 12.dp, vertical = 12.dp), placeholder = "Search settings",
                        leading = TgIcons.search)
                    val words = find.lowercase().split(' ').filter { it.isNotBlank() }
                    val shown = if (words.isEmpty()) SECTIONS
                    else SECTIONS.filter { x -> val t = "${x.label} ${x.help} ${KEYWORDS[x.id].orEmpty()}".lowercase(); words.all { it in t } }
                    Column(Modifier.padding(horizontal = 12.dp).clip(TgShape.card).background(c.panel).border(1.dp, c.line, TgShape.card)) {
                        shown.forEachIndexed { i, x ->
                            Row(Modifier.fillMaxWidth().clickable { if (x.id == "accounts") onAccounts() else current = x.id }
                                .padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                                Box(Modifier.size(36.dp).clip(RoundedCornerShape(10.dp)).background(c.accentSoft), contentAlignment = Alignment.Center) {
                                    TgIconView(x.icon, tint = c.accent, size = 19.dp)
                                }
                                Spacer(Modifier.width(14.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(x.label, style = Tg.type.bodyStrong, color = c.ink)
                                    Text(x.help, style = Tg.type.meta, color = c.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                TgIconView(TgIcons.chevron, tint = c.ink3, size = 16.dp)
                            }
                            if (i < shown.lastIndex) Divider(Modifier.padding(start = 64.dp))
                        }
                        if (shown.isEmpty()) Text("No setting matches that. Try another word, like “proxy”, “cache” or “theme”.",
                            style = Tg.type.body, color = c.ink3, modifier = Modifier.padding(16.dp))
                    }
                    Text("Settings are shared with TG Drive on your computer when you use the same data.", style = Tg.type.meta, color = c.ink3,
                        modifier = Modifier.padding(20.dp))
                }
            } else {
                PageBar(s.label, onMenu, onBack = { current = null })
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 96.dp).navigationBarsPadding()) {
                    when (s.id) {
                        "general" -> General(state)
                        "appearance" -> Appearance(state)
                        "search" -> SearchSection(state)
                        "subjects" -> Subjects(state)
                        "photos" -> Group { NumberRow(state, "slideshow_seconds", "Slideshow speed", "Seconds per picture.", 1, 60, "s") }
                        "downloads" -> Downloads(state)
                        "streaming" -> Streaming(state)
                        "indexing" -> Indexing(state)
                        "network" -> Network(state)
                        "telegram" -> TelegramApi(state)
                        "security" -> Security(state)
                        "phone" -> ThisPhone(state)
                        "data" -> DataSection(state)
                        "about" -> About(state)
                    }
                }
            }
        }
    }
}

private val KEYWORDS = mapOf(
    "general" to "grid list group date duplicates copies albums stacks delete confirm notifications background gentle",
    "appearance" to "dark light theme accent colour color contrast font text size animations motion density cards folders pdf",
    "search" to "smart exact typo meaning semantic live synonyms history",
    "subjects" to "polity economy history tags",
    "downloads" to "download upload parallel parts media structure",
    "streaming" to "cache prefetch autoplay next video audio player",
    "indexing" to "index pause kinds skip chats verify deleted previews",
    "network" to "proxy socks http mtproto",
    "telegram" to "api id hash my.telegram.org channel",
    "security" to "passcode lock idle",
    "phone" to "battery background sync keep running notification storage restart service wifi charging",
    "data" to "optimize vacuum integrity rebuild backup restore export import manifest",
    "about" to "version log debug crash diagnostics cpu",
)

// ---------------------------------------------------------------------- building blocks
@Composable
private fun Group(title: String? = null, intro: String? = null, content: @Composable ColumnScope.() -> Unit) {
    val c = Tg.colors
    if (title != null) Text(title.uppercase(), style = Tg.type.overline, color = c.ink3, modifier = Modifier.padding(start = 20.dp, top = 18.dp, bottom = 6.dp))
    if (intro != null) Text(intro, style = Tg.type.meta, color = c.ink2, modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = if (title == null) 14.dp else 0.dp, bottom = 8.dp))
    Column(Modifier.padding(horizontal = 12.dp, vertical = 4.dp).fillMaxWidth().clip(TgShape.card).background(c.panel).border(1.dp, c.line, TgShape.card)
        .padding(vertical = 4.dp), content = content)
}

@Composable
private fun Row2(title: String, help: String?, control: (@Composable () -> Unit)? = null, onClick: (() -> Unit)? = null, below: (@Composable () -> Unit)? = null) {
    val c = Tg.colors
    Column(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(horizontal = 16.dp, vertical = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = Tg.type.bodyStrong, color = c.ink)
                if (!help.isNullOrBlank()) Text(help, style = Tg.type.meta, color = c.ink3)
            }
            if (control != null) { Spacer(Modifier.width(12.dp)); control() }
        }
        if (below != null) { Spacer(Modifier.height(10.dp)); below() }
    }
}

@Composable
private fun SwitchSetting(state: AppState, key: String, title: String, help: String? = null, default: Boolean = false) {
    val settings by state.settings.collectAsState()
    val on = settings.bool(key, default)
    Row2(title, help, control = { TgSwitch(on, { state.setSetting(key, it) }) }, onClick = { state.setSetting(key, !on) })
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChoiceSetting(state: AppState, key: String, title: String, help: String?, options: List<Pair<String, String>>) {
    val settings by state.settings.collectAsState()
    val cur = settings.str(key) ?: options.first().first
    Row2(title, help, below = {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            options.forEach { (v, l) -> TgChip(l, selected = cur == v, onClick = { state.setSetting(key, v) }) }
        }
    })
}

/** A number, saved a moment after you stop typing (and checked against its range). */
@Composable
private fun NumberRow(state: AppState, key: String, title: String, help: String?, min: Int, max: Int, unit: String = "", decimal: Boolean = false) {
    val settings by state.settings.collectAsState()
    val saved = settings.str(key).orEmpty()
    var text by remember(saved) { mutableStateOf(saved.removeSuffix(".0").takeIf { !decimal } ?: saved) }
    val value = text.toDoubleOrNull()
    val bad = value == null || value < min || value > max
    LaunchedEffect(text) {
        if (text == saved || bad) return@LaunchedEffect
        delay(700)
        state.setSetting(key, if (decimal) value!! else value!!.toInt())
    }
    Row2(title, help, control = {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TgTextField(text, { text = it.filter { ch -> ch.isDigit() || (decimal && ch == '.') } }, Modifier.width(92.dp),
                keyboardType = if (decimal) KeyboardType.Decimal else KeyboardType.Number, height = 40.dp,
                error = if (bad && text.isNotEmpty()) "" else null)
            if (unit.isNotEmpty()) Text(unit, style = Tg.type.meta, color = Tg.colors.ink3, modifier = Modifier.padding(start = 6.dp))
        }
    })
}

/** Text saved a moment after you stop typing. */
@Composable
private fun TextSetting(state: AppState, key: String, title: String?, help: String?, placeholder: String = "", lines: Int = 1, password: Boolean = false) {
    val settings by state.settings.collectAsState()
    val saved = settings.str(key).orEmpty()
    var text by remember { mutableStateOf(if (password) "" else saved) }
    LaunchedEffect(text) {
        if (text == saved || (password && text.isEmpty())) return@LaunchedEffect
        delay(900)
        state.setSetting(key, text)
    }
    Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
        if (title != null) Text(title, style = Tg.type.bodyStrong, color = Tg.colors.ink)
        if (help != null) Text(help, style = Tg.type.meta, color = Tg.colors.ink3)
        Spacer(Modifier.height(8.dp))
        TgTextField(text, { text = it }, placeholder = placeholder, singleLine = lines == 1, minLines = lines, password = password,
            textStyle = if (lines > 1) Tg.type.mono else Tg.type.body)
    }
}

@Composable
private fun Maint(state: AppState, task: String, label: String, confirm: String? = null) {
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var asking by remember { mutableStateOf(false) }
    fun run() {
        busy = true
        scope.launch {
            try {
                val r = state.api.maintenance(state.aid.value, task) as? JsonObject ?: JsonObject(emptyMap())
                val details = (r["details"] as? JsonArray)?.map { (it as? JsonPrimitive)?.contentOrNull.orEmpty() }
                val ok = r.bool("ok", true)
                state.message(when {
                    details != null -> if (ok) "Everything checks out" else "Problems found: ${details.joinToString("; ")}"
                    r.containsKey("removed") -> "Removed ${Format.num(r.long("removed"))} files"
                    else -> "$label: done" + (r.str("seconds")?.let { " in ${it}s" } ?: "")
                }, error = !ok)
            } catch (e: Exception) {
                state.failed("That didn't work.", e)
            } finally { busy = false }
        }
    }
    TgButton(label, { if (confirm != null) asking = true else run() }, small = true, busy = busy)
    if (asking) ConfirmDialog("$label?", confirm!!, label, onConfirm = { run() }, onDismiss = { asking = false })
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Buttons(content: @Composable () -> Unit) {
    FlowRow(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) { content() }
}

// ---------------------------------------------------------------------- sections
@Composable
private fun General(state: AppState) {
    val account by state.account.collectAsState()
    Group {
        ChoiceSetting(state, "view", "Default view", null, listOf("grid" to "Grid", "list" to "List"))
        Divider()
        SwitchSetting(state, "group_by_date", "Group by date", "Section headers such as Today, Yesterday and months when sorted by date.")
        Divider()
        val extra = account?.dupes?.long("extra") ?: 0
        SwitchSetting(state, "hide_duplicates", "Hide duplicates",
            "One card per file: copies forwarded into other chats, and files uploaded again with the same name and size, fold into the best copy. " +
                "A chat still shows its own files. Type copies:show in a search to see them all once." +
                if (extra > 0) " Right now ${Format.num(extra)} extra copies are folded away." else "", default = true)
        Divider()
        SwitchSetting(state, "stack_albums", "Albums as stacks", "Files sent together (an album) show as one stacked card in the grid.", default = true)
        Divider()
        SwitchSetting(state, "confirm_delete", "Ask before deleting from Telegram", default = true)
        Divider()
        SwitchSetting(state, "notifications", "Notifications", "When downloads and uploads finish or fail.", default = true)
    }
    Group {
        ChoiceSetting(state, "background_work", "Background work",
            "The meaning index, subject tagging and the duplicate finder work on their own after files arrive. Gentle runs them slowly so the " +
                "phone stays cool; Full speed finishes a first big index sooner; Paused stops them (search keeps working).",
            listOf("gentle" to "Gentle (recommended)", "full" to "Full speed", "paused" to "Paused"))
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Appearance(state: AppState) {
    val c = Tg.colors
    val settings by state.settings.collectAsState()
    Group {
        ChoiceSetting(state, "theme", "Theme", null, listOf("system" to "Match the system", "light" to "Light", "dark" to "Dark"))
        Divider()
        Row2("Accent colour", "Buttons, selection and highlights.", below = {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                val cur = settings.str("accent").orEmpty()
                ACCENTS.forEach { hex ->
                    val col = parseHex(hex) ?: Color(0xFF2A7FC9)
                    Box(Modifier.size(34.dp).clip(CircleShape).background(col).clickable { state.setSetting("accent", hex) },
                        contentAlignment = Alignment.Center) {
                        if (cur.equals(hex, true)) TgIconView(TgIcons.check, tint = Color.White, size = 16.dp, stroke = 2.6f)
                    }
                }
            }
        })
        Divider()
        ChoiceSetting(state, "contrast", "Contrast", "High contrast makes text, borders and focus rings stronger.",
            listOf("normal" to "Normal", "high" to "High contrast"))
        Divider()
        val saved = settings.str("font_scale")?.toFloatOrNull() ?: 1f
        var scale by remember(saved) { mutableFloatStateOf(saved) }
        Row2("Text size", "Scales text everywhere in TG Drive, on top of the phone's own text size.", control = {
            Text("${(scale * 100).toInt()}%", style = Tg.type.label, color = c.ink2)
        }, below = {
            Slider(scale, { scale = (it * 20).toInt() / 20f }, valueRange = .85f..1.3f, steps = 8,
                onValueChangeFinished = { state.setSetting("font_scale", scale.toDouble()) },
                colors = SliderDefaults.colors(thumbColor = c.accent, activeTrackColor = c.accent, inactiveTrackColor = c.line))
        })
        Divider()
        ChoiceSetting(state, "motion", "Animations", "Panels sliding, lists fading in, menus and dialogs popping.",
            listOf("on" to "On", "system" to "Follow the system", "off" to "Off"))
    }
    Group("Files and folders") {
        ChoiceSetting(state, "grid_size", "Card size", null, listOf("s" to "Small", "m" to "Medium", "l" to "Large"))
        Divider()
        ChoiceSetting(state, "density", "Density", "Compact fits more rows in lists and the sidebar.", listOf("comfortable" to "Comfortable", "compact" to "Compact"))
        Divider()
        ChoiceSetting(state, "folder_style", "Folders", "How folders show above the files.", listOf("tiles" to "Tiles", "cards" to "Cards with covers", "list" to "List"))
        Divider()
        SwitchSetting(state, "pdf_card_previews", "PDF pages as card pictures",
            "Most PDFs on Telegram come without a preview. TG Drive draws the first page of each PDF card you see (fetching only what that page needs) and keeps the picture.",
            default = true)
    }
}

@Composable
private fun SearchSection(state: AppState) {
    val account by state.account.collectAsState()
    val scope = rememberCoroutineScope()
    val sem = account?.semantic
    Group {
        ChoiceSetting(state, "search_mode", "Matching",
            "Smart finds the same words written differently: joined or split (test series ↔ testseries), word endings, typos, abbreviations " +
                "(pyq ↔ previous year questions), Hindi ↔ Latin script, and synonyms. Exact looks for your words only.",
            listOf("smart" to "Smart", "exact" to "Exact words"))
        Divider()
        val semLine = when {
            sem == null -> ""
            sem.str("error") != null -> " (${sem.str("error")})"
            sem.str("state") == "building" -> " (learning: ${Format.num(sem.long("count"))} files so far)"
            sem.long("count") > 0 -> " (${Format.num(sem.long("count"))} files understood)"
            else -> ""
        }
        SwitchSetting(state, "search_semantic", "Related by meaning",
            "Adds files with a similar meaning at the end of “Best match” results, using a small AI model that runs offline on this phone.$semLine", default = true)
        Divider()
        SwitchSetting(state, "search_live", "Search as you type", "Results update while you type.", default = true)
        Divider()
        ChoiceSetting(state, "search_scope_default", "Where search looks first", "Inside a folder or chat, search can start limited to it.",
            listOf("everywhere" to "Everywhere", "here" to "Where I am"))
        Divider()
        SwitchSetting(state, "search_builtin_synonyms", "Built-in synonyms", "Common study and file words: PYQ, current affairs, GS, polity ↔ संविधान, and more.",
            default = true)
    }
    Group {
        TextSetting(state, "search_synonyms", "Your synonyms",
            "One group per line, separated by commas. Any word or phrase in a group finds the others. Example: ts, test series, mock test",
            placeholder = "lax, laxmikanth, indian polity", lines = 5)
    }
    Group {
        Row2("Search history", "TG Drive remembers recent searches on this phone to suggest them.", control = {
            TgButton("Clear", {
                scope.launch {
                    runCatching { state.api.clearHistory(state.aid.value) }
                        .onSuccess { state.message("Search history cleared") }.onFailure { state.failed("That", it) }
                }
            }, small = true, icon = TgIcons.trash)
        })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Subjects(state: AppState) {
    val subjects by state.subjects.collectAsState()
    val scope = rememberCoroutineScope()
    Group(intro = "TG Drive tags every file with a subject (Polity, Economy, History …) from its name, caption and chat, in English and Hindi. " +
        "Subjects appear in the sidebar, in search (subject:polity) and in folder rules.") {
        SwitchSetting(state, "subjects_enabled", "Tag files with subjects", default = true)
        Divider()
        SwitchSetting(state, "subjects_builtin", "Built-in study subjects", "UPSC and general study subjects with English, Hindi and abbreviated keywords.",
            default = true)
        Divider()
        TextSetting(state, "subjects_custom", "Your subjects and keywords",
            "One subject per line: a name, a colon, then keywords separated by commas. An emoji before the name becomes its icon.",
            placeholder = "📑 Tax Law: income tax, gst, itr", lines = 5)
    }
    Group("Now") {
        FlowRow(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            subjects.filter { it.n > 0 }.sortedByDescending { it.n }.forEach { s ->
                TgChip("${listOfNotNull(s.emoji, s.name).joinToString(" ")}  ${Format.compact(s.n)}")
            }
            if (subjects.none { it.n > 0 }) Text("No subjects found yet.", style = Tg.type.meta, color = Tg.colors.ink3)
        }
        Buttons {
            TgButton("Tag everything again", {
                scope.launch { runCatching { state.api.rebuildSubjects(state.aid.value) }.onSuccess { state.message("Tagging every file again in the background.") } }
            }, icon = TgIcons.refresh, small = true)
        }
    }
}

@Composable
private fun Downloads(state: AppState) {
    val status by state.status.collectAsState()
    Group {
        Row2("Download folder", status?.downloadDir ?: "Downloads/TG Drive")
        Divider()
        SwitchSetting(state, "keep_structure", "Keep folder structure", "Downloading a folder recreates its subfolders; uploading a folder recreates it in TG Drive.",
            default = true)
        Divider()
        NumberRow(state, "parallel_transfers", "Transfers at the same time", null, 1, 10)
        Divider()
        NumberRow(state, "download_workers", "Parallel parts per download", "More parts download faster, up to what Telegram allows.", 1, 8)
        Divider()
        NumberRow(state, "upload_workers", "Parallel parts per upload", null, 1, 8)
        Divider()
        SwitchSetting(state, "upload_as_media", "Upload photos and videos as media",
            "Off: files are sent as documents (original quality, any type). On: photos are compressed by Telegram and videos get a streaming preview.")
    }
}

@Composable
private fun Streaming(state: AppState) {
    val aid by state.aid.collectAsState()
    val usage by produceState<Long?>(null, aid) { value = runCatching { state.api.storage(aid).obj("local").long("stream_cache") }.getOrNull() }
    Group(intro = "Videos, audio, voice notes, photos and PDFs play straight from Telegram. TG Drive fetches the parts you watch, a few parts ahead, " +
        "and keeps recent parts on the phone so seeking back is instant.") {
        NumberRow(state, "stream_cache_mb", "Stream cache size", "Oldest parts are removed when the cache is full.", 0, 200000, "MB")
        Divider()
        NumberRow(state, "stream_prefetch", "Parts fetched ahead", "Each part is 512 KB. More makes playback smoother on slow connections.", 0, 16)
        Divider()
        SwitchSetting(state, "autoplay_next", "Play the next file automatically", "When a video or song ends, the next one starts.", default = true)
    }
    Group {
        Row2("Cache", usage?.let { "Using ${Format.size(it)} now." } ?: "…", control = { Maint(state, "clear_stream_cache", "Clear") })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Indexing(state: AppState) {
    val settings by state.settings.collectAsState()
    val kinds = (settings["index_kinds"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
    val skip = (settings["index_skip_kinds_of_chat"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
    Group {
        Row2("File types to index", "Turning a type off stops indexing it; files already indexed stay until you re-index the chat.", below = {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("photo", "video", "document", "audio", "voice", "round", "gif").forEach { k ->
                    val on = k in kinds
                    TgChip(Format.KIND_NAME[k] ?: k, selected = on, icon = if (on) TgIcons.check else null, onClick = {
                        state.setSetting("index_kinds", JsonArray((if (on) kinds - k else kinds + k).map { JsonPrimitive(it) }))
                    })
                }
            }
        })
        Divider()
        Row2("Skip these kinds of chats", "Useful if private chats or bots are full of files you don't need in TG Drive.", below = {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("user" to "Private chats", "bot" to "Bots", "group" to "Basic groups", "supergroup" to "Groups", "channel" to "Channels").forEach { (k, l) ->
                    val on = k in skip
                    TgChip(l, selected = on, icon = if (on) TgIcons.close else null, onClick = {
                        state.setSetting("index_skip_kinds_of_chat", JsonArray((if (on) skip - k else skip + k).map { JsonPrimitive(it) }))
                    })
                }
            }
        })
    }
    Group {
        SwitchSetting(state, "index_paused", "Pause indexing", "Stops fetching history. Live updates keep coming in.")
        Divider()
        NumberRow(state, "index_wait", "Wait between pages", "Seconds between history pages. Raise this if Telegram keeps asking to slow down.", 0, 10, "s",
            decimal = true)
        Divider()
        NumberRow(state, "resync_minutes", "Full check for new files", "How often every chat is compared with Telegram.", 5, 1440, "min")
        Divider()
        SwitchSetting(state, "verify_deleted", "Find files deleted while TG Drive was closed",
            "Slowly re-checks indexed messages in the background and drops ones that no longer exist.", default = true)
        Divider()
        NumberRow(state, "verify_per_hour", "Checks per hour", "100 files per request.", 0, 200000)
        Divider()
        SwitchSetting(state, "save_inline_previews", "Save instant previews",
            "Keeps Telegram's tiny blurred preview in the index, so pictures appear immediately (about 200 bytes each).", default = true)
    }
}

@Composable
private fun Network(state: AppState) {
    val settings by state.settings.collectAsState()
    var dialog by remember { mutableStateOf(false) }
    Group(intro = "Use a proxy if Telegram is blocked or slow on your network. Changes reconnect right away.") {
        val on = settings.bool("proxy_enabled")
        Row2("Proxy", if (on) "${settings.str("proxy_type")?.uppercase()} · ${settings.str("proxy_host")}:${settings.str("proxy_port")}" else "Off",
            control = { TgButton(if (on) "Change" else "Set up", { dialog = true }, small = true) }, onClick = { dialog = true })
    }
    if (dialog) ProxyDialog(state) { dialog = false }
}

@Composable
private fun TelegramApi(state: AppState) {
    val status by state.status.collectAsState()
    val settings by state.settings.collectAsState()
    val scope = rememberCoroutineScope()
    var id by remember { mutableStateOf(settings.str("api_id")?.takeIf { it != "0" }.orEmpty()) }
    var hash by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    Group(intro = "TG Drive signs in as your own Telegram account through Telegram's official API. It needs an API ID and hash, " +
        "which you create once at my.telegram.org → API development tools.") {
        if (status?.envApi == true) Text("The API ID is set by the TG_API_ID / TG_API_HASH environment variables, which override this page.",
            style = Tg.type.meta, color = Tg.colors.warn, modifier = Modifier.padding(16.dp))
        Column(Modifier.padding(16.dp)) {
            TgTextField(id, { id = it.filter(Char::isDigit) }, label = "API ID", keyboardType = KeyboardType.Number)
            Spacer(Modifier.height(12.dp))
            TgTextField(hash, { hash = it.trim() }, label = "API hash", password = true,
                placeholder = if (settings.bool("api_hash_set")) "Saved. Enter a new one to replace it." else "32 characters")
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TgButton("Save", {
                    busy = true
                    scope.launch {
                        try { state.api.setup(id, hash); state.message("Saved. Reconnecting…"); hash = "" }
                        catch (e: Exception) { state.failed("Couldn't save that.", e) }
                        finally { busy = false }
                    }
                }, kind = ButtonKind.Primary, busy = busy, enabled = id.isNotBlank() && hash.length == 32)
                val ctx = LocalContext.current
                TgButton("Open my.telegram.org", { Platform.openUrl(ctx, "https://my.telegram.org/apps") }, kind = ButtonKind.Ghost, icon = TgIcons.external)
            }
        }
    }
    Group { TextSetting(state, "drive_channel_title", "Name of the storage channel", "Only used when TG Drive creates its private channel for the first time.") }
}

@Composable
private fun Security(state: AppState) {
    val status by state.status.collectAsState()
    val scope = rememberCoroutineScope()
    var dialog by remember { mutableStateOf(false) }
    val set = status?.lockSet == true
    Group(intro = "TG Drive only listens inside this app: every request carries a secret that changes each time it starts, and other apps can't read its data.") {
        Row2("App passcode", if (set) "On. TG Drive asks for it when it starts or after being idle." else "Off. Anyone using this phone can open TG Drive.",
            control = { TgButton(if (set) "Change" else "Set", { dialog = true }, small = true) })
        Divider()
        NumberRow(state, "lock_after_minutes", "Lock after being idle", "0 = only when TG Drive starts.", 0, 1440, "min")
        if (set) {
            Divider()
            Row2("Lock now", null, control = {
                TgButton("Lock", { scope.launch { runCatching { state.api.lockNow() }; state.onLocked() } }, small = true, icon = TgIcons.lock)
            })
        }
    }
    if (dialog) PasscodeDialog(state, set) { dialog = false }
}

@Composable
private fun PasscodeDialog(state: AppState, set: Boolean, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var old by remember { mutableStateOf("") }
    var new by remember { mutableStateOf("") }
    var again by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    fun save(remove: Boolean) {
        if (!remove && new.length < 4) { error = "Use at least 4 characters."; return }
        if (!remove && new != again) { error = "The two passcodes are different."; return }
        busy = true
        scope.launch {
            try {
                state.api.setLock(if (remove) null else new, old.ifEmpty { null })
                state.refreshStatus()
                state.message(if (remove) "Passcode removed" else "Passcode set")
                onClose()
            } catch (e: Exception) { error = e.explain("changing the passcode") } finally { busy = false }
        }
    }
    TgDialog(if (set) "Change passcode" else "Set a passcode", onClose, "Save", { save(false) }, busy = busy) {
        if (set) { TgTextField(old, { old = it }, label = "Current passcode", password = true); Spacer(Modifier.height(10.dp)) }
        TgTextField(new, { new = it; error = null }, label = "New passcode", password = true)
        Spacer(Modifier.height(10.dp))
        TgTextField(again, { again = it; error = null }, label = "Again", password = true, error = error)
        if (set) {
            Spacer(Modifier.height(12.dp))
            TgButton("Remove the passcode", { save(true) }, kind = ButtonKind.Danger, small = true, enabled = old.isNotEmpty())
        }
    }
}

/** Background sync (see engine/BackgroundSync.kt): on/off, how often, and when it may run. */
@Composable
private fun BackgroundSyncGroup() {
    val ctx = LocalContext.current
    val c = Tg.colors
    var on by remember { mutableStateOf(BackgroundSync.enabled(ctx)) }
    var minutes by remember { mutableIntStateOf(BackgroundSync.minutes(ctx)) }
    var wifi by remember { mutableStateOf(BackgroundSync.wifiOnly(ctx)) }
    var charging by remember { mutableStateOf(BackgroundSync.chargingOnly(ctx)) }
    var last by remember { mutableStateOf(BackgroundSync.last(ctx)) }
    var limits by remember { mutableStateOf(BatteryLimits.status(ctx)) }
    // Also picks up a change made in Android's settings and coming back.
    LaunchedEffect(Unit) { while (true) { last = BackgroundSync.last(ctx); limits = BatteryLimits.status(ctx); delay(2000) } }
    fun save() = BackgroundSync.update(ctx, on, minutes, wifi, charging)
    Group("Background sync", "While the app is closed, TG Drive checks your chats for new files now and then and indexes them, so " +
        "search and folders are up to date when you open it. Android picks the moment to save battery (with other apps' work, never " +
        "on low battery); a check takes seconds to a few minutes, with no notification. Heavier work (meaning search, subjects, " +
        "duplicates) waits until you open the app.") {
        Row2("Sync in the background", if (on) "On" else "Off: new files are found when you open TG Drive",
            control = { TgSwitch(on, { on = it; save() }) }, onClick = { on = !on; save() })
        if (on) {
            // Android (or the phone's maker) can stop it quietly: say so, and open the screen that fixes it.
            val stale = last.at > 0 && !last.running &&
                System.currentTimeMillis() - last.at > maxOf(3L * minutes * 60_000, 6 * 3_600_000L)
            val problems = buildList {
                if (limits.backgroundRestricted) add("Android is set to restrict TG Drive in the background, so background sync can't run. " +
                    "Open the battery settings and choose “Unrestricted” (or “Optimised”).")
                if (limits.restrictedBucket) add("Android has put TG Drive among its restricted apps (it does this to apps it thinks are " +
                    "unused), so background sync runs about once a day at most. Choosing “Unrestricted” battery use prevents it.")
                if (stale) add("Background sync last ran ${Format.relative(last.at / 1000)}, although it's set to every " +
                    "${if (minutes < 60) "$minutes minutes" else "${minutes / 60} h"}: Android may be holding it back.")
            }
            if (problems.isNotEmpty() || limits.samsung) {
                Divider()
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
                    problems.forEach {
                        Text(it, style = Tg.type.meta, color = c.danger, modifier = Modifier.padding(bottom = 8.dp))
                    }
                    if (limits.samsung) Text("On Samsung phones, also check Settings → Battery → Background usage limits: TG Drive " +
                        "must not be in “Sleeping apps” or “Deep sleeping apps” (add it to “Never sleeping apps”).",
                        style = Tg.type.meta, color = c.ink2, modifier = Modifier.padding(bottom = 8.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        TgButton("Battery settings", { BatteryLimits.openAppSettings(ctx) }, small = true, icon = TgIcons.external,
                            kind = if (problems.isNotEmpty()) ButtonKind.Primary else ButtonKind.Ghost)
                        if (limits.samsung) TgButton("Samsung battery", { BatteryLimits.openSamsungBattery(ctx) }, small = true,
                            icon = TgIcons.external, kind = ButtonKind.Ghost)
                    }
                }
            }
        }
        if (on) {
            Divider()
            Row2("How often", "At most this often; Android may wait longer when the phone is idle or the battery is saving.", below = {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    BackgroundSync.INTERVALS.forEach { m ->
                        TgChip(if (m < 60) "$m min" else "${m / 60} h", selected = minutes == m, onClick = { minutes = m; save() })
                    }
                }
            })
            Divider()
            Row2("Only on Wi-Fi", "Don't use mobile data for it.",
                control = { TgSwitch(wifi, { wifi = it; save() }) }, onClick = { wifi = !wifi; save() })
            Divider()
            Row2("Only while charging", "Uses no battery at all; new files arrive less often.",
                control = { TgSwitch(charging, { charging = it; save() }) }, onClick = { charging = !charging; save() })
        }
        Divider()
        Row2("Last sync", when {
            last.running -> "Syncing now…"
            last.at == 0L -> "Not yet"
            else -> Format.dateTime(last.at / 1000) + " · " + last.result
        }, control = {
            TgButton("Sync now", { BackgroundSync.syncNow(ctx); last = last.copy(running = true) }, small = true,
                icon = TgIcons.refresh, busy = last.running)
        })
        if (!last.ok && !last.running && last.at > 0) {
            Text("The last sync didn't finish: ${last.result}", style = Tg.type.meta, color = c.danger,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        }
    }
}

@Composable
private fun ThisPhone(state: AppState) {
    val ctx = LocalContext.current
    val g = ctx.graph
    val engine by g.engine.state.collectAsState()
    val scope = rememberCoroutineScope()
    var keep by remember { mutableStateOf(g.engine.keepRunning) }
    var restart by remember { mutableStateOf(false) }
    BackgroundSyncGroup()
    Group(intro = "TG Drive's service (Telegram, index, search, streaming) runs on this phone. It runs while the app is open and while " +
        "something needs it — transfers, the player — then stops after a minute to save battery.") {
        Row2("Stay connected all the time",
            "Instead of syncing now and then: new files show up the moment they arrive, even with the app closed. Uses much more battery; " +
                "Android shows a notification while it runs. Most people only need background sync.",
            control = { TgSwitch(keep, { keep = it; g.engine.keepRunning = it }) }, onClick = { keep = !keep; g.engine.keepRunning = keep })
        Divider()
        Row2("Battery optimisation", "If Android stops long downloads, let TG Drive run without battery restrictions.", onClick = {
            runCatching { ctx.startActivity(Intent(AndroidSettings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        }, control = { TgIconView(TgIcons.external, tint = Tg.colors.ink3, size = 18.dp) })
        Divider()
        Row2("Notifications", "Transfers, and what the service is doing.", onClick = {
            runCatching {
                ctx.startActivity(Intent(AndroidSettings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(AndroidSettings.EXTRA_APP_PACKAGE, ctx.packageName)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
        }, control = { TgIconView(TgIcons.external, tint = Tg.colors.ink3, size = 18.dp) })
    }
    Group("Service") {
        Row2("State", when (engine.phase) {
            app.tgdrive.engine.EngineState.Phase.Ready -> "Running" + if (engine.demo) " with sample data" else ""
            app.tgdrive.engine.EngineState.Phase.Starting -> "Starting…"
            app.tgdrive.engine.EngineState.Phase.Failed -> "Stopped with an error: ${engine.error}"
            else -> "Stopped"
        }, control = { TgButton("Restart", { restart = true }, small = true, icon = TgIcons.refresh) })
        Divider()
        Row2("Engine", listOf("TG Drive ${engine.version.ifBlank { BuildConfig.VERSION_NAME }}", "encryption: ${engine.crypto.ifBlank { "—" }}",
            "full-text search: ${engine.fts5.ifBlank { "—" }}", if (engine.numpy) "vector maths: numpy" else "vector maths: built-in").joinToString(" · "))
        Divider()
        Row2(if (engine.demo) "Leave the sample data" else "Try with sample data",
            if (engine.demo) "Go back to your own Telegram account." else "Explore TG Drive with a made-up account. Your own data is kept.",
            onClick = { scope.launch { state.switchMode(!engine.demo) } }, control = { TgIconView(TgIcons.chevron, tint = Tg.colors.ink3, size = 16.dp) })
    }
    if (restart) ConfirmDialog("Restart TG Drive's service?", "Transfers pause and continue after the restart.", "Restart",
        onConfirm = { scope.launch { state.switchMode(engine.demo) } }, onDismiss = { restart = false })
}

@Composable
private fun DataSection(state: AppState) {
    val ctx = LocalContext.current
    val aid by state.aid.collectAsState()
    val folders by state.folders.collectAsState()
    val scope = rememberCoroutineScope()
    var backups by remember { mutableStateOf<List<app.tgdrive.data.Backup>?>(null) }
    var about by remember { mutableStateOf<JsonObject?>(null) }
    var restoreId by remember { mutableStateOf<Long?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    LaunchedEffect(aid, reload) {
        backups = runCatching { state.api.backups(aid) }.getOrDefault(emptyList())
        about = runCatching { state.api.about() }.getOrNull()
    }
    fun write(uri: Uri?, text: suspend () -> String, done: String) {
        uri ?: return
        scope.launch {
            try {
                val t = text()
                kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    ctx.contentResolver.openOutputStream(uri, "wt")?.use { it.write(t.toByteArray()) } ?: error("Couldn't write the file.")
                }
                state.message(done)
            } catch (e: Exception) { state.failed("Couldn't save it.", e) }
        }
    }
    fun read(uri: Uri?, then: suspend (String) -> Unit) {
        uri ?: return
        scope.launch {
            try {
                val t = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    ctx.contentResolver.openInputStream(uri)?.use { it.readBytes().decodeToString() } ?: error("Couldn't read the file.")
                }
                then(t)
            } catch (e: Exception) { state.failed("Couldn't import it.", e) }
        }
    }
    val exportManifest = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) {
        write(it, { state.api.exportManifest(aid) }, "Folders exported")
    }
    val importManifest = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) {
        read(it) { t -> state.api.importManifest(aid, JsonCodec.parseToJsonElement(t), "merge"); state.loadFolders(); state.message("Folders imported") }
    }
    val exportSettings = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) {
        write(it, { state.api.exportSettings(false) }, "Settings exported")
    }
    val importSettings = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) {
        read(it) { t -> state.api.importSettings(JsonCodec.parseToJsonElement(t)); state.refreshStatus(); state.message("Settings imported") }
    }

    Group(intro = "Tidy up or check the index. Nothing here touches Telegram.") {
        about?.let { a -> Row2("Data on this phone", Format.size(a.obj("data").long("bytes"))) ; Divider() }
        Buttons {
            Maint(state, "optimize", "Optimize")
            Maint(state, "integrity", "Check integrity")
            Maint(state, "vacuum", "Compact (VACUUM)", "This can take a few minutes on a big index. TG Drive stays usable but may be slower.")
            Maint(state, "stats", "Recount statistics")
            Maint(state, "rebuild_search", "Rebuild search index", "Search keeps working with the old index while the new one is built.")
            Maint(state, "rebuild_semantic", "Rebuild meaning index", "Search keeps working with the old index while the new one is built.")
            Maint(state, "clear_thumbs", "Clear preview cache")
        }
    }
    Group("Folders, stars, tags and notes",
        "They live in a pinned file in your “${folders.driveTitle}” channel and sync to every device. TG Drive keeps the last 30 versions.") {
        Buttons {
            TgButton("Sync now", { scope.launch { runCatching { state.api.syncDrive(aid) }.onSuccess { state.message("Synced") }
                .onFailure { state.failed("That", it) } } }, icon = TgIcons.refresh, small = true)
            TgButton("Export", { exportManifest.launch("tgdrive-folders.json") }, icon = TgIcons.download, small = true)
            TgButton("Import…", { importManifest.launch(arrayOf("application/json", "text/plain", "*/*")) }, icon = TgIcons.upload, small = true)
        }
        backups?.take(12)?.forEach { b ->
            Divider()
            Row2(b.reason ?: "Backup", listOfNotNull(Format.dateTime(b.at), b.bytes?.let { Format.size(it) }).joinToString(" · "),
                control = { TgButton("Restore", { restoreId = b.id }, small = true, kind = ButtonKind.Ghost) })
        }
    }
    Group("Back up settings", "Save all your settings to a file, and load them on another device or after reinstalling. Folders, stars and tags already sync through Telegram.") {
        Buttons {
            TgButton("Export settings", { exportSettings.launch("tgdrive-settings.json") }, icon = TgIcons.download, small = true)
            TgButton("Import settings…", { importSettings.launch(arrayOf("application/json", "text/plain", "*/*")) }, icon = TgIcons.upload, small = true)
        }
    }
    restoreId?.let { id ->
        ConfirmDialog("Restore this version?", "Your folders, stars, tags, notes and saved searches go back to how they were then. You can undo this.",
            "Restore", onConfirm = {
                scope.launch {
                    runCatching { state.api.restoreBackup(aid, id) }.onSuccess { state.loadFolders(); state.changed("restore"); state.message("Restored"); reload++ }
                        .onFailure { state.failed("That", it) }
                }
            }, onDismiss = { restoreId = null })
    }
}

@Composable
private fun About(state: AppState) {
    val c = Tg.colors
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val settings by state.settings.collectAsState()
    var about by remember { mutableStateOf<JsonObject?>(null) }
    var crashes by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var cpu by remember { mutableStateOf<JsonObject?>(null) }
    var cpuBusy by remember { mutableStateOf(false) }
    var log by remember { mutableStateOf<String?>(null) }
    var crashText by remember { mutableStateOf<String?>(null) }
    var diagBusy by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }
    LaunchedEffect(reload) {
        about = runCatching { state.api.about() }.getOrNull()
        crashes = runCatching { state.api.crashes().arr("reports").mapNotNull { it as? JsonObject } }.getOrDefault(emptyList())
    }
    Group {
        Row2("TG Drive", "Version ${about?.str("version") ?: BuildConfig.VERSION_NAME} · app ${BuildConfig.VERSION_NAME} · meaning-based search " +
            if (about?.bool("semantic_available") == true) "available" else "not installed")
    }
    Group("Something not working?", "Sends a file with TG Drive's logs, crash reports and the phone's details, to whoever helps you fix it. " +
        "It has no passwords, keys, tokens or messages. For the most detail, turn on detailed debug logging below, do the thing that fails, then send.") {
        Buttons { app.tgdrive.diag.ReportButton(null) }
    }
    Group("CPU use", "What TG Drive's service is using the processor for right now (100% is one whole core), measured over a few seconds.") {
        Buttons {
            TgButton("Measure now", {
                cpuBusy = true
                scope.launch {
                    runCatching { state.api.cpu(); delay(3000); state.api.cpu() }.onSuccess { cpu = it }
                    cpuBusy = false
                }
            }, icon = TgIcons.activity, small = true, busy = cpuBusy)
        }
        cpu?.let { r ->
            Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                if (!r.bool("available", true)) Text("Not available on this phone.", style = Tg.type.meta, color = c.ink3)
                else {
                    Text("Total: ${r.str("total") ?: "0"}% over ${r.str("seconds") ?: "?"} s", style = Tg.type.label, color = c.ink)
                    r.arr("parts").forEach { p ->
                        val a = p as? JsonArray ?: return@forEach
                        val label = (a.getOrNull(0) as? JsonPrimitive)?.contentOrNull ?: return@forEach
                        val pct = (a.getOrNull(1) as? JsonPrimitive)?.contentOrNull?.toFloatOrNull() ?: 0f
                        Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(label, style = Tg.type.meta, color = c.ink2, modifier = Modifier.width(130.dp), maxLines = 1)
                            Box(Modifier.weight(1f).height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.line2)) {
                                Box(Modifier.fillMaxWidth((pct / 100f).coerceIn(.01f, 1f)).height(6.dp).background(c.accent))
                            }
                            Text("$pct%", style = Tg.type.meta, color = c.ink3, modifier = Modifier.width(56.dp).padding(start = 8.dp))
                        }
                    }
                }
            }
        }
    }
    Group("Debug logging", "Records everything in detail while it's on: every request, transfers, streaming, indexing, search, errors. It stays on this phone. " +
        "It covers both the service and the app itself. Turn it on to catch a problem, reproduce it, then send a problem report and turn it off again.") {
        SwitchSetting(state, "debug_logging", "Detailed debug logging" + if (settings.bool("debug_logging")) " (ON)" else "")
        Divider()
        Buttons {
            TgButton("View log", { scope.launch { log = runCatching { state.api.logs(400) }.getOrElse { it.message ?: "" } } }, icon = TgIcons.document, small = true)
            TgButton("App log", {
                scope.launch { log = withContext(Dispatchers.IO) { app.tgdrive.diag.AppLog.tail(ctx) } }
            }, icon = TgIcons.document, small = true, kind = ButtonKind.Ghost)
            TgButton("Clear all logs", {
                scope.launch {
                    runCatching { state.api.clearLogs(false) }
                    withContext(Dispatchers.IO) { app.tgdrive.diag.AppLog.clear(ctx) }
                    state.message("Logs cleared")
                }
            },
                icon = TgIcons.trash, small = true, kind = ButtonKind.Danger)
        }
    }
    Group("Crash reports", "When something goes wrong, TG Drive saves a short report on this phone. Nothing is sent anywhere.") {
        SwitchSetting(state, "crash_reports", "Save crash reports", default = true)
        crashes.take(20).forEach { x ->
            Divider()
            Row2(x.str("summary") ?: "Error", listOfNotNull(x.str("kind"), Format.dateTime(x.long("at"))).joinToString(" · "), control = {
                TgButton("View", { scope.launch { crashText = runCatching { state.api.crash(x.str("id").orEmpty()) }.getOrElse { it.message } } }, small = true,
                    kind = ButtonKind.Ghost)
            })
        }
        if (crashes.isEmpty()) Text("No crashes recorded.", style = Tg.type.meta, color = c.ink3, modifier = Modifier.padding(16.dp))
        else Buttons { TgButton("Delete all reports", { scope.launch { runCatching { state.api.clearCrashes() }; reload++ } }, small = true, kind = ButtonKind.Ghost) }
    }
    Group("Diagnostics file", "A .zip with logs, crash reports, versions and settings to attach to a bug report. Phone numbers, keys, tokens and e-mail " +
        "addresses are removed; chat and file names too.") {
        Buttons {
            TgButton("Create and share…", {
                diagBusy = true
                scope.launch {
                    try {
                        val r = state.api.diagnostics(false)
                        Platform.shareFiles(ctx, listOf(r.str("path").orEmpty()))
                    } catch (e: Exception) { state.failed("Couldn't make the file.", e) }
                    finally { diagBusy = false }
                }
            }, icon = TgIcons.bug, small = true, busy = diagBusy)
        }
    }
    log?.let { text ->
        TgDialog("Log", { log = null }, dismiss = "Close", confirm = "Copy", onConfirm = { Platform.copy(ctx, "TG Drive log", text); state.message("Log copied") }) {
            SelectionContainer { Text(text.ifBlank { "No log yet." }, style = Tg.type.mono, color = c.ink2) }
        }
    }
    crashText?.let { text ->
        TgDialog("Crash report", { crashText = null }, dismiss = "Close", confirm = "Copy",
            onConfirm = { Platform.copy(ctx, "TG Drive crash report", text); state.message("Copied") }) {
            SelectionContainer { Text(text, style = Tg.type.mono, color = c.ink2) }
        }
    }
}

// ---------------------------------------------------------------------- accounts
/** Accounts (desktop Settings → Accounts): switch, add, sign out. */
@Composable
fun AccountsScreen(state: AppState, onBack: () -> Unit, onAdd: () -> Unit, onApiKey: () -> Unit) {
    val c = Tg.colors
    val status by state.status.collectAsState()
    val aid by state.aid.collectAsState()
    val scope = rememberCoroutineScope()
    var removing by remember { mutableStateOf<app.tgdrive.data.Account?>(null) }
    LaunchedEffect(Unit) { state.refreshStatus() }
    Column(Modifier.fillMaxSize().background(c.canvas)) {
        PageBar("Accounts", onMenu = onBack, onBack = onBack)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 96.dp)) {
            Group {
                status?.accounts.orEmpty().forEachIndexed { i, a ->
                    if (i > 0) Divider()
                    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Avatar(a.name, 44.dp)
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(a.name ?: "Account", style = Tg.type.bodyStrong, color = c.ink)
                            Text(listOfNotNull(a.username?.let { "@$it" } ?: a.phone, if (a.premium) "Premium" else null, a.status.ifBlank { null })
                                .joinToString(" · "), style = Tg.type.meta, color = c.ink3)
                            a.error?.let { Text(it, style = Tg.type.meta, color = c.danger) }
                        }
                        if (a.id == aid) Text("In use", style = Tg.type.caption, color = c.ok,
                            modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(c.ok.copy(alpha = .12f)).padding(horizontal = 8.dp, vertical = 2.dp))
                        else TgButton("Switch", { state.selectAccount(a.id) }, small = true)
                        IconBtn(TgIcons.signout, { removing = a }, tint = c.danger, contentDescription = "Sign out")
                    }
                }
                if (status?.accounts.isNullOrEmpty()) Text("No accounts yet.", style = Tg.type.body, color = c.ink3, modifier = Modifier.padding(16.dp))
            }
            Buttons {
                if (!state.demo) TgButton("Add another account", onAdd, kind = ButtonKind.Primary, icon = TgIcons.plus)
                TgButton("Telegram API key", onApiKey, icon = TgIcons.telegram)
            }
        }
    }
    removing?.let { a ->
        TgDialog("Sign out of ${a.name ?: "this account"}?", { removing = null }, dismiss = null) {
            Text("TG Drive ends its Telegram session. You can keep this account's index (folders and tags are safe in Telegram either way) to sign in again quickly.",
                style = Tg.type.body, color = c.ink2)
            Spacer(Modifier.height(16.dp))
            Column(horizontalAlignment = Alignment.End, modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                TgButton("Sign out, keep the index", { val x = a; removing = null; scope.launch { remove(state, x, true) } }, kind = ButtonKind.Primary)
                TgButton("Sign out and delete its data", { val x = a; removing = null; scope.launch { remove(state, x, false) } }, kind = ButtonKind.Danger)
                TgButton("Cancel", { removing = null }, kind = ButtonKind.Ghost)
            }
        }
    }
}

private suspend fun remove(state: AppState, a: app.tgdrive.data.Account, keep: Boolean) {
    try {
        state.api.removeAccount(a.id, keep)
        state.message("Signed out of ${a.name ?: "the account"}")
        state.bootstrap()
    } catch (e: Exception) { state.failed("Couldn't sign out.", e) }
}
