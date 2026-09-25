"""t.me links for messages and chats."""
from typing import Optional

CHANNEL_OFFSET = 1_000_000_000_000


def message_link(chat_id: int, chat_kind: Optional[str], username: Optional[str], msg_id: int) -> Optional[str]:
    """Public link when the chat has a username, private /c/ link for channels and supergroups.

    Private chats and basic groups have no message links in Telegram.
    """
    if chat_kind in ("channel", "supergroup"):
        if username:
            return f"https://t.me/{username}/{msg_id}"
        if chat_id <= -CHANNEL_OFFSET:
            return f"https://t.me/c/{-chat_id - CHANNEL_OFFSET}/{msg_id}"
    return None


def chat_link(chat_kind: Optional[str], username: Optional[str]) -> Optional[str]:
    return f"https://t.me/{username}" if username else None
