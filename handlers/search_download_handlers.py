"""
Media Search Handler 🔍🎬🎵🖼️
أوامر البحث عن فيديو/صوت/صور وتحميلها في التليجرام

🔴 الأوامر:
- /video <بحث> — بحث YouTube وتحميل فيديو
- /audio <بحث> — بحث YouTube وتحميل صوت MP3
- /photo <بحث> — بحث عن صور وتحميلها

🔴 كيف بيشتغل:
1. المستخدم يكتب /video اسم الاغنية مثلاً
2. البوت بيبحث في YouTube ويعرض 5 نتائج كأزرار
3. المستخدم يدوس على نتيجة ويتحمل الفيديو/الصوت

🔴 ده نفس النظام الموجود في الواتساب بس دلوقتي للتليجرام كمان
"""

import logging
import asyncio
import os
import time
import hashlib
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from memory import get_language, increment_command_count
from premium import check_limit, increment_usage, premium_required_message, get_premium_keyboard
from dashboard import track_event

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# Cache للنتائج
# ═══════════════════════════════════════

_search_cache = {}
_CACHE_TTL = 600  # 10 دقائق


def _cache_results(key: str, results, search_type: str, query: str):
    """حفظ نتائج البحث في cache"""
    now = time.time()
    # مسح النتائج القديمة
    expired = [k for k, v in _search_cache.items() if now - v["created_at"] > _CACHE_TTL]
    for k in expired:
        del _search_cache[k]
    
    _search_cache[key] = {
        "results": results,
        "type": search_type,
        "query": query,
        "created_at": now,
    }


def _get_cached(key: str):
    """استرجاع نتائج البحث من cache"""
    entry = _search_cache.get(key)
    if not entry:
        return None
    if time.time() - entry["created_at"] > _CACHE_TTL:
        del _search_cache[key]
        return None
    return entry


# ═══════════════════════════════════════
# أوامر البحث
# ═══════════════════════════════════════

async def video_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /video <بحث> — بحث YouTube وتحميل فيديو"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    
    if not check_limit(user_id, "image_gen")["allowed"]:
        feature_name = "🎬 فيديو بالبحث / Video Search"
        await update.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return
    
    query = " ".join(context.args) if context.args else ""
    
    if not query:
        if lang == "ar":
            msg = "🎬 <b>بحث فيديو YouTube</b>\n\nاكتب كلمة البحث بعد الأمر\nمثال: <code>/video اغنية سعاد ماسي</code>"
        else:
            msg = "🎬 <b>YouTube Video Search</b>\n\nType your search query after the command\nExample: <code>/video music video</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    try: track_event("video_search_requests")
    except: pass
    
    status_msg = await update.message.reply_text(
        f"🔍 جاري البحث في YouTube عن: {query}..." if lang == "ar"
        else f"🔍 Searching YouTube for: {query}..."
    )
    
    try:
        from youtube_search import search_youtube, format_search_results
        
        results = await search_youtube(query, max_results=5)
        
        if not results:
            await status_msg.edit_text(
                "❌ مفيش نتائج. جرب كلمات بحث تانية!" if lang == "ar"
                else "❌ No results found. Try different keywords!"
            )
            return
        
        # حفظ النتائج في cache
        cache_key = hashlib.md5(f"vs_{user_id}_{query}".encode()).hexdigest()[:12]
        _cache_results(cache_key, results, "video", query)
        
        # عرض النتائج كأزرار
        await status_msg.delete()
        
        keyboard = []
        for i, r in enumerate(results):
            title = r.get('title', 'بدون عنوان')[:40]
            duration = r.get('duration', '')
            channel = r.get('channel', '')[:15]
            views = r.get('views', '')
            
            btn_text = f"{i+1}. {title}"
            if duration:
                btn_text += f" ({duration})"
            
            keyboard.append([
                InlineKeyboardButton(btn_text, callback_data=f"sv_{cache_key}_{i}")
            ])
        
        if lang == "ar":
            text = f"🎬 <b>نتائج بحث YouTube عن: {query}</b>\n\nاختار فيديو:"
        else:
            text = f"🎬 <b>YouTube results for: {query}</b>\n\nChoose a video:"
        
        await update.message.reply_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except ImportError:
        logger.error("❌ youtube_search module not available")
        await status_msg.edit_text(
            "❌ ميزة البحث مش متاحة حالياً." if lang == "ar"
            else "❌ Search feature is currently unavailable."
        )
    except Exception as e:
        logger.error(f"❌ Video search error: {e}")
        await status_msg.edit_text(
            f"❌ حصل خطأ في البحث. جرب تاني!" if lang == "ar"
            else "❌ Search error. Try again!"
        )


async def audio_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /audio <بحث> — بحث YouTube وتحميل صوت MP3"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    
    if not check_limit(user_id, "image_gen")["allowed"]:
        feature_name = "🎵 صوت بالبحث / Audio Search"
        await update.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return
    
    query = " ".join(context.args) if context.args else ""
    
    if not query:
        if lang == "ar":
            msg = "🎵 <b>بحث صوت YouTube</b>\n\nاكتب كلمة البحث بعد الأمر\nمثال: <code>/audio اغنية سعاد ماسي</code>"
        else:
            msg = "🎵 <b>YouTube Audio Search</b>\n\nType your search query after the command\nExample: <code>/audio song name</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    try: track_event("audio_search_requests")
    except: pass
    
    status_msg = await update.message.reply_text(
        f"🔍 جاري البحث في YouTube عن: {query}..." if lang == "ar"
        else f"🔍 Searching YouTube for: {query}..."
    )
    
    try:
        from youtube_search import search_youtube, format_search_results
        
        results = await search_youtube(query, max_results=5)
        
        if not results:
            await status_msg.edit_text(
                "❌ مفيش نتائج. جرب كلمات بحث تانية!" if lang == "ar"
                else "❌ No results found. Try different keywords!"
            )
            return
        
        # حفظ النتائج في cache
        cache_key = hashlib.md5(f"as_{user_id}_{query}".encode()).hexdigest()[:12]
        _cache_results(cache_key, results, "audio", query)
        
        await status_msg.delete()
        
        keyboard = []
        for i, r in enumerate(results):
            title = r.get('title', 'بدون عنوان')[:40]
            duration = r.get('duration', '')
            
            btn_text = f"{i+1}. {title}"
            if duration:
                btn_text += f" ({duration})"
            
            keyboard.append([
                InlineKeyboardButton(btn_text, callback_data=f"sa_{cache_key}_{i}")
            ])
        
        if lang == "ar":
            text = f"🎵 <b>نتائج بحث YouTube عن: {query}</b>\n\nاختار صوت:"
        else:
            text = f"🎵 <b>YouTube results for: {query}</b>\n\nChoose audio:"
        
        await update.message.reply_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except ImportError:
        logger.error("❌ youtube_search module not available")
        await status_msg.edit_text(
            "❌ ميزة البحث مش متاحة حالياً." if lang == "ar"
            else "❌ Search feature is currently unavailable."
        )
    except Exception as e:
        logger.error(f"❌ Audio search error: {e}")
        await status_msg.edit_text(
            f"❌ حصل خطأ في البحث. جرب تاني!" if lang == "ar"
            else "❌ Search error. Try again!"
        )


async def photo_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /photo <بحث> — بحث عن صور وتحميلها"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    
    if not check_limit(user_id, "image_gen")["allowed"]:
        feature_name = "🖼️ بحث صور / Image Search"
        await update.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return
    
    query = " ".join(context.args) if context.args else ""
    
    if not query:
        if lang == "ar":
            msg = "🖼️ <b>بحث صور</b>\n\nاكتب كلمة البحث بعد الأمر\nمثال: <code>/photo قطط لطيفة</code>\n\n💡 هنرسللك 3 صور تلقائياً"
        else:
            msg = "🖼️ <b>Image Search</b>\n\nType your search query after the command\nExample: <code>/photo cute cats</code>\n\n💡 We'll send you 3 images automatically"
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    try: track_event("photo_search_requests")
    except: pass
    
    status_msg = await update.message.reply_text(
        f"🖼️ جاري البحث عن صور لـ: {query}..." if lang == "ar"
        else f"🖼️ Searching images for: {query}..."
    )
    
    try:
        from image_search import search_images, download_image
        
        results = await search_images(query, count=3)
        
        if not results:
            await status_msg.edit_text(
                "❌ مفيش صور. جرب كلمات بحث تانية!" if lang == "ar"
                else "❌ No images found. Try different keywords!"
            )
            return
        
        await status_msg.edit_text(
            f"📥 جاري تحميل {len(results)} صور..." if lang == "ar"
            else f"📥 Downloading {len(results)} images..."
        )
        
        # تحميل وإرسال كل صورة
        sent_count = 0
        tmpdir = tempfile.mkdtemp(prefix="mybro_photo_")
        
        try:
            for i, r in enumerate(results[:3]):
                url = r.get("full_url") or r.get("url") or r.get("thumbnail", "")
                if not url:
                    continue
                
                file_path = await download_image(url, output_dir=tmpdir)
                
                if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 100:
                    desc = r.get('description', '')[:80]
                    author = r.get('author', '')
                    source = r.get('source', '')
                    
                    if lang == "ar":
                        caption = f"🖼️ صورة {i+1}/{len(results)}"
                        if desc:
                            caption += f"\n📝 {desc}"
                        if author:
                            caption += f"\n📸 {author}"
                        if source:
                            caption += f"\n📁 {source}"
                    else:
                        caption = f"🖼️ Image {i+1}/{len(results)}"
                        if desc:
                            caption += f"\n📝 {desc}"
                        if author:
                            caption += f"\n📸 {author}"
                        if source:
                            caption += f"\n📁 {source}"
                    
                    try:
                        with open(file_path, 'rb') as f:
                            await update.message.reply_photo(
                                photo=f,
                                caption=caption,
                                parse_mode="HTML",
                            )
                        sent_count += 1
                    except Exception as send_err:
                        logger.warning(f"⚠️ Failed to send image {i+1}: {send_err}")
                    finally:
                        try: os.remove(file_path)
                        except: pass
        
        finally:
            try:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            except:
                pass
        
        if sent_count > 0:
            try: os.remove(file_path) if file_path else None
            except: pass
            
            increment_usage(user_id, "image_analyses")
            try: track_event("photo_search_downloads")
            except: pass
            
            await status_msg.delete()
        else:
            await status_msg.edit_text(
                "❌ فشل تحميل الصور. جرب تاني!" if lang == "ar"
                else "❌ Failed to download images. Try again!"
            )
        
    except ImportError:
        logger.error("❌ image_search module not available")
        await status_msg.edit_text(
            "❌ ميزة البحث عن صور مش متاحة حالياً." if lang == "ar"
            else "❌ Image search feature is currently unavailable."
        )
    except Exception as e:
        logger.error(f"❌ Photo search error: {e}")
        await status_msg.edit_text(
            f"❌ حصل خطأ في البحث. جرب تاني!" if lang == "ar"
            else "❌ Search error. Try again!"
        )


# ═══════════════════════════════════════
# Callback Handler للنتائج
# ═══════════════════════════════════════

async def handle_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المستخدم من نتائج البحث
    
    🔴 أنماط الـ callback:
    - sv_{cache_key}_{index} → فيديو
    - sa_{cache_key}_{index} → صوت
    """
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    lang = get_language(user_id)
    
    # تحليل الـ callback data
    parts = data.split("_")
    if len(parts) < 3:
        return
    
    action = parts[0]  # sv أو sa
    cache_key = parts[1]
    try:
        index = int(parts[2])
    except ValueError:
        return
    
    # استرجاع النتائج من cache
    cached = _get_cached(cache_key)
    if not cached:
        if lang == "ar":
            await query.edit_message_text("❌ النتائج انتهت. ابحث تاني!")
        else:
            await query.edit_message_text("❌ Results expired. Search again!")
        return
    
    results = cached.get("results", [])
    search_type = cached.get("type", "video")
    search_query = cached.get("query", "")
    
    if index >= len(results):
        return
    
    selected = results[index]
    url = selected.get("url", "")
    title = selected.get("title", "")
    
    if not url:
        if lang == "ar":
            await query.edit_message_text("❌ الرابط مش متاح.")
        else:
            await query.edit_message_text("❌ URL not available.")
        return
    
    # تحميل الفيديو أو الصوت
    if action == "sv":
        # فيديو — نستخدم download handler
        quality = "best"
        await query.edit_message_text(
            f"📥 جاري تحميل الفيديو: {title[:50]}..." if lang == "ar"
            else f"📥 Downloading video: {title[:50]}..."
        )
        
        from handlers.download_handlers import _download_with_ytdlp
        await _download_with_ytdlp(query, url, quality, lang, user_id)
        
    elif action == "sa":
        # صوت — نستخدم download handler مع جودة audio
        await query.edit_message_text(
            f"🎵 جاري تحميل الصوت: {title[:50]}..." if lang == "ar"
            else f"🎵 Downloading audio: {title[:50]}..."
        )
        
        from handlers.download_handlers import _download_with_ytdlp
        await _download_with_ytdlp(query, url, "audio", lang, user_id)
