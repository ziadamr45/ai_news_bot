"""
Error monitoring system.
Tracks error types and frequencies for admin review.
"""

import asyncio
import time as _time


_error_stats = {}  # {error_type: {"count": int, "last_error": str, "last_time": float}}
_error_stats_lock = asyncio.Lock()


async def record_error(error_type: str, error_msg: str = ""):
    """تسجيل خطأ في نظام المراقبة"""
    async with _error_stats_lock:
        if error_type not in _error_stats:
            _error_stats[error_type] = {"count": 0, "last_error": "", "last_time": 0}
        _error_stats[error_type]["count"] += 1
        _error_stats[error_type]["last_error"] = error_msg[:200]
        _error_stats[error_type]["last_time"] = _time.time()


def get_error_stats() -> str:
    """الحصول على تقرير الأخطاء للأدمن"""
    if not _error_stats:
        return "✅ No errors recorded"
    
    lines = ["📊 <b>Error Monitor</b>\n━━━━━━━━━━━━━━━━━\n"]
    # Sort by count descending
    sorted_errors = sorted(_error_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    
    for error_type, data in sorted_errors[:20]:  # Top 20 errors
        count = data["count"]
        last_msg = data["last_error"][:80] if data["last_error"] else "N/A"
        elapsed = int(_time.time() - data["last_time"])
        lines.append(f"🔴 <b>{error_type}</b>: {count}x\n   Last: {last_msg} ({elapsed}s ago)")
    
    total = sum(d["count"] for d in _error_stats.values())
    lines.append(f"\n━━━━━━━━━━━━━━━━━\n📊 Total: {total} errors in {len(_error_stats)} categories")
    return "\n".join(lines)
