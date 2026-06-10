"""
Media Download Handler
📥 /download — تحميل فيديوهات/صور/صوت من أي منصة اجتماعية
يدعم: YouTube, Facebook, Instagram, TikTok, Twitter/X, Telegram, Threads, وغيرها

🔴 FIX v3: إعادة كتابة كاملة عشان نحل مشكلة YouTube bot detection نهائياً
  - ✅ دعم ملف cookies.txt — الحل الأقوى والأضمن لتخطي bot detection
  - ✅ YouTube visitor cookies في HTTP headers (VISITOR_INFO1_LIVE, CONSENT)
  - ✅ Fallback chain أقوى: mweb → android → ios → tv → default (5 محاولات)
  - ✅ تحديث yt-dlp تلقائي عند تشغيل البوت
  - ✅ أمر /cookies للأدمن عشان يرفع ملف cookies.txt
  - ✅ رسائل خطأ أوضح مع نصائح حقيقية
  - ✅ كشف ffmpeg تلقائي وتعديل التنسيقات حسب التوفر
  - ✅ Logging مفصل عشان نقدر ن debugging
"""

import logging
import asyncio
import io
import os
import re
import hashlib
import tempfile
import shutil
import time
import subprocess
import random
import string

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from memory import get_language, increment_command_count
from premium import (
    check_limit, increment_usage, premium_required_message,
    get_premium_keyboard,
)
from dashboard import track_event
from handlers.dedup import _is_duplicate_update

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# ملف Cookies — الحل الأقوى لتخطي Bot Detection
# ═══════════════════════════════════════

_COOKIES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt")


def _get_cookies_file() -> str:
    """التحقق من وجود ملف cookies.txt وإرجاع المسار لو موجود"""
    if os.path.exists(_COOKIES_FILE):
        # نتأكد إن الملف مش فاضي
        try:
            with open(_COOKIES_FILE, 'r') as f:
                content = f.read().strip()
                if content and len(content) > 50:  # ملف صالح فيه كوكيز
                    return _COOKIES_FILE
        except Exception:
            pass
    return ""


def _cookies_status() -> dict:
    """حالة ملف الكوكيز — للأدمن يعرف إيه اللي شغال"""
    path = _get_cookies_file()
    if not path:
        return {"exists": False, "path": _COOKIES_FILE}
    try:
        size = os.path.getsize(path)
        with open(path, 'r') as f:
            lines = f.readlines()
        # عدد سطور الكوكيز الفعلي (مش تعليقات ولا سطور فاضية)
        cookie_lines = [l for l in lines if l.strip() and not l.strip().startswith('#')]
        # نبحث عن كوكيز YouTube
        yt_cookies = [l for l in cookie_lines if 'youtube.com' in l.lower()]
        return {
            "exists": True,
            "path": path,
            "size_bytes": size,
            "total_cookies": len(cookie_lines),
            "youtube_cookies": len(yt_cookies),
        }
    except Exception as e:
        return {"exists": True, "path": path, "error": str(e)}


# ═══════════════════════════════════════
# كشف الروابط - URL Detection
# ═══════════════════════════════════════

URL_PATTERNS = {
    "youtube": re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube\.com/shorts)/', re.IGNORECASE),
    "facebook": re.compile(r'(https?://)?(www\.)?(facebook\.com|fb\.watch|m\.facebook\.com)/', re.IGNORECASE),
    "instagram": re.compile(r'(https?://)?(www\.)?(instagram\.com|instagr\.am)/', re.IGNORECASE),
    "tiktok": re.compile(r'(https?://)?(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/', re.IGNORECASE),
    "twitter": re.compile(r'(https?://)?(www\.)?(twitter\.com|x\.com|t\.co)/', re.IGNORECASE),
    "telegram": re.compile(r'(https?://)?(t\.me|telegram\.me|telegram\.org)/', re.IGNORECASE),
    "threads": re.compile(r'(https?://)?(www\.)?threads\.net/', re.IGNORECASE),
    "reddit": re.compile(r'(https?://)?(www\.)?(reddit\.com|redd\.it)/', re.IGNORECASE),
    "pinterest": re.compile(r'(https?://)?(www\.)?pinterest\.(com|co)/', re.IGNORECASE),
    "vimeo": re.compile(r'(https?://)?(www\.)?vimeo\.com/', re.IGNORECASE),
    "dailymotion": re.compile(r'(https?://)?(www\.)?dailymotion\.com/', re.IGNORECASE),
    "twitch": re.compile(r'(https?://)?(www\.)?(twitch\.tv|clips\.twitch\.tv)/', re.IGNORECASE),
    "snapchat": re.compile(r'(https?://)?(www\.)?(snapchat\.com|story\.snapchat\.com)/', re.IGNORECASE),
}

GENERAL_URL_PATTERN = re.compile(r'https?://[^\s<>\"]+', re.IGNORECASE)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma', '.opus'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.m4v'}

# User-Agent عشان المنصات مش تبلوكنا
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def _detect_platform(url: str) -> str:
    """كشف المنصة من الرابط"""
    for platform, pattern in URL_PATTERNS.items():
        if pattern.search(url):
            return platform
    return "unknown"


def _is_direct_media_url(url: str) -> str:
    """كشف هل الرابط مباشر لصورة أو صوت"""
    from urllib.parse import urlparse
    parsed = urlparse(url.lower())
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in IMAGE_EXTENSIONS: return "image"
    if ext in AUDIO_EXTENSIONS: return "audio"
    if ext in VIDEO_EXTENSIONS: return "video"
    return ""


def _extract_url(text: str) -> str:
    """استخراج أول رابط من النص"""
    match = GENERAL_URL_PATTERN.search(text)
    return match.group(0) if match else ""


# ═══════════════════════════════════════
# كشف ffmpeg - FFmpeg Availability Check
# ═══════════════════════════════════════

_FFMPEG_AVAILABLE = None

def _is_ffmpeg_available() -> bool:
    """كشف هل ffmpeg متاح على النظام — نتأكد مرة واحدة بس"""
    global _FFMPEG_AVAILABLE
    if _FFMPEG_AVAILABLE is None:
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True, timeout=5
            )
            _FFMPEG_AVAILABLE = result.returncode == 0
        except Exception:
            _FFMPEG_AVAILABLE = False
        logger.info(f"🔧 FFmpeg available: {_FFMPEG_AVAILABLE}")
    return _FFMPEG_AVAILABLE


def _log_ytdlp_version():
    """تسجيل نسخة yt-dlp عشان نعرف لو محتاجة تحديث"""
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
        logger.info(f"📦 yt-dlp version: {version}")
        return version
    except Exception:
        try:
            result = subprocess.run(
                ['yt-dlp', '--version'],
                capture_output=True, timeout=5, text=True
            )
            logger.info(f"📦 yt-dlp CLI version: {result.stdout.strip()}")
            return result.stdout.strip()
        except Exception:
            logger.warning("📦 yt-dlp version could not be determined")
            return "unknown"


# ═══════════════════════════════════════
# 🔴 yt-dlp Auto-Update System v2
# - يتحدث تلقائياً كل ساعة
# - يتحدث فوراً لو YouTube رفض التحميل (bot detection)
# - يتحدث عند تشغيل البوت
# - بيستخدم --break-system-packages عشان Railway
# ═══════════════════════════════════════

_ytdlp_last_update_time = 0        # آخر مرة اتحديث فيها
_YTDLP_UPDATE_INTERVAL = 3600      # كل ساعة (3600 ثانية)
_ytdlp_updating = False            # منع تحديثات متزامنة


def _do_ytdlp_update(reason: str = "scheduled") -> bool:
    """تحديث yt-dlp — يرجع True لو اتحديث فعلاً"""
    global _ytdlp_last_update_time, _ytdlp_updating
    
    if _ytdlp_updating:
        logger.info(f"📦 yt-dlp update already in progress, skipping ({reason})")
        return False
    
    _ytdlp_updating = True
    try:
        import yt_dlp
        current_version = getattr(yt_dlp.version, '__version__', '0')
        logger.info(f"📦 yt-dlp auto-update ({reason}): current={current_version}")
        
        # التحديث باستخدام pip مع --break-system-packages (مهم لـ Railway)
        result = subprocess.run(
            [subprocess.sys.executable, '-m', 'pip', 'install', '--upgrade', 
             'yt-dlp', '--break-system-packages'],
            capture_output=True, timeout=180, text=True
        )
        
        _ytdlp_last_update_time = time.time()
        
        if result.returncode == 0:
            # نتحقق لو فعلاً اتحديث
            try:
                # لازم نعمل reload عشان النسخة الجديدة تشتغل
                import importlib
                importlib.reload(yt_dlp)
                new_version = getattr(yt_dlp.version, '__version__', 'unknown')
            except Exception:
                new_version = _log_ytdlp_version()
            
            if new_version != current_version:
                logger.info(f"📦 ✅ yt-dlp UPDATED: {current_version} → {new_version} ({reason})")
                return True
            else:
                logger.info(f"📦 yt-dlp already up to date: {current_version} ({reason})")
                return False
        else:
            logger.warning(f"📦 yt-dlp auto-update failed: {result.stderr[:300]}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"📦 yt-dlp auto-update timed out ({reason})")
        return False
    except Exception as e:
        logger.warning(f"📦 yt-dlp auto-update error: {e}")
        return False
    finally:
        _ytdlp_updating = False


def _auto_update_ytdlp():
    """تحديث yt-dlp عند تشغيل البوت"""
    _do_ytdlp_update(reason="startup")


def _ytdlp_periodic_updater():
    """تحديث yt-dlp كل ساعة في الـ background"""
    while True:
        time.sleep(_YTDLP_UPDATE_INTERVAL)
        try:
            _do_ytdlp_update(reason="hourly")
        except Exception as e:
            logger.warning(f"📦 yt-dlp periodic update error: {e}")


def trigger_ytdlp_update():
    """تحديث yt-dlp فوراً — يتنادي لو YouTube رفض التحميل
    
    يستخدمها الكود لو شاف خطأ bot detection أو sign in
    """
    import threading as _th
    _th.Thread(target=_do_ytdlp_update, args=("bot_detection",), daemon=True).start()


def should_update_ytdlp() -> bool:
    """هل محتاجين نحدث yt-dlp؟ — بنستخدمها لو التحميل فشل عشان نشوف السبب"""
    time_since_update = time.time() - _ytdlp_last_update_time
    return time_since_update > _YTDLP_UPDATE_INTERVAL


# تسجيل النسخ + تحديث تلقائي عند تشغيل الموديول
try:
    _log_ytdlp_version()
except Exception:
    pass

# 🔴 تحديث yt-dlp في الـ background عند التشغيل
import threading
try:
    _update_thread = threading.Thread(target=_auto_update_ytdlp, daemon=True)
    _update_thread.start()
    logger.info("📦 yt-dlp startup update started in background")
except Exception:
    pass

# 🔴 تحديث دوري كل ساعة في الـ background
try:
    _periodic_thread = threading.Thread(target=_ytdlp_periodic_updater, daemon=True)
    _periodic_thread.start()
    logger.info(f"📦 yt-dlp periodic updater started (every {_YTDLP_UPDATE_INTERVAL}s)")
except Exception:
    pass


# ═══════════════════════════════════════
# تخزين مؤقت للروابط - URL Cache
# ═══════════════════════════════════════

_download_urls = {}
_URL_CACHE_TTL = 600  # 10 دقائق


def _store_url(url: str) -> str:
    """تخزين الرابط وإرجاع مفتاح قصير"""
    now = time.time()
    expired = [k for k, v in _download_urls.items() if now - v["created_at"] > _URL_CACHE_TTL]
    for k in expired:
        del _download_urls[k]
    key = hashlib.md5(url.encode()).hexdigest()[:8]
    _download_urls[key] = {"url": url, "created_at": now}
    return key


def _retrieve_url(key: str) -> str:
    """استرجاع الرابط من المفتاح"""
    entry = _download_urls.get(key)
    return entry["url"] if entry else ""


# ═══════════════════════════════════════
# YouTube Visitor Cookies — يساعد يتخطى الـ Bot Detection
# ═══════════════════════════════════════

def _generate_visitor_id() -> str:
    """توليد VISITOR_INFO1_LIVE cookie — عشان YouTube يشوفنا كزائر حقيقي"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(11))


def _get_youtube_cookies_header() -> str:
    """توليد YouTube cookies header — visitor + consent + GPS"""
    visitor_id = _generate_visitor_id()
    cookies = [
        f"VISITOR_INFO1_LIVE={visitor_id}",
        "CONSENT=YES+cb.20210328-17-p0.en+FX+999",
        "GPS=1",
        "YSC=1",
        "PREF=hl=en&tz=UTC",
    ]
    return "; ".join(cookies)


# ═══════════════════════════════════════
# كيبورد اختيار الجودة
# ═══════════════════════════════════════

def _get_quality_keyboard(url: str, lang: str = "ar") -> InlineKeyboardMarkup:
    """أزرار اختيار جودة الفيديو"""
    url_key = _store_url(url)
    if lang == "ar":
        keyboard = [
            [
                InlineKeyboardButton("🎬 أعلى جودة", callback_data=f"dl_v_b_{url_key}"),
                InlineKeyboardButton("📹 جودة متوسطة", callback_data=f"dl_v_m_{url_key}"),
            ],
            [
                InlineKeyboardButton("📱 جودة منخفضة", callback_data=f"dl_v_l_{url_key}"),
                InlineKeyboardButton("🎵 صوت بس MP3", callback_data=f"dl_a_{url_key}"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🎬 Best Quality", callback_data=f"dl_v_b_{url_key}"),
                InlineKeyboardButton("📹 Medium Quality", callback_data=f"dl_v_m_{url_key}"),
            ],
            [
                InlineKeyboardButton("📱 Low Quality", callback_data=f"dl_v_l_{url_key}"),
                InlineKeyboardButton("🎵 Audio Only MP3", callback_data=f"dl_a_{url_key}"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


# ═══════════════════════════════════════
# أوامر التحميل
# ═══════════════════════════════════════

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /download <url> — تحميل فيديو/صورة/صوت من أي منصة"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    if not check_limit(user_id, "image_gen")["allowed"]:
        feature_name = "📥 تحميل وسائط / Media Download"
        await update.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    url = " ".join(context.args) if context.args else ""
    if not url:
        if lang == "ar":
            msg = """📥 <b>تحميل وسائط من أي منصة</b>

💡 <b>طريقتين:</b>
1️⃣ ابعت الرابط لوحده في الشات وهيحملهولك تلقائي!
2️⃣ أو استخدم الأمر: <code>/download الرابط</code>

<b>المنصات المدعومة:</b>
→ YouTube, Facebook, Instagram
→ TikTok, Twitter/X, Telegram
→ Threads, Reddit, Vimeo
→ وأي منصة تانية!

⭐ الميزة دي للمشتركين Premium بس"""
        else:
            msg = """📥 <b>Download Media from Any Platform</b>

💡 <b>Two ways:</b>
1️⃣ Just paste the URL in chat and it will auto-download!
2️⃣ Or use the command: <code>/download URL</code>

<b>Supported Platforms:</b>
→ YouTube, Facebook, Instagram
→ TikTok, Twitter/X, Telegram
→ Threads, Reddit, Vimeo
→ And many more!

⭐ This feature is Premium only"""
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    await _process_download_request(update, context, url, lang, user_id)


async def _process_download_request(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, lang: str, user_id: int):
    """معالجة طلب التحميل"""
    platform = _detect_platform(url)
    direct_type = _is_direct_media_url(url)
    
    if direct_type == "image":
        await _download_direct_image(update, url, lang, user_id)
        return
    if direct_type == "audio":
        await _download_direct_audio(update, url, lang, user_id)
        return
    if direct_type == "video":
        await _download_with_ytdlp(update, url, "best", lang, user_id)
        return
    
    platform_names = {
        "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
        "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
        "threads": "Threads", "reddit": "Reddit", "pinterest": "Pinterest",
        "vimeo": "Vimeo", "dailymotion": "Dailymotion", "twitch": "Twitch",
        "snapchat": "Snapchat", "unknown": "🌐",
    }
    platform_display = platform_names.get(platform, platform)
    keyboard = _get_quality_keyboard(url, lang)
    
    if lang == "ar":
        msg = f"📥 <b>تحميل من {platform_display}</b>\n\n🔗 <code>{url[:80]}{'...' if len(url) > 80 else ''}</code>\n\nاختر الجودة اللي عايزها:"
    else:
        msg = f"📥 <b>Download from {platform_display}</b>\n\n🔗 <code>{url[:80]}{'...' if len(url) > 80 else ''}</code>\n\nChoose the quality you want:"
    
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)


# ═══════════════════════════════════════
# تحميل مباشر (صور/صوت)
# ═══════════════════════════════════════

async def _download_direct_image(update: Update, url: str, lang: str, user_id: int):
    """تحميل صورة مباشرة من رابط"""
    import aiohttp
    if lang == "ar":
        status_msg = await update.message.reply_text("⏳ جاري تحميل الصورة...")
    else:
        status_msg = await update.message.reply_text("⏳ Downloading image...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    await status_msg.edit_text("❌ فشل تحميل الصورة." if lang == "ar" else "❌ Failed to download image.")
                    return
                image_bytes = await resp.read()
        increment_usage(user_id, "image_analyses")
        try: track_event("media_downloads")
        except: pass
        await status_msg.delete()
        await update.message.reply_photo(
            photo=io.BytesIO(image_bytes),
            caption=f"📥 {'تم تحميل الصورة!' if lang == 'ar' else 'Image downloaded!'}\n🔗 <code>{url[:100]}</code>",
            parse_mode="HTML",
        )
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ انتهى وقت تحميل الصورة." if lang == "ar" else "❌ Image download timed out.")
    except Exception as e:
        logger.error(f"Error downloading direct image: {e}")
        await status_msg.edit_text("❌ فشل تحميل الصورة. جرب تاني." if lang == "ar" else "❌ Failed to download image. Try again.")


async def _download_direct_audio(update: Update, url: str, lang: str, user_id: int):
    """تحميل صوت مباشر من رابط"""
    import aiohttp
    if lang == "ar":
        status_msg = await update.message.reply_text("⏳ جاري تحميل الصوت...")
    else:
        status_msg = await update.message.reply_text("⏳ Downloading audio...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    await status_msg.edit_text("❌ فشل تحميل الصوت." if lang == "ar" else "❌ Failed to download audio.")
                    return
                audio_bytes = await resp.read()
        increment_usage(user_id, "youtube_summaries")
        try: track_event("media_downloads")
        except: pass
        from urllib.parse import urlparse, unquote
        filename = os.path.basename(unquote(urlparse(url).path)) or "audio.mp3"
        await status_msg.delete()
        await update.message.reply_audio(
            audio=io.BytesIO(audio_bytes), filename=filename,
            caption=f"📥 {'تم تحميل الصوت!' if lang == 'ar' else 'Audio downloaded!'}\n🔗 <code>{url[:100]}</code>",
            parse_mode="HTML",
        )
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ انتهى وقت تحميل الصوت." if lang == "ar" else "❌ Audio download timed out.")
    except Exception as e:
        logger.error(f"Error downloading direct audio: {e}")
        await status_msg.edit_text("❌ فشل تحميل الصوت. جرب تاني." if lang == "ar" else "❌ Failed to download audio. Try again.")


# ═══════════════════════════════════════
# Cobalt Public API — لليوتيوب بس (بدل yt-dlp)
# ═══════════════════════════════════════

# 🔴 استراتيجية جديدة: أي رابط YouTube (youtube.com, youtu.be, youtube.com/shorts)
# بنستخدم Cobalt Public API بدل yt-dlp تماماً
# السبب: yt-dlp بيتحجب باستمرار من YouTube (bot detection)
# Cobalt Public API أسرع وأضمن لليوتيوب

_COBALT_PUBLIC_API = "https://api.cobalt.tools/api/json"

_YOUTUBE_URL_PATTERN = re.compile(
    r'(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube\.com/shorts)/',
    re.IGNORECASE
)


def _is_youtube_url(url: str) -> bool:
    """فحص هل الرابط يوتيوب — يشمل youtube.com, youtu.be, youtube.com/shorts"""
    return bool(_YOUTUBE_URL_PATTERN.search(url))


async def _try_cobalt_for_youtube(url: str, quality: str, tmpdir: str) -> dict | None:
    """تحميل فيديو يوتيوب عبر Cobalt API — Self-Hosted أولاً ثم Public
    
    🔴 بيتعمل ليوتيوب بس — باقي المنصات شغالة بـ yt-dlp زي ما هي
    
    Cobalt API بيشتغل كالتالي:
    - POST للـ API endpoint
    - Payload: {"url": video_url, "vQuality": "720", "filenamePattern": "classic"}
    - لو status == "stream" / "redirect" / "tunnel" → رجّع الـ url
    - لو status == "picker" → رجّع أول رابط في القائمة
    
    يرجع dict فيه:
    - filepath: مسار الملف المحمل
    - filename: اسم الملف
    - title: عنوان الفيديو
    - duration: المدة
    - size: حجم الملف
    
    أو None لو فشل
    """
    import aiohttp
    
    # تحويل الجودة لصيغة Cobalt
    quality_map = {
        "best": "1080",
        "medium": "720",
        "low": "480",
        "audio": "720",  # الجودة مش مهمة للأوديو
    }
    v_quality = quality_map.get(quality, "720")
    
    is_audio = quality == "audio"
    
    # ═══ محاولة 1: Self-Hosted Cobalt (COBALT_API_URL) ═══
    # لو عندنا سيرفر Cobalt شغال — ده الأضمن
    try:
        from config import COBALT_API_URL, COBALT_API_KEY
        
        if COBALT_API_URL:
            api_url = COBALT_API_URL.rstrip("/")
            
            # v8 format for self-hosted
            payload = {
                "url": url,
                "videoQuality": v_quality,
                "downloadMode": "audio" if is_audio else "auto",
                "audioFormat": "mp3" if is_audio else "best",
                "filenameStyle": "classic",
                "youtubeVideoCodec": "h264",
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            
            if COBALT_API_KEY:
                headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
            
            logger.info(f"🟠 Cobalt Self-Hosted: requesting download for {url[:80]} (quality={v_quality}, audio={is_audio})")
            
            result = await _cobalt_api_request(api_url, payload, headers, v_quality, is_audio, tmpdir)
            if result:
                return result
            
            logger.warning(f"⚠️ Cobalt Self-Hosted failed, trying next...")
    except Exception as e:
        logger.warning(f"⚠️ Cobalt Self-Hosted error: {e}")
    
    # ═══ محاولة 2: Cobalt Public API (api.cobalt.tools) ═══
    # الـ API الرسمي محتاج API key (JWT) — بنستخدم الـ COBALT_API_KEY لو متاح
    try:
        from config import COBALT_API_KEY
        
        public_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        if COBALT_API_KEY:
            public_headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
        
        # v8 format for public API
        public_payload = {
            "url": url,
            "videoQuality": v_quality,
            "filenameStyle": "classic",
        }
        
        if is_audio:
            public_payload["downloadMode"] = "audio"
            public_payload["audioFormat"] = "mp3"
        
        logger.info(f"🟠 Cobalt Public API: requesting download for {url[:80]}")
        
        result = await _cobalt_api_request("https://api.cobalt.tools", public_payload, public_headers, v_quality, is_audio, tmpdir)
        if result:
            return result
        
        logger.warning(f"⚠️ Cobalt Public API failed")
    except Exception as e:
        logger.warning(f"⚠️ Cobalt Public API error: {e}")
    
    # كل المحاولات فشلت
    logger.warning(f"🟠 All Cobalt methods failed for {url[:80]}")
    return None


async def _cobalt_api_request(api_url: str, payload: dict, headers: dict, 
                               v_quality: str, is_audio: bool, tmpdir: str) -> dict | None:
    """طلب تحميل من أي Cobalt API endpoint — مشتركة بين Self-Hosted و Public
    
    Args:
        api_url: رابط الـ API (بدون trailing slash)
        payload: الـ request payload
        headers: الـ request headers
        v_quality: الجودة (720, 1080, 480)
        is_audio: هل تحميل صوت
        tmpdir: مجلد التحميل المؤقت
    """
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            # الخطوة 1: طلب رابط التحميل من Cobalt
            async with session.post(
                f"{api_url}/",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    resp_text = await resp.text()
                    logger.warning(f"🟠 Cobalt: API returned status {resp.status}: {resp_text[:200]}")
                    return None
                
                data = await resp.json()
            
            status = data.get("status", "")
            
            if status == "error":
                error_code = data.get("error", {})
                if isinstance(error_code, dict):
                    error_code = error_code.get("code", "unknown")
                logger.warning(f"🟠 Cobalt: error response: {error_code}")
                return None
            
            download_url = None
            filename = None
            
            if status in ("stream", "redirect", "tunnel"):
                # رابط مباشر للفيديو
                download_url = data.get("url")
                filename = data.get("filename", "")
            elif status == "picker":
                # محتوى متعدد (carousel, shorts playlist, إلخ)
                picker_items = data.get("picker", [])
                audio_url = data.get("audio")
                if picker_items:
                    # نختار أول عنصر — زي ما المستخدم طلب
                    download_url = picker_items[0].get("url")
                    filename = data.get("filename", "")
                elif audio_url:
                    download_url = audio_url
                    filename = data.get("audioFilename", "audio.mp3")
            else:
                logger.warning(f"🟠 Cobalt: unknown status '{status}'")
                return None
            
            if not download_url:
                logger.warning("🟠 Cobalt: no download URL in response")
                return None
            
            logger.info(f"🟠 Cobalt: got download URL, downloading file...")
            
            # الخطوة 2: تحميل الملف من الرابط
            ext = "mp3" if is_audio else "mp4"
            if not filename:
                filename = f"youtube_download.{ext}"
            # تنظيف اسم الملف
            filename = re.sub(r'[^\w\-.]', '_', filename)
            if not filename.endswith(ext):
                filename = f"{filename.rsplit('.', 1)[0] if '.' in filename else filename}.{ext}"
            
            filepath = os.path.join(tmpdir, filename)
            
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 دقائق للملفات الكبيرة
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.warning(f"🟠 Cobalt: download URL returned status {dl_resp.status}")
                    return None
                
                content_length = dl_resp.headers.get("Content-Length", "unknown")
                logger.info(f"🟠 Cobalt: downloading file (size: {content_length} bytes)...")
                
                with open(filepath, 'wb') as f:
                    async for chunk in dl_resp.content.iter_chunked(8192):
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                logger.warning("🟠 Cobalt: downloaded file is empty")
                os.remove(filepath)
                return None
            
            logger.info(f"🟠 Cobalt: download succeeded! Size: {file_size // (1024*1024)}MB")
            
            return {
                "filepath": filepath,
                "filename": filename,
                "title": filename.rsplit('.', 1)[0] if filename else "YouTube Video",
                "duration": 0,
                "height": int(v_quality) if v_quality.isdigit() else 720,
                "size": file_size,
                "method": "cobalt",
            }
    
    except asyncio.TimeoutError:
        logger.warning("🟠 Cobalt: request timed out")
        return None
    except Exception as e:
        logger.warning(f"🟠 Cobalt: error: {e}")
        return None


# ═══════════════════════════════════════
# تحميل بـ Cobalt Self-Hosted (طبقة إضافية)
# ═══════════════════════════════════════

# 🔴 Cobalt Self-Hosted: طبقة إضافية لو الـ Public API فشل
# بنشغله على سيرفر Railway منفصل ونربطه بالبوت

async def _try_cobalt_download(url: str, quality: str, tmpdir: str) -> dict | None:
    """تحميل فيديو/صوت عبر Cobalt Self-Hosted API
    
    يرجع dict فيه:
    - filepath: مسار الملف المحمل
    - filename: اسم الملف
    - title: عنوان الفيديو (لو موجود)
    - duration: المدة (لو موجودة)
    
    أو None لو فشل
    """
    import aiohttp
    from config import COBALT_API_URL, COBALT_API_KEY
    
    if not COBALT_API_URL:
        logger.info("🔵 Cobalt: COBALT_API_URL not set, skipping")
        return None
    
    api_url = COBALT_API_URL.rstrip("/")
    
    # تحويل الجودة لصيغة Cobalt
    quality_map = {
        "best": "1080",
        "medium": "720",
        "low": "480",
        "audio": "720",  # الجودة مش مهمة للأوديو
    }
    cobalt_quality = quality_map.get(quality, "1080")
    
    is_audio = quality == "audio"
    
    payload = {
        "url": url,
        "videoQuality": cobalt_quality,
        "downloadMode": "audio" if is_audio else "auto",
        "audioFormat": "mp3" if is_audio else "best",
        "audioBitrate": "128",
        "filenameStyle": "basic",
        "youtubeVideoCodec": "h264",  # هام لتوافق Telegram/WhatsApp
        "youtubeVideoContainer": "mp4" if not is_audio else "auto",
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    if COBALT_API_KEY:
        headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
    
    logger.info(f"🔵 Cobalt: requesting download for {url[:80]} (quality={cobalt_quality}, audio={is_audio})")
    
    try:
        async with aiohttp.ClientSession() as session:
            # الخطوة 1: طلب رابط التحميل من Cobalt
            async with session.post(
                f"{api_url}/",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"🔵 Cobalt: API returned status {resp.status}")
                    return None
                
                data = await resp.json()
            
            status = data.get("status", "")
            
            if status == "error":
                error_code = data.get("error", {}).get("code", "unknown")
                logger.warning(f"🔵 Cobalt: error response: {error_code}")
                return None
            
            download_url = None
            filename = None
            picker_items = None
            
            if status in ("tunnel", "redirect"):
                download_url = data.get("url")
                filename = data.get("filename", "")
            elif status == "picker":
                # Instagram carousel أو محتوى متعدد
                picker_items = data.get("picker", [])
                audio_url = data.get("audio")
                # نختار أول فيديو من الـ picker
                if picker_items:
                    for item in picker_items:
                        if item.get("type") == "video":
                            download_url = item.get("url")
                            break
                    if not download_url and picker_items:
                        download_url = picker_items[0].get("url")
                elif audio_url:
                    download_url = audio_url
                    filename = data.get("audioFilename", "audio.mp3")
            elif status == "local-processing":
                # Cobalt بيعمل merge محلي — نحتاج نستنى
                tunnel_urls = data.get("tunnel", [])
                output_info = data.get("output", {})
                filename = output_info.get("filename", "")
                if tunnel_urls:
                    download_url = tunnel_urls[0]
            else:
                logger.warning(f"🔵 Cobalt: unknown status '{status}'")
                return None
            
            if not download_url:
                logger.warning("🔵 Cobalt: no download URL in response")
                return None
            
            logger.info(f"🔵 Cobalt: got download URL, downloading file...")
            
            # الخطوة 2: تحميل الملف من رابط الـ tunnel
            ext = "mp3" if is_audio else "mp4"
            if not filename:
                filename = f"cobalt_download.{ext}"
            
            filepath = os.path.join(tmpdir, filename)
            
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 دقائق للملفات الكبيرة
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.warning(f"🔵 Cobalt: download URL returned status {dl_resp.status}")
                    return None
                
                content_length = dl_resp.headers.get("Content-Length", "unknown")
                logger.info(f"🔵 Cobalt: downloading file (size: {content_length} bytes)...")
                
                with open(filepath, 'wb') as f:
                    async for chunk in dl_resp.content.iter_chunked(8192):
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                logger.warning("🔵 Cobalt: downloaded file is empty")
                os.remove(filepath)
                return None
            
            logger.info(f"🔵 Cobalt: download succeeded! Size: {file_size // (1024*1024)}MB")
            
            return {
                "filepath": filepath,
                "filename": filename,
                "title": filename.rsplit('.', 1)[0] if filename else "Video",
                "duration": 0,
                "height": int(cobalt_quality) if cobalt_quality.isdigit() else 720,
                "size": file_size,
                "method": "cobalt",
            }
    
    except asyncio.TimeoutError:
        logger.warning("🔵 Cobalt: request timed out")
        return None
    except Exception as e:
        logger.warning(f"🔵 Cobalt: error: {e}")
        return None


# ═══════════════════════════════════════
# تحميل بـ yt-dlp (مُحسّن بالكامل v5)
# ═══════════════════════════════════════

# 🔴 FIX v5: إعداد deno + remote_components
# yt-dlp 2025+ محتاج JavaScript runtime (deno) عشان يحل YouTube challenges
# بدونه، مبنقدرش نحصل على كل التنسيقات

_DENO_PATH = os.path.expanduser('~/.deno/bin/deno')


def _ensure_deno_in_path():
    """إضافة deno للـ PATH عشان yt-dlp يقدر يستخدمه"""
    deno_dir = os.path.dirname(_DENO_PATH)
    current_path = os.environ.get('PATH', '')
    if deno_dir not in current_path:
        os.environ['PATH'] = f"{deno_dir}:{current_path}"
        logger.info(f"🔧 Added deno to PATH: {deno_dir}")


# إضافة deno للـ PATH عند تحميل الموديول
try:
    _ensure_deno_in_path()
    if os.path.exists(_DENO_PATH):
        logger.info(f"🔧 Deno found: {_DENO_PATH}")
except Exception:
    pass


# 🔴 FIX v5: YouTube player_client fallback order
# الطريقة الأساسية: بدون player_client (الافتراضي) + deno + remote_components
# ده بيدي أحسن نتيجة (37 تنسيق لحد 1080p)
# player_client بنستخدمه كـ fallback بس لو الطريقة الأساسية فشلت
_YOUTUBE_PLAYER_CLIENTS = [
    ['android', 'web'],    # Android client — fallback أول
    ['ios', 'web'],        # iOS client
    ['mweb', 'web'],       # Mobile Web
    ['tv', 'web'],         # TV client
    ['web'],               # Default web — آخر حل
]


def _get_ydl_opts(quality: str, output_template: str, platform: str = "", 
                  use_ffmpeg: bool = True, player_client_idx: int = 0) -> dict:
    """إعداد خيارات yt-dlp حسب الجودة والمنصة وتوفر ffmpeg
    
    🔴 FIX v3: 
    - بنضيف cookies.txt لو موجود — الحل الأقوى لتخطي bot detection
    - بنضيف YouTube visitor cookies في الـ HTTP headers
    - بنستخدم player_client=mweb أولاً (أقل كشف) مع fallback لـ android → ios → tv → web
    - بنكشف ffmpeg تلقائي وبنعدل التنسيقات حسب التوفر
    """
    ffmpeg_ok = use_ffmpeg and _is_ffmpeg_available()
    
    # 🔴 FIX v5: لا نضيف كوكيز وهمية لليوتيوب!
    # الكوكيز الوهمية (visitor cookies) بتضر أكتر مما تنفع لأن:
    # 1. YouTube بيكتشف إنها random/generated وبيعتبرنا bot
    # 2. كل محاولة بتولد visitor_id مختلف = سلوك مش طبيعي
    # 3. yt-dlp بيدير كوكيز YouTube داخلياً حسب player_client
    # بنستخدم الكوكيز الوهمية بس للمنصات التانية
    
    platform_lower = platform.lower()
    is_youtube = platform_lower == "youtube"
    
    if is_youtube:
        # YouTube — بدون Cookie header (yt-dlp بيدير الكوكيز داخلياً)
        headers = {
            'User-Agent': _USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
        }
    else:
        # باقي المنصات — نضيف كوكيز وهمية عادية
        yt_cookies = _get_youtube_cookies_header()
        headers = {
            'User-Agent': _USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Cookie': yt_cookies,
        }
    
    # إعدادات مشتركة
    common_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 3,
        'file_access_retries': 3,
        'extractor_retries': 3,
        'no_check_certificates': True,
        'http_headers': headers,
    }
    
    # 🔴 FIX: ملف cookies.txt — الحل الأقوى
    cookies_path = _get_cookies_file()
    if cookies_path:
        common_opts['cookiefile'] = cookies_path
        logger.info(f"🍪 Using cookies file: {cookies_path}")
    
    # 🔴 FIX v5: استراتيجية YouTube جديدة
    # الطريقة الأساسية: بدون player_client + deno + remote_components
    # ده بيدي 37 تنسيق لحد 1080p بدون ما YouTube يعتبرنا bot
    # player_client بنستخدمه كـ fallback بس
    
    if is_youtube or platform_lower == "":
        # 🔴 إضافة deno للـ PATH
        _ensure_deno_in_path()
        
        if player_client_idx == 0:
            # المحاولة الأولى: بدون player_client + deno + remote_components
            # ده الأفضل — بيدي كل التنسيقات
            common_opts['remote_components'] = ['ejs:github']
            # لا نضيف player_client خالص — نخلي yt-dlp يستخدم الطريقة الافتراضية
            logger.info("🔧 YouTube: default mode + deno + remote_components (best method)")
        else:
            # Fallback: نستخدم player_client محدد
            if player_client_idx - 1 < len(_YOUTUBE_PLAYER_CLIENTS):
                pc = _YOUTUBE_PLAYER_CLIENTS[player_client_idx - 1]
            else:
                pc = _YOUTUBE_PLAYER_CLIENTS[-1]
            common_opts['extractor_args'] = {'youtube': {'player_client': pc}}
            logger.info(f"🔧 YouTube player_client fallback: {pc} (attempt {player_client_idx + 1})")
    elif platform_lower == "tiktok":
        common_opts['extractor_args'] = {'tiktok': {'api_hostname': 'api22-normal-c-useast2a.tiktokv.com'}}
    
    # 🔴 FIX v4: إعدادات حسب نوع المحتوى
    if quality == "audio":
        if ffmpeg_ok:
            opts = {
                **common_opts,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        else:
            opts = {
                **common_opts,
                'format': 'bestaudio/best',
            }
    else:
        # ═══ فيديو ═══
        # 🔴 FIX v4: format strings بتفضل h264 (avc1) عشان Telegram
        # Telegram مش بيشغل VP9/AV1 — لازم h264 + aac في mp4
        #
        # vcodec^=avc1 = h264 video codec (اللي Telegram بيشغله)
        # بنحط h264 الأول، وبعدين fallback لـ أي mp4، وبعدين best
        #
        # Facebook/Instagram مش بيوفر separate video+audio دايماً
        # فبنفضل pre-merged formats (best[ext=mp4]) عشان نتجنب مشاكل الدمج
        
        is_facebook_family = platform_lower in ("facebook", "instagram", "threads")
        
        if ffmpeg_ok:
            if is_facebook_family:
                # 🔴 FIX v5: Facebook family — بنفضل pre-merged formats بقوة عشان:
                # 1. Facebook بيوفر فيديوهات pre-merged بجودة عالية
                # 2. دمج separate streams من Facebook بيدي فيديو شاشة سوداء
                # 3. Pre-merged بتكون h264 جاهزة للتليجرام
                # 4. بنحط pre-mergedmp4 الأول دايماً عشان نتجنب مشاكل الدمج
                format_map = {
                    "best": (
                        # 🔴 pre-merged mp4 الأول — أضمن حل للشاشة السوداء
                        "best[ext=mp4][height<=1080]/"
                        # h264 separate + audio
                        "bestvideo[vcodec^=avc1][height<=1080]+bestaudio/"
                        # أي pre-merged mp4
                        "best[ext=mp4]/"
                        # أي h264 video + audio
                        "bestvideo[vcodec^=avc1]+bestaudio/"
                        # أي mp4 video + audio
                        "bestvideo[ext=mp4]+bestaudio/"
                        # آخر حل
                        "best"
                    ),
                    "medium": (
                        "best[ext=mp4][height<=720]/"
                        "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
                        "best[ext=mp4][height<=720]/"
                        "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
                        "bestvideo[ext=mp4][height<=720]+bestaudio/"
                        "best[height<=720]/"
                        "best"
                    ),
                    "low": (
                        "best[ext=mp4][height<=480]/"
                        "bestvideo[vcodec^=avc1][height<=480]+bestaudio/"
                        "best[ext=mp4][height<=480]/"
                        "bestvideo[vcodec^=avc1][height<=480]+bestaudio/"
                        "bestvideo[ext=mp4][height<=480]+bestaudio/"
                        "best[height<=480]/"
                        "best"
                    ),
                }
            else:
                # YouTube + باقي المنصات — بنفضل h264 بشكل واضح
                format_map = {
                    "best": (
                        # 1. h264 video + aac audio في mp4 (أفضل للتليجرام)
                        "bestvideo[vcodec^=avc1][ext=mp4][height<=1080]+bestaudio[ext=m4a]/"
                        "bestvideo[vcodec^=avc1]+bestaudio/"
                        # 2. أي mp4 video + audio
                        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/"
                        "bestvideo[ext=mp4]+bestaudio/"
                        # 3. Pre-merged mp4
                        "best[ext=mp4]/"
                        # 4. آخر حل: أي حاجة
                        "best"
                    ),
                    "medium": (
                        "bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[ext=m4a]/"
                        "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
                        "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/"
                        "bestvideo[ext=mp4][height<=720]+bestaudio/"
                        "best[ext=mp4][height<=720]/"
                        "best[height<=720]/"
                        "best"
                    ),
                    "low": (
                        "bestvideo[vcodec^=avc1][ext=mp4][height<=480]+bestaudio[ext=m4a]/"
                        "bestvideo[vcodec^=avc1][height<=480]+bestaudio/"
                        "bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/"
                        "bestvideo[ext=mp4][height<=480]+bestaudio/"
                        "best[ext=mp4][height<=480]/"
                        "best[height<=480]/"
                        "best"
                    ),
                }
            
            opts = {
                **common_opts,
                'format': format_map.get(quality, format_map["best"]),
                'merge_output_format': 'mp4',
                # 🔴 FIX v4: remux_video يضمن إن الحاوية mp4 حتى لو المنصة بترجع webm
                'remux_video': 'mp4',
            }
        else:
            # مش موجود ffmpeg → تنسيقات بسيطة (pre-merged)
            format_map = {
                "best": "best[ext=mp4]/best",
                "medium": "best[ext=mp4][height<=720]/best[height<=720]/best",
                "low": "best[ext=mp4][height<=480]/best[height<=480]/best",
            }
            opts = {
                **common_opts,
                'format': format_map.get(quality, format_map["best"]),
            }
    
    return opts


async def _download_with_ytdlp(update_or_query, url: str, quality: str, lang: str, user_id: int, status_msg=None):
    """تحميل فيديو أو صوت — مُحسّن v7 مع Invidious + Cobalt
    
    🔴 FIX v7: Fallback chain جديدة مع Invidious:
    -1. 🟢 YouTube RapidAPI (الأولوية القصوى لليوتيوب)
    0. 🟣 Invidious API (طبقة جديدة — مجانية ومش بتتأثر بـ bot detection)
    1. 🔵 Cobalt Self-Hosted
    2. yt-dlp default + deno + remote_components
    3. yt-dlp player_client fallback chain (android → ios → mweb → tv → web)
    4. yt-dlp بدون كوكيز
    5. Cloudflare Worker
    6. تنسيق أبسط (best)
    7. صوت بس لو كل حاجة فشلت
    """
    # تحديد الرسالة
    if hasattr(update_or_query, 'message'):
        message = update_or_query.message
    else:
        message = update_or_query.message
    
    # كشف المنصة عشان نستخدم إعداداتها
    platform = _detect_platform(url)
    is_youtube = _is_youtube_url(url)  # 🔴 FIX: لازم نعرّف is_youtube هنا عشان الكود اللي بعد كده يستخدمه
    ffmpeg_ok = _is_ffmpeg_available()
    cookies_available = bool(_get_cookies_file())
    
    logger.info(f"📥 Download request: platform={platform}, quality={quality}, ffmpeg={ffmpeg_ok}, cookies={cookies_available}, url={url[:80]}")
    
    tmpdir = tempfile.mkdtemp(prefix="mybro_dl_")
    
    try:
        if not status_msg:
            if lang == "ar":
                status_msg = await message.reply_text("⏳ جاري التحميل...")
            else:
                status_msg = await message.reply_text("⏳ Downloading...")
        
        output_template = os.path.join(tmpdir, "%(title).100s.%(ext)s")
        
        # تحديث رسالة الحالة
        if quality == "audio":
            status_text = "🎵 جاري تحميل الصوت..." if lang == "ar" else "🎵 Downloading audio..."
        else:
            quality_names = {"best": "عالية", "medium": "متوسطة", "low": "منخفضة"} if lang == "ar" else {"best": "high", "medium": "medium", "low": "low"}
            q_name = quality_names.get(quality, quality)
            status_text = f"🎬 جاري تحميل الفيديو بجودة {q_name}..." if lang == "ar" else f"🎬 Downloading video in {q_name} quality..."
        
        try:
            await status_msg.edit_text(status_text)
        except Exception:
            pass
        
        # ═══ المرحلة -1: Cobalt Public API (لليوتيوب بس — الأولوية القصوى!) ═══
        # 🟠 أي رابط يوتيوب → نستخدم Cobalt Public API بدل yt-dlp
        # ده أسرع وأضمن لأن yt-dlp بيتحجب باستمرار من YouTube
        # لو مش يوتيوب → نتخطى ونكمل بـ yt-dlp عادي
        cobalt_public_result = None
        
        if is_youtube:
            try:
                logger.info(f"🟠 Cobalt Public: YouTube detected — using Cobalt Public API instead of yt-dlp")
                
                try:
                    await status_msg.edit_text(
                        "🟠 جاري التحميل عبر Cobalt..." if lang == "ar"
                        else "🟠 Downloading via Cobalt..."
                    )
                except:
                    pass
                
                cobalt_public_result = await _try_cobalt_for_youtube(url, quality, tmpdir)
                
                if cobalt_public_result and cobalt_public_result.get("filepath"):
                    logger.info(f"🟠 Cobalt Public succeeded! File: {cobalt_public_result['filepath']}")
                    
                    file_path = cobalt_public_result["file_path"] if "file_path" in cobalt_public_result else cobalt_public_result["filepath"]
                    file_size = cobalt_public_result.get("size", os.path.getsize(file_path))
                    video_title = cobalt_public_result.get("title", "YouTube Video")
                    video_height = cobalt_public_result.get("height", 720)
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # تتبع الاستخدام
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    # إرسال الملف
                    if quality == "audio":
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الصوت!' if lang == 'ar' else 'Audio downloaded!'}\n🎵 {video_title[:200]}\n📁 {size_str} | Cobalt"
                                await message.reply_audio(
                                    audio=f, filename=f"{video_title[:50]}.mp3",
                                    caption=caption,
                                    parse_mode="HTML",
                                )
                        except Exception as send_err:
                            logger.warning(f"⚠️ Cobalt audio send failed: {send_err}")
                            await message.reply_text(
                                f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send audio ({size_str}). Try again!"
                            )
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                tech_info = f"{video_height}p | {size_str} | Cobalt"
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {video_title[:200]}\n📊 {tech_info}"
                                await message.reply_video(
                                    video=f, filename=f"{video_title[:50]}.mp4",
                                    caption=caption,
                                    parse_mode="HTML",
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            logger.warning(f"⚠️ Cobalt video send failed (likely too large): {send_err}")
                            if quality != "low" and quality != "audio":
                                if lang == "ar":
                                    await message.reply_text(f"⚠️ الملف كبير ({size_str}). جرب جودة أقل!")
                                else:
                                    await message.reply_text(f"⚠️ File too large ({size_str}). Try a lower quality!")
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                    else f"❌ Failed to send video ({size_str}). Try again!"
                                )
                    
                    # تنظيف الملف
                    try: os.remove(file_path)
                    except: pass
                    
                    return  # ✅ Cobalt Public نجح وخلاص!
                
                else:
                    # Cobalt Public فشل — نكمل بالطرق العادية (Invidious → yt-dlp)
                    logger.warning(f"⚠️ Cobalt Public failed, falling back to Invidious/yt-dlp...")
                    cobalt_public_result = None
                    
            except Exception as cp_err:
                logger.warning(f"⚠️ Cobalt Public error: {cp_err}, falling back to Invidious/yt-dlp...")
                cobalt_public_result = None
        
        # ═══ المرحلة -0.5: Invidious API Fallback (طبقة إضافية لليوتيوب) ═══
        # 🟣 Invidious: واجهة بديلة لليوتيوب — مجانية ومفتوحة
        # الميزة الرئيسية: مش بتتأثر بـ YouTube bot detection خالص
        # الطلبات بتروح لسيرفرات Invidious مش من الـ IP بتاعك
        # بنستخدمه لليوتيوب بس — المنصات التانية شغالة مع yt-dlp عادي
        invidious_result = None
        is_youtube = platform.lower() == "youtube"
        
        if is_youtube:
            try:
                from invidious_api import download_youtube_invidious_file
                
                # تحويل جودة التليجرام لجودة Invidious
                inv_quality_map = {
                    "best": "best",
                    "medium": "medium",
                    "low": "low",
                    "audio": "audio",
                }
                inv_quality = inv_quality_map.get(quality, "best")
                
                logger.info(f"🟣 Invidious: Attempting download quality={inv_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟣 جاري التحميل عبر Invidious..." if lang == "ar"
                        else "🟣 Downloading via Invidious..."
                    )
                except:
                    pass
                
                # 🔴 timeout 60 ثانية — لو Invidious بطيء نروح Cobalt/yt-dlp
                try:
                    invidious_result = await asyncio.wait_for(
                        download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                        timeout=60
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Invidious timed out after 60s, falling back to Cobalt/yt-dlp")
                    invidious_result = None
                
                if invidious_result and invidious_result.get("success") and invidious_result.get("file_path"):
                    logger.info(f"🟣 Invidious succeeded! File: {invidious_result['file_path']}")
                    
                    file_path = invidious_result["file_path"]
                    file_size = invidious_result.get("file_size", os.path.getsize(file_path))
                    real_title = invidious_result.get("title", "YouTube Video")
                    real_duration = invidious_result.get("duration", 0)
                    format_info = invidious_result.get("format_info", {})
                    
                    # تحديد الجودة الحقيقية
                    quality_label = format_info.get("quality_label", "") or format_info.get("resolution", "")
                    if not quality_label:
                        if quality == "audio":
                            quality_label = "MP3"
                        else:
                            quality_label = f"{inv_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # تتبع الاستخدام
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    # إرسال الملف
                    if quality == "audio":
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الصوت!' if lang == 'ar' else 'Audio downloaded!'}\n🎵 {real_title[:200]}\n📁 {size_str} | Invidious"
                                await message.reply_audio(
                                    audio=f, filename=f"{real_title[:50]}.mp3",
                                    caption=caption,
                                    parse_mode="HTML",
                                )
                        except Exception as send_err:
                            logger.warning(f"⚠️ Invidious audio send failed: {send_err}")
                            await message.reply_text(
                                f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send audio ({size_str}). Try again!"
                            )
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                tech_info = f"{quality_label} | {size_str} | Invidious"
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {real_title[:200]}\n📊 {tech_info}"
                                await message.reply_video(
                                    video=f, filename=f"{real_title[:50]}.mp4",
                                    caption=caption,
                                    parse_mode="HTML",
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            logger.warning(f"⚠️ Invidious video send failed (likely too large): {send_err}")
                            if quality != "low" and quality != "audio":
                                if lang == "ar":
                                    await message.reply_text(f"⚠️ الملف كبير ({size_str}). جرب جودة أقل!")
                                else:
                                    await message.reply_text(f"⚠️ File too large ({size_str}). Try a lower quality!")
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                    else f"❌ Failed to send video ({size_str}). Try again!"
                                )
                    
                    # تنظيف الملف
                    try: os.remove(file_path)
                    except: pass
                    
                    return  # ✅ Invidious نجح وخلاص!
                
                else:
                    # Invidious فشل — نكمل بالطرق العادية
                    error_code = invidious_result.get("error", "unknown") if invidious_result else "unknown"
                    logger.warning(f"⚠️ Invidious failed ({error_code}), falling back to Cobalt/yt-dlp...")
                    invidious_result = None
                    
            except ImportError:
                logger.warning("⚠️ invidious_api module not available, skipping Invidious")
            except Exception as inv_err:
                logger.warning(f"⚠️ Invidious error: {inv_err}, falling back to Cobalt/yt-dlp...")
        
        # ═══ المرحلة 0: Cobalt Self-Hosted ═══
        # 🔵 طريقة تانية — بيشتغل على سيرفر منفصل ومش بيتأثر بـ bot detection
        # 🔴 لو Invidious نجح — مش محتاجين Cobalt
        if not invidious_result:
            cobalt_result = await _try_cobalt_download(url, quality, tmpdir)
        else:
            cobalt_result = None
        if cobalt_result:
            logger.info(f"🔵 Cobalt succeeded! Skipping yt-dlp, sending file directly...")
            # Cobalt نجح — نجهز الملف ونرسله مباشرة بدون yt-dlp
            filepath = cobalt_result["filepath"]
            filename = cobalt_result["filename"]
            filesize = cobalt_result["size"]
            video_height = cobalt_result.get("height", 720)
            video_title = cobalt_result.get("title", "Video")
            video_vcodec = "h264"
            video_acodec = "aac"
            
            # بنعمل info dict وهمي عشان الكود يكمل عادي
            info = {
                "title": video_title,
                "duration": cobalt_result.get("duration", 0),
                "height": video_height,
                "vcodec": "h264",
                "acodec": "aac",
                "requested_downloads": [{"height": video_height, "vcodec": "h264", "acodec": "aac"}],
            }
        else:
            # ═══ Cobalt فشل أو مش متاح → yt-dlp Fallback Chain ═══
            info = None
            last_error = None
            
            def _run_ytdlp(opts):
                import yt_dlp
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=True)
            
            loop = asyncio.get_event_loop()
            
            # ═══ المحاولة الأولى: الطريقة الأساسية + deno + remote_components ═══
            ydl_opts = _get_ydl_opts(quality, output_template, platform, player_client_idx=0)
            
            try:
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: _run_ytdlp(ydl_opts)),
                    timeout=300  # 5 دقائق
                )
            except Exception as first_error:
                err_str = str(first_error).lower()
                last_error = first_error
                logger.warning(f"⚠️ First download attempt failed (default+deno): {first_error}")
                
                # ═══ Fallback chain — نجرب طرق مختلفة ═══
                should_retry = any(kw in err_str for kw in [
                    "requested format", "ffmpeg", "merge", "format not available",
                    "no video formats", "unable to", "error", "http error",
                    "sign in", "login", "bot", "captcha", "confirm",
                    "http error 403", "forbidden", "age", "inappropriate",
                ])
                
                # 🔴 لو YouTube حجبنا (bot detection) — حدث yt-dlp فوراً
                if any(kw in err_str for kw in ["sign in", "bot", "captcha", "confirm", "login", "403"]):
                    logger.warning("🔴 YouTube bot detection detected! Triggering yt-dlp update...")
                    trigger_ytdlp_update()
                
                if not should_retry:
                    raise  # خطأ مش متعلق — بنرفعه على طول
                
                is_youtube = platform.lower() == "youtube"
                
                # 🔴 FIX v5: لو YouTube — fallback chain محسّن
                if is_youtube:
                    # ═══ المرحلة 1: نجرب player_clients كـ fallback ═══
                    for client_idx in range(1, 1 + len(_YOUTUBE_PLAYER_CLIENTS)):
                        client_name = _YOUTUBE_PLAYER_CLIENTS[client_idx - 1][0]
                        retry_label = {
                            "android": "Android", "ios": "iOS", "mweb": "Mobile Web", "tv": "TV", "web": "Web"
                        }.get(client_name, client_name)
                        
                        logger.info(f"🔄 Trying YouTube with {client_name} player_client (attempt {client_idx + 1})...")
                        
                        try:
                            await status_msg.edit_text(
                                f"🔄 جاري تجربة طريقة تانية ({retry_label})..." if lang == "ar" 
                                else f"🔄 Trying another method ({retry_label})..."
                            )
                        except:
                            pass
                        
                        fallback_opts = _get_ydl_opts(quality, output_template, platform, player_client_idx=client_idx)
                        
                        try:
                            info = await asyncio.wait_for(
                                loop.run_in_executor(None, lambda o=fallback_opts: _run_ytdlp(o)),
                                timeout=300
                            )
                            if info is not None:
                                logger.info(f"✅ Download succeeded with {client_name} player_client!")
                                break
                        except Exception as retry_error:
                            last_error = retry_error
                            err_str_retry = str(retry_error).lower()
                            logger.warning(f"⚠️ Attempt {client_idx + 1} ({client_name}) also failed: {retry_error}")
                            
                            bot_keywords = ["sign in", "bot", "confirm", "captcha", "login", "403"]
                            if not any(kw in err_str_retry for kw in bot_keywords):
                                break
                    
                    # ═══ المرحلة 2: كل الطرق فشلت — نجرب بدون كوكيز ═══
                    if info is None:
                        logger.info("🔄 All methods with cookies failed, trying WITHOUT cookies...")
                        
                        try:
                            await status_msg.edit_text(
                                "🔄 جاري تجربة طريقة نظيفة (بدون كوكيز)..." if lang == "ar" 
                                else "🔄 Trying clean method (no cookies)..."
                            )
                        except:
                            pass
                        
                        clean_opts = _get_ydl_opts(quality, output_template, platform, player_client_idx=0)
                        clean_opts.pop('cookiefile', None)
                        
                        logger.info("🔄 Clean attempt (default+deno, no cookies)...")
                        
                        try:
                            info = await asyncio.wait_for(
                                loop.run_in_executor(None, lambda o=clean_opts: _run_ytdlp(o)),
                                timeout=300
                            )
                            if info is not None:
                                logger.info("✅ Download succeeded with default+deno (no cookies)!")
                        except Exception as clean_error:
                            last_error = clean_error
                            logger.warning(f"⚠️ Clean attempt (no cookies) failed: {clean_error}")
                            
                            android_clean = _get_ydl_opts(quality, output_template, platform, player_client_idx=1)
                            android_clean.pop('cookiefile', None)
                            
                            try:
                                info = await asyncio.wait_for(
                                    loop.run_in_executor(None, lambda o=android_clean: _run_ytdlp(o)),
                                    timeout=300
                                )
                                if info is not None:
                                    logger.info("✅ Download succeeded with android (no cookies)!")
                            except Exception as ac_error:
                                last_error = ac_error
                                logger.warning(f"⚠️ Android clean attempt also failed: {ac_error}")
                        
                        # ═══ المرحلة 2.5: Cloudflare Worker Fallback ═══
                        if info is None:
                            from config import CLOUDFLARE_WORKER_URL
                            if CLOUDFLARE_WORKER_URL:
                                logger.info(f"🔄 All yt-dlp methods failed, trying Cloudflare Worker: {CLOUDFLARE_WORKER_URL}")
                                try:
                                    await status_msg.edit_text(
                                        "🔄 جاري التحميل عبر سيرفر خاص..." if lang == "ar"
                                        else "🔄 Downloading via proxy server..."
                                    )
                                except:
                                    pass
                                
                                try:
                                    import requests as sync_requests
                                    from urllib.parse import quote
                                    worker_url = CLOUDFLARE_WORKER_URL.rstrip("/")
                                    dl_type = "audio" if quality == "audio" else "video"
                                    api_url = f"{worker_url}/download?url={quote(url)}&type={dl_type}"
                                    
                                    cf_response = sync_requests.get(api_url, timeout=120, stream=True)
                                    
                                    if cf_response.status_code == 200:
                                        content_type = cf_response.headers.get('Content-Type', '')
                                        if 'video' in content_type or 'audio' in content_type or 'octet-stream' in content_type:
                                            ext = "mp3" if quality == "audio" else "mp4"
                                            cf_filename = f"youtube_cf.{ext}"
                                            cf_filepath = os.path.join(tmpdir, cf_filename)
                                            
                                            with open(cf_filepath, 'wb') as cf_f:
                                                for chunk in cf_response.iter_content(chunk_size=8192):
                                                    cf_f.write(chunk)
                                            
                                            cf_size = os.path.getsize(cf_filepath)
                                            if cf_size > 0:
                                                info = {
                                                    "title": "YouTube Video",
                                                    "duration": 0,
                                                    "height": 720,
                                                    "vcodec": "h264",
                                                    "acodec": "aac",
                                                    "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                                                }
                                                logger.info(f"✅ Cloudflare Worker download succeeded! Size: {cf_size // (1024*1024)}MB")
                                            else:
                                                os.remove(cf_filepath)
                                        else:
                                            try:
                                                cf_data = cf_response.json()
                                                if cf_data.get("url"):
                                                    stream_url = cf_data["url"]
                                                    ext = "mp3" if quality == "audio" else "mp4"
                                                    cf_filename = f"youtube_cf.{ext}"
                                                    cf_filepath = os.path.join(tmpdir, cf_filename)
                                                    
                                                    dl_resp = sync_requests.get(stream_url, timeout=120, stream=True, headers={
                                                        'User-Agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 14)',
                                                        'Referer': 'https://www.youtube.com/',
                                                    })
                                                    
                                                    if dl_resp.status_code == 200:
                                                        with open(cf_filepath, 'wb') as cf_f:
                                                            for chunk in dl_resp.iter_content(chunk_size=8192):
                                                                cf_f.write(chunk)
                                                        
                                                        cf_size = os.path.getsize(cf_filepath)
                                                        if cf_size > 0:
                                                            info = {
                                                                "title": "YouTube Video",
                                                                "duration": 0,
                                                                "height": 720,
                                                                "vcodec": "h264",
                                                                "acodec": "aac",
                                                                "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                                                            }
                                                            logger.info(f"✅ CF Worker stream URL download succeeded! Size: {cf_size // (1024*1024)}MB")
                                                        else:
                                                            os.remove(cf_filepath)
                                                    else:
                                                        proxy_url = f"{worker_url}/proxy?url={quote(stream_url)}"
                                                        proxy_resp = sync_requests.get(proxy_url, timeout=120, stream=True)
                                                        
                                                        if proxy_resp.status_code == 200:
                                                            with open(cf_filepath, 'wb') as cf_f:
                                                                for chunk in proxy_resp.iter_content(chunk_size=8192):
                                                                    cf_f.write(chunk)
                                                            
                                                            cf_size = os.path.getsize(cf_filepath)
                                                            if cf_size > 0:
                                                                info = {
                                                                    "title": "YouTube Video",
                                                                    "duration": 0,
                                                                    "height": 720,
                                                                    "vcodec": "h264",
                                                                    "acodec": "aac",
                                                                    "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                                                                }
                                                                logger.info(f"✅ CF Worker proxy download succeeded! Size: {cf_size // (1024*1024)}MB")
                                                            else:
                                                                os.remove(cf_filepath)
                                            except Exception as cf_json_err:
                                                logger.warning(f"⚠️ CF Worker JSON parse error: {cf_json_err}")
                                    else:
                                        logger.warning(f"⚠️ CF Worker returned status {cf_response.status_code}")
                                except Exception as cf_err:
                                    logger.warning(f"⚠️ Cloudflare Worker fallback failed: {cf_err}")
                            else:
                                logger.info("⚠️ CLOUDFLARE_WORKER_URL not set, skipping CF Worker fallback")
                        
                        # ═══ المرحلة 3: محاولة أخيرة — تنسيق أبسط ═══
                        if info is None:
                            logger.info("🔄 Trying simple 'best' format as last resort...")
                            
                            try:
                                await status_msg.edit_text(
                                    "🔄 جاري تجربة طريقة أبسط..." if lang == "ar" else "🔄 Trying simpler method..."
                                )
                            except:
                                pass
                            
                            simple_opts = _get_ydl_opts(quality, output_template, platform, use_ffmpeg=False, player_client_idx=0)
                            simple_opts['format'] = 'best[ext=mp4]/best' if quality != "audio" else 'bestaudio/best'
                            simple_opts.pop('postprocessors', None)
                            simple_opts.pop('merge_output_format', None)
                            simple_opts.pop('remux_video', None)
                            simple_opts.pop('extractor_args', None)
                            simple_opts.pop('remote_components', None)
                            simple_opts.pop('cookiefile', None)
                            
                            try:
                                info = await asyncio.wait_for(
                                    loop.run_in_executor(None, lambda: _run_ytdlp(simple_opts)),
                                    timeout=300
                                )
                            except Exception as final_error:
                                last_error = final_error
                                logger.warning(f"⚠️ Final attempt (simple format) also failed: {final_error}")
                else:
                    # مش YouTube — نجرب تنسيق أبسط بس
                    logger.info("🔄 Trying simple 'best' format for non-YouTube platform...")
                    fallback_opts = _get_ydl_opts(quality, output_template, platform, use_ffmpeg=False, player_client_idx=0)
                    fallback_opts['format'] = 'best[ext=mp4]/best' if quality != "audio" else 'bestaudio/best'
                    fallback_opts.pop('postprocessors', None)
                    fallback_opts.pop('merge_output_format', None)
                    fallback_opts.pop('remux_video', None)
                    
                    try:
                        await status_msg.edit_text(
                            "🔄 جاري إعادة المحاولة..." if lang == "ar" else "🔄 Retrying..."
                        )
                    except:
                        pass
                    
                    try:
                        info = await asyncio.wait_for(
                            loop.run_in_executor(None, lambda: _run_ytdlp(fallback_opts)),
                            timeout=300
                        )
                    except Exception as second_error:
                        last_error = second_error
                        logger.warning(f"⚠️ Second attempt (simple format) also failed: {second_error}")
        
        # ═══ البحث عن الملف المحمل ═══
        if info is None and last_error:
            raise last_error
        
        downloaded_files = os.listdir(tmpdir)
        if not downloaded_files:
            await status_msg.edit_text("❌ فشل التحميل — ملف مش موجود." if lang == "ar" else "❌ Download failed — file not found.")
            return
        
        filepath = os.path.join(tmpdir, downloaded_files[0])
        filesize = os.path.getsize(filepath)
        filename = downloaded_files[0]
        
        # 🔴 FIX v4: استخراج معلومات الجودة الحقيقية من info dict
        video_height = 0
        video_vcodec = ""
        video_acodec = ""
        if info:
            # لو فيه requested_downloads (بعد التحميل الفعلي)
            req_dl = info.get("requested_downloads", [])
            if req_dl:
                dl_info = req_dl[0]
                video_height = dl_info.get("height", 0) or 0
                # كوديك الفيديو
                vcodec_note = dl_info.get("vcodec", "") or ""
                acodec_note = dl_info.get("acodec", "") or ""
                video_vcodec = vcodec_note.split('.')[0] if vcodec_note else ""
                video_acodec = acodec_note.split('.')[0] if acodec_note else ""
            
            # fallback: من الـ info نفسه
            if not video_height:
                video_height = info.get("height", 0) or 0
            if not video_vcodec:
                vcodec = info.get("vcodec", "") or ""
                video_vcodec = vcodec.split('.')[0] if vcodec else ""
            if not video_acodec:
                acodec = info.get("acodec", "") or ""
                video_acodec = acodec.split('.')[0] if acodec else ""
        
        # لو مفيش info عن الكوديك، نجيبها بـ ffprobe
        if _is_ffmpeg_available() and quality != "audio" and (not video_vcodec or video_vcodec == "none"):
            try:
                probe_result = subprocess.run(
                    ['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
                     '-show_entries', 'stream=codec_name,width,height',
                     '-of', 'csv=p=0', filepath],
                    capture_output=True, timeout=10, text=True
                )
                if probe_result.returncode == 0 and probe_result.stdout.strip():
                    parts = probe_result.stdout.strip().split(',')
                    if len(parts) >= 3:
                        video_vcodec = parts[0]
                        try: 
                            h = int(parts[2])
                            video_height = h if h > (video_height or 0) else video_height
                        except (ValueError, IndexError): pass
                    elif len(parts) >= 1:
                        video_vcodec = parts[0]
            except Exception:
                pass
        
        # 🔴 FIX v4: لو الكوديك مش h264 والملف فيديو، نعمل remux لـ h264
        # عشان Telegram مش بيشغل VP9/AV1
        if (_is_ffmpeg_available() and quality != "audio" 
            and video_vcodec and video_vcodec not in ("h264", "avc1", "avc", "mpeg4", "")):
            logger.info(f"🔧 Video codec is {video_vcodec}, converting to h264 for Telegram compatibility...")
            try:
                converted_path = filepath + "_h264.mp4"
                convert_result = subprocess.run(
                    ['ffmpeg', '-i', filepath,
                     '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                     '-c:a', 'aac', '-b:a', '128k',
                     '-movflags', '+faststart',
                     '-y', converted_path],
                    capture_output=True, timeout=180
                )
                if convert_result.returncode == 0 and os.path.exists(converted_path):
                    converted_size = os.path.getsize(converted_path)
                    if converted_size > 0:
                        os.remove(filepath)
                        filepath = converted_path
                        filename = os.path.basename(filepath)
                        filesize = converted_size
                        video_vcodec = "h264"
                        logger.info(f"✅ Converted to h264: {filesize // (1024*1024)}MB")
                    else:
                        os.remove(converted_path)
                else:
                    if os.path.exists(converted_path):
                        os.remove(converted_path)
                    logger.warning(f"⚠️ h264 conversion failed, keeping original: {convert_result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ h264 conversion timed out, keeping original")
                try:
                    if os.path.exists(filepath + "_h264.mp4"):
                        os.remove(filepath + "_h264.mp4")
                except: pass
            except Exception as conv_err:
                logger.warning(f"⚠️ h264 conversion error: {conv_err}")
        
        # تحديد الدقة كنص
        if video_height:
            if video_height >= 1080: quality_label = "1080p"
            elif video_height >= 720: quality_label = "720p"
            elif video_height >= 480: quality_label = "480p"
            elif video_height >= 360: quality_label = "360p"
            else: quality_label = f"{video_height}p"
        else:
            quality_names_map = {"best": "1080p", "medium": "720p", "low": "480p"}
            quality_label = quality_names_map.get(quality, quality)
        
        logger.info(f"✅ Downloaded: {filename} ({filesize // (1024*1024)}MB, {quality_label}, codec={video_vcodec})")
        
        # 🔴 FIX: رفع الحد الأقصى من 50MB إلى 2GB
        # Telegram Premium bots: 2GB limit
        # Telegram Free bots: 50MB limit (but we try anyway — Telegram handles the rejection)
        # If file is too large for direct send, we try sendVideo which streams the file
        MAX_FILESIZE_DIRECT = 2000 * 1024 * 1024  # 2GB — Telegram premium bots support up to 2GB
        MAX_FILESIZE_FALLBACK = 100 * 1024 * 1024  # 100MB — if direct fails, try lower quality
        
        if filesize > MAX_FILESIZE_DIRECT:
            # فوق 2GB — محاولة بجودة أقل
            if quality != "audio":
                if lang == "ar":
                    await status_msg.edit_text(f"⚠️ الملف كبير جداً ({filesize // (1024*1024)}MB). جاري تحميل جودة أقل...")
                else:
                    await status_msg.edit_text(f"⚠️ File too large ({filesize // (1024*1024)}MB). Trying lower quality...")
                os.remove(filepath)
                lower_quality = {"best": "medium", "medium": "low", "low": "audio"}.get(quality, "medium")
                return await _download_with_ytdlp(update_or_query, url, lower_quality, lang, user_id, status_msg)
            else:
                if lang == "ar":
                    await status_msg.edit_text(f"❌ الملف كبير جداً ({filesize // (1024*1024)}MB). الحد الأقصى 2GB.\n💡 جرب تحميل صوت أقل جودة.")
                else:
                    await status_msg.edit_text(f"❌ File too large ({filesize // (1024*1024)}MB). Maximum is 2GB.\n💡 Try downloading lower quality audio.")
                return
        
        # تتبع
        increment_usage(user_id, "youtube_summaries")
        try: track_event("media_downloads")
        except: pass
        
        # إرسال الملف
        title = info.get("title", filename) if info else filename
        duration = info.get("duration", 0) if info else 0
        
        # 🔴 FIX v4: معلومات الجودة الحقيقية في الـ caption
        size_mb = filesize / (1024 * 1024)
        size_str = f"{size_mb:.1f}MB"
        
        await status_msg.delete()
        
        # 🔴 FIX: محاولة إرسال الملف مع fallback للجودة الأقل لو فشل الإرسال
        send_failed = False
        
        if quality == "audio":
            try:
                with open(filepath, 'rb') as f:
                    caption = f"📥 {'تم تحميل الصوت!' if lang == 'ar' else 'Audio downloaded!'}\n🎵 {title[:200]}\n📁 {size_str}"
                    await message.reply_audio(
                        audio=f, filename=filename,
                        caption=caption,
                        parse_mode="HTML",
                    )
            except Exception as send_err:
                send_failed = True
                logger.warning(f"⚠️ Audio send failed: {send_err}")
        else:
            try:
                with open(filepath, 'rb') as f:
                    # معلومات الجودة + الكوديك
                    tech_info = f"{quality_label} | {size_str}"
                    if video_vcodec and video_vcodec not in ("None", ""):
                        tech_info += f" | {video_vcodec}"
                    caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {title[:200]}\n📊 {tech_info}"
                    await message.reply_video(
                        video=f, filename=filename,
                        caption=caption,
                        parse_mode="HTML",
                        duration=int(duration) if duration else None,
                        supports_streaming=True,
                    )
            except Exception as send_err:
                send_failed = True
                logger.warning(f"⚠️ Video send failed (likely too large for free bot): {send_err}")
        
        # 🔴 FIX: لو الإرسال فشل (ملف كبير على بوت مجاني)، نجرب جودة أقل
        if send_failed and quality != "audio":
            if lang == "ar":
                await message.reply_text(f"⚠️ الملف كبير ({size_str}) ومش قادر أبعته مباشرة. جاري تحميل جودة أقل...")
            else:
                await message.reply_text(f"⚠️ File too large ({size_str}) for direct send. Trying lower quality...")
            
            try:
                os.remove(filepath)
            except Exception:
                pass
            
            lower_quality = {"best": "medium", "medium": "low", "low": "audio"}.get(quality, "medium")
            return await _download_with_ytdlp(update_or_query, url, lower_quality, lang, user_id, status_msg)
        elif send_failed and quality == "audio":
            if lang == "ar":
                await message.reply_text(f"❌ فشل إرسال الملف الصوتي ({size_str}). جرب تاني!")
            else:
                await message.reply_text(f"❌ Failed to send audio file ({size_str}). Try again!")
    
    except asyncio.TimeoutError:
        logger.error("yt-dlp download timed out")
        try:
            await status_msg.edit_text("❌ انتهى وقت التحميل. جرب جودة أقل." if lang == "ar" else "❌ Download timed out. Try a lower quality.")
        except: pass
    
    except Exception as e:
        logger.error(f"Error in yt-dlp download: {e}", exc_info=True)
        error_hint = ""
        err_str = str(e).lower()
        
        # 🔴 FIX v3: رسائل خطأ أوضح مع نصائح حقيقية
        if "sign in" in err_str or "confirm you" in err_str or "bot" in err_str:
            # YouTube bot detection — نصايح حقيقية
            cookies_hint = ""
            if not cookies_available:
                cookies_hint = (
                    "\n\n🍪 <b>نصيحة:</b> لو المشكلة مستمرة، الأدمن يقدر يرفع ملف cookies.txt بأمر /cookies"
                    if lang == "ar" else
                    "\n\n🍪 <b>Tip:</b> If this keeps happening, admin can upload a cookies.txt file with /cookies"
                )
            error_hint = (
                f"\n💡 YouTube طلب تسجيل دخول — ده مش من الرابط، ده من YouTube نفسه.{cookies_hint}"
                if lang == "ar" else
                f"\n💡 YouTube requested sign-in — this isn't about the link, it's YouTube's bot detection.{cookies_hint}"
            )
        elif "private" in err_str and "sign in" not in err_str:
            error_hint = "\n💡 المحتوى خاص ومش متاح للتحميل." if lang == "ar" else "\n💡 Content is private and cannot be downloaded."
        elif "not found" in err_str or "404" in err_str or "does not exist" in err_str:
            error_hint = "\n💡 الرابط مش موجود أو اتمسح." if lang == "ar" else "\n💡 URL not found or deleted."
        elif "geo" in err_str or "country" in err_str or "region" in err_str or "blocked" in err_str:
            error_hint = "\n💡 المحتوى مش متاح في المنطقة دي." if lang == "ar" else "\n💡 Content not available in this region."
        elif "ffmpeg" in err_str or "merge" in err_str:
            error_hint = "\n💡 مشكل في تحويل الفيديو. جرب صوت بس." if lang == "ar" else "\n💡 Video conversion issue. Try audio only."
        elif "format" in err_str or "no video" in err_str:
            error_hint = "\n💡 التنسيق مش متاح. جرب جودة تانية أو صوت بس." if lang == "ar" else "\n💡 Format unavailable. Try another quality or audio only."
        elif "copyright" in err_str or "unavailable" in err_str:
            error_hint = "\n💡 المحتوى مش متاح للتحميل." if lang == "ar" else "\n💡 Content unavailable for download."
        elif "login" in err_str:
            error_hint = "\n💡 المحتوى محتاج حساب. جرب رابط تاني." if lang == "ar" else "\n💡 Content requires account. Try a different link."
        else:
            error_hint = f"\n💡 {str(e)[:150]}" 
            logger.error(f"📥 Unhandled download error for {url}: {e}")
        
        try:
            await status_msg.edit_text(f"❌ {'فشل التحميل' if lang == 'ar' else 'Download failed'}.{error_hint}")
        except:
            try:
                await message.reply_text(f"❌ {'فشل التحميل' if lang == 'ar' else 'Download failed'}.{error_hint}")
            except: pass
    
    finally:
        try: shutil.rmtree(tmpdir, ignore_errors=True)
        except: pass


# ═══════════════════════════════════════
# معالجة أزرار التحميل
# ═══════════════════════════════════════

async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار اختيار الجودة"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    lang = get_language(user_id)
    
    if not check_limit(user_id, "image_gen")["allowed"]:
        feature_name = "📥 تحميل وسائط / Media Download"
        await query.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return
    
    if not data.startswith("dl_"):
        return
    
    parts = data.split("_")
    if len(parts) < 3:
        return
    
    dl_type = parts[1]
    
    if dl_type == "v":
        if len(parts) < 4: return
        quality_map = {"b": "best", "m": "medium", "l": "low"}
        quality = quality_map.get(parts[2], "best")
        url_key = parts[3]
    elif dl_type == "a":
        quality = "audio"
        url_key = parts[2]
    else:
        return
    
    url = _retrieve_url(url_key)
    
    if not url:
        if lang == "ar":
            await query.message.edit_text("❌ انتهت صلاحية الرابط. جرب /download تاني.")
        else:
            await query.message.edit_text("❌ Link expired. Please try /download again.")
        return
    
    try:
        if lang == "ar":
            await query.message.edit_text("⏳ جاري تجهيز التحميل...")
        else:
            await query.message.edit_text("⏳ Preparing download...")
    except: pass
    
    await _download_with_ytdlp(query, url, quality, lang, user_id)


# ═══════════════════════════════════════
# أمر /cookies — للأدمن يرفع ملف cookies.txt
# ═══════════════════════════════════════

async def cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /cookies — إدارة ملف cookies.txt (أدمن فقط)"""
    from admin import is_admin
    from config import CHAT_ID
    
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user else None
    lang = get_language(user_id)
    
    # 🔴 أدمن بس
    if not is_admin(user_id, username) and str(user_id) != str(CHAT_ID):
        await update.message.reply_text("❌ الأمر ده للأدمن بس." if lang == "ar" else "❌ Admin only command.")
        return
    
    # عرض الحالة الحالية
    status = _cookies_status()
    
    # 🔴 حالة نظام تدوير الكوكيز التلقائي
    auto_rotation_status = ""
    try:
        from cookie_rotator import is_rotation_running, get_cookie_rotation_status
        rot_status = get_cookie_rotation_status()
        if is_rotation_running():
            auto_rotation_status = (
                f"\n\n🔄 <b>Auto-Rotation:</b> ✅ شغال (كل {rot_status.get('rotation_interval', '?')})"
                f"\n🤖 كوكيز تلقائية: {rot_status.get('auto_cookies', 0)}"
                f"\n⏰ آخر تحديث: {rot_status.get('last_modified', 'غير معروف')}"
            )
        else:
            auto_rotation_status = "\n\n🔄 <b>Auto-Rotation:</b> ❌ مش شغال"
    except ImportError:
        auto_rotation_status = "\n\n🔄 <b>Auto-Rotation:</b> ❌ مش متاح"
    except Exception:
        auto_rotation_status = ""
    
    if status.get("exists"):
        msg = f"""🍪 <b>حالة ملف الكوكيز</b>

📁 المسار: <code>{status.get('path', '')}</code>
📊 الحجم: {status.get('size_bytes', 0)} bytes
🔢 عدد الكوكيز: {status.get('total_cookies', 0)}
▶️ كوكيز YouTube: {status.get('youtube_cookies', 0)}

✅ الملف موجود وشغال!{auto_rotation_status}

💡 <b>لتجديد الملف:</b>
1️⃣ افتح Chrome على الكمبيوتر
2️⃣ ثبّت إضافة "Get cookies.txt LOCALLY"
3️⃣ افتح youtube.com واعمل login
4️⃣ اضغط على الإضافة واختار "Export"
5️⃣ ابعت الملف هنا كـ document

🗑️ لمسح الملف: <code>/cookies delete</code>"""
    else:
        msg = f"""🍪 <b>ملف الكوكيز مش موجود</b>

⚠️ بدون ملف كوكيز، YouTube ممكن يطلب sign in ويمنع التحميل.{auto_rotation_status}

💡 <b>إزاي ترفع ملف cookies.txt:</b>
1️⃣ افتح Chrome على الكمبيوتر
2️⃣ ثبّت إضافة "Get cookies.txt LOCALLY" من Chrome Web Store
3️⃣ افتح youtube.com واعمل login بحسابك
4️⃣ اضغط على الإضافة واختار "Export as cookies.txt"
5️⃣ ابعت الملف هنا كـ document (ملف)

⚡ بعد رفع الملف، التحميل من YouTube هيشتغل بشكل أفضل بكثير!
🔄 الكوكيز التلقائية بتتولد كل 1-2 دقيقة كمان!

📁 أو ارفع الملف يدوياً: <code>{_COOKIES_FILE}</code>"""
    
    # 🔴 حذف الملف
    args = " ".join(context.args) if context.args else ""
    if args.lower() in ("delete", "remove", "مسح", "حذف"):
        try:
            if os.path.exists(_COOKIES_FILE):
                os.remove(_COOKIES_FILE)
                msg = "✅ تم حذف ملف الكوكيز." if lang == "ar" else "✅ Cookies file deleted."
                logger.info(f"🍪 Cookies file deleted by admin {user_id}")
            else:
                msg = "❌ ملف الكوكيز مش موجود أصلاً." if lang == "ar" else "❌ Cookies file doesn't exist."
        except Exception as e:
            msg = f"❌ فشل الحذف: {e}" if lang == "ar" else f"❌ Delete failed: {e}"
    
    await update.message.reply_text(msg, parse_mode="HTML")


async def handle_cookies_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رفع ملف cookies.txt — الأدمن يبعت ملف وكوكيز"""
    from admin import is_admin
    from config import CHAT_ID
    
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user else None
    lang = get_language(user_id)
    
    # 🔴 أدمن بس
    if not is_admin(user_id, username) and str(user_id) != str(CHAT_ID):
        return  # مش أدمن — نتجاهل بس
    
    if not update.message.document:
        return
    
    doc = update.message.document
    filename = doc.file_name or ""
    
    # 🔴 بنقبل بس ملفات cookies.txt
    if not (filename.lower().endswith('.txt') and 'cookie' in filename.lower()) and filename.lower() != 'cookies.txt':
        # ممكن الملف اسمه حاجة تانية — بنشوف المحتوى
        pass  # هنفحص المحتوى بعد التحميل
    
    try:
        # تحميل الملف
        file = await asyncio.wait_for(context.bot.get_file(doc.file_id), timeout=15.0)
        file_bytes = await asyncio.wait_for(file.download_as_bytearray(), timeout=30.0)
        content = bytes(file_bytes).decode('utf-8', errors='ignore')
        
        # 🔴 فحص المحتوى — نتأكد إنه ملف كوكيز حقيقي
        if '# Netscape HTTP Cookie File' in content or '.youtube.com' in content or 'youtube.com' in content:
            # ملف كوكيز صحيح
            with open(_COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # التحقق
            new_status = _cookies_status()
            yt_count = new_status.get('youtube_cookies', 0)
            
            logger.info(f"🍪 Cookies file uploaded by admin {user_id}: {yt_count} YouTube cookies")
            
            if lang == "ar":
                msg = f"""✅ <b>تم رفع ملف الكوكيز بنجاح!</b>

📊 عدد كوكيز YouTube: {yt_count}
📁 المحتوى محفوظ في: <code>{_COOKIES_FILE}</code>

🎬 دلوقتي تحميل الفيديوهات من YouTube هيشتغل بشكل أفضل!"""
            else:
                msg = f"""✅ <b>Cookies file uploaded successfully!</b>

📊 YouTube cookies: {yt_count}
📁 Saved to: <code>{_COOKIES_FILE}</code>

🎬 YouTube downloads should work much better now!"""
            
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            # الملف مش كوكيز
            if lang == "ar":
                await update.message.reply_text("❌ الملف ده مش ملف كوكيز صحيح. لازم يكون Netscape HTTP Cookie File وفيه كوكيز YouTube.")
            else:
                await update.message.reply_text("❌ This doesn't look like a valid cookies file. It needs to be a Netscape HTTP Cookie File with YouTube cookies.")
    
    except asyncio.TimeoutError:
        await update.message.reply_text("❌ انتهى وقت تحميل الملف. جرب تاني." if lang == "ar" else "❌ File download timed out. Try again.")
    except Exception as e:
        logger.error(f"Error handling cookies file upload: {e}")
        await update.message.reply_text(f"❌ حصل خطأ: {e}" if lang == "ar" else f"❌ Error: {e}")
