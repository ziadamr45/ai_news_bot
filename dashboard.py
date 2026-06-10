"""
لوحة التحكم - Dashboard
تتبع الإحصائيات والأداء
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict

logger = logging.getLogger(__name__)

CAIRO_TZ = timezone(timedelta(hours=2))


def _is_postgres():
    from memory import _is_postgres
    return _is_postgres()


def _execute(query, params=(), fetch=False, fetchone=False):
    from memory import _execute
    return _execute(query, params, fetch=fetch, fetchone=fetchone)


def init_dashboard_tables():
    """Create dashboard tracking tables"""
    try:
        if _is_postgres():
            _execute("""
                CREATE TABLE IF NOT EXISTS bot_stats (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL UNIQUE,
                    total_messages INTEGER DEFAULT 0,
                    total_commands INTEGER DEFAULT 0,
                    total_errors INTEGER DEFAULT 0,
                    new_users INTEGER DEFAULT 0,
                    active_users INTEGER DEFAULT 0,
                    premium_users INTEGER DEFAULT 0,
                    ai_requests INTEGER DEFAULT 0,
                    search_requests INTEGER DEFAULT 0,
                    pdf_analyses INTEGER DEFAULT 0,
                    image_analyses INTEGER DEFAULT 0,
                    voice_messages INTEGER DEFAULT 0,
                    youtube_summaries INTEGER DEFAULT 0
                );
            """)
        else:
            _execute("""
                CREATE TABLE IF NOT EXISTS bot_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    total_messages INTEGER DEFAULT 0,
                    total_commands INTEGER DEFAULT 0,
                    total_errors INTEGER DEFAULT 0,
                    new_users INTEGER DEFAULT 0,
                    active_users INTEGER DEFAULT 0,
                    premium_users INTEGER DEFAULT 0,
                    ai_requests INTEGER DEFAULT 0,
                    search_requests INTEGER DEFAULT 0,
                    pdf_analyses INTEGER DEFAULT 0,
                    image_analyses INTEGER DEFAULT 0,
                    voice_messages INTEGER DEFAULT 0,
                    youtube_summaries INTEGER DEFAULT 0
                );
            """)
        logger.info("✅ Dashboard tables initialized")
    except Exception as e:
        logger.warning(f"Dashboard tables init error: {e}")


def _get_today_key() -> str:
    return datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")


def _ensure_stats_row(date_key: str):
    """Ensure stats row exists for date"""
    ph = "%s" if _is_postgres() else "?"
    row = _execute(f"SELECT id FROM bot_stats WHERE date = {ph}", (date_key,), fetchone=True)
    if not row:
        _execute(
            f"INSERT INTO bot_stats (date) VALUES ({ph})",
            (date_key,)
        )


def track_event(event_type: str, count: int = 1):
    """Track a bot event"""
    date_key = _get_today_key()
    _ensure_stats_row(date_key)

    valid_events = [
        "total_messages", "total_commands", "total_errors", "new_users",
        "active_users", "premium_users", "ai_requests", "search_requests",
        "pdf_analyses", "image_analyses", "voice_messages", "youtube_summaries"
    ]
    if event_type not in valid_events:
        return

    ph = "%s" if _is_postgres() else "?"
    _execute(
        f"UPDATE bot_stats SET {event_type} = {event_type} + {count} WHERE date = {ph}",
        (date_key,)
    )


def get_today_stats() -> Dict:
    """Get today's statistics"""
    date_key = _get_today_key()
    _ensure_stats_row(date_key)

    ph = "%s" if _is_postgres() else "?"
    row = _execute(
        f"SELECT total_messages, total_commands, total_errors, new_users, "
        f"active_users, premium_users, ai_requests, search_requests, "
        f"pdf_analyses, image_analyses, voice_messages, youtube_summaries "
        f"FROM bot_stats WHERE date = {ph}",
        (date_key,), fetchone=True
    )
    if row:
        return {
            "total_messages": row[0],
            "total_commands": row[1],
            "total_errors": row[2],
            "new_users": row[3],
            "active_users": row[4],
            "premium_users": row[5],
            "ai_requests": row[6],
            "search_requests": row[7],
            "pdf_analyses": row[8],
            "image_analyses": row[9],
            "voice_messages": row[10],
            "youtube_summaries": row[11],
        }
    return {k: 0 for k in [
        "total_messages", "total_commands", "total_errors", "new_users",
        "active_users", "premium_users", "ai_requests", "search_requests",
        "pdf_analyses", "image_analyses", "voice_messages", "youtube_summaries"
    ]}


def get_total_users() -> int:
    """Get total registered users"""
    try:
        row = _execute("SELECT COUNT(*) FROM user_profiles", fetchone=True)
        return row[0] if row else 0
    except Exception:
        return 0


def get_total_subscribers() -> int:
    """Get total news subscribers"""
    try:
        ph = "%s" if _is_postgres() else "?"
        row = _execute(f"SELECT COUNT(*) FROM user_profiles WHERE subscribed = {ph}", (1,), fetchone=True)
        return row[0] if row else 0
    except Exception:
        return 0


def get_total_premium() -> int:
    """Get total premium users"""
    try:
        ph = "%s" if _is_postgres() else "?"
        row = _execute(f"SELECT COUNT(*) FROM premium_users WHERE plan = {ph}", ("premium",), fetchone=True)
        return row[0] if row else 0
    except Exception:
        return 0


def format_dashboard(lang: str = "ar") -> str:
    """Format dashboard display"""
    today = get_today_stats()
    total_users = get_total_users()
    total_subscribers = get_total_subscribers()
    total_premium = get_total_premium()

    if lang == "ar":
        return f"""📊 <b>لوحة تحكم My Bro</b>
━━━━━━━━━━━━━━━━━

👥 <b>المستخدمين</b>
→ الإجمالي: {total_users}
→ المشتركين في الأخبار: {total_subscribers}
→ Premium: {total_premium}

📈 <b>إحصائيات اليوم</b>
→ الرسائل: {today['total_messages']}
→ الأوامر: {today['total_commands']}
→ طلبات AI: {today['ai_requests']}
→ عمليات البحث: {today['search_requests']}
→ تحليلات PDF: {today['pdf_analyses']}
→ تحليلات الصور: {today['image_analyses']}
→ رسائل صوتية: {today['voice_messages']}
→ ملخصات YouTube: {today['youtube_summaries']}
→ أخطاء: {today['total_errors']}
→ مستخدمين جدد: {today['new_users']}

🤖 <b>My Bro v9.0 — AI Super Assistant</b>"""
    else:
        return f"""📊 <b>My Bro Dashboard</b>
━━━━━━━━━━━━━━━━━

👥 <b>Users</b>
→ Total: {total_users}
→ News Subscribers: {total_subscribers}
→ Premium: {total_premium}

📈 <b>Today's Stats</b>
→ Messages: {today['total_messages']}
→ Commands: {today['total_commands']}
→ AI Requests: {today['ai_requests']}
→ Searches: {today['search_requests']}
→ PDF Analyses: {today['pdf_analyses']}
→ Image Analyses: {today['image_analyses']}
→ Voice Messages: {today['voice_messages']}
→ YouTube Summaries: {today['youtube_summaries']}
→ Errors: {today['total_errors']}
→ New Users: {today['new_users']}

🤖 <b>My Bro v9.0 — AI Super Assistant</b>"""
