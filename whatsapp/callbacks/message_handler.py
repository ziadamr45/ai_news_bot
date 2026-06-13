"""
Message Handler — Full AI Integration
======================================
Extracted from whatsapp/callbacks.py — contains:
- _handle_incoming_message: Process an incoming WhatsApp message with full feature set
"""

import os
import re
import logging
import asyncio
import hashlib
import time

from whatsapp.state import (
    DEVELOPER_WHATSAPP_URL,
    WHATSAPP_ACCESS_TOKEN,
    ALLOWED_WA_NUMBERS,
    _set_user_state,
    _get_user_state,
    _clear_user_state,
    _wa_user_pdf_context,
    _wa_user_edit_images,
    _get_url,
    _detect_platform,
    _extract_url,
    _strip_html_for_whatsapp,
    _split_whatsapp_message,
    _log_event,
    _log_activity,
    _is_duplicate_wa_message,
    _is_wa_admin,
    _ensure_wa_admin_premium,
    _wa_phone_to_user_id,
    _wa_search_cache,
    _COMMAND_TRIGGERS,
)

from whatsapp.api import (
    _send_whatsapp_message,
    _mark_message_read,
    _send_interactive_buttons,
    ThinkingFeedback,
)

from content_safety import (
    check_query_safety,
    get_block_message,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# Message Handler — Full AI Integration
# ═══════════════════════════════════════

async def _handle_incoming_message(message: dict, value: dict):
    """Process an incoming WhatsApp message with full feature set."""
    # Lazy imports for media and commands (avoid circular dependency)
    from whatsapp.commands import _handle_command, _handle_command_with_arg
    from whatsapp.media import (
        _download_and_send_video,
        _generate_and_send_image,
        _edit_and_send_image,
        _execute_photo_search,
        _transcribe_audio,
        _download_wa_media_base64,
        _analyze_image,
        _analyze_document,
        _show_quality_selection,
        _show_quality_selection_for_search,
    )
    # Lazy imports for cross-module references within callbacks package
    from whatsapp.callbacks.ai_response import _send_ai_response
    from whatsapp.callbacks.admin_handler import _handle_admin_with_args
    from whatsapp.callbacks.search_handlers import (
        _wa_download_youtube,
        _handle_wa_video_search,
        _handle_wa_audio_search,
        _handle_wa_search_callback,
    )

    try:
        wa_id = message.get("from", "")
        message_type = message.get("type", "")
        message_id = message.get("id", "")
        timestamp = message.get("timestamp", "")

        # Deduplication
        if _is_duplicate_wa_message(message_id):
            logger.debug(f"⏭️ Duplicate WA message {message_id} — skipping")
            return

        # Security: Check allowed numbers
        if ALLOWED_WA_NUMBERS and wa_id not in ALLOWED_WA_NUMBERS:
            logger.warning(f"🚫 WA message from unauthorized number: {wa_id}")
            return

        # Mark message as read
        asyncio.create_task(_mark_message_read(message_id))

        # Contact info
        contacts = value.get("contacts", [])
        contact_name = ""
        if contacts:
            contact_name = contacts[0].get("profile", {}).get("name", "Unknown")

        # Generate user ID
        # ✅ FIX: First check if user already exists by wa_phone (handles hash changes after restarts)
        # If found, use their existing user_id to preserve all data
        from memory import find_user_by_wa_phone
        existing_user_id = find_user_by_wa_phone(wa_id)
        if existing_user_id is not None:
            wa_user_id = existing_user_id
        else:
            wa_user_id = _wa_phone_to_user_id(wa_id)
        is_admin = _is_wa_admin(wa_id)

        # Ensure admin is premium
        if is_admin:
            _ensure_wa_admin_premium(wa_id)

        # Check if user is banned (skip for admin)
        if not is_admin:
            try:
                from memory import _execute, _is_postgres
                ph = "%s" if _is_postgres() else "?"
                banned = _execute(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (wa_user_id,), fetchone=True)
                if banned:
                    await _send_whatsapp_message(wa_id, f"🚫 تم حظر حسابك. لو عندك استفسار تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return
            except Exception:
                pass

        # Ensure user exists in DB
        try:
            from memory import _ensure_user_in_db
            _ensure_user_in_db(wa_user_id, platform="whatsapp")
            # Save name from WhatsApp profile
            updates = {}
            if contact_name and contact_name != "Unknown":
                updates["name"] = contact_name
                # 🔴 حفظ الاسم الأصلي من بروفايل واتساب (منفصل عن الاسم المفضل)
                updates["profile_name"] = contact_name
            # 🔴 حفظ رقم واتساب المستخدم — ضروري لإرسال الإشعارات من التليجرام
            if wa_id:
                updates["wa_phone"] = wa_id
            if updates:
                try:
                    from memory import update_user
                    update_user(wa_user_id, updates)
                except Exception:
                    pass
        except Exception:
            pass

        # Extract message content
        content = ""
        is_audio = False
        is_image = False
        is_document = False
        image_media_id = ""
        audio_media_id = ""
        document_media_id = ""
        document_filename = ""   # 🔴 FIX: WhatsApp document filename
        document_mime_type = ""  # 🔴 FIX: WhatsApp document MIME type
        interactive_id = ""

        if message_type == "text":
            content = message.get("text", {}).get("body", "")
        elif message_type == "audio":
            audio_media_id = message.get("audio", {}).get("id", "")
            is_audio = True
            content = "[Audio message]"
        elif message_type == "image":
            image_media_id = message.get("image", {}).get("id", "")
            caption = message.get("image", {}).get("caption", "")
            is_image = True
            content = caption if caption else "[Image]"
        elif message_type == "video":
            content = message.get("video", {}).get("caption", "[Video]")
        elif message_type == "document":
            document_media_id = message.get("document", {}).get("id", "")
            is_document = True
            content = message.get("document", {}).get("caption", "[Document]")
            # 🔴 FIX: Extract filename and mime_type from WhatsApp document message
            # Without filename, PDFAgent defaults to "document.pdf" which breaks
            # Word/TXT/CSV/JSON files — they'd be processed as PDF and fail
            document_filename = message.get("document", {}).get("filename", "")
            document_mime_type = message.get("document", {}).get("mime_type", "")
        elif message_type == "location":
            loc = message.get("location", {})
            content = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type", "")
            if interactive_type == "button_reply":
                button_reply = interactive.get("button_reply", {})
                content = button_reply.get("title", "[Button]")
                interactive_id = button_reply.get("id", "")
            elif interactive_type == "list_reply":
                list_reply = interactive.get("list_reply", {})
                content = list_reply.get("title", "[List Item]")
                interactive_id = list_reply.get("id", "")
        elif message_type == "reaction":
            emoji = message.get("reaction", {}).get("emoji", "")
            content = f"[Reaction: {emoji}]"
        elif message_type == "sticker":
            content = "[Sticker]"
        elif message_type == "contacts":
            content = "[Contacts]"
        elif message_type == "order":
            content = "[Order]"
        else:
            content = f"[{message_type}]"

        _log_event("IN", "message", {
            "from": wa_id,
            "contact_name": contact_name,
            "type": message_type,
            "content": content[:200],
            "message_id": message_id,
            "interactive_id": interactive_id,
        })

        logger.info(f"📩 WA Message from {contact_name} ({wa_id}): {content[:100]}")

        # Skip non-processable types
        if message_type in ("reaction", "sticker", "contacts", "order", "location"):
            return

        # ═══ الأولوية الأولى: Workflow النشط ═══
        # لو المستخدم في وسط عملية تفاعلية (بحث صور، تعديل صورة، الخ)
        # الرسالة بتروح للخدمة المسؤولة مش للذكاء الاصطناعي
        active_state = _get_user_state(wa_id)
        if active_state and message_type == "text" and content.strip():
            flow = active_state.get("flow", "")
            state_data = active_state.get("data", {})
            
            # 🔴 لو المستخدم عايز يلغي — أي كلمة إلغاء
            cancel_words = ["إلغاء", "الغاء", "cancel", "خلاص", "لا", "ابقى لا", "امسح"]
            if content.strip().lower() in cancel_words:
                _clear_user_state(wa_id)
                await _send_whatsapp_message(wa_id, "✅ تم إلغاء العملية.")
                return
            
            if flow == "photo_search":
                # المستخدم بيرد على "كم صورة تريد؟"
                query = state_data.get("query", "")
                cache_key = state_data.get("cache_key", "")
                # محاولة استخراج رقم من الرسالة
                import re as _re_num
                num_match = _re_num.search(r'\d+', content.strip())
                if num_match:
                    count = int(num_match.group())
                    # أقصى 20 صورة
                    count = min(count, 20)
                    if count < 1:
                        count = 3
                    logger.info(f"📸 Photo search workflow: user wants {count} images for '{query}'")
                    _clear_user_state(wa_id)
                    # كمل البحث بالعدد المحدد
                    await _execute_photo_search(wa_id, query, count, wa_user_id, contact_name, message_id, is_admin, cache_key)
                    return
                else:
                    # مش رقم — ممكن المستخدم كتب حاجة تانية
                    await _send_whatsapp_message(wa_id, "📝 اكتب رقم (مثلاً: 3 أو 5 أو 10) أو اضغط إلغاء.")
                    return
            
            elif flow == "image_edit":
                # المستخدم بيرد بوصف التعديل بعد ما بعت صورة
                cached_image = _wa_user_edit_images.get(wa_user_id, {})
                if cached_image and cached_image.get("image_base64"):
                    edit_prompt = content.strip()
                    logger.info(f"🖌️ Image edit workflow: user says '{edit_prompt[:50]}'")
                    _clear_user_state(wa_id)
                    # كمل تعديل الصورة
                    await _edit_and_send_image(wa_id, cached_image["image_base64"], edit_prompt, wa_user_id, contact_name, message_id, is_admin)
                    return
                else:
                    _clear_user_state(wa_id)
                    await _send_whatsapp_message(wa_id, "⚠️ الصورة انتهت صلاحيتها. ابعت صورة تانية وحاول تاني.")
                    return
            
            elif flow == "video_search":
                # المستخدم يكتب رقم الفيديو من النتائج
                cache_key = state_data.get("cache_key", "")
                cached = _wa_search_cache.get(cache_key)
                if cached and cached.get("results"):
                    num_match = __import__('re').search(r'\d+', content.strip())
                    if num_match:
                        idx = int(num_match.group()) - 1  # المستخدم بيكتب 1-5 ونحوله لـ 0-4
                        if 0 <= idx < len(cached["results"]):
                            r = cached["results"][idx]
                            logger.info(f"🎬 Video search workflow: user selected #{idx+1}")
                            _clear_user_state(wa_id)
                            await _send_whatsapp_message(wa_id, f"🎬 جاري تحميل الفيديو...\n\n📺 {r['title']}")
                            await _wa_download_youtube(wa_id, r['url'], wa_user_id, contact_name, message_id, is_admin, format="720")
                            return
                    # مش رقم صحيح
                    await _send_whatsapp_message(wa_id, "📝 اكتب رقم الفيديو (1-5) من القائمة أو اضغط إلغاء.")
                    return
                else:
                    _clear_user_state(wa_id)
                    await _send_whatsapp_message(wa_id, "❌ انتهت صلاحية النتائج! ابحث تاني.")
                    return
            
            elif flow == "audio_search":
                # نفس video_search بس صوت
                cache_key = state_data.get("cache_key", "")
                cached = _wa_search_cache.get(cache_key)
                if cached and cached.get("results"):
                    num_match = __import__('re').search(r'\d+', content.strip())
                    if num_match:
                        idx = int(num_match.group()) - 1
                        if 0 <= idx < len(cached["results"]):
                            r = cached["results"][idx]
                            logger.info(f"🎵 Audio search workflow: user selected #{idx+1}")
                            _clear_user_state(wa_id)
                            await _send_whatsapp_message(wa_id, f"🎵 جاري تحميل الصوت...\n\n📺 {r['title']}")
                            await _wa_download_youtube(wa_id, r['url'], wa_user_id, contact_name, message_id, is_admin, format="mp3")
                            return
                    await _send_whatsapp_message(wa_id, "📝 اكتب رقم الصوت (1-5) من القائمة أو اضغط إلغاء.")
                    return
                else:
                    _clear_user_state(wa_id)
                    await _send_whatsapp_message(wa_id, "❌ انتهت صلاحية النتائج! ابحث تاني.")
                    return
            
            elif flow == "video_search_query":
                # المستخدم كتب كلمات البحث بعد ما ضغط "فيديو بالبحث"
                query = content.strip()
                logger.info(f"🎬 Video search query workflow: user typed '{query[:50]}'")
                _clear_user_state(wa_id)
                await _handle_wa_video_search(wa_id, query, wa_user_id, contact_name, message_id, is_admin)
                # حفظ حالة انتظار اختيار الفيديو
                cache_key = hashlib.md5(f"wa_vs_{wa_id}_{query}".encode()).hexdigest()[:12]
                _set_user_state(wa_id, "video_search", {"cache_key": cache_key})
                return
            
            elif flow == "audio_search_query":
                # المستخدم كتب كلمات البحث بعد ما ضغط "صوت بالبحث"
                query = content.strip()
                logger.info(f"🎵 Audio search query workflow: user typed '{query[:50]}'")
                _clear_user_state(wa_id)
                await _handle_wa_audio_search(wa_id, query, wa_user_id, contact_name, message_id, is_admin)
                # حفظ حالة انتظار اختيار الصوت
                cache_key = hashlib.md5(f"wa_as_{wa_id}_{query}".encode()).hexdigest()[:12]
                _set_user_state(wa_id, "audio_search", {"cache_key": cache_key})
                return
            
            elif flow == "photo_search_query":
                # المستخدم كتب كلمات البحث بعد ما ضغط "بحث صور"
                query = content.strip()
                logger.info(f"🖼️ Photo search query workflow: user typed '{query[:50]}'")
                _clear_user_state(wa_id)
                # نوجهه لـ photo search اللي هيبدأ الـ workflow
                await _handle_command_with_arg(wa_id, "photo_search_query", query, wa_user_id, contact_name, message_id, is_admin)
                return

        # ═══ Handle Interactive Button/List Replies ═══
        if interactive_id:
            # Check for download quality selections first (dl_v_b_KEY, dl_v_m_KEY, dl_aq_320_KEY, etc.)
            if interactive_id.startswith("dl_"):
                quality_map = {
                    "dl_v_b_": "best",
                    "dl_v_m_": "medium",
                    "dl_v_l_": "low",
                    "dl_a_": "audio",
                }
                # 🔴 Audio quality with specific bitrate: dl_aq_{bitrate}_{key}
                audio_quality = None
                if interactive_id.startswith("dl_aq_"):
                    # dl_aq_320_abc123 → quality="audio_320", url_key="abc123"
                    aq_parts = interactive_id.split("_", 3)  # dl, aq, 320, abc123
                    if len(aq_parts) >= 4:
                        bitrate = aq_parts[2]
                        audio_quality = f"audio_{bitrate}"
                        url_key = aq_parts[3]
                
                if audio_quality:
                    cached_url = _get_url(url_key)
                    if cached_url:
                        logger.info(f"📥 Audio quality selection: {audio_quality} for URL key {url_key}")
                        await _download_and_send_video(wa_id, cached_url, wa_user_id, contact_name, message_id, is_admin, quality=audio_quality)
                    else:
                        await _send_whatsapp_message(wa_id, "⚠️ انتهت صلاحية الرابط. ابعت الرابط تاني! 📥")
                    return
                
                for prefix, q in quality_map.items():
                    if interactive_id.startswith(prefix):
                        url_key = interactive_id[len(prefix):]
                        cached_url = _get_url(url_key)
                        if cached_url:
                            logger.info(f"📥 Quality selection: {q} for URL key {url_key}")
                            # تحميل مباشر بـ yt-dlp لكل المنصات
                            await _download_and_send_video(wa_id, cached_url, wa_user_id, contact_name, message_id, is_admin, quality=q)
                        else:
                            await _send_whatsapp_message(wa_id, "⚠️ انتهت صلاحية الرابط. ابعت الرابط تاني! 📥")
                        return
                # Unknown dl_ prefix
                await _send_whatsapp_message(wa_id, "⚠️ اختيار مش معروف. جرب تاني! 📥")
                return
            
            command_map = {
                # Main features
                "cmd_chat": "chat",
                "cmd_commands": "commands",
                "cmd_news": "news",
                "cmd_more_news": "news",
                "cmd_about": "about",
                "cmd_admin": "admin",
                # News
                "cmd_breaking": "breaking",
                "cmd_weekly": "weekly",
                "cmd_trending": "trending",
                # AI
                "cmd_ask": "ask",
                "cmd_ask_ai": "cmd_ask_ai",
                "cmd_ask_code": "cmd_ask_code",
                "cmd_search": "search",
                "cmd_search_ai": "cmd_search_ai",
                "cmd_search_code": "cmd_search_code",
                "cmd_learn": "learn",
                "cmd_learn_ai": "cmd_learn_ai",
                "cmd_learn_ml": "cmd_learn_ml",
                "cmd_learn_dl": "cmd_learn_dl",
                "cmd_learn_nlp": "cmd_learn_nlp",
                "cmd_learn_llm": "cmd_learn_llm",
                "cmd_learn_python": "cmd_learn_python",
                "cmd_learn_web": "cmd_learn_web",
                "cmd_roadmap": "roadmap",
                "cmd_roadmap_ai": "cmd_roadmap_ai",
                "cmd_roadmap_ml": "cmd_roadmap_ml",
                "cmd_roadmap_dl": "cmd_roadmap_dl",
                "cmd_roadmap_nlp": "cmd_roadmap_nlp",
                "cmd_roadmap_llm": "cmd_roadmap_llm",
                # Company
                "cmd_company": "company",
                "cmd_company_openai": "cmd_company_openai",
                "cmd_company_google": "cmd_company_google",
                "cmd_company_anthropic": "cmd_company_anthropic",
                "cmd_company_meta": "cmd_company_meta",
                "cmd_company_xai": "cmd_company_xai",
                "cmd_company_nvidia": "cmd_company_nvidia",
                # Settings
                "cmd_subscribe": "subscribe",
                "cmd_subscribe_confirm": "subscribe_confirm",
                "cmd_skip_subscribe": "skip_subscribe",
                "cmd_unsubscribe_confirm": "unsubscribe_confirm",
                "cmd_language": "language",
                "cmd_lang_ar": "lang_ar",
                "cmd_lang_en": "lang_en",
                "cmd_settings": "settings",
                # Memory
                "cmd_memory": "memory",
                "cmd_memory_view": "memory_view",
                "cmd_memory_reset": "memory_reset",
                "cmd_memory_reset_confirm": "memory_reset_confirm",
                "cmd_forget": "forget",
                # Premium / Plan
                "cmd_premium": "premium",
                "cmd_plan": "plan",
                # Favorites
                "cmd_favorite": "favorite",
                "cmd_favorites": "favorites",
                # Download
                "cmd_download": "download",
                "cmd_download_yt": "download_yt",
                # Study
                "cmd_study": "study",
                "cmd_study_learn": "cmd_study_learn",
                "cmd_study_quiz": "cmd_study_quiz",
                "cmd_study_exam": "cmd_study_exam",
                "cmd_study_notes": "cmd_study_notes",
                "cmd_study_flash": "cmd_study_flash",
                # YouTube
                "cmd_youtube": "youtube",
                # Cookies
                "cmd_cookies": "cookies",
                # PDF
                "cmd_pdf": "pdf",
                "cmd_pdf_keypoints": "pdf_keypoints",
                "cmd_pdf_ask": "pdf_ask",
                # Image gen/edit
                "cmd_image_gen": "image_gen",
                "cmd_image_edit": "image_edit",
                # 🔴 إصلاح: أضفنا أزرار البحث اللي كانت مكسورة
                "video_search": "video_search",
                "audio_search": "audio_search",
                "photo_search": "photo_search",
            }
            cmd = command_map.get(interactive_id)
            if cmd:
                await _handle_command(wa_id, cmd, wa_user_id, contact_name, message_id)
                return
            
            # 🔍 Handle search callbacks (video/audio/photo selections)
            if interactive_id.startswith("wa_vs_") or interactive_id.startswith("wa_as_") or interactive_id.startswith("wa_ph_"):
                await _handle_wa_search_callback(wa_id, interactive_id, wa_user_id, contact_name, message_id, is_admin)
                return

        # ═══ Handle Text Commands ═══
        if message_type == "text" and content.strip():
            content_lower = content.strip().lower()

            # Check for admin commands with arguments (e.g., /grant 123456789)
            if is_admin:
                admin_arg_commands = ["/grant", "/revoke", "/resetlimit", "/ban", "/unban", "/userinfo", "/userstats", "/broadcast"]
                for admin_cmd in admin_arg_commands:
                    if content_lower.startswith(admin_cmd + " ") or content_lower == admin_cmd:
                        await _handle_admin_with_args(wa_id, content.strip(), wa_user_id, contact_name)
                        return True

            # Check for prefix commands with arguments (e.g., /download URL, /study topic)
            prefix_commands = {
                "/download": "download",
                "/image": "image_gen",
                "/edit": "image_edit",
                "/youtube": "youtube",
                "/quiz": "quiz",
                "/exam": "exam",
                "/study": "study",
                "/search": "search",
                "/video": "video_search_query",
                "/audio": "audio_search_query",
                "/photo": "photo_search_query",
                "/cookies": "cookies",
                "/potoken": "potoken",
            }
            for prefix, cmd_name in prefix_commands.items():
                if content_lower.startswith(prefix + " "):
                    arg = content.strip()[len(prefix):].strip()
                    if arg:
                        await _handle_command_with_arg(wa_id, cmd_name, arg, wa_user_id, contact_name, message_id, is_admin)
                        return

            # Arabic prefix commands
            arabic_prefix_map = {
                "تحميل": "download",
                "صورة": "image_gen",
                "عدل صورة": "image_edit",
                "يوتيوب": "youtube",
                "كويز": "quiz",
                "امتحان": "exam",
                "دراسة": "study",
                "بحث": "search",
                "فيديو بالبحث": "video_search_query",
                "فيديو بحث": "video_search_query",
                "صوت بالبحث": "audio_search_query",
                "صوت بحث": "audio_search_query",
                "بحث صور": "photo_search_query",
            }
            for arabic_prefix, cmd_name in arabic_prefix_map.items():
                if content_lower.startswith(arabic_prefix):
                    arg = content.strip()[len(arabic_prefix):].strip()
                    if arg:
                        await _handle_command_with_arg(wa_id, cmd_name, arg, wa_user_id, contact_name, message_id, is_admin)
                        return

            # Check for simple command trigger
            command = _COMMAND_TRIGGERS.get(content_lower)
            if command:
                handled = await _handle_command(wa_id, command, wa_user_id, contact_name, message_id)
                if handled:
                    return

            # ═══ Time Change Detection (HH:MM pattern) ═══
            # لو المستخدم كتب وقت بصيغة HH:MM (زي 14:30 أو 09:00)
            # ده معناه إنه عايز يغير وقت الأخبار اليومية
            import re as _time_re
            _time_match = _time_re.match(r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$', content.strip())
            if _time_match:
                hour_str = _time_match.group(1).zfill(2)
                minute_str = _time_match.group(2).zfill(2)
                new_time = f"{hour_str}:{minute_str}"
                
                try:
                    from memory import set_news_time
                    set_news_time(wa_user_id, new_time)
                    await _send_whatsapp_message(wa_id,
                        f"✅ تم تغيير وقت الأخبار!\n\n"
                        f"⏰ الوقت الجديد: {new_time} (توقيت القاهرة)\n"
                        f"📬 هابعتلك الأخبار كل يوم في الوقت ده.\n\n"
                        f"💡 ممكن تغيره تاني من الإعدادات"
                    )
                except Exception:
                    await _send_whatsapp_message(wa_id, f"✅ تم تغيير وقت الأخبار إلى {new_time}")
                return

            # ═══ PDF Follow-up Q&A ═══
            # If user has a PDF context and asks a question, answer based on the PDF
            # 🔴 FIX: Only treat as PDF question if the message clearly relates to the file
            # (starts with question word, or mentions "الملف"/"الوثيقة")
            if not command:  # Not a recognized command
                pdf_ctx = _wa_user_pdf_context.get(wa_user_id, {})
                if not pdf_ctx:
                    # Try loading from DB
                    try:
                        from memory import get_memories
                        mems = get_memories(wa_user_id)
                        pdf_text = mems.get("pdf_context_text", "")
                        pdf_fn = mems.get("pdf_context_filename", "")
                        if pdf_text:
                            pdf_ctx = {"text": pdf_text, "filename": pdf_fn}
                            _wa_user_pdf_context[wa_user_id] = pdf_ctx
                    except Exception:
                        pass
                
                if pdf_ctx and len(content.strip()) > 3:
                    # 🔴 FIX: Smarter detection — only treat as PDF question if:
                    # 1. Message contains question indicators AND mentions the file
                    # 2. OR message explicitly references "الملف"/"الوثيقة"/"الملف ده"
                    # This prevents normal conversation from being treated as PDF questions
                    question_indicators = ["ايه", "إيه", "ازاي", "إزاي", "ليه", "ليه", "هل", "كام", "فين", "مين", "ان", "أن", "what", "how", "why", "when", "where", "who", "is", "are", "can", "?", "؟"]
                    file_indicators = ["الملف", "الوثيقة", "المستند", "الpdf", "الـ pdf", "الملف ده", "في الملف", "من الملف", "the file", "the document", "this file"]
                    
                    is_question = any(content.strip().lower().startswith(q) for q in question_indicators) or "؟" in content or "?" in content
                    mentions_file = any(ind in content.lower() for ind in file_indicators)
                    
                    # Only route to PDF Q&A if question + mentions file, OR explicitly about the file
                    if mentions_file or (is_question and len(content.strip()) < 100):
                        from ai_engine import smart_chat
                        from formatters import clean_ai_response
                        
                        # Start thinking feedback for PDF Q&A (uses document threshold)
                        feedback = ThinkingFeedback(wa_id, message_id, context_type="document")
                        await feedback.start()
                        
                        pdf_question_prompt = f"""بناءً على المستند ده ({pdf_ctx.get('filename', 'PDF')}), جاوب على السؤال:

المحتوى:
{pdf_ctx['text'][:15000]}

السؤال: {content}"""
                        
                        # 🔴 لو المستخدم هو الأدمن، نمرر username=ziadamr
                        _pdf_is_admin = _is_wa_admin(wa_id)
                        ai_response = await smart_chat(
                            user_message=pdf_question_prompt,
                            language="ar",
                            user_id=wa_user_id,
                            username="ziadamr" if _pdf_is_admin else (contact_name if contact_name != "Unknown" else None),
                        )
                        ai_response = clean_ai_response(ai_response)
                        wa_response = _strip_html_for_whatsapp(ai_response)
                        chunks = _split_whatsapp_message(wa_response)
                        for chunk in chunks:
                            await _send_whatsapp_message(wa_id, chunk)
                        
                        await feedback.complete()
                        
                        await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية مع الملف؟",
                            buttons=[
                                {"id": "cmd_pdf_keypoints", "title": "🔑 نقاط رئيسية"},
                                {"id": "cmd_study", "title": "📚 ادرسه"},
                                {"id": "cmd_commands", "title": "📋 الأوامر"},
                            ])
                        return

        # ═══ Process Audio Messages ═══
        if is_audio and audio_media_id:
            try:
                # Start thinking feedback for voice
                feedback = ThinkingFeedback(wa_id, message_id, context_type="voice")
                await feedback.start()

                audio_content = await _transcribe_audio(audio_media_id, wa_user_id=wa_user_id)
                if audio_content:
                    content = audio_content
                    logger.info(f"🎤 Audio transcribed from {wa_id}: {content[:80]}")
                    await feedback.complete()
                else:
                    await _send_whatsapp_message(wa_id, "⚠️ مش قادر أفهم الصوت ده. جرب تبعت رسالة نصية! 🎤")
                    await feedback.error()
                    return
            except Exception as e:
                logger.error(f"❌ Audio transcription error: {e}")
                await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في تحويل الصوت لنص. جرب تاني! 🎤")
                await feedback.error()
                return

        # ═══ Process Image Messages ═══
        if is_image and image_media_id:
            try:
                # Start thinking feedback for image analysis
                feedback = ThinkingFeedback(wa_id, message_id, context_type="image")
                await feedback.start()

                # Check premium for image analysis
                if not is_admin:
                    try:
                        from premium import check_limit
                        limit_check = check_limit(wa_user_id, "image_analyses_per_day")
                        if not limit_check.get("allowed", True):
                            await _send_whatsapp_message(wa_id, "⚠️ وصلت حد تحليل الصور اليومي!\n⭐ ترقية لـ Premium عشان استخدام غير محدود!")
                            await feedback.error()
                            return
                    except Exception:
                        pass

                image_description = await _analyze_image(image_media_id, content, wa_user_id=wa_user_id)
                
                # Cache the image for later /edit (like Telegram caches photos)
                try:
                    cached_img_b64 = await _download_wa_media_base64(image_media_id)
                    if cached_img_b64:
                        _wa_user_edit_images[wa_user_id] = {
                            "image_base64": cached_img_b64,
                            "created_at": time.time(),
                        }
                        # Clean old entries (older than 1 hour)
                        expired_users = [uid for uid, data in _wa_user_edit_images.items() 
                                        if time.time() - data.get("created_at", 0) > 3600]
                        for uid in expired_users:
                            del _wa_user_edit_images[uid]
                except Exception as e:
                    logger.debug(f"Could not cache image for editing: {e}")
                
                if image_description:
                    response_text = _strip_html_for_whatsapp(image_description)
                    chunks = _split_whatsapp_message(response_text)
                    for chunk in chunks:
                        await _send_whatsapp_message(wa_id, chunk)

                    # Increment usage
                    if not is_admin:
                        try:
                            from premium import increment_usage
                            increment_usage(wa_user_id, "image_analyses")
                        except Exception:
                            pass

                    # Detect interests from image (same as Telegram)
                    try:
                        from memory import detect_interests
                        detect_interests(wa_user_id, f"[صورة] {image_description[:200]}", "ar")
                    except Exception:
                        pass

                    await feedback.complete()

                    # Quick action buttons
                    await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                        buttons=[
                            {"id": "cmd_chat", "title": "💬 اسأل عنها"},
                            {"id": "cmd_image_edit", "title": "🖌️ عدّلها"},
                            {"id": "cmd_commands", "title": "📋 الأوامر"},
                        ])
                    
                    # 🔴 حفظ حالة المستخدم — لو كتب وصف تعديل يروح للخدمة مش AI
                    _set_user_state(wa_id, "image_edit", {"step": "awaiting_edit_prompt"})
                else:
                    await _send_whatsapp_message(wa_id, "⚠️ مش قادر أحلل الصورة دي. جرب صورة تانية! 👁️")
                    await feedback.error()
                return
            except Exception as e:
                logger.error(f"❌ Image analysis error: {e}")
                await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في تحليل الصورة. جرب تاني! 👁️")
                try:
                    await feedback.error()
                except Exception:
                    pass
                return

        # ═══ Process Document — Cookies file check first ═══
        # 🍪 لو الملف اسمه cookies أو الرسالة فيها كلمة cookies → نوجهه لـ cookies handler
        if is_document and document_media_id:
            is_cookies_doc = False
            content_lower = (content or "").lower()
            # فحص الـ caption/الرسالة
            if 'cookie' in content_lower or 'كوكيز' in content_lower:
                is_cookies_doc = True

            if is_cookies_doc:
                try:
                    # تحميل الملف من WhatsApp
                    import aiohttp
                    cookie_file_content = ""
                    async with aiohttp.ClientSession() as session:
                        media_url_resp = await session.get(
                            f"https://graph.facebook.com/v21.0/{document_media_id}",
                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                        )
                        if media_url_resp.status == 200:
                            media_data = await media_url_resp.json()
                            download_url = media_data.get("url", "")
                            if download_url:
                                doc_resp = await session.get(
                                    download_url,
                                    headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                )
                                if doc_resp.status == 200:
                                    doc_bytes = await doc_resp.read()
                                    cookie_file_content = doc_bytes.decode('utf-8', errors='ignore')

                    if cookie_file_content:
                        # 🔴 فحص المحتوى — نتأكد إنه ملف كوكيز حقيقي
                        has_netscape_header = '# Netscape HTTP Cookie File' in cookie_file_content
                        has_youtube = '.youtube.com' in cookie_file_content or 'youtube.com' in cookie_file_content

                        is_valid = False
                        if has_netscape_header or has_youtube:
                            cookie_lines = [l for l in cookie_file_content.splitlines() if l.strip() and not l.strip().startswith('#')]
                            valid_lines = [l for l in cookie_lines if len(l.split('\t')) >= 7]
                            if valid_lines:
                                is_valid = True

                        if is_valid:
                            # 🔴 دمج الكوكيز مع الملف الموجود
                            cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
                            existing_content = ""
                            if os.path.exists(cookies_path):
                                try:
                                    with open(cookies_path, 'r', encoding='utf-8') as f:
                                        existing_content = f.read()
                                except Exception:
                                    existing_content = ""

                            if existing_content.strip():
                                # في ملف موجود — ندمج
                                from handlers.download_handlers import _merge_cookies
                                merged_content, new_added, new_yt_added = _merge_cookies(existing_content, cookie_file_content)
                                with open(cookies_path, 'w', encoding='utf-8') as f:
                                    f.write(merged_content)
                                logger.info(f"🍪 WA Cookies merged from user {wa_id}: {new_added} new cookies ({new_yt_added} YouTube)")
                            else:
                                # مفيش ملف موجود — نكتب مباشرة
                                with open(cookies_path, 'w', encoding='utf-8') as f:
                                    f.write(cookie_file_content)
                                new_added = 0
                                new_yt_added = 0
                                logger.info(f"🍪 WA Cookies file created by user {wa_id}")

                            # التحقق
                            total_yt = 0
                            total_all = 0
                            try:
                                with open(cookies_path, 'r') as f:
                                    all_lines = f.readlines()
                                total_all = len([l for l in all_lines if l.strip() and not l.strip().startswith('#')])
                                total_yt = len([l for l in all_lines if 'youtube.com' in l.lower() and l.strip() and not l.strip().startswith('#')])
                            except Exception:
                                pass

                            # ✅ للمستخدم العادي — رسالة بسيطة
                            if not is_admin:
                                await _send_whatsapp_message(wa_id, "✅ تم رفع ملف الكوكيز بنجاح! شكراً لمساعدتنا 🎬")
                            else:
                                # 🔴 للأدمن — تفاصيل كاملة
                                if new_added > 0:
                                    await _send_whatsapp_message(wa_id,
                                        f"✅ *تم دمج الكوكيز بنجاح!*\n\n"
                                        f"🆕 كوكيز جديدة: {new_added} ({new_yt_added} YouTube)\n"
                                        f"📊 إجمالي الكوكيز: {total_all}\n"
                                        f"▶️ كوكيز YouTube: {total_yt}\n\n"
                                        f"🎬 التحميل هيشتغل بشكل أفضل!")
                                else:
                                    await _send_whatsapp_message(wa_id,
                                        f"✅ *تم رفع ملف الكوكيز بنجاح!*\n\n"
                                        f"▶️ كوكيز YouTube: {total_yt}\n\n"
                                        f"🎬 التحميل هيشتغل بشكل أفضل!")
                        else:
                            await _send_whatsapp_message(wa_id, "❌ الملف ده مش ملف كوكيز صحيح. لازم يكون Netscape HTTP Cookie File وفيه كوكيز YouTube.")
                    else:
                        await _send_whatsapp_message(wa_id, "❌ مش قادر أحمل الملف. جرب تاني!")
                except Exception as e:
                    logger.error(f"🍪 WA Cookies document handling error: {e}")
                    await _send_whatsapp_message(wa_id, f"❌ حصل خطأ في رفع الكوكيز: {e}")
                return  # 🍪 مهم — منع الملف يروح لـ PDF analysis

        # ═══ Process Document (PDF) ═══
        if is_document and document_media_id:
            try:
                # Start thinking feedback for document analysis (10s threshold)
                feedback = ThinkingFeedback(wa_id, message_id, context_type="document")
                await feedback.start()

                # Check premium for PDF
                if not is_admin:
                    try:
                        from premium import check_limit
                        limit_check = check_limit(wa_user_id, "pdf_analyses_per_day")
                        if not limit_check.get("allowed", True):
                            await _send_whatsapp_message(wa_id, "⚠️ وصلت حد تحليل PDF اليومي!\n⭐ ترقية لـ Premium!")
                            await feedback.error()
                            return
                    except Exception:
                        pass

                pdf_result = await _analyze_document(document_media_id, content, wa_user_id=wa_user_id, filename=document_filename, mime_type=document_mime_type)
                if pdf_result:
                    response_text = _strip_html_for_whatsapp(pdf_result)
                    chunks = _split_whatsapp_message(response_text)
                    for chunk in chunks:
                        await _send_whatsapp_message(wa_id, chunk)

                    # Increment usage
                    if not is_admin:
                        try:
                            from premium import increment_usage
                            increment_usage(wa_user_id, "pdf_analyses")
                        except Exception:
                            pass

                    # Detect interests from document (same as Telegram)
                    try:
                        from memory import detect_interests, save_conversation
                        # 🔴 FIX: Use actual file type instead of always "PDF"
                        file_label = f"[{document_filename or 'ملف'}: {content[:80]}]" if document_filename else f"[PDF: {content[:80]}]"
                        detect_interests(wa_user_id, file_label, "ar")
                        save_conversation(wa_user_id, "user", file_label[:100], platform="whatsapp")
                    except Exception:
                        pass

                    await feedback.complete()

                    # PDF interactive buttons (same as Telegram)
                    pdf_filename = ""
                    pdf_ctx = _wa_user_pdf_context.get(wa_user_id, {})
                    if pdf_ctx:
                        pdf_filename = pdf_ctx.get("filename", "")
                    
                    pdf_body = "عايز حاجة تانية مع الملف ده؟"
                    if pdf_filename:
                        pdf_body = f"📄 {pdf_filename}\n\nعايز حاجة تانية؟"
                    
                    await _send_interactive_buttons(wa_id, body_text=pdf_body,
                        buttons=[
                            {"id": "cmd_pdf_keypoints", "title": "🔑 نقاط رئيسية"},
                            {"id": "cmd_study", "title": "📚 ادرسه"},
                            {"id": "cmd_chat", "title": "💬 اسأل عنه"},
                        ])
                else:
                    await _send_whatsapp_message(wa_id, "⚠️ مش قادر أحلل الملف ده. جرب تاني! 📄")
                    await feedback.error()
                return
            except Exception as e:
                logger.error(f"❌ Document analysis error: {e}")
                await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في تحليل الملف. جرب تاني! 📄")
                try:
                    await feedback.error()
                except Exception:
                    pass
                return

        # ═══ Skip empty content ═══
        if not content.strip() or content.startswith("["):
            if not content.strip() or content in ("[Video]", "[Document]"):
                await _handle_command(wa_id, "start", wa_user_id, contact_name)
            return

        # ═══ Auto-detect URLs for download (like Telegram auto-download) ═══
        if message_type == "text":
            url = _extract_url(content.strip())
            if url:
                platform = _detect_platform(url)
                if platform != "unknown":
                    # 🔴 فحص Premium — التحميل من المنصات مميز بريميوم بس
                    if not is_admin:
                        try:
                            from premium import get_user_plan
                            plan = get_user_plan(wa_user_id)
                            if plan not in ("premium", "premium_plus"):
                                await _send_whatsapp_message(wa_id,
                                    f"📥 تحميل الفيديوهات مميز Premium بس!\n\n"
                                    f"⭐ مع Premium تقدر:\n"
                                    f"• تحميل من أي منصة 📥\n"
                                    f"  (YouTube, Insta, TikTok, FB, Twitter...)\n"
                                    f"• فيديو بالبحث 🎬\n"
                                    f"• صوت بالبحث 🎵\n\n"
                                    f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                                return
                        except Exception:
                            pass
                    
                    # 🛡️ Safety: Check URL/query before proceeding with download
                    try:
                        is_safe, reason = await check_query_safety(url, platform="whatsapp", user_id=str(wa_user_id))
                        if not is_safe:
                            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
                            return
                    except Exception as e:
                        logger.warning(f"🛡️ URL safety check failed (allowing): {e}")
                    
                    # User sent a video/social media URL — show quality selection!
                    logger.info(f"🔗 Auto-detected {platform} URL from {wa_id}: {url[:80]}")
                    await _show_quality_selection(wa_id, url, wa_user_id, contact_name, message_id, is_admin)
                    return

        # ═══ Route to AI Engine with Thinking Feedback ═══
        # Rate limit check for AI chat actions
        from rate_limiter import rate_limiter
        if rate_limiter.is_rate_limited(wa_user_id, "ai_chat"):
            await _send_whatsapp_message(wa_id, "⚠️ أنت بتبعت رسائل كتير أوي، استنى شوية وجرّب تاني")
            return

        logger.info(f"🤖 Routing WA message to AI: {content[:80]}")

        await _send_ai_response(wa_id, content, wa_user_id, contact_name, message_id, context_type="general")

    except Exception as e:
        logger.error(f"❌ Error handling WA message: {e}", exc_info=True)
        _log_activity("message_handler_error", {"error": str(e)[:200]}, "error")
        # 🐦 Sentry — capture message handler errors
        from sentry_config import capture_exception, set_context
        set_context("whatsapp_message", {"wa_id": wa_id if 'wa_id' in dir() else "unknown"})
        capture_exception(e)
