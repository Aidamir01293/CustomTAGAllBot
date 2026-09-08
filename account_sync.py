"""Синхронизация состава группы через пользовательский аккаунт (Telethon)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatAdminRequiredError
from telethon.tl.types import Channel, Chat, User

from storage import DATA_DIR, SESSION_PATH, chat_bucket, load_db, save_db, upsert_member

log = logging.getLogger("tagall.sync")

API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
PHONE = os.getenv("PHONE", "").strip()

_client: TelegramClient | None = None
_lock = asyncio.Lock()


def credentials_ok() -> bool:
    return bool(API_ID and API_HASH)


def session_exists() -> bool:
    return SESSION_PATH.with_suffix(".session").exists()


def bot_api_chat_id(entity) -> int:
    if isinstance(entity, Channel):
        return int(f"-100{entity.id}")
    if isinstance(entity, Chat):
        return -entity.id
    return int(entity.id)


async def get_client() -> TelegramClient:
    global _client
    if not credentials_ok():
        raise RuntimeError("В .env нет API_ID / API_HASH")
    if _client is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _client = TelegramClient(str(SESSION_PATH), API_ID, API_HASH)
    if not _client.is_connected():
        await _client.connect()
    if not await _client.is_user_authorized():
        raise RuntimeError("Аккаунт не авторизован. Сначала запусти: python login.py")
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.disconnect()
        _client = None


async def snapshot_chat(chat_ref: int | str) -> dict[str, Any]:
    """Подтянуть участников одной группы. Возвращает статистику."""
    async with _lock:
        client = await get_client()
        if isinstance(chat_ref, str) and chat_ref.lstrip("-").isdigit():
            chat_ref = int(chat_ref)
        entity = await client.get_entity(chat_ref)
        if not isinstance(entity, (Channel, Chat)):
            raise RuntimeError("Это не группа")

        chat_id = bot_api_chat_id(entity)
        db = load_db()
        bucket = chat_bucket(db, chat_id)
        added = 0
        seen = 0
        try:
            async for user in client.iter_participants(entity):
                if not isinstance(user, User) or user.bot:
                    continue
                seen += 1
                if upsert_member(bucket, user):
                    added += 1
        except ChatAdminRequiredError as exc:
            raise RuntimeError(
                "Telegram не отдал полный список. Сделай аккаунт админом этой группы."
            ) from exc
        except FloodWaitError as exc:
            raise RuntimeError(f"Flood wait {exc.seconds} сек. Подожди и повтори.") from exc

        bucket["last_sync"] = int(time.time())
        save_db(db)
        log.info("sync chat=%s seen=%s added=%s total=%s", chat_id, seen, added, len(bucket["members"]))
        return {
            "chat_id": chat_id,
            "seen": seen,
            "added": added,
            "total": len(bucket["members"]),
        }


async def snapshot_known_chats() -> list[dict[str, Any]]:
    db = load_db()
    results = []
    for key in list(db.keys()):
        if not key.lstrip("-").isdigit():
            continue
        try:
            results.append(await snapshot_chat(int(key)))
        except Exception as exc:
            log.warning("не синкнул %s: %s", key, exc)
            results.append({"chat_id": int(key), "error": str(exc)})
    return results
