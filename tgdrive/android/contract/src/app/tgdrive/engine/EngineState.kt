package app.tgdrive.engine

/** What Api.kt reads of the engine's state (the Android class also tracks its process). */
data class EngineState(val port: Int = 0, val mediaPort: Int = 0, val token: String = "", val mediaToken: String = "")
