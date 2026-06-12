"""Download handlers - yt-dlp core download function and fallback stages.

Main _download_with_ytdlp function, Cobalt API helpers, yt-dlp update
management, download command, direct download helpers, and ydl opts.
"""

import logging
import asyncio
import os
import re
import tempfile
import time
import subprocess

from telegram import Update

from telegram.ext import ContextTypes

from memory import get_language, increment_command_count
from premium import (
    check_limit, increment_usage, premium_required_message,
    get_premium_keyboard,
)
from dashboard import track_event
from handlers.dedup import _is_duplicate_update

from content_safety import (
    check_query_safety,
    comprehensive_media_safety_check,
    get_block_message,
)

from handlers.downloads.utils import (
    _is_audio_quality,
    _get_audio_bitrate,
    _ensure_audio_only,
    _send_telegram_audio,
    _get_cookies_file,
    _cookies_status,
    _detect_platform,
    _is_direct_media_url,
    _extract_url,
    _is_threads_url,
    _is_ffmpeg_available,
    _store_url,
    _retrieve_url,
    _get_quality_keyboard,
    _get_audio_quality_keyboard,
    _COBALT_PUBLIC_API,
    _is_youtube_url,
    _YOUTUBE_URL_PATTERN,
    _DENO_PATH,
    _ensure_deno_in_path,
    _YOUTUBE_PLAYER_CLIENTS,
    _FFMPEG_AVAILABLE,
    _COOKIES_FILE,
    _USER_AGENT,
    URL_PATTERNS,
    GENERAL_URL_PATTERN,
    IMAGE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
)

from handlers.downloads.threads import _download_threads_media

logger = logging.getLogger(__name__)


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
    # 🛡️ Safety check on URL
    try:
        is_safe, reason = await check_query_safety(url, platform="telegram", user_id=str(user_id))
        if not is_safe:
            msg = get_block_message(lang, reason)
            await update.message.reply_text(msg, parse_mode="HTML")
            return
    except Exception:
        pass  # Fail-open
    
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
        
        # 🛡️ Safety check on image
        try:
            from content_safety import check_image_safety
            is_safe_img, reason_img, _score = await check_image_safety(
                image_bytes=image_bytes, platform="telegram", user_id=str(user_id)
            )
            if not is_safe_img:
                msg = get_block_message(lang, reason_img)
                await status_msg.edit_text(msg, parse_mode="HTML")
                return
        except Exception:
            pass  # Fail-open
        
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
        
        # 🛡️ Safety check on audio
        from urllib.parse import urlparse, unquote
        filename = os.path.basename(unquote(urlparse(url).path)) or "audio.mp3"
        try:
            from content_safety import check_audio_safety
            is_safe_audio, reason_audio, _score = await check_audio_safety(
                title=filename, platform="telegram", user_id=str(user_id)
            )
            if not is_safe_audio:
                msg = get_block_message(lang, reason_audio)
                await status_msg.edit_text(msg, parse_mode="HTML")
                return
        except Exception:
            pass  # Fail-open
        
        increment_usage(user_id, "youtube_summaries")
        try: track_event("media_downloads")
        except: pass
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

# 🔴 Cobalt v6 API (api/json) اتنفصل في نوفمبر 2024
# v7 API بيتطلب JWT — بنستخدمه في المحاولة 8 (Cobalt JWT)
# Self-hosted Cobalt لسه شغال لو عندك COBALT_API_URL

# 🔴 Cobalt API and YouTube URL helpers are imported from utils.py
# (_COBALT_PUBLIC_API, _YOUTUBE_URL_PATTERN, _is_youtube_url)


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
    
    is_audio = _is_audio_quality(quality)
    
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
    
    is_audio = _is_audio_quality(quality)
    
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



def _get_ydl_opts(quality: str, output_template: str, platform: str = "", 
                  use_ffmpeg: bool = True, player_client_idx: int = 0) -> dict:
    """إعداد خيارات yt-dlp حسب الجودة والمنصة وتوفر ffmpeg
    
    🔴 FIX v3: 
    - بنضيف cookies.txt لو موجود — الحل الأقوى لتخطي bot detection
    - 🔴 الكوكيز الوهمية اتشالت نهائياً — مش بتفيد وبتضر
    - بنستخدم player_client=mweb أولاً (أقل كشف) مع fallback لـ android → ios → tv → web
    - بنكشف ffmpeg تلقائي وبنعدل التنسيقات حسب التوفر
    """
    ffmpeg_ok = use_ffmpeg and _is_ffmpeg_available()
    platform_lower = platform.lower() if platform else ""
    # 🔴 FIX: لازم نعرّف is_youtube و platform_lower جوه الدالة
    # platform بتتباصى من _detect_platform() — لو فاضي بنعامل كأنه YouTube
    is_youtube = platform_lower == "youtube" or platform_lower == ""
    
    # 🔴 الكوكيز الوهمية اتشالت نهائياً!
    # الكوكيز الوهمية (visitor cookies) بتضر أكتر مما تنفع لأن:
    # 1. YouTube بيكتشف إنها random/generated وبيعتبرنا bot
    # 2. كل محاولة بتولد visitor_id مختلف = سلوك مش طبيعي
    # 3. yt-dlp بيدير كوكيز YouTube داخلياً حسب player_client
    # بنستخدم الكوكيز الوهمية بس للمنصات التانية
    
    # 🔴 الكوكيز الوهمية اتشالت نهائياً — مش بتفيد وبتضر
    # بنستخدم headers نظيفة بدون أي Cookie
    headers = {
        'User-Agent': _USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
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
    
    if is_youtube:
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
    if _is_audio_quality(quality):
        if ffmpeg_ok:
            opts = {
                **common_opts,
                # 🔴 FIX v6: bestaudio فقط — بدون /best fallback
                # الـ /best بيحمل فيديو لو مفيش audio-only format متاح
                # yt-dlp هيحاول أفضل صوت متاح، ولو مفيش هيستخدم bestaudio
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio[ext=mp3]/bestaudio/best[ext=mp4]/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': str(_get_audio_bitrate(quality)),
                }],
            }
        else:
            opts = {
                **common_opts,
                # 🔴 بدون ffmpeg → بنحاول نحمل audio فقط بدون تحويل
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
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
    """تحميل فيديو أو صوت — مُحسّن v9 مع yt-dlp كأولوية
    
    🔴 FIX v9: Cobalt API كـ fallback تالت + Apify كـ fallback رابع
    1. yt-dlp + deno + remote_components (الأفضل)
    2. yt-dlp player_client fallback (android → ios → mweb → tv → web)
    3. 🟠 Cobalt API (fallback تالت — أسرع وأضمن من yt-dlp بدون كوكيز)
    4. 🔵 Apify (fallback رابع — سيرفرات مختلفة عن YouTube خالص)
    5. yt-dlp بدون كوكيز
    6. Invidious API (fallback)
    7. Piped API (fallback — زي Invidious بس سيرفرات مختلفة)
    8. Cobalt JWT (fallback)
    9. Cloudflare Worker (آخر محاولة)
    """
    # تحديد الرسالة
    if hasattr(update_or_query, 'message'):
        message = update_or_query.message
    else:
        message = update_or_query.message
    
    # كشف المنصة عشان نستخدم إعداداتها
    platform = _detect_platform(url)
    is_youtube = _is_youtube_url(url)  # 🔴 FIX: لازم نعرّف is_youtube هنا عشان الكود اللي بعد كده يستخدمه
    is_threads = _is_threads_url(url)   # 🔴 FIX: Threads مش مدعوم من yt-dlp — لازم طريقة مخصصة
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
        
        # 🔴 FIX: Threads — yt-dlp مش بيدعمه، نستخدم طريقة مخصصة
        if is_threads:
            logger.info(f"🧵 Threads detected — using custom download method (yt-dlp doesn't support threads.com)")
            try:
                await status_msg.edit_text(
                    "🧵 جاري التحميل من Threads..." if lang == "ar"
                    else "🧵 Downloading from Threads..."
                )
            except:
                pass
            
            threads_result = await _download_threads_media(url, tmpdir, quality)
            
            if threads_result and threads_result.get("success"):
                file_path = threads_result["file_path"]
                file_size = threads_result.get("file_size", os.path.getsize(file_path))
                real_title = threads_result.get("title", "Threads Post")
                is_video = threads_result.get("is_video", True)
                size_mb = file_size / (1024 * 1024)
                size_str = f"{size_mb:.1f}MB"
                
                # 🛡️ Safety check on downloaded media
                try:
                    media_type = "video" if is_video else "image"
                    is_safe_dl, block_msg_dl, _reason_dl = await comprehensive_media_safety_check(
                        title=real_title, file_path=file_path, file_type=media_type,
                        platform="telegram", user_id=str(user_id), lang=lang,
                    )
                    if not is_safe_dl:
                        await message.reply_text(block_msg_dl, parse_mode="HTML")
                        try: os.remove(file_path)
                        except: pass
                        return
                except Exception:
                    pass  # Fail-open
                
                increment_usage(user_id, "youtube_summaries")
                try: track_event("media_downloads")
                except: pass
                
                await status_msg.delete()
                
                # 🔴 FIX: لو المستخدم طلب صوت بس، نستخرج الصوت من الفيديو
                if is_video and _is_audio_quality(quality):
                    bitrate = _get_audio_bitrate(quality)
                    audio_sent = await _send_telegram_audio(
                        message, file_path, real_title, size_str, lang,
                        method_name="Threads", bitrate=bitrate
                    )
                    if not audio_sent:
                        # لو فشل إرسال الصوت، نجرب نبعت الفيديو عادي
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🧵 {real_title[:200]}\n📁 {size_str} | Threads"
                                await message.reply_video(
                                    video=f,
                                    caption=caption,
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                await message.reply_text(
                                    f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                    else f"❌ File too large for Telegram ({size_str})"
                                )
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                                    else f"❌ Failed to send audio ({size_str}). Try again!"
                                )
                elif is_video:
                    try:
                        with open(file_path, 'rb') as f:
                            caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🧵 {real_title[:200]}\n📁 {size_str} | Threads"
                            await message.reply_video(
                                video=f,
                                caption=caption,
                                supports_streaming=True,
                            )
                    except Exception as send_err:
                        if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                            await message.reply_text(
                                f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                else f"❌ File too large for Telegram ({size_str})"
                            )
                        else:
                            await message.reply_text(
                                f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send video ({size_str}). Try again!"
                            )
                else:
                    try:
                        with open(file_path, 'rb') as f:
                            caption = f"📥 {'تم تحميل الصورة!' if lang == 'ar' else 'Image downloaded!'}\n🧵 {real_title[:200]}\n📁 {size_str} | Threads"
                            await message.reply_photo(
                                photo=f,
                                caption=caption,
                            )
                    except Exception as send_err:
                        await message.reply_text(
                            f"❌ فشل إرسال الصورة. جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send image. Try again!"
                        )
                
                try: os.remove(file_path)
                except: pass
                return  # ✅ Threads نجح!
            else:
                # 🔴 FIX v5: Threads مش مدعوم من yt-dlp — لا fallback!
                # yt-dlp بيرجع "Unsupported URL" لـ threads.com/threads.net
                logger.warning("🧵 Threads: All custom methods failed — yt-dlp doesn't support Threads, not trying it")
                error_msg = (
                    "❌ فشل تحميل الفيديو من Threads. جرب تاني!" if lang == "ar"
                    else "❌ Failed to download from Threads. Try again!"
                )
                await message.reply_text(error_msg)
                try:
                    await status_msg.delete()
                except:
                    pass
                return
        
        output_template = os.path.join(tmpdir, "%(title).100s.%(ext)s")
        
        # تحديث رسالة الحالة
        if _is_audio_quality(quality):
            status_text = "🎵 جاري تحميل الصوت..." if lang == "ar" else "🎵 Downloading audio..."
        else:
            quality_names = {"best": "عالية", "medium": "متوسطة", "low": "منخفضة"} if lang == "ar" else {"best": "high", "medium": "medium", "low": "low"}
            q_name = quality_names.get(quality, quality)
            status_text = f"🎬 جاري تحميل الفيديو بجودة {q_name}..." if lang == "ar" else f"🎬 Downloading video in {q_name} quality..."
        
        try:
            await status_msg.edit_text(status_text)
        except Exception:
            pass
        
        # ═══════════════════════════════════════════════════════════════
        # 🔴 FIX v9: yt-dlp هو الأولوية الأولى!
        # الترتيب الجديد:
        # 1. yt-dlp + deno + remote_components (الأفضل)
        # 2. yt-dlp player_client fallback (android → ios → mweb → tv → web)
        # 3. 🟠 Cobalt API (fallback تالت — أسرع وأضمن)
        # 4. 🔵 Apify (fallback رابع — سيرفرات مختلفة عن YouTube)
        # 5. yt-dlp بدون كوكيز
        # 6. Invidious API (fallback)
        # 7. Piped API (fallback)
        # 8. Cobalt JWT (fallback)
        # 9. Cloudflare Worker (آخر محاولة)
        # ═══════════════════════════════════════════════════════════════
        
        info = None
        last_error = None
        
        def _run_ytdlp(opts):
            import yt_dlp
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=True)
        
        loop = asyncio.get_event_loop()
        
        # Progress timer removed — no periodic updates
        
        from urllib.parse import quote as _url_quote
        # 🔴 FIX: quote for URL encoding
        def quote(s): return _url_quote(s, safe='')
        
        # ═══ المحاولة 0: سيرفر التحميل الخاص (VPS بـ IP نظيف) ═══
        # 🔴 ده أفضل طريقة — السيرفر بيحمل من YouTube بـ IP نظيف ومبيحصلش حظر
        # السيرفر بيرفع على Supabase وبيرجع رابط — مفيش OOM على Railway
        if is_youtube:
            try:
                from config import DOWNLOAD_SERVICE_URL, DOWNLOAD_SERVICE_KEY
                if DOWNLOAD_SERVICE_URL:
                    logger.info(f"🖥️ Download Service: Trying VPS download for {url[:80]}")
                    try:
                        await status_msg.edit_text(
                            "🖥️ جاري التحميل عبر السيرفر الخاص..." if lang == "ar"
                            else "🖥️ Downloading via dedicated server..."
                        )
                    except:
                        pass
                    
                    import aiohttp as _aiohttp_ds
                    ds_url = DOWNLOAD_SERVICE_URL.rstrip("/")
                    api_url = f"{ds_url}/download?url={quote(url)}&quality={quality}&platform=telegram&lang={lang}"
                    ds_headers = {}
                    if DOWNLOAD_SERVICE_KEY:
                        ds_headers["X-API-Key"] = DOWNLOAD_SERVICE_KEY
                    
                    try:
                        async with _aiohttp_ds.ClientSession(timeout=_aiohttp_ds.ClientTimeout(total=360)) as ds_session:
                            async with ds_session.get(api_url, headers=ds_headers) as ds_resp:
                                if ds_resp.status == 200:
                                    ds_result = await ds_resp.json()
                                    if ds_result and ds_result.get("success"):
                                        logger.info(f"🖥️ Download Service succeeded! URL: {ds_result.get('url', '')[:60]}")
                                        
                                        # بعت الرابط للمستخدم
                                        cloud_msg = ds_result.get("cloud_msg", "")
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                        else:
                                            dl_url = ds_result.get("url", "")
                                            title = ds_result.get("title", "Video")
                                            size_mb = ds_result.get("size_mb", 0)
                                            if lang == "ar":
                                                await message.reply_text(
                                                    f"🎬 {title}\n\n☁️ تم رفعه على السحابة ({size_mb:.1f}MB)\n\n🔗 رابط التحميل:\n{dl_url}",
                                                    parse_mode="HTML", disable_web_page_preview=False
                                                )
                                            else:
                                                await message.reply_text(
                                                    f"🎬 {title}\n\n☁️ Uploaded to cloud ({size_mb:.1f}MB)\n\n🔗 Download link:\n{dl_url}",
                                                    parse_mode="HTML", disable_web_page_preview=False
                                                )
                                        
                                        try: await status_msg.delete()
                                        except: pass
                                        
                                        # Increment usage
                                        increment_usage(user_id, "youtube_summaries")
                                        try: track_event("media_downloads")
                                        except: pass
                                        
                                        try: shutil.rmtree(tmpdir, ignore_errors=True)
                                        except: pass
                                        return  # ✅ السيرفر الخاص نجح!
                                    else:
                                        error_msg = ds_result.get("message", "unknown error") if ds_result else "no response"
                                        logger.warning(f"🖥️ Download Service failed: {error_msg}")
                                else:
                                    logger.warning(f"🖥️ Download Service returned status {ds_resp.status}")
                    except asyncio.TimeoutError:
                        logger.warning("🖥️ Download Service timed out")
                    except Exception as ds_err:
                        logger.warning(f"🖥️ Download Service error: {ds_err}")
                    
                    logger.info("🖥️ Download Service failed, falling back to local yt-dlp...")
            except ImportError:
                pass
            except Exception as ds_outer_err:
                logger.warning(f"🖥️ Download Service outer error: {ds_outer_err}")
        
        # ═══ المحاولة 1: Invidious API (IP مختلف — مش بيتأثر بـ YouTube bot detection!) ═══
        # 🔴 Invidious بيشتغل من سيرفرات مختلفة — مش من Railway IP
        # ده أحسن من yt-dlp عشان yt-dlp بيستخدم Railway IP وبيتحظر
        if is_youtube:
            try:
                from invidious_api import download_youtube_invidious_file
                
                inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                    "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                inv_quality = inv_quality_map.get(quality, "audio" if _is_audio_quality(quality) else "best")
                
                logger.info(f"🟣 Invidious (early): Attempting download quality={inv_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟣 جاري التحميل عبر Invidious..." if lang == "ar"
                        else "🟣 Downloading via Invidious..."
                    )
                except:
                    pass
                
                try:
                    invidious_result = await asyncio.wait_for(
                        download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                        timeout=60
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Invidious (early) timed out after 60s")
                    invidious_result = None
                
                if invidious_result and invidious_result.get("success") and invidious_result.get("file_path"):
                    logger.info(f"🟣 Invidious (early) succeeded! File: {invidious_result['file_path']}")
                    
                    file_path = invidious_result["file_path"]
                    file_size = invidious_result.get("file_size", os.path.getsize(file_path))
                    real_title = invidious_result.get("title", "YouTube Video")
                    real_duration = invidious_result.get("duration", 0)
                    format_info = invidious_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "") or format_info.get("resolution", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{inv_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check
                    try:
                        inv_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_inv, block_msg_inv, _reason_inv = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=inv_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_inv:
                            await message.reply_text(block_msg_inv, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Invidious", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
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
                            logger.warning(f"⚠️ Invidious video send failed: {send_err}")
                            try:
                                from supabase_storage import upload_and_get_link
                                cloud_msg = await upload_and_get_link(
                                    file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                    content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                )
                                if cloud_msg:
                                    await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                    try: os.remove(file_path)
                                    except: pass
                                    return
                            except:
                                pass
                            await message.reply_text(
                                f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send video ({size_str}). Try again!"
                            )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Invidious (early) نجح!
                
                logger.warning(f"⚠️ Invidious (early) failed, trying Piped...")
                    
            except ImportError:
                logger.warning("⚠️ invidious_api module not available, skipping Invidious")
            except Exception as inv_err:
                logger.warning(f"⚠️ Invidious (early) error: {inv_err}, trying Piped...")
        
        # ═══ المحاولة 2: Piped API (IP مختلف — سيرفرات مختلفة عن Invidious!) ═══
        # 🔴 Piped بيستخدم NewPipe Extractor — سيرفرات مختلفة عن Invidious
        # لو Invidious فشل، Piped ممكن يشتغل لأنه بيستخدم طريقة مختلفة
        if is_youtube:
            try:
                from piped_api import download_youtube_piped_file
                
                piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio"}
                piped_quality = piped_quality_map.get(quality, "best")
                
                logger.info(f"🟢 Piped (early): Attempting download quality={piped_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟢 جاري التحميل عبر Piped..." if lang == "ar"
                        else "🟢 Downloading via Piped..."
                    )
                except:
                    pass
                
                try:
                    piped_result = await asyncio.wait_for(
                        download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                        timeout=90
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Piped (early) timed out after 90s")
                    piped_result = None
                
                if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                    logger.info(f"🟢 Piped (early) succeeded! File: {piped_result['file_path']}")
                    
                    file_path = piped_result["file_path"]
                    file_size = piped_result.get("file_size", os.path.getsize(file_path))
                    real_title = piped_result.get("title", "YouTube Video")
                    real_duration = piped_result.get("duration", 0)
                    format_info = piped_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{piped_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check
                    try:
                        pp_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_pp, block_msg_pp, _reason_pp = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=pp_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_pp:
                            await message.reply_text(block_msg_pp, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Piped", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {real_title[:200]}\n📁 {size_str} | {quality_label} | Piped"
                                await message.reply_video(
                                    video=f,
                                    caption=caption,
                                    duration=int(real_duration) if real_duration else None,
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                        content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                        try: os.remove(file_path)
                                        except: pass
                                        return
                                except Exception:
                                    pass
                                await message.reply_text(
                                    f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                    else f"❌ File too large for Telegram ({size_str})"
                                )
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                    else f"❌ Failed to send video ({size_str}). Try again!"
                                )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Piped (early) نجح!
                
                logger.warning(f"⚠️ Piped (early) failed, falling back to yt-dlp...")
                    
            except ImportError:
                logger.warning("⚠️ piped_api module not available, skipping Piped")
            except Exception as piped_err:
                logger.warning(f"⚠️ Piped (early) error: {piped_err}, falling back to yt-dlp...")
        
        # ═══ المحاولة 3: yt-dlp + deno + remote_components ═══
        logger.info(f"📥 yt-dlp: Attempting download with deno+remote_components for {url[:80]}")
        ydl_opts = _get_ydl_opts(quality, output_template, platform, player_client_idx=0)
        
        try:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: _run_ytdlp(ydl_opts)),
                timeout=300  # 5 دقائق
            )
        except Exception as first_error:
            err_str = str(first_error).lower()
            last_error = first_error
            logger.warning(f"⚠️ yt-dlp first attempt failed (default+deno): {first_error}")
            
            # 🔴 لو YouTube حجبنا (bot detection) — حدث yt-dlp فوراً
            if any(kw in err_str for kw in ["sign in", "bot", "captcha", "confirm", "login", "403"]):
                logger.warning("🔴 YouTube bot detection detected! Triggering yt-dlp update...")
                trigger_ytdlp_update()
            
            # ═══ Fallback chain — نجرب طرق مختلفة ═══
            should_retry = any(kw in err_str for kw in [
                "requested format", "ffmpeg", "merge", "format not available",
                "no video formats", "unable to", "error", "http error",
                "sign in", "login", "bot", "captcha", "confirm",
                "http error 403", "forbidden", "age", "inappropriate",
            ])
            
            if not should_retry:
                raise  # خطأ مش متعلق — بنرفعه على طول
            
            is_youtube = platform.lower() == "youtube"
            
            # 🔴 FIX v5: لو YouTube — fallback chain محسّن
            if is_youtube:
                # ═══ المحاولة 2: نجرب player_clients كـ fallback ═══
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
                
                # ═══ المحاولة 3: Cobalt API (fallback تالت — أسرع وأضمن من yt-dlp بدون كوكيز) ═══
                # 🔴 لو yt-dlp فشل مع player_clients → Cobalt أضمن من تجربة yt-dlp تاني
                if info is None:
                    logger.info("🟠 yt-dlp player_clients failed, trying Cobalt API as 3rd fallback...")
                    try:
                        await status_msg.edit_text(
                            "🟠 جاري التحميل عبر Cobalt..." if lang == "ar"
                            else "🟠 Downloading via Cobalt..."
                        )
                    except:
                        pass
                    
                    try:
                        cobalt_3rd_result = await _try_cobalt_for_youtube(url, quality, tmpdir)
                        
                        if cobalt_3rd_result and cobalt_3rd_result.get("filepath"):
                            logger.info(f"🟠 Cobalt (3rd fallback) succeeded! File: {cobalt_3rd_result['filepath']}")
                            
                            cb_file_path = cobalt_3rd_result.get("file_path", cobalt_3rd_result["filepath"])
                            cb_file_size = cobalt_3rd_result.get("size", os.path.getsize(cb_file_path))
                            cb_title = cobalt_3rd_result.get("title", "YouTube Video")
                            cb_height = cobalt_3rd_result.get("height", 720)
                            
                            cb_size_mb = cb_file_size / (1024 * 1024)
                            cb_size_str = f"{cb_size_mb:.1f}MB"
                            
                            # 🛡️ Safety check on Cobalt downloaded media
                            try:
                                cb_file_type = "audio" if _is_audio_quality(quality) else "video"
                                is_safe_cb, block_msg_cb, _reason_cb = await comprehensive_media_safety_check(
                                    title=cb_title, file_path=cb_file_path, file_type=cb_file_type,
                                    platform="telegram", user_id=str(user_id), lang=lang,
                                )
                                if not is_safe_cb:
                                    await message.reply_text(block_msg_cb, parse_mode="HTML")
                                    try: os.remove(cb_file_path)
                                    except: pass
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            increment_usage(user_id, "youtube_summaries")
                            try: track_event("media_downloads")
                            except: pass
                            
                            await status_msg.delete()
                            
                            if _is_audio_quality(quality):
                                bitrate = _get_audio_bitrate(quality)
                                audio_sent = await _send_telegram_audio(message, cb_file_path, cb_title, cb_size_str, lang, method_name="Cobalt", bitrate=bitrate)
                                if audio_sent:
                                    try: os.remove(cb_file_path)
                                    except: pass
                                    return
                                # 🔴 لو الإرسال فشل — نجرب Supabase
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=cb_file_path, filename=f"{cb_title[:50]}.mp3",
                                        content_type="audio/mpeg", platform="telegram",
                                        title=cb_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML")
                                        try: await status_msg.delete()
                                        except: pass
                                        try: os.remove(cb_file_path)
                                        except: pass
                                        return  # ✅ رفع السحابة نجح
                                except:
                                    pass
                                if lang == "ar":
                                    await message.reply_text(f"❌ فشل إرسال الصوت ({cb_size_str}). جرب تاني!")
                                else:
                                    await message.reply_text(f"❌ Failed to send audio ({cb_size_str}). Try again!")
                                try: os.remove(cb_file_path)
                                except: pass
                                return
                            else:
                                try:
                                    with open(cb_file_path, 'rb') as f:
                                        tech_info = f"{cb_height}p | {cb_size_str} | Cobalt"
                                        caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {cb_title[:200]}\n📊 {tech_info}"
                                        await message.reply_video(
                                            video=f, filename=f"{cb_title[:50]}.mp4",
                                            caption=caption,
                                            parse_mode="HTML",
                                            supports_streaming=True,
                                        )
                                except Exception as send_err:
                                    logger.warning(f"⚠️ Cobalt video send failed (likely too large): {send_err}")
                                    # 🔴 لو الإرسال فشل — نجرب Supabase
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=cb_file_path, filename=f"{cb_title[:50]}.mp4",
                                            content_type="video/mp4", platform="telegram",
                                            title=cb_title, lang=lang,
                                        )
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                            try: await status_msg.delete()
                                            except: pass
                                            try: os.remove(cb_file_path)
                                            except: pass
                                            return  # ✅ رفع السحابة نجح
                                    except:
                                        pass
                                    if lang == "ar":
                                        await message.reply_text(f"❌ فشل إرسال الفيديو ({cb_size_str}). جرب تاني!")
                                    else:
                                        await message.reply_text(f"❌ Failed to send video ({cb_size_str}). Try again!")
                            
                            try: os.remove(cb_file_path)
                            except: pass
                            return  # ✅ Cobalt (3rd fallback) نجح!
                        
                        logger.warning(f"⚠️ Cobalt (3rd fallback) also failed, trying Apify...")
                    except Exception as cobalt_3rd_err:
                        logger.warning(f"⚠️ Cobalt (3rd fallback) error: {cobalt_3rd_err}, trying Apify...")
                
                # ═══ المحاولة 4: Apify — fallback رابع (سيرفرات مختلفة عن YouTube خالص) ═══
                # 🔵 Apify بيستخدم actors عشان يحمل الفيديو — مش بيتأثر بـ bot detection
                if info is None:
                    logger.info("🔵 Cobalt failed, trying Apify as 4th fallback...")
                    try:
                        await status_msg.edit_text(
                            "🔵 جاري التحميل عبر Apify..." if lang == "ar"
                            else "🔵 Downloading via Apify..."
                        )
                    except:
                        pass
                    
                    try:
                        from apify_download import download_youtube_apify
                        
                        apify_result = await asyncio.wait_for(
                            download_youtube_apify(url, quality, tmpdir),
                            timeout=150  # Apify بيستنى الـ actor يخلص
                        )
                        
                        if apify_result and apify_result.get("success") and apify_result.get("filepath"):
                            logger.info(f"🔵 Apify (4th fallback) succeeded! File: {apify_result['filepath']}")
                            
                            af_file_path = apify_result["filepath"]
                            af_file_size = apify_result.get("size", os.path.getsize(af_file_path))
                            af_title = apify_result.get("title", "YouTube Video")
                            af_height = apify_result.get("height", 720)
                            
                            af_size_mb = af_file_size / (1024 * 1024)
                            af_size_str = f"{af_size_mb:.1f}MB"
                            
                            # 🛡️ Safety check on Apify downloaded media
                            try:
                                af_file_type = "audio" if _is_audio_quality(quality) else "video"
                                is_safe_af, block_msg_af, _reason_af = await comprehensive_media_safety_check(
                                    title=af_title, file_path=af_file_path, file_type=af_file_type,
                                    platform="telegram", user_id=str(user_id), lang=lang,
                                )
                                if not is_safe_af:
                                    await message.reply_text(block_msg_af, parse_mode="HTML")
                                    try: os.remove(af_file_path)
                                    except: pass
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            increment_usage(user_id, "youtube_summaries")
                            try: track_event("media_downloads")
                            except: pass
                            
                            await status_msg.delete()
                            
                            if _is_audio_quality(quality):
                                bitrate = _get_audio_bitrate(quality)
                                audio_sent = await _send_telegram_audio(message, af_file_path, af_title, af_size_str, lang, method_name="Apify", bitrate=bitrate)
                                if audio_sent:
                                    try: os.remove(af_file_path)
                                    except: pass
                                    return
                                # 🔴 لو الإرسال فشل — نجرب Supabase
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=af_file_path, filename=f"{af_title[:50]}.mp3",
                                        content_type="audio/mpeg", platform="telegram",
                                        title=af_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML")
                                        try: await status_msg.delete()
                                        except: pass
                                        try: os.remove(af_file_path)
                                        except: pass
                                        return  # ✅ رفع السحابة نجح
                                except:
                                    pass
                                if lang == "ar":
                                    await message.reply_text(f"❌ فشل إرسال الصوت ({af_size_str}). جرب تاني!")
                                else:
                                    await message.reply_text(f"❌ Failed to send audio ({af_size_str}). Try again!")
                                try: os.remove(af_file_path)
                                except: pass
                                return
                            else:
                                try:
                                    with open(af_file_path, 'rb') as f:
                                        tech_info = f"{af_height}p | {af_size_str} | Apify"
                                        caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {af_title[:200]}\n📊 {tech_info}"
                                        await message.reply_video(
                                            video=f, filename=f"{af_title[:50]}.mp4",
                                            caption=caption,
                                            parse_mode="HTML",
                                            supports_streaming=True,
                                        )
                                except Exception as send_err:
                                    logger.warning(f"⚠️ Apify video send failed (likely too large): {send_err}")
                                    # 🔴 لو الإرسال فشل — نجرب Supabase
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=af_file_path, filename=f"{af_title[:50]}.mp4",
                                            content_type="video/mp4", platform="telegram",
                                            title=af_title, lang=lang,
                                        )
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                            try: await status_msg.delete()
                                            except: pass
                                            try: os.remove(af_file_path)
                                            except: pass
                                            return  # ✅ رفع السحابة نجح
                                    except:
                                        pass
                                    if lang == "ar":
                                        await message.reply_text(f"❌ فشل إرسال الفيديو ({af_size_str}). جرب تاني!")
                                    else:
                                        await message.reply_text(f"❌ Failed to send video ({af_size_str}). Try again!")
                            
                            try: os.remove(af_file_path)
                            except: pass
                            return  # ✅ Apify (4th fallback) نجح!
                        
                        logger.warning(f"⚠️ Apify (4th fallback) also failed, trying yt-dlp without cookies...")
                    except ImportError:
                        logger.warning("⚠️ Apify module not available, trying yt-dlp without cookies...")
                    except asyncio.TimeoutError:
                        logger.warning(f"⚠️ Apify timed out, trying yt-dlp without cookies...")
                    except Exception as apify_err:
                        logger.warning(f"⚠️ Apify error: {apify_err}, trying yt-dlp without cookies...")
                
                # ═══ المحاولة 5: كل الطرق فشلت — نجرب بدون كوكيز ═══
                if info is None:
                    logger.info("🔄 All methods failed (including Cobalt & Apify), trying WITHOUT cookies...")
                    
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
        
        # ═══ المحاولة 5: Invidious API (تم تجربته فوق — هنا fallback إضافي لو حاجة اتغيرت) ═══
        # 🔴 لو Invidious (early) فشل فوق، مش هنجرب تاني هنا عشان مفيش فايدة
        # بس لو info لسه None (يعني كل المحاولات فوق فشلت) هنحاول مرة تانية
        # مع instance مختلف يمكن
        if info is None and is_youtube:
            try:
                from invidious_api import download_youtube_invidious_file
                
                inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                    "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                inv_quality = inv_quality_map.get(quality, "audio" if _is_audio_quality(quality) else "best")
                
                logger.info(f"🟣 Invidious: Attempting download quality={inv_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟣 جاري التحميل عبر Invidious..." if lang == "ar"
                        else "🟣 Downloading via Invidious..."
                    )
                except:
                    pass
                
                try:
                    invidious_result = await asyncio.wait_for(
                        download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                        timeout=60
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Invidious timed out after 60s")
                    invidious_result = None
                
                if invidious_result and invidious_result.get("success") and invidious_result.get("file_path"):
                    logger.info(f"🟣 Invidious succeeded! File: {invidious_result['file_path']}")
                    
                    file_path = invidious_result["file_path"]
                    file_size = invidious_result.get("file_size", os.path.getsize(file_path))
                    real_title = invidious_result.get("title", "YouTube Video")
                    real_duration = invidious_result.get("duration", 0)
                    format_info = invidious_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "") or format_info.get("resolution", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{inv_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check on Invidious downloaded media
                    try:
                        inv_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_inv, block_msg_inv, _reason_inv = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=inv_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_inv:
                            await message.reply_text(block_msg_inv, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass  # Fail-open
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Invidious", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
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
                            # 🔴 لو الملف كبير → رفع على Supabase فوراً
                            try:
                                from supabase_storage import upload_and_get_link
                                cloud_msg = await upload_and_get_link(
                                    file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                    content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                )
                                if cloud_msg:
                                    await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                    try: await status_msg.delete()
                                    except: pass
                                    try: os.remove(file_path)
                                    except: pass
                                    return
                            except Exception:
                                pass
                            await message.reply_text(
                                f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send video ({size_str}). Try again!"
                            )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Invidious نجح!
                
                error_code = invidious_result.get("error", "unknown") if invidious_result else "unknown"
                logger.warning(f"⚠️ Invidious failed ({error_code}), trying Cobalt Self-Hosted...")
                    
            except ImportError:
                logger.warning("⚠️ invidious_api module not available, skipping Invidious")
            except Exception as inv_err:
                logger.warning(f"⚠️ Invidious error: {inv_err}, trying Piped...")
        
        # ═══ المحاولة 6: Piped API (تم تجربته فوق — هنا fallback إضافي) ═══
        if info is None and is_youtube:
            try:
                from piped_api import download_youtube_piped_file
                
                piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio"}
                piped_quality = piped_quality_map.get(quality, "best")
                
                logger.info(f"🟢 Piped: Attempting download quality={piped_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟢 جاري التحميل عبر Piped..." if lang == "ar"
                        else "🟢 Downloading via Piped..."
                    )
                except:
                    pass
                
                try:
                    piped_result = await asyncio.wait_for(
                        download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                        timeout=90
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Piped timed out after 90s")
                    piped_result = None
                
                if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                    logger.info(f"🟢 Piped succeeded! File: {piped_result['file_path']}")
                    
                    file_path = piped_result["file_path"]
                    file_size = piped_result.get("file_size", os.path.getsize(file_path))
                    real_title = piped_result.get("title", "YouTube Video")
                    real_duration = piped_result.get("duration", 0)
                    format_info = piped_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{piped_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check on Piped downloaded media
                    try:
                        pp_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_pp, block_msg_pp, _reason_pp = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=pp_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_pp:
                            await message.reply_text(block_msg_pp, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass  # Fail-open
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Piped", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: await status_msg.delete()
                                except: pass
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {real_title[:200]}\n📁 {size_str} | {quality_label} | Piped"
                                await message.reply_video(
                                    video=f,
                                    caption=caption,
                                    duration=int(real_duration) if real_duration else None,
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                # 🔴 لو الملف كبير → رفع على Supabase فوراً
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                        content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                        try: await status_msg.delete()
                                        except: pass
                                        try: os.remove(file_path)
                                        except: pass
                                        return
                                except Exception:
                                    pass
                                await message.reply_text(
                                    f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                    else f"❌ File too large for Telegram ({size_str})"
                                )
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الفيديو ({size_str}). جرب تالي!" if lang == "ar"
                                    else f"❌ Failed to send video ({size_str}). Try again!"
                                )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Piped نجح!
                
                error_code = piped_result.get("error", "unknown") if piped_result else "unknown"
                logger.warning(f"⚠️ Piped failed ({error_code}), trying Cobalt Self-Hosted...")
                    
            except ImportError:
                logger.warning("⚠️ piped_api module not available, skipping Piped")
            except Exception as piped_err:
                logger.warning(f"⚠️ Piped error: {piped_err}, trying Cobalt Self-Hosted...")
        
        # ═══ المحاولة 7: Cobalt Self-Hosted (fallback) ═══
        cobalt_result = None
        if info is None:
            cobalt_result = await _try_cobalt_download(url, quality, tmpdir)
        
        if cobalt_result:
            logger.info(f"🔵 Cobalt Self-Hosted succeeded! Sending file directly...")
            filepath = cobalt_result["filepath"]
            filename = cobalt_result["filename"]
            filesize = cobalt_result["size"]
            video_height = cobalt_result.get("height", 720)
            video_title = cobalt_result.get("title", "Video")
            video_vcodec = "h264"
            video_acodec = "aac"
            
            info = {
                "title": video_title,
                "duration": cobalt_result.get("duration", 0),
                "height": video_height,
                "vcodec": "h264",
                "acodec": "aac",
                "requested_downloads": [{"height": video_height, "vcodec": "h264", "acodec": "aac"}],
            }
        
        # ═══ المحاولة 8: Cobalt JWT — آخر طبقة قبل Cloudflare Worker ═══
        # 🔴 ده JWT شخصي من cobalt.tools — بنستخدمه كـ آخر حل لو كل حاجة فشلت
        # ليه آخر واحد؟ لأن الـ JWT بيتجدد وبيوقف — مش حل دائم
        # بس لو شغال هيحل المشكلة وقتها
        if info is None and is_youtube:
            try:
                from config import COBALT_JWT
                
                if COBALT_JWT:
                    logger.info(f"🔐 Cobalt JWT: Last-resort attempt for {url[:80]}")
                    
                    try:
                        await status_msg.edit_text(
                            "🔐 جاري التحميل عبر Cobalt JWT..." if lang == "ar"
                            else "🔐 Downloading via Cobalt JWT..."
                        )
                    except:
                        pass
                    
                    jwt_quality_map = {"best": "1080", "medium": "720", "low": "480", "audio": "720"}
                    jwt_quality = jwt_quality_map.get(quality, "720")
                    is_jwt_audio = _is_audio_quality(quality)
                    
                    jwt_headers = {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Authorization": f"Bearer {COBALT_JWT}",
                    }
                    
                    jwt_payload = {
                        "url": url,
                        "videoQuality": jwt_quality,
                        "filenameStyle": "classic",
                    }
                    
                    if is_jwt_audio:
                        jwt_payload["downloadMode"] = "audio"
                        jwt_payload["audioFormat"] = "mp3"
                    
                    jwt_result = await _cobalt_api_request(
                        "https://api.cobalt.tools", jwt_payload, jwt_headers,
                        jwt_quality, is_jwt_audio, tmpdir
                    )
                    
                    if jwt_result and jwt_result.get("filepath"):
                        logger.info(f"🔐 Cobalt JWT succeeded! File: {jwt_result['filepath']}")
                        
                        file_path = jwt_result["filepath"]
                        file_size = jwt_result.get("size", os.path.getsize(file_path))
                        video_title = jwt_result.get("title", "YouTube Video")
                        video_height = jwt_result.get("height", 720)
                        
                        size_mb = file_size / (1024 * 1024)
                        size_str = f"{size_mb:.1f}MB"
                        
                        # 🛡️ Safety check on Cobalt JWT downloaded media
                        try:
                            jwt_file_type = "audio" if _is_audio_quality(quality) else "video"
                            is_safe_jwt, block_msg_jwt, _reason_jwt = await comprehensive_media_safety_check(
                                title=video_title, file_path=file_path, file_type=jwt_file_type,
                                platform="telegram", user_id=str(user_id), lang=lang,
                            )
                            if not is_safe_jwt:
                                await message.reply_text(block_msg_jwt, parse_mode="HTML")
                                try: os.remove(file_path)
                                except: pass
                                return
                        except Exception:
                            pass  # Fail-open
                        
                        increment_usage(user_id, "youtube_summaries")
                        try: track_event("media_downloads")
                        except: pass
                        
                        await status_msg.delete()
                        
                        if _is_audio_quality(quality):
                            bitrate = _get_audio_bitrate(quality)
                            audio_sent = await _send_telegram_audio(message, file_path, video_title, size_str, lang, method_name="Cobalt JWT", bitrate=bitrate)
                            if audio_sent:
                                try: os.remove(file_path)
                                except: pass
                                return
                            # 🔴 لو الإرسال فشل — نجرب Supabase
                            try:
                                from supabase_storage import upload_and_get_link
                                cloud_msg = await upload_and_get_link(
                                    file_path=file_path, filename=f"{video_title[:50]}.mp3",
                                    content_type="audio/mpeg", platform="telegram", title=video_title, lang=lang,
                                )
                                if cloud_msg:
                                    await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                    try: os.remove(file_path)
                                    except: pass
                                    return
                            except:
                                pass
                            await message.reply_text(
                                f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send audio ({size_str}). Try again!"
                            )
                            try: os.remove(file_path)
                            except: pass
                            return
                        else:
                            try:
                                with open(file_path, 'rb') as f:
                                    tech_info = f"{video_height}p | {size_str} | Cobalt JWT"
                                    caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {video_title[:200]}\n📊 {tech_info}"
                                    await message.reply_video(
                                        video=f, filename=f"{video_title[:50]}.mp4",
                                        caption=caption,
                                        parse_mode="HTML",
                                        supports_streaming=True,
                                    )
                            except Exception as send_err:
                                logger.warning(f"⚠️ Cobalt JWT video send failed: {send_err}")
                                if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                    # 🔴 لو الملف كبير → رفع على Supabase فوراً
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=jwt_file_path, filename=f"{jwt_title[:50]}.mp4",
                                            content_type="video/mp4", platform="telegram", title=jwt_title, lang=lang,
                                        )
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                            try: await status_msg.delete()
                                            except: pass
                                            try: os.remove(jwt_file_path)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    await message.reply_text(
                                        f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                        else f"❌ Failed to send video ({size_str}). Try again!"
                                    )
                                else:
                                    await message.reply_text(
                                        f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                        else f"❌ Failed to send video ({size_str}). Try again!"
                                    )
                        
                        try: os.remove(file_path)
                        except: pass
                        return  # ✅ Cobalt JWT نجح!
                    
                    logger.warning(f"⚠️ Cobalt JWT failed, trying Cloudflare Worker...")
                else:
                    logger.info("🔐 Cobalt JWT: No COBALT_JWT configured, skipping")
            except Exception as jwt_err:
                logger.warning(f"⚠️ Cobalt JWT error: {jwt_err}")
        
        # ═══ المحاولة 9: Cloudflare Worker (آخر محاولة نهائية) ═══
        if info is None and is_youtube:
            from config import CLOUDFLARE_WORKER_URL
            if CLOUDFLARE_WORKER_URL:
                logger.info(f"🔄 All methods failed, trying Cloudflare Worker: {CLOUDFLARE_WORKER_URL}")
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
                    dl_type = "audio" if _is_audio_quality(quality) else "video"
                    api_url = f"{worker_url}/download?url={quote(url)}&type={dl_type}"
                    
                    cf_response = sync_requests.get(api_url, timeout=120, stream=True)
                    
                    if cf_response.status_code == 200:
                        content_type = cf_response.headers.get('Content-Type', '')
                        if 'video' in content_type or 'audio' in content_type or 'octet-stream' in content_type:
                            ext = "mp3" if _is_audio_quality(quality) else "mp4"
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
                                    ext = "mp3" if _is_audio_quality(quality) else "mp4"
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
                            except Exception as cf_json_err:
                                logger.warning(f"⚠️ CF Worker JSON parse error: {cf_json_err}")
                    else:
                        logger.warning(f"⚠️ CF Worker returned status {cf_response.status_code}")
                except Exception as cf_err:
                    logger.warning(f"⚠️ Cloudflare Worker fallback failed: {cf_err}")
            else:
                logger.info("⚠️ CLOUDFLARE_WORKER_URL not set, skipping CF Worker fallback")
        
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
        
        # ═══ إرسال الملف — Direct Send أو Supabase Cloud Upload ═══
        #
        # 🔴 المسار الجديد (بدون تجربة جودة أقل — على طول السحابة):
        # 1. لو الملف > 2GB → جودة أقل (الاستثناء الوحيد)
        # 2. لو الملف > 50MB → رفع على Supabase فوراً + بعت رابط
        # 3. لو الملف <= 50MB → إرسال مباشر
        # 4. لو الإرسال المباشر فشل → نحاول كـ document → Supabase
        #
        TELEGRAM_MAX_FREE = 50 * 1024 * 1024     # 50MB — بوت مجاني
        TELEGRAM_MAX_PREMIUM = 2000 * 1024 * 1024  # 2GB — بوت premium
        
        if filesize > TELEGRAM_MAX_PREMIUM:
            # فوق 2GB — ده الحد الأقصى الحقيقي
            if quality != "audio":
                if lang == "ar":
                    await status_msg.edit_text(f"⏳ جاري تحميل جودة أقل...")
                else:
                    await status_msg.edit_text(f"⏳ Trying lower quality...")
                os.remove(filepath)
                lower_quality = {"best": "medium", "medium": "low", "low": "audio"}.get(quality, "medium")
                # 🔴 FIX: نمرر status_msg=None عشان ينشئ واحد جديد — القديم ممكن يكون اتمسح
                return await _download_with_ytdlp(update_or_query, url, lower_quality, lang, user_id, status_msg=None)
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
        
        # 🛡️ Safety check on downloaded media before sending
        try:
            dl_file_type = "audio" if _is_audio_quality(quality) else "video"
            dl_title = info.get("title", filename) if info else filename
            is_safe_dl, block_msg_dl, _reason_dl = await comprehensive_media_safety_check(
                title=dl_title, file_path=filepath, file_type=dl_file_type,
                platform="telegram", user_id=str(user_id), lang=lang,
            )
            if not is_safe_dl:
                await message.reply_text(block_msg_dl, parse_mode="HTML")
                try: shutil.rmtree(tmpdir, ignore_errors=True)
                except: pass
                return
        except Exception:
            pass  # Fail-open
        
        # إرسال الملف
        title = info.get("title", filename) if info else filename
        duration = info.get("duration", 0) if info else 0
        
        # 🔴 FIX v5: لو الجودة صوت، نتأكد إن الملف فعلاً صوت بس
        # بعض طرق التحميل بترجع فيديو حتى لو طلبنا صوت
        if _is_audio_quality(quality):
            bitrate = _get_audio_bitrate(quality)
            filepath = _ensure_audio_only(filepath, bitrate)
            if os.path.exists(filepath):
                filesize = os.path.getsize(filepath)
                filename = os.path.basename(filepath)
        
        # 🔴 FIX v4: معلومات الجودة الحقيقية في الـ caption
        size_mb = filesize / (1024 * 1024)
        size_str = f"{size_mb:.1f}MB"
        
        # 🔴 FIX: منحذفش status_msg هنا — ممكن نحتاجه لو الإرسال فشل
        # بنحذفه بس لو الإرسال نجح
        send_failed = False
        is_too_large = False
        
        if _is_audio_quality(quality):
            bitrate = _get_audio_bitrate(quality)
            audio_sent = await _send_telegram_audio(message, filepath, title, size_str, lang, bitrate=bitrate)
            if audio_sent:
                try: await status_msg.delete()
                except: pass
            else:
                send_failed = True
                is_too_large = filesize > TELEGRAM_MAX_FREE
                logger.warning(f"⚠️ Audio send failed | is_too_large={is_too_large}")
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
                # ✅ الإرسال نجح — نحذف status_msg
                try: await status_msg.delete()
                except: pass
            except Exception as send_err:
                send_failed = True
                # 🔴 FIX: نفرق بين "ملف كبير" و "خطأ تاني"
                err_str = str(send_err).lower()
                # 🔴 FIX: نقول "كبير" بس لو فعلاً عدى الحد
                file_exceeds_limit = filesize > TELEGRAM_MAX_FREE  # 50MB — ده الحد الحقيقي للبوت المجاني
                is_too_large = file_exceeds_limit and any(kw in err_str for kw in ["too large", "file is too big", "file too large", "exceeds", "413"])
                logger.warning(f"⚠️ Video send failed: {send_err} | is_too_large={is_too_large} | file_size={filesize}")
        
        # 🔴 FIX v5: لو الإرسال فشل — Supabase Cloud Upload (مع ضغط تلقائي) → جودة أقل → خطأ
        if send_failed:
            if is_too_large or filesize > TELEGRAM_MAX_FREE:
                # الملف كبير (>50MB) — نحاول رفعه على Supabase (مع ضغط تلقائي)
                # 🔴 FIX v3: Supabase free tier = 50MB limit. upload_and_get_link auto-compresses.
                logger.info(f"☁️ File too large for Telegram ({size_str}), uploading to Supabase (with auto-compression)...")
                
                try:
                    await status_msg.edit_text(
                        "☁️ جاري ضغط الملف ورفعه على السحابة..." if lang == "ar" else "☁️ Compressing and uploading to cloud..."
                    )
                except:
                    pass
                
                # 🔴 رفع على Supabase (مع ضغط تلقائي لو > 50MB)
                cloud_success = False
                try:
                    from supabase_storage import upload_and_get_link
                    content_type = "audio/mpeg" if _is_audio_quality(quality) else "video/mp4"
                    ext = ".mp3" if _is_audio_quality(quality) else ".mp4"
                    safe_name = re.sub(r'[^\w\-.]', '_', title[:80]) + ext
                    
                    cloud_msg = await upload_and_get_link(
                        file_path=filepath,
                        filename=safe_name,
                        content_type=content_type,
                        platform="telegram",
                        title=title,
                        lang=lang,
                    )
                    
                    if cloud_msg:
                        # ✅ رفع السحابة نجح — نبعت الرابط
                        await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                        try: await status_msg.delete()
                        except: pass
                        cloud_success = True
                        try: shutil.rmtree(tmpdir, ignore_errors=True)
                        except: pass
                        return
                    else:
                        logger.warning("☁️ Supabase upload returned None (compression may have failed)")
                except Exception as sup_err:
                    logger.error(f"☁️ Supabase upload error: {sup_err}")
                
                if not cloud_success:
                    # 🔴 Supabase فشل — نجرب جودة أقل كآخر محاولة
                    logger.error(f"☁️ Supabase upload failed, trying lower quality")
                    if quality != "low" and quality != "audio":
                        # نجرب نحمل بجودة أقل
                        if lang == "ar":
                            await message.reply_text("⏳ فشل رفع الملف على السحابة. جاري تجربة جودة أقل...")
                        else:
                            await message.reply_text("⏳ Cloud upload failed. Trying lower quality...")
                        try: await status_msg.delete()
                        except: pass
                        try: shutil.rmtree(tmpdir, ignore_errors=True)
                        except: pass
                        # إعادة المحاولة بجودة أقل
                        lower_quality = {"best": "medium", "medium": "low"}.get(quality, "low")
                        # This is handled by the callback query handler, so we just return
                        return
                    else:
                        if lang == "ar":
                            await message.reply_text("❌ فشل رفع الملف على السحابة. جرب تاني!")
                        else:
                            await message.reply_text("❌ Failed to upload file to cloud. Try again!")
                        try: await status_msg.delete()
                        except: pass
                        return
            
            elif quality != "audio":
                # مشكلة تانية (مش حجم) — نجرب نبعته كـ document
                logger.info(f"⚠️ Video send failed (not size), trying send as document...")
                try:
                    with open(filepath, 'rb') as f:
                        await message.reply_document(
                            document=f, filename=filename,
                            caption=f"📥 {title[:200]}\n📁 {size_str}",
                        )
                    # لو وصل كـ document — نعتبره نجاح
                    try: os.remove(filepath)
                    except: pass
                    try: await status_msg.delete()
                    except: pass
                    return
                except Exception as doc_err:
                    logger.warning(f"⚠️ Document send also failed: {doc_err}")
                    
                    # 🔴 حتى الـ document فشل — نجرب Supabase كحل أخير
                    try:
                        from supabase_storage import upload_and_get_link
                        content_type = "video/mp4"
                        safe_name = re.sub(r'[^\w\-.]', '_', title[:80]) + ".mp4"
                        cloud_msg = await upload_and_get_link(
                            file_path=filepath,
                            filename=safe_name,
                            content_type=content_type,
                            platform="telegram",
                            title=title,
                            lang=lang,
                        )
                        if cloud_msg:
                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                            try: await status_msg.delete()
                            except: pass
                            return
                    except Exception as sup_err2:
                        logger.error(f"☁️ Final Supabase attempt failed: {sup_err2}")
                    
                    if lang == "ar":
                        await message.reply_text(f"❌ فشل إرسال الفيديو. جرب تاني!")
                    else:
                        await message.reply_text(f"❌ Failed to send video. Try again!")
                    try: await status_msg.delete()
                    except: pass
                    return
            
            else:
                # audio فشل بس مش بسبب حجم — نحاول Supabase
                try:
                    from supabase_storage import upload_and_get_link
                    safe_name = re.sub(r'[^\w\-.]', '_', title[:80]) + ".mp3"
                    cloud_msg = await upload_and_get_link(
                        file_path=filepath,
                        filename=safe_name,
                        content_type="audio/mpeg",
                        platform="telegram",
                        title=title,
                        lang=lang,
                    )
                    if cloud_msg:
                        await message.reply_text(cloud_msg, parse_mode="HTML")
                        try: await status_msg.delete()
                        except: pass
                        return
                except:
                    pass
                
                if lang == "ar":
                    await message.reply_text(f"❌ فشل إرسال الصوت. جرب تاني!")
                else:
                    await message.reply_text(f"❌ Failed to send audio. Try again!")
                try: await status_msg.delete()
                except: pass
    
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



