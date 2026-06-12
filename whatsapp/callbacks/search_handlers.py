"""
Search Handlers — Video, Audio, Photo Search
==============================================
Extracted from whatsapp/callbacks.py — contains:
- _wa_download_youtube: YouTube video/audio download helper
- _handle_wa_video_search: Dailymotion video search + download
- _handle_wa_audio_search: Audio search + download
- _handle_wa_photo_search: Photo search + count selection
- _handle_wa_search_callback: Handle search callback selections
"""

import hashlib
import logging
import time

from whatsapp.state import (
    _set_user_state,
    _clear_user_state,
    _wa_search_cache,
)

from whatsapp.api import (
    _send_whatsapp_message,
    _send_interactive_buttons,
    _send_interactive_list,
)

from content_safety import (
    check_query_safety,
    get_block_message,
    check_search_results_safety,
    get_no_safe_results_message,
)

logger = logging.getLogger(__name__)


async def _wa_download_youtube(wa_id: str, url: str, wa_user_id: int,
                                 contact_name: str, message_id: str, is_admin: bool,
                                 format: str = "720"):
    """تحميل فيديو/صوت YouTube عبر yt-dlp مباشرة للواتساب
    
    format: "720" لفيديو 720p, "mp3" لصوت, الخ
    """
    from whatsapp.media import _download_and_send_video

    # تحويل الفورمات لجودة yt-dlp
    is_audio = (format == "mp3")
    quality_map = {"1080": "best", "720": "medium", "360": "low", "mp3": "audio"}
    yt_quality = quality_map.get(format, "medium")
    
    logger.info(f"🎬 WA YouTube download: format={format} → yt_quality={yt_quality} for {url[:80]}")
    await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=yt_quality, force_audio=is_audio)


# ═══════════════════════════════════════
# WhatsApp Video/Audio/Photo Search Handlers
# ═══════════════════════════════════════

async def _handle_wa_video_search(wa_id: str, query: str, wa_user_id: int, 
                                   contact_name: str, message_id: str, is_admin: bool):
    """بحث Dailymotion + عرض نتائج + تحميل فيديو عبر WhatsApp"""
    # 🛡️ Safety: Check query before searching
    try:
        is_safe, reason = await check_query_safety(query, platform="whatsapp", user_id=str(wa_user_id))
        if not is_safe:
            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
            return
    except Exception as e:
        logger.warning(f"🛡️ Query safety check failed (allowing): {e}")
    
    await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في Dailymotion عن: {query}...")
    
    try:
        from dailymotion_search import search_dailymotion, format_search_results as format_dm_results
        
        results = await search_dailymotion(query, max_results=5)
        
        # ✅ FIX: If Dailymotion fails, fallback to YouTube search
        if not results:
            logger.info(f"🎬 Dailymotion search failed for '{query}', trying YouTube as fallback...")
            await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في YouTube عن: {query}...")
            try:
                from youtube_search import search_youtube
                results = await search_youtube(query, max_results=5)
            except Exception as yt_err:
                logger.warning(f"🎬 YouTube fallback also failed: {yt_err}")
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش نتائج. جرب كلمات بحث تانية!")
            return
        
        # 🛡️ Safety: Filter search results
        try:
            results = await check_search_results_safety(results, platform="whatsapp", user_id=str(wa_user_id))
            if not results:
                await _send_whatsapp_message(wa_id, get_no_safe_results_message("ar"))
                return
        except Exception as e:
            logger.warning(f"🛡️ Search results safety check failed (allowing): {e}")
        
        # حفظ النتائج في cache
        cache_key = hashlib.md5(f"wa_{wa_id}_{query}".encode()).hexdigest()[:12]
        _wa_search_cache[cache_key] = {
            "results": results,
            "query": query,
            "type": "video",
            "created_at": time.time(),
        }
        
        # عرض النتائج كـ interactive list
        text = format_dm_results(results, lang="ar")
        
        sections = [{
            "title": "🎬 نتائج Dailymotion",
            "rows": []
        }]
        
        for i, r in enumerate(results):
            title = r['title'][:24]
            desc = f"⏱ {r['duration']} | 📺 {r['channel'][:15]}"
            sections[0]["rows"].append({
                "id": f"wa_vs_{cache_key}_{i}",
                "title": f"{i+1}. {title}",
                "description": desc,
            })
        
        await _send_interactive_list(wa_id, text, "🎬 اختر فيديو", sections)
        
    except Exception as e:
        logger.error(f"WA video search error: {e}")
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ في البحث. جرب تاني!")


async def _handle_wa_audio_search(wa_id: str, query: str, wa_user_id: int,
                                   contact_name: str, message_id: str, is_admin: bool):
    """بحث صوت + عرض نتائج + تحميل صوت عبر WhatsApp
    
    🔴 FIX v3: Dailymotion كمحرك بحث أساسي للصوت
    - Dailymotion API مجاني ومفتوح — مش محتاج API key
    - yt-dlp بيدعم Dailymotion للتحميل
    - SoundCloud كـ fallback
    """
    # 🛡️ Safety: Check query before searching
    try:
        is_safe, reason = await check_query_safety(query, platform="whatsapp", user_id=str(wa_user_id))
        if not is_safe:
            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
            return
    except Exception as e:
        logger.warning(f"🛡️ Query safety check failed (allowing): {e}")
    
    await _send_whatsapp_message(wa_id, f"🔍 جاري البحث عن صوت: {query}...")
    
    results = None
    search_source = "dailymotion"
    
    try:
        # 🔴 الطريقة 1: Dailymotion Search (أساسي — مجاني ومفتوح ومستقر)
        try:
            from dailymotion_search import search_dailymotion
            results = await search_dailymotion(query, max_results=5)
            if results:
                # Mark results as audio search for proper handling
                for r in results:
                    r["_search_type"] = "audio"
                logger.info(f"🎵 Dailymotion audio search: {len(results)} results for '{query}'")
        except Exception as dm_err:
            logger.warning(f"🎵 Dailymotion search failed: {dm_err}")
        
        # 🔴 الطريقة 2: SoundCloud كـ fallback
        if not results:
            logger.info(f"🎵 Dailymotion search failed for '{query}', trying SoundCloud as fallback...")
            await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في SoundCloud عن: {query}...")
            try:
                from soundcloud_search import search_soundcloud
                results = await search_soundcloud(query, max_results=5)
                if results:
                    search_source = "soundcloud"
                    logger.info(f"🎵 SoundCloud audio search: {len(results)} results for '{query}'")
            except Exception as sc_err:
                logger.warning(f"🎵 SoundCloud fallback also failed: {sc_err}")
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش نتائج. جرب كلمات بحث تانية!")
            return
        
        # 🛡️ Safety: Filter search results
        try:
            results = await check_search_results_safety(results, platform="whatsapp", user_id=str(wa_user_id))
            if not results:
                await _send_whatsapp_message(wa_id, get_no_safe_results_message("ar"))
                return
        except Exception as e:
            logger.warning(f"🛡️ Search results safety check failed (allowing): {e}")
        
        cache_key = hashlib.md5(f"wa_{wa_id}_{query}".encode()).hexdigest()[:12]
        _wa_search_cache[cache_key] = {
            "results": results,
            "query": query,
            "type": "audio",
            "created_at": time.time(),
        }
        
        # تنسيق النتائج
        source_label = "Dailymotion" if search_source == "dailymotion" else "SoundCloud"
        text = f"🔍 *نتائج بحث صوت {source_label}* ({len(results)} نتيجة)\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        
        for i, r in enumerate(results):
            title = r.get('title', 'بدون عنوان')
            duration = r.get('duration', '0:00')
            channel = r.get('channel', '')
            views = r.get('views', '0')
            
            text += f"*{i+1}.* {title}\n"
            if duration and duration != "0:00":
                text += f"⏱ {duration}"
            if channel:
                text += f" | 🎤 {channel[:20]}"
            if views and views != "0":
                text += f" | ▶️ {views}"
            text += "\n\n"
        
        sections = [{
            "title": f"🎵 نتائج {source_label} - صوت",
            "rows": []
        }]
        
        for i, r in enumerate(results):
            title = r['title'][:24]
            desc = f"⏱ {r.get('duration', '0:00')} | 🎤 {r.get('channel', '')[:15]}"
            sections[0]["rows"].append({
                "id": f"wa_as_{cache_key}_{i}",
                "title": f"{i+1}. {title}",
                "description": desc,
            })
        
        await _send_interactive_list(wa_id, text, "🎵 اختر صوت", sections)
        
    except Exception as e:
        logger.error(f"WA audio search error: {e}")
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ في البحث. جرب تاني!")


async def _handle_wa_photo_search(wa_id: str, query: str, wa_user_id: int,
                                   contact_name: str, message_id: str, is_admin: bool):
    """بحث صور + اختيار عدد + إرسال عبر WhatsApp"""
    # 🛡️ Safety: Check query before searching
    try:
        is_safe, reason = await check_query_safety(query, platform="whatsapp", user_id=str(wa_user_id))
        if not is_safe:
            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
            return
    except Exception as e:
        logger.warning(f"🛡️ Query safety check failed (allowing): {e}")
    
    # حفظ الاستعلام في cache
    cache_key = hashlib.md5(f"wa_ph_{wa_id}_{query}".encode()).hexdigest()[:12]
    _wa_search_cache[cache_key] = {
        "query": query,
        "type": "photo",
        "results": [],
        "created_at": time.time(),
    }
    
    # 🔴 حفظ حالة المستخدم — في انتظار عدد الصور
    _set_user_state(wa_id, "photo_search", {"query": query, "cache_key": cache_key})
    
    text = f"🖼️ *بحث عن صور: {query}*\n━━━━━━━━━━━━━━━━━\n\nكم صورة تريد؟\n\n💡 ممكن تكتب رقم أو تختار من الأزرار:"
    
    await _send_interactive_buttons(wa_id, text, [
        {"id": f"wa_ph_{cache_key}_3", "title": "3 صور"},
        {"id": f"wa_ph_{cache_key}_5", "title": "5 صور"},
        {"id": f"wa_ph_{cache_key}_10", "title": "10 صور"},
    ])


async def _handle_wa_search_callback(wa_id: str, callback_id: str, wa_user_id: int,
                                      contact_name: str, message_id: str, is_admin: bool):
    """معالجة اختيارات البحث من الواتساب (list/button callbacks)"""
    from whatsapp.media import _show_quality_selection_for_search, _execute_photo_search

    # فيديو بالبحث: wa_vs_{cache_key}_{index}
    if callback_id.startswith("wa_vs_"):
        parts = callback_id.split("_", 3)
        if len(parts) < 4:
            return
        cache_key = parts[2]
        try:
            idx = int(parts[3])
        except ValueError:
            return
        
        cached = _wa_search_cache.get(cache_key)
        if not cached or idx >= len(cached["results"]):
            await _send_whatsapp_message(wa_id, "❌ النتائج انتهت! ابحث تاني.")
            return
        
        r = cached["results"][idx]
        # 🔴 FIX: مسح حالة المستخدم لأنه اختار من الأزرار — عشان الرسالة العادية اللي بعد كده متتعاملش كأنها اختيار بحث
        _clear_user_state(wa_id)
        # 🔴 FIX: بدل ما نحمل بجودة ثابتة، نعرض اختيار الجودة للمستخدم (زي التليجرام)
        await _show_quality_selection_for_search(wa_id, r['url'], r['title'], wa_user_id, contact_name, message_id, is_admin, search_type="video")
    
    # صوت بالبحث: wa_as_{cache_key}_{index}
    elif callback_id.startswith("wa_as_"):
        parts = callback_id.split("_", 3)
        if len(parts) < 4:
            return
        cache_key = parts[2]
        try:
            idx = int(parts[3])
        except ValueError:
            return
        
        cached = _wa_search_cache.get(cache_key)
        if not cached or idx >= len(cached["results"]):
            await _send_whatsapp_message(wa_id, "❌ النتائج انتهت! ابحث تاني.")
            return
        
        r = cached["results"][idx]
        # 🔴 FIX: مسح حالة المستخدم لأنه اختار من الأزرار — عشان الرسالة العادية اللي بعد كده متتعاملش كأنها اختيار بحث
        _clear_user_state(wa_id)
        # 🔴 FIX: بدل ما نحمل صوت مباشرة، نعرض اختيار الجودة (فيديو أو صوت)
        await _show_quality_selection_for_search(wa_id, r['url'], r['title'], wa_user_id, contact_name, message_id, is_admin, search_type="audio")
    
    # صور: wa_ph_{cache_key}_{count}
    elif callback_id.startswith("wa_ph_"):
        parts = callback_id.split("_", 3)
        if len(parts) < 4:
            return
        cache_key = parts[2]
        try:
            count = int(parts[3])
        except ValueError:
            return
        
        # 🔴 مسح حالة المستخدم لأنه اختار من الأزرار
        _clear_user_state(wa_id)
        
        cached = _wa_search_cache.get(cache_key)
        if not cached or not cached.get("query"):
            await _send_whatsapp_message(wa_id, "❌ انتهت الجلسة! ابحث تاني.")
            return
        
        query = cached["query"]

        # 🔴 FIX: بنستخدم _execute_photo_search بدل تكرار الكود
        # _execute_photo_search بيدي أخطاء بنفسه — مش محتاجين try/except هنا
        await _execute_photo_search(wa_id, query, count, wa_user_id, contact_name, message_id, is_admin, cache_key)
