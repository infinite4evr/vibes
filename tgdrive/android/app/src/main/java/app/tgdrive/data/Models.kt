@file:UseSerializers(FlexBoolean::class)

package app.tgdrive.data

import app.tgdrive.util.Format
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.UseSerializers
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

// The shapes of TG Drive's HTTP API (tgdrive/tgdrive/api.py). Unknown fields are ignored, so the
// app keeps working when the service grows.

/**
 * Yes/no fields as the service sends them: true/false, and also 1/0 or "1"/"0" where a value comes
 * straight from its database (SQLite has no booleans). Used for every Boolean in this file.
 */
object FlexBoolean : KSerializer<Boolean> {
    override val descriptor = PrimitiveSerialDescriptor("app.tgdrive.FlexBoolean", PrimitiveKind.BOOLEAN)
    override fun serialize(encoder: Encoder, value: Boolean) = encoder.encodeBoolean(value)
    override fun deserialize(decoder: Decoder): Boolean {
        val json = decoder as? JsonDecoder ?: return decoder.decodeBoolean()
        val el = json.decodeJsonElement()
        if (el is JsonNull || el !is JsonPrimitive) return false
        return when (el.content.lowercase()) {
            "true", "1" -> true
            "false", "0", "" -> false
            else -> el.content.toDoubleOrNull()?.let { it != 0.0 } ?: false
        }
    }
}

@Serializable
data class Account(
    val id: Long,
    val name: String? = null,
    val username: String? = null,
    val phone: String? = null,
    val premium: Boolean = false,
    val status: String = "",
    val error: String? = null,
)

@Serializable
data class AppStatus(
    val version: String = "",
    @SerialName("api_configured") val apiConfigured: Boolean = false,
    val locked: Boolean = false,
    @SerialName("lock_set") val lockSet: Boolean = false,
    @SerialName("media_token") val mediaToken: String = "",
    val accounts: List<Account> = emptyList(),
    val settings: JsonObject = JsonObject(emptyMap()),
    @SerialName("data_dir") val dataDir: String? = null,
    @SerialName("download_dir") val downloadDir: String? = null,
    @SerialName("env_api") val envApi: Boolean = false,
)

@Serializable
data class FileItem(
    val id: Long? = null,
    @SerialName("chat_id") val chatId: Long,
    @SerialName("msg_id") val msgId: Long,
    val kind: String = "document",
    val name: String = "",
    @SerialName("original_name") val originalName: String? = null,
    val renamed: Boolean = false,
    val ext: String? = null,
    val mime: String? = null,
    val size: Long = 0,
    val date: Long? = null,
    val caption: String = "",
    @SerialName("chat_title") val chatTitle: String? = null,
    @SerialName("chat_kind") val chatKind: String? = null,
    @SerialName("sender_name") val senderName: String? = null,
    @SerialName("fwd_from") val fwdFrom: String? = null,
    @SerialName("is_forward") val isForward: Boolean = false,
    @SerialName("is_out") val isOut: Boolean = false,
    val width: Int? = null,
    val height: Int? = null,
    val duration: Double? = null,
    val performer: String? = null,
    @SerialName("audio_title") val audioTitle: String? = null,
    @SerialName("has_thumb") val hasThumb: Boolean = false,
    val inline: String? = null,
    @SerialName("folder_id") val folderId: String? = null,
    val starred: Boolean = false,
    val tags: List<String> = emptyList(),
    val note: JsonElement? = null,
    @SerialName("grouped_id") val groupedId: Long? = null,
    @SerialName("topic_id") val topicId: Long? = null,
    val match: String? = null,
    val subject: String? = null,
    @SerialName("play_pos") val playPos: Double = 0.0,
    @SerialName("play_dur") val playDur: Double? = null,
    val watched: Boolean = false,
    val copies: Int = 0,
    val link: String? = null,
) {
    val key: String get() = "$chatId:$msgId"
    val ref: FileRef get() = FileRef(chatId, msgId)
    val displayName: String get() = Format.friendlyName(name, kind, renamed) ?: name.ifEmpty { Format.KIND_NAME[kind] ?: "File" }
    val streamable: Boolean get() = kind in Format.STREAMABLE
    val isPdf: Boolean get() = ext.equals("pdf", true) || mime == "application/pdf"
    val isImage: Boolean get() = kind == "photo" || (mime?.startsWith("image/") == true && ext?.lowercase() in setOf("jpg", "jpeg", "png", "webp", "gif", "bmp", "heic"))
    val isText: Boolean get() = ext?.lowercase() in Format.TEXT_EXT || mime?.startsWith("text/") == true
    val progress: Float? get() = if (playPos > 0 && (playDur ?: duration ?: 0.0) > 0) (playPos / (playDur ?: duration!!)).toFloat().coerceIn(0f, 1f) else null
}

@Serializable
data class FileRef(val chatId: Long, val msgId: Long) {
    fun pair(): List<Long> = listOf(chatId, msgId)
}

@Serializable
data class FilePage(
    val items: List<FileItem> = emptyList(),
    val next: String? = null,
    @SerialName("took_ms") val tookMs: Long? = null,
    val sort: String? = null,
    val words: List<String> = emptyList(),
    val corrected: String? = null,
)

@Serializable
data class FileStats(
    val total: Long = 0,
    @SerialName("total_bytes") val totalBytes: Long = 0,
    @SerialName("kind_counts") val kindCounts: Map<String, Long> = emptyMap(),
    val tiers: Map<String, Long> = emptyMap(),
)

@Serializable
data class PathPart(val id: String, val name: String)

@Serializable
data class CopyRef(
    @SerialName("chat_id") val chatId: Long,
    @SerialName("msg_id") val msgId: Long,
    val name: String? = null,
    @SerialName("chat_title") val chatTitle: String? = null,
    @SerialName("chat_kind") val chatKind: String? = null,
    val date: Long? = null,
    val size: Long = 0,
    @SerialName("this") val isThis: Boolean = false,
    @SerialName("folder_id") val folderId: String? = null,
    val starred: Boolean = false,
)

/** The extra fields of GET /files/{cid}/{mid} (the same JSON also decodes as a [FileItem]). */
@Serializable
data class FileExtras(
    @SerialName("folder_path") val folderPath: List<PathPart> = emptyList(),
    @SerialName("in_drive_channel") val inDriveChannel: Boolean = false,
    @SerialName("can_copy") val canCopy: Boolean = false,
    @SerialName("can_forward") val canForward: Boolean = false,
    @SerialName("can_delete") val canDelete: Boolean = false,
    @SerialName("tg_link") val tgLink: String? = null,
    val album: Int = 0,
    @SerialName("copy_list") val copyList: List<CopyRef> = emptyList(),
    val duplicates: Int = 0,
    @SerialName("local_path") val localPath: String? = null,
    val topic: String? = null,
    val note: String? = null,
)

data class FileDetail(val file: FileItem, val extras: FileExtras)

@Serializable
data class Folder(
    val id: String,
    @SerialName("parent_id") val parentId: String? = null,
    val name: String = "",
    val created: Long? = null,
    val color: String? = null,
    val description: String? = null,
    val emoji: String? = null,
    val cover: String? = null,
    val rules: JsonElement? = null,
    val kind: String? = null,
    @SerialName("file_count") val fileCount: Long = 0,
    val bytes: Long = 0,
) {
    val smart: Boolean get() = kind == "smart"
    val auto: Boolean get() = kind == "auto"
}

@Serializable
data class DriveInfo(
    @SerialName("channel_id") val channelId: Long? = null,
    val loaded: Boolean = false,
    @SerialName("pending_save") val pendingSave: Boolean = false,
    val error: String? = null,
    @SerialName("last_saved") val lastSaved: Long? = null,
    val undo: List<String> = emptyList(),
)

@Serializable
data class SavedSearch(
    val id: String,
    val name: String = "",
    val q: String = "",
    val params: JsonObject = JsonObject(emptyMap()),
    val icon: String? = null,
)

@Serializable
data class FoldersResponse(
    val folders: List<Folder> = emptyList(),
    val drive: DriveInfo = DriveInfo(),
    @SerialName("drive_title") val driveTitle: String = "TG Drive",
    val saved: List<SavedSearch> = emptyList(),
    val starred: Long = 0,
    val recent: Long = 0,
    @SerialName("continue") val continueWatching: Long = 0,
)

@Serializable
data class Chat(
    val id: Long,
    val title: String? = null,
    val kind: String = "channel",
    val username: String? = null,
    @SerialName("is_creator") val isCreator: Int = 0,
    @SerialName("is_admin") val isAdmin: Int = 0,
    val noforwards: Int = 0,
    val excluded: Int = 0,
    val pinned: Int = 0,
    val archived: Int = 0,
    @SerialName("is_forum") val isForum: Int = 0,
    @SerialName("index_state") val indexState: String? = null,
    @SerialName("index_error") val indexError: String? = null,
    @SerialName("file_count") val fileCount: Long = 0,
    @SerialName("total_bytes") val totalBytes: Long = 0,
    @SerialName("last_indexed") val lastIndexed: Long? = null,
    val members: Int? = null,
) {
    val group: String get() = when (kind) {
        "supergroup", "group" -> "group"
        else -> kind
    }
}

@Serializable
data class DialogFilter(val id: Int, val title: String = "", val emoticon: String? = null,
                        @SerialName("chat_ids") val chatIds: List<Long> = emptyList())

@Serializable
data class Topic(@SerialName("topic_id") val topicId: Long, val title: String? = null, val n: Long = 0)

@Serializable
data class Tag(val tag: String, val n: Long = 0)

@Serializable
data class Subject(val id: String, val name: String = "", val emoji: String? = null, val n: Long = 0)

@Serializable
data class IndexStatus(
    val phase: String = "",
    val current: String? = null,
    @SerialName("chats_total") val chatsTotal: Int = 0,
    @SerialName("chats_done") val chatsDone: Int = 0,
    @SerialName("chats_error") val chatsError: Int = 0,
    @SerialName("chats_pending") val chatsPending: Int = 0,
    val files: Long = 0,
    val bytes: Long = 0,
    @SerialName("files_per_min") val filesPerMin: Long = 0,
    @SerialName("last_sync") val lastSync: Long? = null,
    val error: String? = null,
)

@Serializable
data class TransferSummary(val active: Int = 0, val size: Long = 0, val done: Long = 0, val speed: Long = 0)

@Serializable
data class AccountStatus(
    val account: Account? = null,
    val index: IndexStatus = IndexStatus(),
    val drive: DriveInfo = DriveInfo(),
    val transfers: TransferSummary = TransferSummary(),
    val search: JsonObject = JsonObject(emptyMap()),
    val semantic: JsonObject = JsonObject(emptyMap()),
    val dupes: JsonObject = JsonObject(emptyMap()),
    @SerialName("thumbs_backoff") val thumbsBackoff: Int = 0,
    val locked: Boolean = false,
)

@Serializable
data class Transfer(
    val id: Long,
    val direction: String = "down",
    @SerialName("chat_id") val chatId: Long? = null,
    @SerialName("msg_id") val msgId: Long? = null,
    val name: String = "",
    val size: Long = 0,
    val done: Long = 0,
    val path: String? = null,
    @SerialName("folder_id") val folderId: String? = null,
    val status: String = "queued",
    val error: String? = null,
    val created: Long? = null,
    val updated: Long? = null,
    val batch: String? = null,
    val speed: Long = 0,
) {
    val up: Boolean get() = direction == "up"
    val fraction: Float get() = if (size > 0) (done.toFloat() / size).coerceIn(0f, 1f) else 0f
    val active: Boolean get() = status in setOf("queued", "running", "paused")
}

@Serializable
data class TransfersResponse(val transfers: List<Transfer> = emptyList(), val summary: TransferSummary = TransferSummary())

@Serializable
data class Suggestions(
    val chats: List<SuggestChat> = emptyList(),
    val folders: List<SuggestFolder> = emptyList(),
    val files: List<SuggestFile> = emptyList(),
    val history: List<HistoryQuery> = emptyList(),
    val saved: List<SavedSearch> = emptyList(),
    val operators: List<SuggestOperator> = emptyList(),
    @SerialName("did_you_mean") val didYouMean: String? = null,
)

@Serializable
data class SuggestChat(val id: Long, val title: String? = null, val kind: String? = null, @SerialName("file_count") val fileCount: Long = 0)

@Serializable
data class HistoryQuery(val q: String = "")

@Serializable
data class SuggestFolder(val id: String, val name: String = "", @SerialName("parent_id") val parentId: String? = null)

@Serializable
data class SuggestFile(
    @SerialName("chat_id") val chatId: Long, @SerialName("msg_id") val msgId: Long, val name: String = "",
    val kind: String = "document", val ext: String? = null, @SerialName("chat_title") val chatTitle: String? = null,
)

@Serializable
data class SuggestOperator(val op: String = "", val label: String? = null, val insert: String? = null)

@Serializable
data class Activity(val at: Long = 0, val action: String = "", val detail: String = "")

@Serializable
data class ContextMessage(
    val id: Long,
    val date: Long? = null,
    val text: String = "",
    val out: Boolean = false,
    val sender: String = "",
    @SerialName("reply_to") val replyTo: Long? = null,
    val fwd: String? = null,
    val media: String? = null,
    val file: FileItem? = null,
    val target: Boolean = false,
)

@Serializable
data class ChatContext(
    val chat: JsonObject = JsonObject(emptyMap()),
    val messages: List<ContextMessage> = emptyList(),
    @SerialName("has_older") val hasOlder: Boolean = false,
    @SerialName("has_newer") val hasNewer: Boolean = false,
)

@Serializable
data class Month(val ym: String, val n: Long = 0)

@Serializable
data class Timeline(val months: List<Month> = emptyList(), val total: Long = 0)

@Serializable
data class Cover(@SerialName("chat_id") val chatId: Long, @SerialName("msg_id") val msgId: Long, val kind: String = "",
                 @SerialName("has_thumb") val hasThumb: Boolean = false, val inline: String? = null)

@Serializable
data class LoginStart(@SerialName("login_id") val loginId: String = "", @SerialName("sent_via") val sentVia: String? = null)

@Serializable
data class LoginStep(
    @SerialName("need_password") val needPassword: Boolean = false,
    val hint: String? = null,
    val account: JsonObject? = null,
)

@Serializable
data class QrLogin(
    @SerialName("login_id") val loginId: String = "",
    val state: String = "waiting",
    val error: String? = null,
    val hint: String? = null,
    val svg: String? = null,
    val url: String? = null,
    val expires: Long? = null,
    val account: JsonObject? = null,
)

@Serializable
data class Backup(val id: Long, val at: Long? = null, val reason: String? = null, val bytes: Long? = null)

@Serializable
data class ServerEvent(val id: Long, val at: Long = 0, val kind: String = "", val title: String? = null, val body: String? = null,
                       val path: String? = null, val account: Long? = null, val online: Boolean? = null)

/** Duplicates (Tools → Duplicates): groups of copies of one file. */
@Serializable
data class DupGroup(val n: Long = 0, val size: Long = 0, val waste: Long = 0, val files: List<FileItem> = emptyList())

@Serializable
data class DuplicatesPage(val groups: List<DupGroup> = emptyList(), val offset: Int = 0, val more: Boolean = false)
