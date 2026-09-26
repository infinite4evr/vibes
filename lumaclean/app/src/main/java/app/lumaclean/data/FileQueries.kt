package app.lumaclean.data

import app.lumaclean.core.DAY_MS

/** A saved question over the storage index; each one backs a file list screen. */
sealed interface FileQuery {
    val title: String

    data class Category(val category: FileCategory) : FileQuery {
        override val title get() = category.label
    }

    data class Large(val minBytes: Long) : FileQuery {
        override val title get() = "Large files"
    }

    data class OldDownloads(val days: Int) : FileQuery {
        override val title get() = "Old downloads"
    }

    data class Folder(val path: String, override val title: String) : FileQuery

    data object Screenshots : FileQuery {
        override val title get() = "Screenshots"
    }

    data object LargeVideos : FileQuery {
        override val title get() = "Large videos"
    }

    data class Search(val text: String) : FileQuery {
        override val title get() = "“$text”"
    }
}

enum class FileSort(val label: String) { SIZE("Size"), DATE("Newest"), OLDEST("Oldest"), NAME("Name") }

fun FileIndex.query(q: FileQuery, showHidden: Boolean): List<FileEntry> {
    val now = System.currentTimeMillis()
    val base = if (showHidden) files.asSequence() else files.asSequence().filterNot { it.isHidden }
    val seq = when (q) {
        is FileQuery.Category -> base.filter { it.category == q.category }
        is FileQuery.Large -> base.filter { it.size >= q.minBytes }
        is FileQuery.OldDownloads -> {
            val prefix = "$root/Download/"
            base.filter { it.path.startsWith(prefix) && now - it.modified > q.days * DAY_MS }
        }
        // chat apps keep media in hidden folders (.Statuses), so folder queries always include them
        is FileQuery.Folder -> files.asSequence().filter { it.path.startsWith(q.path + "/") && !it.name.startsWith(".nomedia") }
        FileQuery.Screenshots -> base.filter {
            it.category == FileCategory.IMAGES && it.path.contains("/screenshots/", ignoreCase = true)
        }
        FileQuery.LargeVideos -> base.filter { it.category == FileCategory.VIDEOS && it.size >= 20_000_000 }
        is FileQuery.Search -> {
            val needle = q.text.trim()
            if (needle.isEmpty()) emptySequence() else base.filter { it.name.contains(needle, ignoreCase = true) }
        }
    }
    return seq.toList()
}

fun List<FileEntry>.applySort(sort: FileSort): List<FileEntry> = when (sort) {
    FileSort.SIZE -> sortedByDescending { it.size }
    FileSort.DATE -> sortedByDescending { it.modified }
    FileSort.OLDEST -> sortedBy { it.modified }
    FileSort.NAME -> sortedBy { it.name.lowercase() }
}
