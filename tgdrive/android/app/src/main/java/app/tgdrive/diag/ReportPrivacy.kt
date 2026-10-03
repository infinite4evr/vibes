package app.tgdrive.diag

/** Privacy mode drops free-form log messages instead of guessing which words are names.
 * This deliberately retains only timestamps, severity, and source locations. */
object ReportPrivacy {
    fun clean(text: String, includeNames: Boolean): String {
        val scrubbed = text.replace(Regex("(?i)([?&](?:t|token)=|(?:api_hash|proxy_pass|password|token|secret)[=:]\\s*)[^&\\s,}]+"), "$1[removed]")
            .replace(Regex("(?<![a-zA-Z0-9])\\+?\\d{10,15}(?![a-zA-Z0-9])"), "[number]")
        if (includeNames) return scrubbed
        return scrubbed.lineSequence().map { line ->
            when {
                line.trim().startsWith("at app.tgdrive.") -> line.substringBefore(": ")
                line.trim().startsWith("File ") -> "[source location omitted]"
                else -> {
                    val stamp = Regex("^\\d{4}-\\d{2}-\\d{2}[T ][0-9:.Z+\\-]+").find(line)?.value.orEmpty()
                    val severity = Regex("\\b(ERROR|WARN|WARNING|INFO|DEBUG|CRITICAL)\\b").find(line)?.value.orEmpty()
                    "$stamp $severity [personal text omitted]".trim()
                }
            }
        }.joinToString("\n")
    }
}
