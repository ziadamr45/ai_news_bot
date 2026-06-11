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

🔴 تحميل الصور:
1. المستخدم يكتب /photo قطط مثلاً
2. البوت بيسأله: عايز كام صورة؟ وبيعرض أزرار (3 / 5 / 10 / 15)
3. المستخدم يدوس على العدد ويتحملوا
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
    
    # 🛡️ Safety check on query
    try:
        is_safe, reason = await check_query_safety(query, platform="telegram", user_id=str(user_id))
        if not is_safe:
            msg = get_block_message(lang, reason)
            await update.message.reply_text(msg, parse_mode="HTML")
            return
    except Exception:
        pass  # Fail-open: let content through if safety check fails
    
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
        
        # 🛡️ Filter search results for safety
        try:
            results = await check_search_results_safety(results, platform="telegram", user_id=str(user_id))
            if not results:
                await status_msg.edit_text(get_no_safe_results_message(lang), parse_mode="HTML")
                return
        except Exception:
            pass  # Fail-open
        
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
    
    # 🛡️ Safety check on query
    try:
        is_safe, reason = await check_query_safety(query, platform="telegram", user_id=str(user_id))
        if not is_safe:
            msg = get_block_message(lang, reason)
            await update.message.reply_text(msg, parse_mode="HTML")
            return
    except Exception:
        pass  # Fail-open: let content through if safety check fails
    
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
        
        # 🛡️ Filter search results for safety
        try:
            results = await check_search_results_safety(results, platform="telegram", user_id=str(user_id))
            if not results:
                await status_msg.edit_text(get_no_safe_results_message(lang), parse_mode="HTML")
                return
        except Exception:
            pass  # Fail-open
        
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
    """أمر /photo <بحث> — بحث عن صور وتحميلها
    
    🔴 FIX: دلوقتي بيظهر أزرار اختيار عدد الصور (3 / 5 / 10 / 15)
    زي الواتساب بالظبط — المستخدم يدوس على العدد ويتنفذ التحميل
    """
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
            msg = "🖼️ <b>بحث صور</b>\n\nاكتب كلمة البحث بعد الأمر\nمثال: <code>/photo قطط لطيفة</code>\n\n💡 هتختار عدد الصور من الأزرار"
        else:
            msg = "🖼️ <b>Image Search</b>\n\nType your search query after the command\nExample: <code>/photo cute cats</code>\n\n💡 You'll choose the number of images from buttons"
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    try: track_event("photo_search_requests")
    except: pass
    
    # 🛡️ Safety check on query
    try:
        is_safe, reason = await check_query_safety(query, platform="telegram", user_id=str(user_id))
        if not is_safe:
            msg = get_block_message(lang, reason)
            await update.message.reply_text(msg, parse_mode="HTML")
            return
    except Exception:
        pass  # Fail-open: let content through if safety check fails
    
    # ═══ حفظ الاستعلام في cache + عرض أزرار عدد الصور ═══
    # مثل الواتساب بالضبط — المستخدم يختار العدد الأول وبعدين ننفذ البحث
    cache_key = hashlib.md5(f"ps_{user_id}_{query}".encode()).hexdigest()[:12]
    _cache_results(cache_key, [], "photo", query)
    
    if lang == "ar":
        text = f"🖼️ <b>بحث عن صور: {query}</b>\n━━━━━━━━━━━━━━━━━\n\nكم صورة تريد؟\n\n💡 اختار من الأزرار:"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("3 صور", callback_data=f"sp_{cache_key}_3"),
                InlineKeyboardButton("5 صور", callback_data=f"sp_{cache_key}_5"),
            ],
            [
                InlineKeyboardButton("10 صور", callback_data=f"sp_{cache_key}_10"),
                InlineKeyboardButton("15 صورة", callback_data=f"sp_{cache_key}_15"),
            ],
        ])
    else:
        text = f"🖼️ <b>Image search: {query}</b>\n━━━━━━━━━━━━━━━━━\n\nHow many images?\n\n💡 Choose from buttons:"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("3 images", callback_data=f"sp_{cache_key}_3"),
                InlineKeyboardButton("5 images", callback_data=f"sp_{cache_key}_5"),
            ],
            [
                InlineKeyboardButton("10 images", callback_data=f"sp_{cache_key}_10"),
                InlineKeyboardButton("15 images", callback_data=f"sp_{cache_key}_15"),
            ],
        ])
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def _execute_photo_search(query_obj, query_text: str, count: int, lang: str, user_id: int):
    """تنفيذ بحث الصور بعد ما المستخدم حدد العدد
    
    🔴 FIX v2:
    - بنبحث عن count * 3 نتائج عشان نعوض عن فشل تحميل بعض الصور
    - بنكمل نحمل لحد ما نوصل للعدد المطلوب بالظبط
    - بنستخدم safesearch=on عشان نمنع الصور غير المناسبة
    """
    message = query_obj.message
    
    try:
        from image_search import search_images, download_image
        
        if lang == "ar":
            await query_obj.edit_message_text(f"🖼️ جاري البحث عن {count} صور لـ: {query_text}...")
        else:
            await query_obj.edit_message_text(f"🖼️ Searching for {count} images: {query_text}...")
        
        # 🔴 FIX: بنبحث عن عدد أكبر عشان نوفر بدائل لو فشل تحميل بعض الصور
        # search_images داخلياً بيزود count * 3 في DuckDuckGo
        results = await search_images(query_text, count=count)
        
        if not results:
            if lang == "ar":
                await query_obj.edit_message_text("❌ مفيش صور. جرب كلمات بحث تانية!")
            else:
                await query_obj.edit_message_text("❌ No images found. Try different keywords!")
            return
        
        if lang == "ar":
            await query_obj.edit_message_text(f"📥 جاري تحميل {count} صور (وصلت {len(results)} نتيجة بحث)...")
        else:
            await query_obj.edit_message_text(f"📥 Downloading {count} images ({len(results)} results found)...")
        
        # 🔴 FIX: بنحمل من كل النتائج لحد ما نوصل للعدد المطلوب
        # مش بس أول count نتائج — لأن ممكن فشل تحميل بعض الصور
        sent_count = 0
        tmpdir = tempfile.mkdtemp(prefix="mybro_photo_")
        
        try:
            for i, r in enumerate(results):
                # 🔴 وقفنا لما وصلنا للعدد المطلوب
                if sent_count >= count:
                    break
                
                url = r.get("full_url") or r.get("url") or r.get("thumbnail", "")
                if not url:
                    continue
                
                # 🔴 محاولة تحميل الصورة الكاملة أولاً
                file_path = await download_image(url, output_dir=tmpdir)
                
                # 🔴 FIX: لو الصورة الكاملة فشلت، جرب الـ thumbnail كبديل
                if not file_path:
                    thumb_url = r.get("thumbnail", "")
                    if thumb_url and thumb_url != url:
                        logger.info(f"🖼️ Full image failed, trying thumbnail for result {i+1}")
                        file_path = await download_image(thumb_url, output_dir=tmpdir)
                
                if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 100:
                    # 🛡️ Safety check on image before sending
                    image_is_safe = True
                    try:
                        from content_safety import check_image_safety
                        is_safe_img, reason_img, _score = await check_image_safety(
                            image_path=file_path, platform="telegram", user_id=str(user_id)
                        )
                        if not is_safe_img:
                            image_is_safe = False
                            logger.info(f"🛡️ Image {i+1} blocked by safety check: {reason_img}")
                    except Exception:
                        pass  # Fail-open
                    
                    if not image_is_safe:
                        try: os.remove(file_path)
                        except: pass
                        continue  # Skip this image, don't count it
                    
                    desc = r.get('description', '')[:80]
                    author = r.get('author', '')
                    source = r.get('source', '')
                    
                    if lang == "ar":
                        caption = f"🖼️ صورة {sent_count + 1}/{count}"
                        if desc:
                            caption += f"\n📝 {desc}"
                        if author:
                            caption += f"\n📸 {author}"
                        if source:
                            caption += f"\n📁 {source}"
                    else:
                        caption = f"🖼️ Image {sent_count + 1}/{count}"
                        if desc:
                            caption += f"\n📝 {desc}"
                        if author:
                            caption += f"\n📸 {author}"
                        if source:
                            caption += f"\n📁 {source}"
                    
                    try:
                        with open(file_path, 'rb') as f:
                            await message.reply_photo(
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
            increment_usage(user_id, "image_analyses")
            try: track_event("photo_search_downloads")
            except: pass
            
            # حذف رسالة "جاري التحميل"
            try:
                await query_obj.delete_message()
            except:
                try:
                    if lang == "ar":
                        await query_obj.edit_message_text(f"✅ تم إرسال {sent_count}/{count} صورة!")
                    else:
                        await query_obj.edit_message_text(f"✅ Sent {sent_count}/{count} images!")
                except:
                    pass
        else:
            if lang == "ar":
                await query_obj.edit_message_text("❌ فشل تحميل الصور. جرب تاني!")
            else:
                await query_obj.edit_message_text("❌ Failed to download images. Try again!")
        
    except ImportError:
        logger.error("❌ image_search module not available")
        if lang == "ar":
            await query_obj.edit_message_text("❌ ميزة البحث عن صور مش متاحة حالياً.")
        else:
            await query_obj.edit_message_text("❌ Image search feature is currently unavailable.")
    except Exception as e:
        logger.error(f"❌ Photo search error: {e}", exc_info=True)
        try:
            if lang == "ar":
                await query_obj.edit_message_text("❌ حصل خطأ في البحث. جرب تاني!")
            else:
                await query_obj.edit_message_text("❌ Search error. Try again!")
        except:
            pass


# ═══════════════════════════════════════
# Callback Handler للنتائج
# ═══════════════════════════════════════

async def handle_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المستخدم من نتائج البحث
    
    🔴 أنماط الـ callback:
    - sv_{cache_key}_{index} → فيديو
    - sa_{cache_key}_{index} → صوت
    - sp_{cache_key}_{count} → صور (عدد الصور المطلوب)
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
    
    action = parts[0]  # sv أو sa أو sp
    
    # 🔴 معالجة خاصة لبحث الصور — sp_{cache_key}_{count}
    if action == "sp":
        cache_key = parts[1]
        try:
            count = int(parts[2])
        except ValueError:
            return
        
        # استرجاع الاستعلام من cache
        cached = _get_cached(cache_key)
        if not cached:
            if lang == "ar":
                await query.edit_message_text("❌ النتائج انتهت. ابحث تاني!")
            else:
                await query.edit_message_text("❌ Results expired. Search again!")
            return
        
        search_query = cached.get("query", "")
        
        if not search_query:
            if lang == "ar":
                await query.edit_message_text("❌ حصل خطأ. جرب تاني!")
            else:
                await query.edit_message_text("❌ Error occurred. Try again!")
            return
        
        # تنفيذ بحث الصور بالعدد المحدد
        await _execute_photo_search(query, search_query, count, lang, user_id)
        return
    
    # ═══ معالجة فيديو وصوت ═══
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
    
    # تحميل الفيديو أو الصوت — 🔴 FIX: عرض اختيار الجودة للمستخدم بدل التحميل المباشر
    if action == "sv":
        # فيديو — نعرض أزرار اختيار الجودة (زي /download بالظبط)
        from handlers.download_handlers import _get_quality_keyboard
        
        if lang == "ar":
            msg = f"📥 *اختر جودة التحميل*\n\n📺 {title[:100]}"
        else:
            msg = f"📥 *Choose download quality*\n\n📺 {title[:100]}"
        
        keyboard = _get_quality_keyboard(url, lang)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        
    elif action == "sa":
        # صوت — نعرض أزرار اختيار الجودة (مع الصوت كأول خيار)
        from handlers.download_handlers import _get_quality_keyboard, _store_url
        
        if lang == "ar":
            msg = f"🎵 *اختر جودة التحميل*\n\n📺 {title[:100]}"
        else:
            msg = f"🎵 *Choose download quality*\n\n📺 {title[:100]}"
        
        keyboard = _get_quality_keyboard(url, lang)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
