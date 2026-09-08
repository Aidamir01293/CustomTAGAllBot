"""Разовый синк из терминала. В группе удобнее /sync."""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from account_sync import snapshot_chat, snapshot_known_chats, close_client

CHAT = os.getenv("SYNC_CHAT", "").strip()


async def main() -> None:
    if CHAT:
        stats = await snapshot_chat(CHAT)
        print(stats)
    else:
        print(await snapshot_known_chats())
    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
