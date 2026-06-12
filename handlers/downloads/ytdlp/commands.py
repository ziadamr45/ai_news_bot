"""Download command handlers and direct media download helpers.

Contains download_command, _process_download_request, _download_direct_image,
and _download_direct_audio.
"""

import asyncio
import io
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from memory import get_language, increment_command_count
from premium import (
    check_limit, increment_usage, premium_required_message,
    get_premium_keyboard,
)
from dashboard import track_event

from content_safety import (
    check_query_safety,
    get_block_message,
)

from handlers.downloads.utils import (
    _is_audio_quality,
    _detect_platform,
    _is_direct_media_url,
    _get_quality_keyboard,
)

logger = logging.getLogger(__name__)


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
        # Lazy import to avoid circular dependency
        from handlers.downloads.ytdlp.download_main import _download_with_ytdlp
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
