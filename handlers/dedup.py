"""
Message deduplication system.
Prevents duplicate processing of updates and user messages.
"""

import asyncio
import time as _time
from collections import OrderedDict


# ═══ Update-level dedup ═══
_processed_updates = OrderedDict()
_MAX_PROCESSED = 1000
_DEDUP_TTL = 300  # 5 minutes TTL for update IDs

# ═══ Per-user message dedup ═══
_user_last_message = {}  # {user_id: (text_hash, timestamp)}
_USER_DEDUP_SECONDS = 3

# ═══ Memory response dedup ═══
_user_last_memory_response = {}  # {user_id: timestamp}
_MEMORY_RESPONSE_COOLDOWN = 10  # seconds

# Lock for thread-safe dedup operations (prevents race conditions)
_dedup_lock = asyncio.Lock()


async def _is_duplicate_update(update_id: int) -> bool:
    """فحص هل التحديث ده اتعمل عليه رد قبل كده (منع التكرار) — ASYNC SAFE"""
    async with _dedup_lock:
        now = _time.time()

        expired = [uid for uid, ts in _processed_updates.items() if now - ts > _DEDUP_TTL]
        for uid in expired:
            del _processed_updates[uid]

        if update_id in _processed_updates:
            return True

        _processed_updates[update_id] = now

        while len(_processed_updates) > _MAX_PROCESSED:
            _processed_updates.popitem(last=False)

        return False


async def _is_duplicate_user_message(user_id: int, text: str) -> bool:
    """فحص هل المستخدم ده بعت نفس الرسالة مؤخرًا (منع التكرار لكل مستخدم) — ASYNC SAFE"""
    async with _dedup_lock:
        now = _time.time()

        old_users = [uid for uid, (_, ts) in _user_last_message.items() if now - ts > 60]
        for uid in old_users:
            del _user_last_message[uid]

        text_hash = hash(text.strip().lower())

        if user_id in _user_last_message:
            last_hash, last_ts = _user_last_message[user_id]
            if last_hash == text_hash and (now - last_ts) < _USER_DEDUP_SECONDS:
                return True

        _user_last_message[user_id] = (text_hash, now)
        return False
