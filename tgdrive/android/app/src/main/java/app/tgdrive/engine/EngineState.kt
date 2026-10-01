package app.tgdrive.engine

import android.content.Context
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File

/**
 * What the engine process tells the app: whether TG Drive's service runs, where, and with which
 * secrets. Written by [EngineService] to the app's private storage (only this app can read it)
 * and announced with a package-local broadcast; [EngineClient] reads it.
 */
@Serializable
data class EngineState(
    val phase: Phase = Phase.Stopped,
    val port: Int = 0,
    val mediaPort: Int = 0,
    val token: String = "",
    val mediaToken: String = "",
    val demo: Boolean = false,
    val error: String? = null,
    val pid: Int = 0,
    val startedAt: Long = 0,
    val crypto: String = "",
    val fts5: String = "",
    val numpy: Boolean = true,
    val version: String = "",
    /** What the service is doing while it starts ("Starting Python" …), shown under the spinner. */
    val stage: String = "",
    val updatedAt: Long = 0,
) {
    @Serializable
    enum class Phase { Stopped, Starting, Ready, Failed }

    val ready: Boolean get() = phase == Phase.Ready && port > 0

    companion object {
        private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
        private const val FILE = "engine-state.json"

        fun read(context: Context): EngineState = try {
            json.decodeFromString(serializer(), File(context.filesDir, FILE).readText())
        } catch (_: Exception) {
            EngineState()
        }

        fun write(context: Context, state: EngineState) {
            val dir = context.filesDir
            val tmp = File(dir, "$FILE.tmp")
            tmp.writeText(json.encodeToString(serializer(), state))
            tmp.renameTo(File(dir, FILE))
        }
    }
}
