"""
WhatsApp Shared State Module
=============================
Central state, configuration, constants, and utility functions shared by all
whatsapp sub-modules (api.py, handlers.py, etc.).

Contents:
  - Environment / config constants
  - Admin & developer identifiers
  - Message deduplication cache
  - Per-user workflow state management
  - URL cache & user image-edit cache
  - Webhook activity log
  - Signature verification
  - WhatsApp text formatting helpers
  - URL detection / platform utilities
  - Command triggers dictionary
  - Search cache
  - Arabic character detection
"""

import os
import json
import logging
import hashlib
import hmac
import re
import asyncio
import base64
import io
import tempfile
import shutil
import time
from datetime import datetime, timezone
from collections import OrderedDict

from aiohttp import web

from i18n import t

from content_safety import (
    check_query_safety,
    check_search_results_safety,
    comprehensive_media_safety_check,
    get_block_message,
    get_no_safe_results_message,
    should_enable_safe_search,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# Configuration
# ═══════════════════════════════════════

# Helper: treat "PENDING" as unset (placeholder from initial Railway setup)
def _get_env(key: str, default: str = "") -> str:
    """Get env var, treating 'PENDING' as unset"""
    val = os.environ.get(key, default)
    if val.upper() == "PENDING":
        logger.warning(f"⚠️ {key} is set to 'PENDING' — treating as not configured")
        return default
    return val

WHATSAPP_VERIFY_TOKEN = _get_env("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = _get_env("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _get_env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = _get_env("WHATSAPP_APP_SECRET")
# Railway sets PORT automatically — use it if available, otherwise fallback to WEBHOOK_PORT or 8080
WEBHOOK_PORT = int(os.environ.get("PORT", os.environ.get("WEBHOOK_PORT", "8080")))

# Allowed WhatsApp numbers (for security — only respond to allowed numbers)
# Leave empty to allow all numbers (anyone can message the bot)
ALLOWED_WA_NUMBERS = os.environ.get("ALLOWED_WA_NUMBERS", "").split(",") if os.environ.get("ALLOWED_WA_NUMBERS") else []

# ═══════════════════════════════════════
# WhatsApp API Base URL
# ═══════════════════════════════════════

WHATSAPP_API_URL = "https://graph.facebook.com/v21.0"

# ═══════════════════════════════════════
# WhatsApp Message Limits
# ═══════════════════════════════════════

WA_MAX_MSG = 4000  # WhatsApp message max length (unified constant)

# ═══════════════════════════════════════
# Admin Configuration
# ═══════════════════════════════════════

ADMIN_WA_ID = os.environ.get("ADMIN_WA_ID", "201203551789")  # Admin WhatsApp ID (env var for security)

# Developer WhatsApp contact for premium/subscription messages
DEVELOPER_WHATSAPP = os.environ.get("DEVELOPER_WHATSAPP", "01203551789")
DEVELOPER_WHATSAPP_URL = f"https://wa.me/{DEVELOPER_WHATSAPP.lstrip('0')}"


def _wa_phone_to_user_id(phone: str) -> int:
    """تحويل رقم واتساب (موبايل) لـ user_id داخلي
    
    الواتساب بيتعامل برقم الموبايل (زي 201203551789)
    بس الدوال الداخلية بتستخدم hashed user_id
    الدالة دي بتاخد الرقم وترجع الـ user_id الصح
    
    ⚠️ BUG FIX: Python's hash() is NOT deterministic across restarts!
    Since Python 3.3, hash() uses a random seed (PYTHONHASHSEED) that changes
    on every interpreter start. This means the same phone number would produce
    different user_ids after each bot restart, orphaning all user data.
    
    FIX: Use hashlib.sha256 for deterministic hashing.
    """
    # إزالة + من البداية لو موجود
    clean = phone.lstrip('+')
    # إزالة مسافات
    clean = clean.strip()
    # ✅ Deterministic hash — same result every time, even after restarts
    h = hashlib.sha256(f"wa_{clean}".encode()).hexdigest()
    return -(int(h, 16) % (2**31))


def _wa_phone_to_display(phone: str) -> str:
    """تنسيق رقم الموبايل للعرض"""
    clean = phone.lstrip('+').strip()
    return f"+{clean}"


def _is_wa_admin(wa_id: str) -> bool:
    """Check if WhatsApp ID belongs to the admin (Ziad Amr)"""
    if wa_id == ADMIN_WA_ID:
        return True
    # Also check via admin.py using the hashed user_id
    try:
        from admin import is_admin
        wa_user_id = _wa_phone_to_user_id(wa_id)
        return is_admin(wa_user_id)
    except Exception:
        return False


def _ensure_wa_admin_premium(wa_id: str):
    """Ensure the WhatsApp admin is always premium"""
    if wa_id == ADMIN_WA_ID:
        try:
            from admin import ensure_admin_premium
            wa_user_id = _wa_phone_to_user_id(wa_id)
            ensure_admin_premium(wa_user_id)
        except Exception as e:
            logger.warning(f"Could not ensure admin premium: {e}")


# ═══════════════════════════════════════
# Message Deduplication
# ═══════════════════════════════════════

_processed_message_ids = OrderedDict()
_MAX_DEDUP_CACHE = 1000

_wa_user_pdf_context = {}  # PDF context per user for follow-up Q&A
_wa_user_yt_url = {}  # {wa_id: "youtube_url"} — 🍪 cache YouTube URL for download button

# ═══════════════════════════════════════
# نظام حالة المستخدم — Workflow State Management
# ═══════════════════════════════════════
# بيحفظ حالة المستخدم النشطة عشان الرسائل توصل للخدمة الصح
# الأنواع المدعومة:
#   photo_search  → في انتظار عدد الصور
#   video_search  → في انتظار اختيار فيديو من القائمة
#   audio_search  → في انتظار اختيار صوت من القائمة
#   image_edit    → في انتظار وصف التعديل على صورة
#   pdf_qa        → في انتظار سؤال عن PDF
#   download      → في انتظار اختيار جودة التحميل
_wa_user_state = {}  # {wa_id: {"flow": str, "data": dict, "expires": float}}
_WA_STATE_TTL = 300  # 5 دقائق — بعد كده الحالة تنتهي تلقائيًا

def _set_user_state(wa_id: str, flow: str, data: dict = None):
    """حفظ حالة المستخدم النشطة"""
    _wa_user_state[wa_id] = {
        "flow": flow,
        "data": data or {},
        "expires": time.time() + _WA_STATE_TTL,
    }

def _get_user_state(wa_id: str) -> dict:
    """الحصول على حالة المستخدم النشطة (أو None لو مفيش)"""
    state = _wa_user_state.get(wa_id)
    if not state:
        return None
    if time.time() > state.get("expires", 0):
        # الحالة انتهت — امسحها
        del _wa_user_state[wa_id]
        return None
    return state

def _clear_user_state(wa_id: str):
    """مسح حالة المستخدم"""
    _wa_user_state.pop(wa_id, None)

# URL cache for multi-quality downloads (like Telegram's _url_cache)
_url_cache = {}  # {key: {"url": str, "expires": float}}
_URL_CACHE_TTL = 1800  # 30 minutes (was 10 min — too short for quality selection)

# User image cache for image editing (like Telegram's _user_edit_images)
_wa_user_edit_images = {}  # {wa_user_id: {"image_base64": str, "created_at": float}}

# ═══════════════════════════════════════
# Webhook Activity Log (for diagnostics)
# ═══════════════════════════════════════

_webhook_activity_log = []
_MAX_ACTIVITY_LOG = 50


def _log_activity(event_type: str, data: dict, status: str = "received"):
    """Log webhook activity for the /debug/whatsapp/activity endpoint"""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "status": status,
        "data": data,
    }
    _webhook_activity_log.append(entry)
    while len(_webhook_activity_log) > _MAX_ACTIVITY_LOG:
        _webhook_activity_log.pop(0)


def _is_duplicate_wa_message(message_id: str) -> bool:
    """Check if we already processed this WhatsApp message ID"""
    if message_id in _processed_message_ids:
        return True
    _processed_message_ids[message_id] = True
    while len(_processed_message_ids) > _MAX_DEDUP_CACHE:
        _processed_message_ids.popitem(last=False)
    return False


# ═══════════════════════════════════════
# Webhook Event Logging
# ═══════════════════════════════════════

def _log_event(direction: str, event_type: str, data: dict):
    """Log webhook events in a structured format"""
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": direction,
        "type": event_type,
        "data": data,
    }
    logger.info(f"📲 WA Webhook [{direction}] {event_type}: {json.dumps(data, ensure_ascii=False)[:500]}")


# ═══════════════════════════════════════
# Signature Verification
# ═══════════════════════════════════════

def _verify_signature(payload: bytes, signature_header: str) -> bool:
    """Verify the X-Hub-Signature-256 header from Meta"""
    if not WHATSAPP_APP_SECRET:
        logger.warning("⚠️ WHATSAPP_APP_SECRET not set — skipping signature verification")
        return True

    if not signature_header:
        return False

    try:
        if not signature_header.startswith("sha256="):
            return False

        expected = hmac.new(
            WHATSAPP_APP_SECRET.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        received = signature_header.split("=", 1)[1]
        return hmac.compare_digest(expected, received)
    except Exception as e:
        logger.error(f"❌ Signature verification error: {e}")
        return False


# ═══════════════════════════════════════
# WhatsApp Message Formatting
# ═══════════════════════════════════════

def _strip_html_for_whatsapp(text: str) -> str:
    """
    Strip HTML tags from AI response for WhatsApp.
    WhatsApp doesn't support HTML — only plain text and *bold*, _italic_, ~strikethrough~, ```code```
    """
    if not text:
        return text

    text = re.sub(r'<b>(.*?)</b>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<i>(.*?)</i>', r'_\1_', text, flags=re.DOTALL)
    text = re.sub(r'<code>(.*?)</code>', r'```\1```', text, flags=re.DOTALL)
    text = re.sub(r'<s>(.*?)</s>', r'~\1~', text, flags=re.DOTALL)
    text = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', r'\2 (\1)', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()


def _split_whatsapp_message(text: str, max_length: int = WA_MAX_MSG) -> list:
    """Split a long message for WhatsApp (WA_MAX_MSG char limit per message)."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    split_markers = ['\n\n', '\n', ' • ', ' — ', ' ']

    remaining = text
    while len(remaining) > max_length:
        split_pos = -1
        search_end = min(max_length, len(remaining))

        for marker in split_markers:
            pos = remaining.rfind(marker, 0, search_end)
            if pos > 0:
                split_pos = pos + len(marker)
                break

        if split_pos <= 0:
            for end_char in ['؟', '،', '؛', '.']:
                pos = remaining.rfind(end_char, 0, search_end)
                if pos > 0:
                    split_pos = pos + 1
                    break

        if split_pos <= 0:
            split_pos = max_length

        chunk = remaining[:split_pos].rstrip()
        remaining = remaining[split_pos:].lstrip()

        if chunk:
            chunks.append(chunk)

    if remaining.strip():
        chunks.append(remaining.strip())

    return chunks if chunks else [text]


# ═══════════════════════════════════════
# URL Detection & Platform Utilities
# ═══════════════════════════════════════

# URL detection patterns (shared with Telegram download_handlers)
_URL_PATTERNS = {
    "youtube": re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube\.com/shorts)/', re.IGNORECASE),
    "facebook": re.compile(r'(https?://)?(www\.)?(facebook\.com|fb\.watch|m\.facebook\.com)/', re.IGNORECASE),
    "instagram": re.compile(r'(https?://)?(www\.)?(instagram\.com|instagr\.am)/', re.IGNORECASE),
    "tiktok": re.compile(r'(https?://)?(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/', re.IGNORECASE),
    "twitter": re.compile(r'(https?://)?(www\.)?(twitter\.com|x\.com|t\.co)/', re.IGNORECASE),
    "telegram": re.compile(r'(https?://)?(t\.me|telegram\.me|telegram\.org)/', re.IGNORECASE),
    "threads": re.compile(r'(https?://)?(www\.)?threads\.(net|com)/', re.IGNORECASE),
    "reddit": re.compile(r'(https?://)?(www\.)?(reddit\.com|redd\.it)/', re.IGNORECASE),
    "dailymotion": re.compile(r'(https?://)?(www\.)?(dailymotion\.com|dai\.ly)/', re.IGNORECASE),
    "soundcloud": re.compile(r'(https?://)?(www\.)?soundcloud\.com/', re.IGNORECASE),
}

_GENERAL_URL_PATTERN = re.compile(r'https?://[^\s<>\"]+', re.IGNORECASE)


def _detect_platform(url: str) -> str:
    """Detect platform from URL"""
    for platform, pattern in _URL_PATTERNS.items():
        if pattern.search(url):
            return platform
    return "unknown"


def _is_youtube_url(url: str) -> bool:
    """فحص هل الرابط يوتيوب — يشمل youtube.com, youtu.be, youtube.com/shorts"""
    return bool(_URL_PATTERNS.get("youtube") and _URL_PATTERNS["youtube"].search(url))


def _extract_url(text: str) -> str:
    """Extract first URL from text"""
    match = _GENERAL_URL_PATTERN.search(text)
    return match.group(0) if match else ""


# ═══════════════════════════════════════
# تحميل Threads — طريقة مخصصة
# ═══════════════════════════════════════

_THREADS_URL_PATTERN = re.compile(r'(https?://)?(www\.)?threads\.(net|com)/', re.IGNORECASE)


def _is_threads_url(url: str) -> bool:
    """كشف هل الرابط من Threads"""
    return bool(_THREADS_URL_PATTERN.search(url))


def _store_url(url: str) -> str:
    """Store URL in cache and return key (like Telegram's _store_url)"""
    key = hashlib.md5(url.encode()).hexdigest()[:10]
    _url_cache[key] = {"url": url, "expires": time.time() + _URL_CACHE_TTL}
    # Clean expired entries
    expired = [k for k, v in _url_cache.items() if v["expires"] < time.time()]
    for k in expired:
        del _url_cache[k]
    return key


def _get_url(key: str) -> str:
    """Get URL from cache by key"""
    entry = _url_cache.get(key)
    if entry and entry["expires"] > time.time():
        return entry["url"]
    return ""


# ═══════════════════════════════════════
# Commands System — Full Feature Parity with Telegram
# ═══════════════════════════════════════

_COMMAND_TRIGGERS = {
    # Start / Welcome
    "/start": "start", "start": "start", "اهلا": "start", "مرحبا": "start", "سلام": "start", "هاي": "start",
    # Help / Commands
    "/help": "help", "help": "help", "مساعدة": "help", "اوامر": "help", "الأوامر": "help", "الاوامر": "help",
    # Commands menu
    "/commands": "commands", "commands": "commands", "قائمة": "commands", "القائمة": "commands", "الميزات": "commands",
    # News
    "/news": "news", "news": "news", "اخبار": "news", "أخبار": "news", "الاخبار": "news",
    # Breaking news
    "/breaking": "breaking", "breaking": "breaking", "عاجل": "breaking", "عاجلة": "breaking",
    # Weekly summary
    "/weekly": "weekly", "weekly": "weekly", "اسبوعي": "weekly", "أسبوعي": "weekly", "ملخص اسبوعي": "weekly",
    # Trending
    "/trending": "trending", "trending": "trending", "ترند": "trending", "ترندات": "trending", "الأكثر": "trending",
    # Search
    "/search": "search", "search": "search", "بحث": "search", "ابحث": "search", "البحث": "search",
    # Ask
    "/ask": "ask", "ask": "ask", "اسأل": "ask", "اسال": "ask", "سؤال": "ask",
    # Learn
    "/learn": "learn", "learn": "learn", "تعلم": "learn", "اتعلم": "learn",
    # Roadmap
    "/roadmap": "roadmap", "roadmap": "roadmap", "خريطة": "roadmap", "مسار": "roadmap",
    # Chat (force AI mode)
    "/chat": "chat", "chat": "chat", "محادثة": "chat", "كلم": "chat", "كلمني": "chat",
    # Company info
    "/company": "company", "company": "company", "شركة": "company", "شركات": "company",
    # About
    "/about": "about", "about": "about", "عن": "about", "مين": "about", "مين انت": "about",
    # Subscribe / Unsubscribe
    "/subscribe": "subscribe", "subscribe": "subscribe", "اشترك": "subscribe", "اشتراك": "subscribe",
    "/unsubscribe": "unsubscribe", "unsubscribe": "unsubscribe", "الغاء": "unsubscribe", "إلغاء": "unsubscribe", "الغاء اشتراك": "unsubscribe",
    # Language
    "/language": "language", "language": "language", "لغة": "language", "اللغة": "language",
    # Memory
    "/memory": "memory", "memory": "memory", "ذاكرة": "memory", "الذاكرة": "memory",
    # Premium
    "/premium": "premium", "premium": "premium", "بريميوم": "premium", "اشتراك مدفوع": "premium",
    # Plan / Usage
    "/plan": "plan", "plan": "plan", "حدود": "plan", "الحدود": "plan", "استخدام": "plan",
    "/usage": "plan",
    # Settings
    "/settings": "settings", "settings": "settings", "اعدادات": "settings", "الإعدادات": "settings", "ضبط": "settings",
    # Download
    "/download": "download", "download": "download", "تحميل": "download", "حمّل": "download",
    # Video/Audio Search
    "/video": "video_search", "فيديو بالبحث": "video_search", "فيديو بحث": "video_search",
    "/audio": "audio_search", "صوت بالبحث": "audio_search", "صوت بحث": "audio_search",
    # Photo Search
    "/photo": "photo_search", "بحث صور": "photo_search", "صور": "photo_search",
    # Study Mode
    "/study": "study", "study": "study", "دراسة": "study", "ادرس": "study",
    "/quiz": "quiz", "quiz": "quiz", "كويز": "quiz",
    "/exam": "exam", "exam": "exam", "امتحان": "exam",
    # Exit
    "/exit": "exit", "exit": "exit", "خروج": "exit", "الغاء": "exit", "إلغاء": "exit",
    # YouTube
    "/youtube": "youtube", "youtube": "youtube", "يوتيوب": "youtube",
    # Cookies
    "/cookies": "cookies", "cookies": "cookies", "كوكيز": "cookies",
    # PO Token
    "/potoken": "potoken", "potoken": "potoken",
    # PDF
    "/pdf": "pdf", "pdf": "pdf",
    "/keypoints": "pdf_keypoints",
    # Image gen
    "/image": "image_gen", "image": "image_gen", "صورة": "image_gen",
    # Image edit
    "/edit": "image_edit", "edit": "image_edit", "عدل": "image_edit", "عدل صورة": "image_edit",
    # Favorites
    "/favorite": "favorite", "favorite": "favorite", "مفضلة": "favorite",
    "/favorites": "favorites", "favorites": "favorites", "المفضلات": "favorites",
    # Forget
    "/forget": "forget", "نسي": "forget", "امسح ذاكرة": "forget",
    # Admin commands
    "/admin": "admin", "ادمن": "admin", "لوحة التحكم": "admin",
    "/dashboard": "admin", "لوحة": "admin",
    "/stats": "admin_stats", "احصائيات": "admin_stats",
    "/botstats": "admin_stats",
    "/grant": "admin_grant", "تفعيل بروميوم": "admin_grant",
    "/revoke": "admin_revoke", "شيل بروميوم": "admin_revoke",
    "/resetlimit": "admin_resetlimit", "ريست حد": "admin_resetlimit",
    "/ban": "admin_ban", "حظر": "admin_ban",
    "/unban": "admin_unban", "الغاء حظر": "admin_unban",
    "/warn": "admin_warn", "تحذير": "admin_warn",
    "/userinfo": "admin_userinfo", "معلومات يوزر": "admin_userinfo",
    "/userstats": "admin_userstats", "احصائيات يوزر": "admin_userstats",
    "/broadcast": "admin_broadcast", "بث": "admin_broadcast",
    "/allusers": "admin_allusers", "كل المستخدمين": "admin_allusers",
    "/addadmin": "admin_addadmin", "اضافة ادمن": "admin_addadmin",
    "/removeadmin": "admin_removeadmin", "شيل ادمن": "admin_removeadmin",
    "/listadmins": "admin_listadmins", "الادمنز": "admin_listadmins",
}


# ═══════════════════════════════════════
# WhatsApp Search Cache
# ═══════════════════════════════════════

# Cache لنتائج بحث الواتساب
_wa_search_cache = {}  # {wa_id: {"results": [...], "query": str, "type": str, "created_at": float}}
_WA_SEARCH_CACHE_TTL = 300


# ═══════════════════════════════════════
# Arabic Character Detection
# ═══════════════════════════════════════

# Arabic character detection for prompt translation
_ARABIC_CHAR_PATTERN = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')


def _contains_arabic(text: str) -> bool:
    """Check if text contains Arabic characters"""
    return bool(_ARABIC_CHAR_PATTERN.search(text))
