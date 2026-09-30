package app.tgdrive

/** The passcode the passcode journey sets (and removes again). */
const val JOURNEY_PASSCODE = "2468"

/**
 * A passcode left behind by a run that died in the middle of the passcode journey would lock every
 * later test out of TG Drive (and make them fail for that reason only). Removes it; true if there was one.
 */
suspend fun removeLeftoverPasscode(g: AppGraph): Boolean = runCatching {
    val st = g.api.status()
    if (!st.lockSet) return@runCatching false
    if (st.locked) g.api.unlock(JOURNEY_PASSCODE)
    g.api.setLock(null, JOURNEY_PASSCODE)
    android.util.Log.w("TestHygiene", "removed a passcode left by an earlier run")
    g.state.bootstrap()   // the app showed its lock screen
    true
}.getOrDefault(false)
