package app.tgdrive.diag

/** The app's log as the shared files use it, on the JVM: problems to stderr. */
object AppLog {
    @Volatile var verbose = false
    fun d(tag: String, msg: String) { if (verbose) System.err.println("D/$tag: $msg") }
    fun i(tag: String, msg: String) = System.err.println("I/$tag: $msg")
    fun w(tag: String, msg: String, t: Throwable? = null) = System.err.println("W/$tag: $msg" + (t?.let { ": $it" } ?: ""))
    fun e(tag: String, msg: String, t: Throwable? = null) = System.err.println("E/$tag: $msg" + (t?.let { ": $it" } ?: ""))
}
