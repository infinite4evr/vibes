package android.util

/** android.util.Log.w as the shared files use it, on the JVM. */
object Log {
    fun w(tag: String, msg: String, tr: Throwable? = null): Int {
        System.err.println("W/$tag: $msg" + (tr?.let { ": $it" } ?: ""))
        return 0
    }
}
