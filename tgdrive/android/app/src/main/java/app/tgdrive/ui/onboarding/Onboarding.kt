package app.tgdrive.ui.onboarding

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import app.tgdrive.ui.components.TgDialog
import androidx.compose.ui.unit.sp
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import app.tgdrive.data.AppState
import app.tgdrive.data.explain
import app.tgdrive.data.QrLogin
import app.tgdrive.ui.components.ButtonKind
import app.tgdrive.ui.components.Spinner
import app.tgdrive.ui.components.TgButton
import app.tgdrive.ui.components.TgLogo
import app.tgdrive.ui.components.TgTextField
import app.tgdrive.ui.components.QrImage
import app.tgdrive.ui.settings.ProxyDialog
import app.tgdrive.ui.theme.Tg
import app.tgdrive.ui.theme.TgIcon
import app.tgdrive.ui.theme.TgIconView
import app.tgdrive.ui.theme.TgIcons
import app.tgdrive.ui.theme.TgShape
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** The centred column every first-run and sign-in step uses (the desktop's .login card). */
@Composable
fun FramePage(modifier: Modifier = Modifier, logo: Boolean = true, content: @Composable ColumnScope.() -> Unit) {
    val c = Tg.colors
    Box(modifier.fillMaxSize().background(c.canvas).systemBarsPadding().imePadding(), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier
                .widthIn(max = 480.dp)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 28.dp),
        ) {
            if (logo) {
                TgLogo(56.dp)
                Spacer(Modifier.height(22.dp))
            }
            content()
        }
    }
}

@Composable
private fun H1(text: String) = Text(text, style = Tg.type.title, color = Tg.colors.ink)

@Composable
private fun P(text: String, modifier: Modifier = Modifier) =
    Text(text, style = Tg.type.body, color = Tg.colors.ink2, modifier = modifier.padding(top = 8.dp))

@Composable
private fun ErrorText(text: String?) {
    if (!text.isNullOrBlank()) Text(text, style = Tg.type.label, color = Tg.colors.danger, modifier = Modifier.padding(top = 12.dp))
}

// ---------------------------------------------------------------------- splash
/**
 * While the service starts: what it's doing right now and, if that takes unusually long, a way to
 * see why and to start it again (never a spinner with no way out).
 */
@Composable
fun SplashScreen(stage: String, seconds: Int, report: () -> String, onRestart: () -> Unit) {
    val c = Tg.colors
    var details by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxSize().background(c.canvas).systemBarsPadding(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(horizontal = 32.dp)) {
            TgLogo(84.dp)
            Spacer(Modifier.height(26.dp))
            Spinner(24.dp)
            Spacer(Modifier.height(14.dp))
            Text("Starting TG Drive…", style = Tg.type.label, color = c.ink2)
            if (stage.isNotBlank() && seconds >= 2) {
                Spacer(Modifier.height(6.dp))
                Text(stage, style = Tg.type.meta, color = c.ink3, textAlign = TextAlign.Center)
            }
            if (seconds >= 6 && seconds < 45) {
                Spacer(Modifier.height(4.dp))
                Text("The first start unpacks TG Drive's service; it takes a little longer.", style = Tg.type.meta, color = c.ink3,
                    textAlign = TextAlign.Center)
            }
            if (seconds >= 45) {
                Spacer(Modifier.height(10.dp))
                Text("This is taking longer than it should (${seconds}s).", style = Tg.type.meta, color = c.warn, textAlign = TextAlign.Center)
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    TgButton("Show details", { details = true }, small = true, icon = TgIcons.info)
                    TgButton("Restart", onRestart, small = true, icon = TgIcons.refresh)
                }
            }
        }
    }
    if (details) ReportDialog(report) { details = false }
}

/** The start report, to read, copy or send (the error screen and a slow start show it). */
@Composable
fun ReportDialog(report: () -> String, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val text = remember { report() }
    TgDialog("Details", onClose, confirm = "Copy", onConfirm = {
        app.tgdrive.ui.actions.Platform.copy(ctx, "TG Drive start report", text)
    }, dismiss = "Close") {
        Text("Copy this and send it to report the problem. It has no passwords, keys or messages.", style = Tg.type.meta, color = Tg.colors.ink3)
        Spacer(Modifier.height(10.dp))
        androidx.compose.foundation.text.selection.SelectionContainer {
            Text(text, style = Tg.type.mono.copy(fontSize = 11.sp), color = Tg.colors.ink2)
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            app.tgdrive.diag.ReportButton(null)
            TgButton("Share as text", { app.tgdrive.ui.actions.Platform.shareText(ctx, text) }, small = true, kind = ButtonKind.Ghost)
        }
    }
}

@Composable
fun EngineFailedScreen(error: String, report: () -> String, onRetry: () -> Unit, onSample: () -> Unit) {
    var details by remember { mutableStateOf(false) }
    FramePage {
        H1("TG Drive's service didn't start")
        P("Something went wrong while starting the part of TG Drive that talks to Telegram. Your files and sign-in are safe.")
        Spacer(Modifier.height(14.dp))
        Box(Modifier.fillMaxWidth().clip(TgShape.control).background(Tg.colors.panel2).border(1.dp, Tg.colors.line, TgShape.control).padding(12.dp)) {
            Text(error, style = Tg.type.mono, color = Tg.colors.ink2)
        }
        Spacer(Modifier.height(18.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            TgButton("Try again", onRetry, kind = ButtonKind.Primary, icon = TgIcons.refresh)
            TgButton("Use sample data", onSample)
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            TgButton("Show details", { details = true }, kind = ButtonKind.Ghost, icon = TgIcons.info)
            app.tgdrive.diag.ReportButton(error, small = false)
        }
    }
    if (details) ReportDialog(report) { details = false }
}

// ---------------------------------------------------------------------- welcome
@Composable
fun WelcomeScreen(onSignIn: () -> Unit, onSample: () -> Unit) {
    val c = Tg.colors
    FramePage {
        Text("TG Drive", style = Tg.type.display, color = c.ink)
        P("Every file in your Telegram — every channel, group, private chat, bot and Saved Messages — in one place that works like Google Drive.")
        Spacer(Modifier.height(22.dp))
        Feature(TgIcons.search, "Search that understands you", "Typos, joined words, Hindi or Latin script, and files about the same topic.")
        Feature(TgIcons.play, "Play and preview instantly", "Videos, music, PDFs and photos stream straight from Telegram.")
        Feature(TgIcons.folder, "Folders, stars and tags", "Organise files without moving them. Your folders sync with TG Drive on your computer.")
        Feature(TgIcons.shield, "Private", "Runs on this phone and signs in as you. Nothing goes anywhere except Telegram.")
        Spacer(Modifier.height(26.dp))
        TgButton("Sign in with Telegram", onSignIn, Modifier.fillMaxWidth(), kind = ButtonKind.Primary, icon = TgIcons.telegram)
        Spacer(Modifier.height(10.dp))
        TgButton("Try it with sample data", onSample, Modifier.fillMaxWidth(), icon = TgIcons.sparkle)
        Spacer(Modifier.height(14.dp))
        Text("Sample data is a made-up account to look around in. You can sign in later from the account menu.",
            style = Tg.type.meta, color = c.ink3)
    }
}

@Composable
private fun Feature(icon: TgIcon, title: String, text: String) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Box(Modifier.size(38.dp).clip(RoundedCornerShape(11.dp)).background(c.accentSoft), contentAlignment = Alignment.Center) {
            TgIconView(icon, tint = c.accent, size = 20.dp)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = Tg.type.bodyStrong, color = c.ink)
            Text(text, style = Tg.type.meta, color = c.ink2)
        }
    }
}

// ---------------------------------------------------------------------- app key
@Composable
fun ApiKeyScreen(state: AppState, onBack: (() -> Unit)?) {
    val c = Tg.colors
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var id by remember { mutableStateOf("") }
    var hash by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    FramePage {
        H1("Connect TG Drive to Telegram")
        P("TG Drive signs in as your own account, so Telegram asks for an app key first. It takes a minute and you only do it once.")
        Spacer(Modifier.height(16.dp))
        Steps(listOf(
            buildAnnotatedString { append("Open "); withStyle(SpanStyle(color = c.accent, fontWeight = FontWeight.Medium)) { append("my.telegram.org/apps") }; append(" and sign in with your phone number.") },
            buildAnnotatedString { append("Fill in "); b("App title"); append(" (e.g. “TG Drive”) and "); b("Short name"); append(", pick "); b("Android"); append(", and create it.") },
            buildAnnotatedString { append("Copy the "); b("App api_id"); append(" and "); b("App api_hash"); append(" here.") },
        ))
        TgButton("Open my.telegram.org", {
            try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://my.telegram.org/apps"))) } catch (_: ActivityNotFoundException) {}
        }, Modifier.padding(top = 4.dp), icon = TgIcons.external, small = true)
        Spacer(Modifier.height(18.dp))
        TgTextField(id, { id = it.filter(Char::isDigit) }, label = "API ID", placeholder = "1234567", keyboardType = KeyboardType.Number,
            imeAction = ImeAction.Next)
        Spacer(Modifier.height(12.dp))
        TgTextField(hash, { hash = it.trim() }, label = "API hash", placeholder = "32 letters and digits", imeAction = ImeAction.Done)
        ErrorText(error)
        Spacer(Modifier.height(18.dp))
        TgButton("Continue", {
            busy = true; error = null
            scope.launch {
                try {
                    state.api.setup(id, hash)
                    state.bootstrap()
                } catch (e: Exception) {
                    error = e.explain("saving the API key")
                } finally { busy = false }
            }
        }, Modifier.fillMaxWidth(), kind = ButtonKind.Primary, busy = busy, enabled = id.isNotBlank() && hash.length >= 32)
        Spacer(Modifier.height(14.dp))
        Text("The key and your session stay on this phone. TG Drive talks only to Telegram.", style = Tg.type.meta, color = c.ink3)
        if (onBack != null) {
            Spacer(Modifier.height(10.dp))
            TgButton("Back", onBack, kind = ButtonKind.Ghost)
        }
    }
}

private fun androidx.compose.ui.text.AnnotatedString.Builder.b(t: String) = withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(t) }

@Composable
private fun Steps(items: List<androidx.compose.ui.text.AnnotatedString>) {
    val c = Tg.colors
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items.forEachIndexed { i, t ->
            Row {
                Box(Modifier.size(24.dp).clip(RoundedCornerShape(12.dp)).background(c.accentSoft), contentAlignment = Alignment.Center) {
                    Text("${i + 1}", style = Tg.type.caption, color = c.accent)
                }
                Spacer(Modifier.width(12.dp))
                Text(t, style = Tg.type.body, color = c.ink2, modifier = Modifier.weight(1f).padding(top = 1.dp))
            }
        }
    }
}

// ---------------------------------------------------------------------- sign in
private sealed interface SignStep {
    data object Phone : SignStep
    data class Code(val loginId: String, val phone: String, val via: String?) : SignStep
    data class Password(val loginId: String, val hint: String?) : SignStep
    data object Qr : SignStep
}

@Composable
fun SignInScreen(state: AppState, adding: Boolean, onDone: () -> Unit, onBack: (() -> Unit)?) {
    val c = Tg.colors
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var step by remember { mutableStateOf<SignStep>(SignStep.Phone) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var proxy by remember { mutableStateOf(false) }

    fun finished(name: String?) {
        state.message(if (name != null) "Signed in as $name. Indexing starts now." else "Signed in. Indexing starts now.")
        state.bootstrap()
        onDone()
    }

    fun act(block: suspend () -> Unit) {
        busy = true; error = null
        scope.launch {
            try { block() } catch (e: Exception) { error = e.explain("Something went wrong.") } finally { busy = false }
        }
    }

    FramePage {
        if (step is SignStep.Phone || step is SignStep.Qr) {
            Segmented(listOf("Phone number", "QR code"), if (step is SignStep.Qr) 1 else 0) {
                error = null
                step = if (it == 1) SignStep.Qr else SignStep.Phone
            }
            Spacer(Modifier.height(20.dp))
        }
        AnimatedContent(step, transitionSpec = { fadeIn() togetherWith fadeOut() }, label = "sign-in") { s ->
            Column {
                when (s) {
                    SignStep.Phone -> {
                        var phone by remember { mutableStateOf("") }
                        H1(if (adding) "Add another account" else "Sign in to Telegram")
                        P("Telegram sends you a code, like signing in on a new device. Your session stays on this phone.")
                        Spacer(Modifier.height(18.dp))
                        TgTextField(phone, { phone = it }, label = "Phone number with country code", placeholder = "+91 98765 43210",
                            keyboardType = KeyboardType.Phone, onDone = {
                                if (phone.isNotBlank()) act { val r = state.api.loginStart(phone); step = SignStep.Code(r.loginId, phone.trim(), r.sentVia) }
                            })
                        ErrorText(error)
                        Spacer(Modifier.height(16.dp))
                        TgButton("Send code", { act { val r = state.api.loginStart(phone); step = SignStep.Code(r.loginId, phone.trim(), r.sentVia) } },
                            Modifier.fillMaxWidth(), kind = ButtonKind.Primary, busy = busy, enabled = phone.count(Char::isDigit) >= 6)
                    }
                    is SignStep.Code -> {
                        var code by remember { mutableStateOf("") }
                        val where = when (s.via) { "app" -> "in your Telegram app"; "sms" -> "by SMS"; else -> "to you" }
                        H1("Enter the code")
                        P("Telegram sent a login code $where for ${s.phone}.")
                        Spacer(Modifier.height(18.dp))
                        val submit = {
                            act {
                                val r = state.api.loginCode(s.loginId, code)
                                if (r.needPassword) step = SignStep.Password(s.loginId, r.hint)
                                else finished(r.account?.get("name")?.toString()?.trim('"'))
                            }
                        }
                        TgTextField(code, { code = it.filter(Char::isDigit).take(8) }, label = "Code", placeholder = "12345",
                            keyboardType = KeyboardType.NumberPassword, onDone = { if (code.length >= 5) submit() })
                        ErrorText(error)
                        Spacer(Modifier.height(16.dp))
                        TgButton("Sign in", { submit() }, Modifier.fillMaxWidth(), kind = ButtonKind.Primary, busy = busy, enabled = code.length >= 5)
                        Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                            LinkText("Send a new code") {
                                act {
                                    val r = state.api.loginStart(s.phone)
                                    step = s.copy(loginId = r.loginId)
                                    state.message("A new code is on its way.")
                                }
                            }
                            Text("  ·  ", color = c.ink3, style = Tg.type.label)
                            LinkText("Change number") { error = null; step = SignStep.Phone }
                        }
                    }
                    is SignStep.Password -> {
                        var pw by remember { mutableStateOf("") }
                        H1("Two-step verification")
                        P("This account has a cloud password." + (if (!s.hint.isNullOrBlank()) " Hint: ${s.hint}" else ""))
                        Spacer(Modifier.height(18.dp))
                        val submit = { act { val r = state.api.loginPassword(s.loginId, pw); finished(r.account?.get("name")?.toString()?.trim('"')) } }
                        TgTextField(pw, { pw = it }, label = "Password", password = true, onDone = { if (pw.isNotEmpty()) submit() })
                        ErrorText(error)
                        Spacer(Modifier.height(16.dp))
                        TgButton("Sign in", { submit() }, Modifier.fillMaxWidth(), kind = ButtonKind.Primary, busy = busy, enabled = pw.isNotEmpty())
                    }
                    SignStep.Qr -> QrStep(state, adding, onPassword = { id, hint -> step = SignStep.Password(id, hint) },
                        onDone = { finished(it) })
                }
            }
        }
        Spacer(Modifier.height(22.dp))
        LinkText("Connection settings (proxy)…", icon = TgIcons.external) { proxy = true }
        if (onBack != null) {
            Spacer(Modifier.height(14.dp))
            TgButton(if (adding) "Back to my files" else "Back", onBack, kind = ButtonKind.Ghost)
        }
    }
    if (proxy) ProxyDialog(state) { proxy = false }
}

@Composable
private fun QrStep(state: AppState, adding: Boolean, onPassword: (String, String?) -> Unit, onDone: (String?) -> Unit) {
    val c = Tg.colors
    val ctx = LocalContext.current
    var qr by remember { mutableStateOf<QrLogin?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableStateOf(0) }
    LaunchedEffect(attempt) {
        error = null
        qr = null
        try {
            var cur = state.api.loginQr()
            qr = cur
            while (true) {
                delay(1500)
                cur = state.api.loginQrStatus(cur.loginId).copy(loginId = cur.loginId)
                when (cur.state) {
                    "done" -> { onDone(cur.account?.get("name")?.toString()?.trim('"')); return@LaunchedEffect }
                    "password" -> { onPassword(cur.loginId, cur.hint); return@LaunchedEffect }
                    "error", "expired" -> { error = cur.error ?: "The code expired. Get a new one and use it within a minute."; qr = null; return@LaunchedEffect }
                }
                if (cur.svg != null) qr = cur
            }
        } catch (e: Exception) {
            error = e.explain("QR sign-in")
        }
    }
    H1(if (adding) "Add another account" else "Sign in with a QR code")
    P("On this phone, open the link in Telegram and confirm. Or scan the code with Telegram on another device: Settings → Devices → Link Desktop Device.")
    Spacer(Modifier.height(18.dp))
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Box(Modifier.size(232.dp).clip(RoundedCornerShape(16.dp)).background(Color.White).border(1.dp, c.line, RoundedCornerShape(16.dp)),
            contentAlignment = Alignment.Center) {
            val cur = qr
            when {
                cur?.svg != null -> QrImage(cur.svg, Modifier.size(208.dp))
                error != null -> TgButton("Get a new code", { attempt++ }, kind = ButtonKind.Primary, icon = TgIcons.refresh)
                else -> Spinner(28.dp)
            }
        }
    }
    ErrorText(error)
    Spacer(Modifier.height(16.dp))
    TgButton("Open in Telegram", {
        val url = qr?.url ?: return@TgButton
        try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
        catch (_: ActivityNotFoundException) { state.message("Telegram isn't installed on this phone. Scan the code from another device.", error = true) }
    }, Modifier.fillMaxWidth(), kind = ButtonKind.Primary, icon = TgIcons.telegram, enabled = qr?.url != null)
}

@Composable
fun LinkText(text: String, icon: TgIcon? = null, onClick: () -> Unit) {
    val c = Tg.colors
    Row(Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClick = onClick).padding(vertical = 4.dp, horizontal = 2.dp),
        verticalAlignment = Alignment.CenterVertically) {
        if (icon != null) { TgIconView(icon, tint = c.accent, size = 15.dp); Spacer(Modifier.width(6.dp)) }
        Text(text, style = Tg.type.label, color = c.accent)
    }
}

@Composable
fun Segmented(options: List<String>, selected: Int, onSelect: (Int) -> Unit) {
    val c = Tg.colors
    Row(Modifier.fillMaxWidth().height(40.dp).clip(TgShape.control).background(c.panel2).border(1.dp, c.line, TgShape.control).padding(3.dp)) {
        options.forEachIndexed { i, o ->
            val on = i == selected
            Box(Modifier.weight(1f).fillMaxSize().clip(RoundedCornerShape(7.dp)).background(if (on) c.panel else Color.Transparent)
                .then(if (on) Modifier.border(1.dp, c.line, RoundedCornerShape(7.dp)) else Modifier)
                .clickable { onSelect(i) }, contentAlignment = Alignment.Center) {
                Text(o, style = Tg.type.label, color = if (on) c.ink else c.ink2)
            }
        }
    }
}

// ---------------------------------------------------------------------- lock
@Composable
fun LockScreen(state: AppState, biometric: (() -> Unit)?) {
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val submit = {
        busy = true
        scope.launch {
            try {
                state.api.unlock(code)
                state.onUnlocked()
            } catch (e: Exception) {
                error = e.explain("unlocking"); code = ""
            } finally { busy = false }
        }
    }
    FramePage {
        H1("TG Drive is locked")
        P("Enter your passcode to continue.")
        Spacer(Modifier.height(18.dp))
        TgTextField(code, { code = it; error = null }, label = "Passcode", password = true, keyboardType = KeyboardType.Password,
            onDone = { if (code.isNotEmpty()) submit() }, error = error)
        Spacer(Modifier.height(16.dp))
        TgButton("Unlock", { submit() }, Modifier.fillMaxWidth(), kind = ButtonKind.Primary, icon = TgIcons.lock, busy = busy,
            enabled = code.isNotEmpty())
        if (biometric != null) {
            Spacer(Modifier.height(10.dp))
            TgButton("Use fingerprint or face", biometric, Modifier.fillMaxWidth(), icon = TgIcons.shield)
        }
    }
}

