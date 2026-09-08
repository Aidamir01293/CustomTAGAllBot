"""
Первый вход аккаунта для синка состава.

1. https://my.telegram.org → API development tools → создать приложение
2. Впиши API_ID, API_HASH, PHONE в .env
3. python login.py
4. Введи код из Telegram (и пароль 2FA, если есть)

После этого бот сам дергает /sync и фоновое обновление.
Не используй основной номер.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

from storage import DATA_DIR, SESSION_PATH

API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
PHONE = os.getenv("PHONE", "").strip()


async def main() -> None:
    if not API_ID or not API_HASH:
        raise SystemExit("Сначала заполни API_ID и API_HASH в .env (my.telegram.org)")
    if not PHONE:
        raise SystemExit("Укажи PHONE в .env, например +79991234567")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(SESSION_PATH), API_ID, API_HASH)

    print(f"Вход для {PHONE} ...")
    await client.start(phone=PHONE)
    me = await client.get_me()
    name = " ".join(p for p in [me.first_name, me.last_name] if p)
    print(f"Ок, сессия сохранена: {name} @{me.username or '—'} id={me.id}")
    print(f"Файл: {SESSION_PATH}.session")
    print("Дальше: запусти бота и в группе напиши /sync")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
