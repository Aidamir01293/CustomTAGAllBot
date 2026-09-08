"""TagAll — пинг группы. Состав подтягивается аккаунтом через /sync."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatMemberUpdated, Message
from dotenv import load_dotenv

load_dotenv()

from account_sync import (
    close_client,
    credentials_ok,
    session_exists,
    snapshot_chat,
    snapshot_known_chats,
)
from storage import chat_bucket, load_db, save_db, upsert_member

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ONLY = os.getenv("ADMIN_ONLY", "false").lower() in {"1", "true", "yes"}
MENTIONS_PER_MESSAGE = max(5, int(os.getenv("MENTIONS_PER_MESSAGE", "40")))
SNOOZE_SECONDS = max(60, int(os.getenv("SNOOZE_SECONDS", "3600")))
SYNC_EVERY_MINUTES = max(0, int(os.getenv("SYNC_EVERY_MINUTES", "180")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tagall")
router = Router()
DB: dict[str, Any] = load_db()


def persist() -> None:
    save_db(DB)


def bucket(chat_id: int) -> dict[str, Any]:
    return chat_bucket(DB, chat_id)


def remember_user(chat_id: int, user) -> None:
    if user is None or getattr(user, "is_bot", False):
        return
    b = bucket(chat_id)
    uid = str(user.id)
    rec = {
        "id": user.id,
        "first_name": user.first_name or "Участник",
        "last_name": user.last_name or "",
        "username": user.username or "",
    }
    if b["members"].get(uid) != rec:
        b["members"][uid] = rec
        persist()


def forget_user(chat_id: int, user_id: int) -> None:
    b = bucket(chat_id)
    b["members"].pop(str(user_id), None)
    b["snooze"].pop(str(user_id), None)
    persist()


def set_snooze(chat_id: int, user_id: int, seconds: int) -> float:
    until = time.time() + seconds
    bucket(chat_id)["snooze"][str(user_id)] = until
    persist()
    return until


def clear_snooze(chat_id: int, user_id: int) -> None:
    if str(user_id) in bucket(chat_id)["snooze"]:
        bucket(chat_id)["snooze"].pop(str(user_id), None)
        persist()


def mentionable(chat_id: int) -> list[dict[str, Any]]:
    b = bucket(chat_id)
    now = time.time()
    stale = [uid for uid, until in b["snooze"].items() if float(until) <= now]
    for uid in stale:
        b["snooze"].pop(uid, None)
    if stale:
        persist()
    result = [
        item
        for item in b["members"].values()
        if not (b["snooze"].get(str(item["id"])) and float(b["snooze"][str(item["id"])]) > now)
    ]
    result.sort(key=lambda x: (x.get("first_name") or "").lower())
    return result


def html_mention(member: dict[str, Any]) -> str:
    name = (member.get("first_name") or "Участник").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={member["id"]}">{name}</a>'


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def is_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


def parse_duration(raw: str | None, default: int) -> int:
    if not raw:
        return default
    text = raw.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)([smhdсмчд]?)", text)
    if not match:
        return default
    value = int(match.group(1))
    unit = match.group(2)
    if unit in {"s", "с"}:
        return max(30, value)
    if unit in {"m", "м", ""}:
        return max(60, value * 60)
    if unit in {"h", "ч"}:
        return max(60, value * 3600)
    if unit in {"d", "д"}:
        return max(60, min(value * 86400, 7 * 86400))
    return default


def fmt_left(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h} ч {m} мин"
    if m:
        return f"{m} мин"
    return f"{seconds} сек"


def fmt_ago(ts: int) -> str:
    if not ts:
        return "ещё не было"
    delta = int(time.time()) - int(ts)
    if delta < 60:
        return "только что"
    if delta < 3600:
        return f"{delta // 60} мин назад"
    if delta < 86400:
        return f"{delta // 3600} ч назад"
    return f"{delta // 86400} дн назад"


async def is_admin(message: Message) -> bool:
    member = await message.chat.get_member(message.from_user.id)
    return member.status in {"creator", "administrator"}


async def remember_admins(message: Message) -> None:
    try:
        admins = await message.chat.get_administrators()
    except Exception:
        return
    changed = False
    b = bucket(message.chat.id)
    for member in admins:
        user = member.user
        if user.is_bot:
            continue
        rec = {
            "id": user.id,
            "first_name": user.first_name or "Участник",
            "last_name": user.last_name or "",
            "username": user.username or "",
        }
        if b["members"].get(str(user.id)) != rec:
            b["members"][str(user.id)] = rec
            changed = True
    if changed:
        persist()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            "Добавь меня в группу, выключи Privacy в @BotFather "
            "(/setprivacy → Disable) и пиши в группе /all.\n\n"
            "/out — не пинговать час."
        )
        return
    remember_user(message.chat.id, message.from_user)
    await remember_admins(message)
    await message.answer("Готов. /all — сбор, /out — час тишины.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Команды</b>\n"
        "/all [текст] — пинг\n"
        "/out — не пинговать 1 час\n"
        "/stats — сколько человек в базе",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("in"))
async def cmd_in(message: Message) -> None:
    if not is_group(message):
        await message.answer("Только в группе.")
        return
    remember_user(message.chat.id, message.from_user)
    clear_snooze(message.chat.id, message.from_user.id)
    await message.reply("Снова в списке пинга.")


@router.message(Command("out"))
async def cmd_out(message: Message, command: CommandObject) -> None:
    if not is_group(message):
        await message.answer("Только в группе.")
        return
    remember_user(message.chat.id, message.from_user)
    seconds = parse_duration(command.args, SNOOZE_SECONDS)
    until = set_snooze(message.chat.id, message.from_user.id, seconds)
    await message.reply(
        f"Не буду пинговать {fmt_left(until - time.time())}. Раньше — /in"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not is_group(message):
        await message.answer("Статистика — в группе.")
        return
    remember_user(message.chat.id, message.from_user)
    b = bucket(message.chat.id)
    now = time.time()
    snoozed = sum(1 for until in b["snooze"].values() if float(until) > now)
    pingable = len(mentionable(message.chat.id))
    try:
        total = await message.bot.get_chat_member_count(message.chat.id)
        extra = f"\nВсего в группе: {total}"
    except Exception:
        extra = ""
    text = (
        f"В базе: {len(b['members'])}\n"
        f"Сейчас пингуются: {pingable}\n"
        f"На паузе: {snoozed}{extra}"
    )
    await message.answer(text)


@router.message(Command("sync"))
async def cmd_sync(message: Message) -> None:
    if not is_group(message):
        await message.answer("Напиши /sync в той группе, которую надо обновить.")
        return
    if not await is_admin(message):
        await message.reply("Синк только для админов.")
        return
    if not credentials_ok():
        await message.reply(
            "Нет API_ID / API_HASH в .env.\n"
            "Возьми их на my.telegram.org и запусти python login.py"
        )
        return
    if not session_exists():
        await message.reply("Аккаунт ещё не вошёл. На сервере: python login.py")
        return

    wait = await message.reply("Тяну состав группы через аккаунт...")
    try:
        stats = await snapshot_chat(message.chat.id)
        global DB
        DB = load_db()
        await wait.edit_text(
            f"Синк готов.\n"
            f"Увидел: {stats['seen']}\n"
            f"Новых: {stats['added']}\n"
            f"В базе: {stats['total']}"
        )
    except Exception as exc:
        await wait.edit_text(f"Не вышло: {exc}")


@router.message(Command("all", "everyone", "пинг", "все"))
async def cmd_all(message: Message, command: CommandObject) -> None:
    if not is_group(message):
        await message.answer("Пинг только в группах.")
        return
    remember_user(message.chat.id, message.from_user)
    await remember_admins(message)
    if ADMIN_ONLY and not await is_admin(message):
        await message.reply("Пинговать всех могут только админы.")
        return

    people = [p for p in mentionable(message.chat.id) if p["id"] != message.from_user.id]
    if not people:
        await message.reply(
            "Пока некого пинговать — бот ещё никого не видел.\n"
            "Пусть люди напишут в чат что угодно. "
            "Кто пишет после этого — попадёт в /all."
        )
        return

    header = (command.args or "Сбор!").strip()
    batches = list(chunks(people, MENTIONS_PER_MESSAGE))
    for i, batch in enumerate(batches, start=1):
        mentions = " ".join(html_mention(p) for p in batch)
        suffix = f"\n\n{i}/{len(batches)}" if len(batches) > 1 else ""
        await message.answer(f"{header}\n\n{mentions}{suffix}", parse_mode=ParseMode.HTML)
        if i < len(batches):
            await asyncio.sleep(0.4)


@router.message(F.new_chat_members)
async def on_join(message: Message) -> None:
    if is_group(message):
        for user in message.new_chat_members:
            remember_user(message.chat.id, user)


@router.message(F.left_chat_member)
async def on_left(message: Message) -> None:
    if is_group(message) and message.left_chat_member:
        forget_user(message.chat.id, message.left_chat_member.id)


@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated) -> None:
    user = event.new_chat_member.user
    if user.is_bot:
        return
    if event.new_chat_member.status in {"member", "administrator", "creator", "restricted"}:
        remember_user(event.chat.id, user)
    elif event.new_chat_member.status in {"left", "kicked"}:
        forget_user(event.chat.id, user.id)


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def collect_writers(message: Message) -> None:
    remember_user(message.chat.id, message.from_user)


async def auto_sync_loop() -> None:
    if SYNC_EVERY_MINUTES <= 0:
        return
    if not credentials_ok() or not session_exists():
        log.info("автосинк выключен: нет ключей или сессии")
        return
    log.info("автосинк каждые %s мин", SYNC_EVERY_MINUTES)
    while True:
        await asyncio.sleep(SYNC_EVERY_MINUTES * 60)
        try:
            results = await snapshot_known_chats()
            global DB
            DB = load_db()
            log.info("автосинк: %s", results)
        except Exception as exc:
            log.warning("автосинк упал: %s", exc)


async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN.startswith("123456789"):
        raise SystemExit("Укажи BOT_TOKEN в .env")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    me = await bot.get_me()
    log.info("бот @%s", me.username)

    loop = asyncio.get_event_loop()
    loop.create_task(auto_sync_loop())
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "chat_member", "my_chat_member"],
        )
    finally:
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())
