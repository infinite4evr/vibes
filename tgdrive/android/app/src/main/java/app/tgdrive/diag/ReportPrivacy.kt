package app.tgdrive.diag

/** Privacy mode drops free-form log messages instead of guessing which words are names. What stays
 *  is what code wrote, never what a person typed or named: timestamps, severity, log source, exception
 *  types, stack frames (file names reduced to their base name) and service start steps without paths. */
object ReportPrivacy {
    private val frame = Regex("""^\s*at [\w.$<>\-]+\([\w.$\- ]*(?::\d+)?\)\s*$""")
    private val more = Regex("""^\s*\.\.\. \d+ more\s*$""")
    private val exception = Regex("""^(\s*(?:Caused by: |Suppressed: )?)((?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*(?:Exception|Error|Throwable))(?::.*)?$""")
    private val pyFrame = Regex("""^(\s*)File "(?:[^"]*[/\\])?([^"/\\]+)", line (\d+), in ([\w<>.]+)""")
    private val appLine = Regex("""^(\d{4}-\d{2}-\d{2}[T ][\d:.,]+) ([EWID]) ([\w.\-]+) \[[^\]]*\]: """)
    private val serviceLine = Regex("""^(\d{4}-\d{2}-\d{2} [\d:.,]+) ([A-Z]+) ([\w.]+) \[[^\]]*\]: """)
    private val debugLine = Regex("""^(\d{4}-\d{2}-\d{2} [\d:.,]+) ([A-Z]+)\s+\[[^\]]*\] ([\w.]+) """)
    private val startLine = Regex("""^(\d{4}-\d{2}-\d{2}T[\d:.]+Z) \[(\d+)\] (.*)$""")

    fun clean(text: String, includeNames: Boolean): String {
        val scrubbed = text.replace(Regex("(?i)([?&](?:t|token)=|(?:api_hash|proxy_pass|password|token|secret)[=:]\\s*)[^&\\s,}]+"), "$1[removed]")
            .replace(Regex("(?<![a-zA-Z0-9])\\+?\\d{10,15}(?![a-zA-Z0-9])"), "[number]")
        if (includeNames) return scrubbed
        return scrubbed.lineSequence().map(::redact).joinToString("\n")
    }

    private fun redact(line: String): String {
        if (line.isBlank() || frame.matches(line) || more.matches(line) || line.trim() == "Traceback (most recent call last):") return line
        pyFrame.find(line)?.let { m -> return "${m.groupValues[1]}File \"${m.groupValues[2]}\", line ${m.groupValues[3]}, in ${m.groupValues[4]}" }
        exception.matchEntire(line)?.let { m -> return m.groupValues[1] + m.groupValues[2] }
        for (r in listOf(appLine, serviceLine, debugLine))
            r.find(line)?.let { m -> return "${m.groupValues[1]} ${m.groupValues[2]} ${m.groupValues[3]}: [personal text omitted]" }
        startLine.matchEntire(line)?.let { m ->
            val step = m.groupValues[3].replace(Regex("""(?:/[^\s/:"'“”]+){2,}/?"""), "[path]").replace(Regex("""[“"][^”"]*[”"]"""), "[name]")
            return "${m.groupValues[1]} [${m.groupValues[2]}] $step"
        }
        val stamp = Regex("^\\d{4}-\\d{2}-\\d{2}[T ][0-9:.Z+\\-]+").find(line)?.value.orEmpty()
        val severity = Regex("\\b(ERROR|WARN|WARNING|INFO|DEBUG|CRITICAL)\\b").find(line)?.value.orEmpty()
        return "$stamp $severity [personal text omitted]".trim()
    }
}
