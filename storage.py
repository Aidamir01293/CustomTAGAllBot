from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "members.json"
SESSION_PATH = DATA_DIR / "user"


def empty_chat() -> dict[str, Any]:
    return {"members": {}, "snooze": {}, "last_sync": 0}


def load_db() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {}
    try:
        raw = json.loads(DB_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    for bucket in raw.values():
        if not isinstance(bucket, dict):
            continue
        bucket.setdefault("members", {})
        bucket.setdefault("snooze", {})
        bucket.setdefault("last_sync", 0)
        if "opt_out" in bucket:
            forever = time.time() + 10 * 365 * 24 * 3600
            for uid in bucket.pop("opt_out") or []:
                bucket["snooze"][str(uid)] = forever
    return raw


def save_db(db: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DB_PATH)


def chat_bucket(db: dict[str, Any], chat_id: int) -> dict[str, Any]:
    key = str(chat_id)
    if key not in db:
        db[key] = empty_chat()
    bucket = db[key]
    bucket.setdefault("members", {})
    bucket.setdefault("snooze", {})
    bucket.setdefault("last_sync", 0)
    return bucket


def upsert_member(bucket: dict[str, Any], user) -> bool:
    if user is None or getattr(user, "is_bot", False):
        return False
    uid = str(user.id)
    is_new = uid not in bucket["members"]
    bucket["members"][uid] = {
        "id": user.id,
        "first_name": getattr(user, "first_name", None) or "Участник",
        "last_name": getattr(user, "last_name", None) or "",
        "username": getattr(user, "username", None) or "",
    }
    return is_new
