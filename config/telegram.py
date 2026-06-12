"""
إعدادات تيليجرام والهوية - Telegram & Bot Identity Settings
═══════════════════════════════════════════════════════════════
BOT_TOKEN, CHAT_ID, DATABASE_URL, BOT_NAME, BOT_VERSION,
Developer identity, Scheduler settings, Message templates
"""

import os

# ═══════════════════════════════════════
# Telegram Settings
# ═══════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# PostgreSQL (Neon) - قاعدة بيانات دائمة
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ═══════════════════════════════════════
# إعدادات البوت - Bot Settings
# ═══════════════════════════════════════

BOT_NAME = "My Bro"
BOT_VERSION = "9.15"

# ═══════════════════════════════════════
# معرف المطور - Developer Identity
# ═══════════════════════════════════════

_DEVELOPER_ID_FROM_ENV = int(CHAT_ID) if CHAT_ID else 0
DEVELOPER_USER_ID = _DEVELOPER_ID_FROM_ENV if _DEVELOPER_ID_FROM_ENV else 8674141938
DEVELOPER_USERNAME = "ziadamr"  # @ziadamr

# ═══════════════════════════════════════
# إعدادات Premium - Premium Settings
# ═══════════════════════════════════════

DEVELOPER_TELEGRAM = "@ziadamr"
DEVELOPER_TELEGRAM_URL = "https://t.me/ziadamr"
DEVELOPER_WHATSAPP = os.environ.get("DEVELOPER_WHATSAPP", "01203551789")
DEVELOPER_WHATSAPP_URL = f"https://wa.me/{DEVELOPER_WHATSAPP.lstrip('0')}"

# ═══════════════════════════════════════
# إعدادات الجدولة - Scheduler Settings
# ═══════════════════════════════════════

DAILY_NEWS_HOUR = 12
DAILY_NEWS_MINUTE = 0
DAILY_NEWS_TIMEZONE = "Africa/Cairo"
DEFAULT_NEWS_TIME = "12:00"  # 🔴 الوقت الافتراضي للأخبار — 12:00 الظهر
BROADCAST_DELAY_SECONDS = 0.5

# No News Message
NO_NEWS_MESSAGE = "لا توجد اليوم أخبار كبيرة في مجال الذكاء الاصطناعي تستحق التنبيه. 🤖"

# Message Template
MESSAGE_TEMPLATE = """📰 <b>أخبار الذكاء الاصطناعي اليوم</b>
📅 {date}

━━━━━━━━━━━━━━━━━

{news_items}

━━━━━━━━━━━━━━━━━
🤖 <i>بوت أخبار AI — يتم التشغيل تلقائياً كل يوم الساعة 12 الظهر بتوقيت القاهرة</i>"""

NEWS_ITEM_TEMPLATE = """{badge} <b>{title}</b>

{summary}

🔗 <a href="{url}">اقرأ المزيد</a>"""

TOP_NEWS_BADGE = "🔥"
REGULAR_NEWS_BADGE = "⚪️"
