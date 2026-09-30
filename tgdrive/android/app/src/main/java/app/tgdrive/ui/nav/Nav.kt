package app.tgdrive.ui.nav

import androidx.compose.runtime.Stable
import androidx.compose.runtime.mutableStateListOf
import app.tgdrive.data.FileItem
import app.tgdrive.data.FileRef

/** What a file list shows (the desktop's views: #drive, #all, #starred, #chat/… ). */
sealed interface View {
    data class Drive(val folderId: String? = null) : View
    data object All : View
    data object Starred : View
    data object Recent : View
    data object Continue : View
    data class Chat(val chatId: Long, val topicId: Long? = null) : View
    data class TgFolder(val filterId: Int) : View
    data class Saved(val savedId: String) : View
    data class TagView(val tag: String) : View
    data class SubjectView(val subject: String) : View
    data class Album(val chatId: Long, val groupedId: Long) : View
    data class Search(val q: String, val scope: SearchScope? = null) : View
}

/** Search limited to where you were (a folder, chat or Telegram folder). */
data class SearchScope(val label: String, val params: Map<String, String>)

sealed interface Screen {
    data class Browse(val view: View) : Screen
    data class Viewer(val files: List<FileItem>, val index: Int) : Screen
    data class Details(val ref: FileRef) : Screen
    data class ChatContext(val ref: FileRef, val title: String) : Screen
    data class SearchInput(val q: String = "", val scope: SearchScope? = null) : Screen
    data object Transfers : Screen
    data object Photos : Screen
    data object Storage : Screen
    data object Duplicates : Screen
    data object Index : Screen
    data object Activity : Screen
    data class Settings(val section: String? = null) : Screen
    data object Accounts : Screen
    data class SignIn(val adding: Boolean) : Screen
    data object ApiKey : Screen
}

class Entry(val id: Long, val screen: Screen) {
    /** State holders of this entry (its list model, scroll position …), kept while it is on the stack. */
    val store = HashMap<String, Any>()

    @Suppress("UNCHECKED_CAST")
    fun <T : Any> keep(key: String, create: () -> T): T = store.getOrPut(key, create) as T
}

/** A simple back stack: the main area shows the top entry; Back pops it. */
@Stable
class Navigator(root: Screen) {
    private var nextId = 1L
    val stack = mutableStateListOf(Entry(0, root))
    val top: Entry get() = stack.last()

    fun push(s: Screen) {
        if (top.screen == s) return
        stack.add(Entry(nextId++, s))
    }

    /** Go to a place in the sidebar: replaces what's on the stack above the root. */
    fun navigate(s: Screen) {
        while (stack.size > 1) stack.removeAt(stack.lastIndex)
        if (stack[0].screen == s) return
        stack[0] = Entry(nextId++, s)
    }

    fun replace(s: Screen) {
        stack[stack.lastIndex] = Entry(nextId++, s)
    }

    fun pop(): Boolean {
        if (stack.size <= 1) return false
        stack.removeAt(stack.lastIndex)
        return true
    }

    val canPop: Boolean get() = stack.size > 1
}
