package android.util

/** The two members of android.util.Base64 the shared files use, on the JVM. */
object Base64 {
    const val DEFAULT = 0
    fun decode(s: String, flags: Int): ByteArray = java.util.Base64.getMimeDecoder().decode(s)
}
