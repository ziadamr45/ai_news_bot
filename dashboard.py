"""
لوحة التحكم - Dashboard
تتبع الإحصائيات والأداء
+ دعم فصل الإحصائيات حسب المنصة (Telegram / WhatsApp)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

CAIRO_TZ = timezone(timedelta(hours=2))


def _is_postgres():
    from memory import _is_postgres
    return _is_postgres()


def _execute(query, params=(), fetch=False, fetchone=False):
    from memory import _execute
    return _execute(query, params, fetch=fetch, fetchone=fetchone)


def init_dashboard_tables():
    """Create dashboard tracking tables + migrate old schema"""
    try:
        if _is_postgres():
            _execute("""
                CREATE TABLE IF NOT EXISTS bot_stats (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    platform TEXT DEFAULT 'telegram',
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
                    youtube_summaries INTEGER DEFAULT 0,
                    UNIQUE(date, platform)
                );
            """)
            # Migration: إضافة عمود platform لو الجدول القديم مش عنده
            try:
                _execute("ALTER TABLE bot_stats ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'telegram'")
            except Exception:
                pass
        else:
            _execute("""
                CREATE TABLE IF NOT EXISTS bot_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    platform TEXT DEFAULT 'telegram',
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
                    youtube_summaries INTEGER DEFAULT 0,
                    UNIQUE(date, platform)
                );
            """)
            # Migration: إضافة عمود platform لو الجدول القديم مش عنده (SQLite)
            try:
                _execute("SELECT platform FROM bot_stats LIMIT 1", fetchone=True)
            except Exception:
                try:
                    _execute("ALTER TABLE bot_stats ADD COLUMN platform TEXT DEFAULT 'telegram'")
                except Exception:
                    pass
        logger.info("✅ Dashboard tables initialized")
    except Exception as e:
        logger.warning(f"Dashboard tables init error: {e}")


def _get_today_key() -> str:
    return datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")


def _ensure_stats_row(date_key: str, platform: str = "telegram"):
    """Ensure stats row exists for date+platform"""
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    row = _execute(
        f"SELECT id FROM bot_stats WHERE date = {ph1} AND platform = {ph2}",
        (date_key, platform), fetchone=True
    )
    if not row:
        _execute(
            f"INSERT INTO bot_stats (date, platform) VALUES ({ph1}, {ph2})",
            (date_key, platform)
        )


def track_event(event_type: str, count: int = 1, platform: str = "telegram"):
    """Track a bot event for a specific platform"""
    date_key = _get_today_key()
    _ensure_stats_row(date_key, platform)

    valid_events = [
        "total_messages", "total_commands", "total_errors", "new_users",
        "active_users", "premium_users", "ai_requests", "search_requests",
        "pdf_analyses", "image_analyses", "voice_messages", "youtube_summaries"
    ]
    if event_type not in valid_events:
        return

    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    _execute(
        f"UPDATE bot_stats SET {event_type} = {event_type} + {count} WHERE date = {ph1} AND platform = {ph2}",
        (date_key, platform)
    )


def get_today_stats(platform: str = None) -> Dict:
    """Get today's statistics, optionally filtered by platform"""
    date_key = _get_today_key()

    if platform:
        _ensure_stats_row(date_key, platform)
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        row = _execute(
            f"SELECT total_messages, total_commands, total_errors, new_users, "
            f"active_users, premium_users, ai_requests, search_requests, "
            f"pdf_analyses, image_analyses, voice_messages, youtube_summaries "
            f"FROM bot_stats WHERE date = {ph1} AND platform = {ph2}",
            (date_key, platform), fetchone=True
        )
    else:
        # Aggregate across all platforms
        row = _execute(
            f"SELECT SUM(total_messages), SUM(total_commands), SUM(total_errors), SUM(new_users), "
            f"SUM(active_users), SUM(premium_users), SUM(ai_requests), SUM(search_requests), "
            f"SUM(pdf_analyses), SUM(image_analyses), SUM(voice_messages), SUM(youtube_summaries) "
            f"FROM bot_stats WHERE date = %s" if _is_postgres() else
            f"SELECT SUM(total_messages), SUM(total_commands), SUM(total_errors), SUM(new_users), "
            f"SUM(active_users), SUM(premium_users), SUM(ai_requests), SUM(search_requests), "
            f"SUM(pdf_analyses), SUM(image_analyses), SUM(voice_messages), SUM(youtube_summaries) "
            f"FROM bot_stats WHERE date = ?",
            (date_key,), fetchone=True
        )

    keys = [
        "total_messages", "total_commands", "total_errors", "new_users",
        "active_users", "premium_users", "ai_requests", "search_requests",
        "pdf_analyses", "image_analyses", "voice_messages", "youtube_summaries"
    ]
    if row:
        return {k: (row[i] or 0) for i, k in enumerate(keys)}
    return {k: 0 for k in keys}


def get_total_users(platform: str = None) -> int:
    """Get total registered users, optionally filtered by platform"""
    try:
        if platform:
            ph = "%s" if _is_postgres() else "?"
            row = _execute(f"SELECT COUNT(*) FROM user_profiles WHERE platform = {ph}", (platform,), fetchone=True)
        else:
            row = _execute("SELECT COUNT(*) FROM user_profiles", fetchone=True)
        return row[0] if row else 0
    except Exception:
        return 0


def get_total_subscribers(platform: str = None) -> int:
    """Get total news subscribers, optionally filtered by platform"""
    try:
        if platform:
            ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
            row = _execute(f"SELECT COUNT(*) FROM user_profiles WHERE subscribed = {ph1} AND platform = {ph2}", (1, platform), fetchone=True)
        else:
            ph = "%s" if _is_postgres() else "?"
            row = _execute(f"SELECT COUNT(*) FROM user_profiles WHERE subscribed = {ph}", (1,), fetchone=True)
        return row[0] if row else 0
    except Exception:
        return 0


def get_total_premium(platform: str = None) -> int:
    """Get total premium users, optionally filtered by platform"""
    try:
        if platform:
            ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
            row = _execute(f"SELECT COUNT(*) FROM premium_users pu JOIN user_profiles up ON pu.user_id = up.user_id WHERE pu.plan = {ph1} AND up.platform = {ph2}", ("premium", platform), fetchone=True)
        else:
            ph = "%s" if _is_postgres() else "?"
            row = _execute(f"SELECT COUNT(*) FROM premium_users WHERE plan = {ph}", ("premium",), fetchone=True)
        return row[0] if row else 0
    except Exception:
        return 0


def format_dashboard(lang: str = "ar", platform: str = None) -> str:
    """Format dashboard display, optionally filtered by platform"""
    today = get_today_stats(platform=platform)
    total_users = get_total_users(platform=platform)
    total_subscribers = get_total_subscribers(platform=platform)
    total_premium = get_total_premium(platform=platform)

    # Platform label
    platform_label = ""
    if platform == "telegram":
        platform_label = "📱 تليجرام" if lang == "ar" else "📱 Telegram"
    elif platform == "whatsapp":
        platform_label = "📱 واتساب" if lang == "ar" else "📱 WhatsApp"

    if lang == "ar":
        header = f"📊 <b>لوحة تحكم My Bro</b>"
        if platform_label:
            header += f"\n{platform_label}"
        return f"""{header}
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
        header = f"📊 <b>My Bro Dashboard</b>"
        if platform_label:
            header += f"\n{platform_label}"
        return f"""{header}
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
