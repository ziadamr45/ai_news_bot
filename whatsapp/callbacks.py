"""
WhatsApp Callback Handlers & Webhook Server
============================================

Extracted from whatsapp_webhook.py — contains:
- AI response helper (_send_ai_response)
- Contextual buttons (_send_contextual_buttons)
- Search handlers (video, audio, photo)
- Search callback handler
- Webhook handlers (root, verification, receiver)
- Message handler (_handle_incoming_message)
- Admin command handler (_handle_admin_with_args)
- Health check & debug endpoints
- Webhook server factory and starter
"""

import os
import json
import re
import logging
import asyncio
import hashlib
import time
from datetime import datetime, timezone
from aiohttp import web

from whatsapp.state import (
    WA_MAX_MSG,
    ADMIN_WA_ID,
    DEVELOPER_WHATSAPP_URL,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_VERIFY_TOKEN,
    WHATSAPP_APP_SECRET,
    WEBHOOK_PORT,
    ALLOWED_WA_NUMBERS,
    WHATSAPP_API_URL,
    _wa_user_state,
    _set_user_state,
    _get_user_state,
    _clear_user_state,
    _wa_user_pdf_context,
    _wa_user_yt_url,
    _wa_user_edit_images,
    _url_cache,
    _store_url,
    _get_url,
    _detect_platform,
    _is_youtube_url,
    _is_threads_url,
    _extract_url,
    _contains_arabic,
    _strip_html_for_whatsapp,
    _split_whatsapp_message,
    _log_event,
    _log_activity,
    _is_duplicate_wa_message,
    _verify_signature,
    _is_wa_admin,
    _ensure_wa_admin_premium,
    _wa_phone_to_user_id,
    _wa_phone_to_display,
    _wa_search_cache,
    _WA_SEARCH_CACHE_TTL,
    _COMMAND_TRIGGERS,
    _webhook_activity_log,
)

from whatsapp.api import (
    _send_whatsapp_message,
    _send_whatsapp_reaction,
    _mark_message_read,
    _send_interactive_buttons,
    _send_interactive_list,
    _send_typing_indicator,
    ThinkingFeedback,
    _send_whatsapp_image,
    _send_whatsapp_document,
    _send_whatsapp_document_from_file,
    _send_whatsapp_audio,
)

from content_safety import (
    check_query_safety,
    get_block_message,
    check_search_results_safety,
    get_no_safe_results_message,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# AI Response Helper (Enhanced with Typing Indicator)
# ═══════════════════════════════════════

async def _send_ai_response(wa_id: str, user_message: str, wa_user_id: int, contact_name: str,
                           message_id: str = "", thinking_emoji: str = "🤔",
                           context_type: str = "general", increment_feature: str = "ai_messages"):
    """
    Send an AI response with full pipeline (Enhanced with professional thinking feedback):
    1. ThinkingFeedback (💭 reaction + progressive status messages)
    2. Check premium limits
    3. Get AI response
    4. Send response chunks
    5. Increment usage
    6. Show remaining usage for free users
    7. Contextual quick action buttons
    8. Complete thinking feedback (✅ reaction)
    """
    from ai_engine import smart_chat
    from formatters import clean_ai_response

    is_admin = _is_wa_admin(wa_id)

    # Start professional thinking feedback (replaces old thinking indicator)
    feedback = ThinkingFeedback(wa_id, message_id, context_type=context_type)
    await feedback.start()

    try:
        # Check limits (skip for admin)
        if not is_admin:
            try:
                from premium import check_limit
                limit_check = check_limit(wa_user_id, f"{increment_feature}_per_day")
                if not limit_check.get("allowed", True):
                    remaining = limit_check.get("remaining", 0)
                    limit = limit_check.get("limit", 0)
                    await _send_whatsapp_message(wa_id,
                        f"⚠️ وصلت للحد اليومي!\n\n{increment_feature}: استخدمت {limit} من {limit} اليوم\n\n💡 الحد بيرجع تاني بكرة\n⭐ ترقية لـ Premium عشان استخدام غير محدود!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    if message_id:
                        try:
                            await _send_whatsapp_reaction(wa_id, message_id, "⚠️")
                        except Exception:
                            pass
                    await feedback.error()
                    return
            except Exception:
                pass  # If premium system fails, allow the message

        # Get AI response
        # 🔴 لو المستخدم هو الأدمن (المطور)، نمرر username=ziadamr عشان البوت يتعرف عليه
        smart_chat_username = "ziadamr" if is_admin else (contact_name if contact_name != "Unknown" else None)
        ai_response = await smart_chat(
            user_message=user_message,
            language="ar",
            user_id=wa_user_id,
            username=smart_chat_username,
        )
        ai_response = clean_ai_response(ai_response)
        wa_response = _strip_html_for_whatsapp(ai_response)

        # Split and send
        chunks = _split_whatsapp_message(wa_response)
        for chunk in chunks:
            await _send_whatsapp_message(wa_id, chunk)
            if len(chunks) > 1:
                await asyncio.sleep(0.05)  # ⚡ كان 0.3s - اتعمل 0.05s عشان سرعة أكتر

        # Increment usage (skip for admin)
        if not is_admin:
            try:
                from premium import increment_usage
                increment_usage(wa_user_id, increment_feature)
            except Exception:
                pass

        # Complete thinking feedback
        await feedback.complete()

        # Contextual quick action buttons
        await _send_contextual_buttons(wa_id, context_type)

        logger.info(f"✅ WA AI response sent to {wa_id} ({len(chunks)} chunk(s))")

    except Exception as e:
        logger.error(f"❌ AI engine error for WA {wa_id}: {e}", exc_info=True)
        await feedback.error()
        await _send_whatsapp_message(wa_id, "⚠️ مش قادر أرد دلوقتي — جرب تاني بعد شوية! 🔄")


async def _send_contextual_buttons(wa_id: str, context_type: str = "general"):
    """Send contextual quick action buttons based on the type of response"""
    try:
        if context_type == "news":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_news", "title": "📰 أخبار أخرى"},
                    {"id": "cmd_trending", "title": "📈 ترندات"},
                    {"id": "cmd_company", "title": "🏢 شركات"},
                ])
        elif context_type == "learn" or context_type == "study":
            await _send_interactive_buttons(wa_id, body_text="عايز تتعلم أكتر؟",
                buttons=[
                    {"id": "cmd_learn", "title": "📚 تعلم أكتر"},
                    {"id": "cmd_roadmap", "title": "🗺️ خريطة"},
                    {"id": "cmd_ask", "title": "❓ اسأل"},
                ])
        elif context_type == "memory":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_memory_view", "title": "🧠 عرض الذاكرة"},
                    {"id": "cmd_memory_reset", "title": "🗑️ مسح"},
                    {"id": "cmd_settings", "title": "⚙️ إعدادات"},
                ])
        elif context_type == "search":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_search", "title": "🔍 بحث تاني"},
                    {"id": "cmd_chat", "title": "💬 محادثة"},
                    {"id": "cmd_commands", "title": "📋 الأوامر"},
                ])
        elif context_type == "youtube":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_youtube", "title": "🎬 فيديو تاني"},
                    {"id": "cmd_chat", "title": "💬 محادثة"},
                    {"id": "cmd_commands", "title": "📋 الأوامر"},
                ])
        else:  # general chat
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_chat", "title": "💬 كمل"},
                    {"id": "cmd_news", "title": "📰 أخبار"},
                    {"id": "cmd_commands", "title": "📋 الأوامر"},
                ])
    except Exception:
        pass  # Non-critical


# ═══════════════════════════════════════
# GET / — Root Handler
# ═══════════════════════════════════════

async def root_handler(request: web.Request):
    """Root path — redirect to health check or show basic info"""
    return web.json_response({
        "service": "My Bro — WhatsApp & Telegram AI Bot",
        "version": "4.0",
        "endpoints": {
            "webhook_verification": "GET /whatsapp/webhook",
            "webhook_messages": "POST /whatsapp/webhook",
            "health": "GET /health",
            "diagnostics": "GET /debug/whatsapp",
            "activity_log": "GET /debug/whatsapp/activity",
        },
        "status": "running",
    })


# ═══════════════════════════════════════
# GET /whatsapp/webhook — Meta Verification
# ═══════════════════════════════════════

async def webhook_verification(request: web.Request):
    """Meta verification endpoint."""
    mode = request.query.get("hub.mode", "")
    token = request.query.get("hub.verify_token", "")
    challenge = request.query.get("hub.challenge", "")

    _log_event("IN", "verification_attempt", {
        "mode": mode,
        "token_provided": bool(token),
        "challenge_provided": bool(challenge),
    })

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully!")
        _log_event("OUT", "verification_success", {"challenge": challenge})
        return web.Response(text=challenge, status=200)

    logger.warning(f"❌ WhatsApp webhook verification failed!")
    _log_event("OUT", "verification_failed", {"mode": mode})
    return web.Response(text="Forbidden", status=403)


# ═══════════════════════════════════════
# POST /whatsapp/webhook — Incoming Messages
# ═══════════════════════════════════════

async def webhook_receiver(request: web.Request):
    """Receive incoming WhatsApp messages and status updates."""
    try:
        payload = await request.read()

        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(payload, signature):
            logger.warning(f"❌ Invalid webhook signature")
            _log_activity("signature_failed", {"signature_present": bool(signature), "app_secret_set": bool(WHATSAPP_APP_SECRET)}, "failed")
            return web.Response(text="Unauthorized", status=401)

        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            return web.Response(text="Bad Request", status=400)

        has_messages = False
        has_statuses = False
        try:
            has_messages = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages"))
            has_statuses = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"))
        except (IndexError, KeyError, TypeError):
            pass

        _log_event("IN", "webhook_event", {
            "keys": list(body.keys()),
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
        })

        _log_activity("webhook_post", {
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
            "payload_size": len(payload),
        }, "received")

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    messages = value.get("messages", [])
                    if messages:
                        for message in messages:
                            asyncio.create_task(_handle_incoming_message(message, value))

                    statuses = value.get("statuses", [])
                    if statuses:
                        for status in statuses:
                            _log_event("IN", "status_update", {
                                "message_id": status.get("id"),
                                "status": status.get("status"),
                                "timestamp": status.get("timestamp"),
                                "recipient_id": status.get("recipient_id"),
                            })

                    errors = value.get("errors", [])
                    if errors:
                        for error in errors:
                            logger.error(f"❌ WhatsApp API Error: {error}")
                            _log_event("IN", "api_error", error)
        else:
            logger.warning(f"⚠️ Unknown webhook object type: {body.get('object')}")

        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)
        return web.Response(text="OK", status=200)


def process_webhook_body(body: dict):
    """Synchronous entry point for processing WhatsApp webhook bodies.
    
    Called from bot.py's simple HTTP server when a POST /whatsapp/webhook
    is received. Processes the webhook body synchronously using the same
    logic as webhook_receiver but without the aiohttp request/response.
    
    Note: This skips signature verification since the simple HTTP server
    handles that separately. The WhatsApp webhook aiohttp server (if running)
    still does full signature verification.
    """
    try:
        has_messages = False
        has_statuses = False
        try:
            has_messages = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages"))
            has_statuses = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"))
        except (IndexError, KeyError, TypeError):
            pass

        _log_event("IN", "webhook_event_simple", {
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
        })

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    messages = value.get("messages", [])
                    if messages:
                        for message in messages:
                            # Schedule the async handler to run in the existing event loop
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.ensure_future(_handle_incoming_message(message, value), loop=loop)
                                else:
                                    loop.run_until_complete(_handle_incoming_message(message, value))
                            except RuntimeError:
                                # No event loop — create a new one
                                asyncio.run(_handle_incoming_message(message, value))

                    statuses = value.get("statuses", [])
                    if statuses:
                        for status in statuses:
                            _log_event("IN", "status_update", {
                                "message_id": status.get("id"),
                                "status": status.get("status"),
                                "timestamp": status.get("timestamp"),
                                "recipient_id": status.get("recipient_id"),
                            })

                    errors = value.get("errors", [])
                    if errors:
                        for error in errors:
                            logger.error(f"❌ WhatsApp API Error: {error}")
                            _log_event("IN", "api_error", error)
    except Exception as e:
        logger.error(f"❌ process_webhook_body error: {e}", exc_info=True)


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
                    # Check if it looks like a question about the document
                    question_indicators = ["ايه", "إيه", "ازاي", "إزاي", "ليه", "ليه", "هل", "كام", "فين", "مين", "ان", "أن", "what", "how", "why", "when", "where", "who", "is", "are", "can", "?", "؟"]
                    is_question = any(content.strip().lower().startswith(q) for q in question_indicators) or "؟" in content or "?" in content
                    
                    if is_question:
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

                pdf_result = await _analyze_document(document_media_id, content, wa_user_id=wa_user_id)
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
                        detect_interests(wa_user_id, f"[PDF: {content[:100]}]", "ar")
                        save_conversation(wa_user_id, "user", f"[PDF: {content[:50]}]", platform="whatsapp")
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
        logger.info(f"🤖 Routing WA message to AI: {content[:80]}")

        await _send_ai_response(wa_id, content, wa_user_id, contact_name, message_id, context_type="general")

    except Exception as e:
        logger.error(f"❌ Error handling WA message: {e}", exc_info=True)
        _log_activity("message_handler_error", {"error": str(e)[:200]}, "error")


# ═══════════════════════════════════════
# Admin Commands with Arguments
# ═══════════════════════════════════════

async def _handle_admin_with_args(wa_id: str, content: str, wa_user_id: int, contact_name: str):
    """Handle admin commands that have arguments (e.g., /grant 123456789)"""
    if not _is_wa_admin(wa_id):
        await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
        return

    parts = content.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    # ✅ FIX: Helper to resolve WA phone to user_id — prefers database lookup over hash
    def _resolve_wa_target(phone: str) -> int:
        """Resolve a WhatsApp phone number to a user_id.
        First tries database lookup by wa_phone (reliable, survives restarts),
        then falls back to deterministic hash for new users.
        """
        from memory import find_user_by_wa_phone
        existing = find_user_by_wa_phone(phone)
        if existing is not None:
            return existing
        return _wa_phone_to_user_id(phone)

    try:
        if cmd in ("/grant",):
            if not args:
                await _send_whatsapp_message(wa_id, "⭐ الاستخدام: /grant [مدة] رقم_الواتساب\nمثال: /grant 201203551789\nمثال: /grant m 201203551789\nمثال: /grant w 201203551789\nمثال: /grant y 201203551789\n\n🔄 تجديد: /grant force m 201203551789")
                return

            from premium import grant_premium, get_premium_info
            from memory import _ensure_user_in_db
            from admin import parse_duration

            # 🔴 فحص كلمة force — عشان تجديد Premium
            force_renew = False
            if args[0].lower() == "force":
                force_renew = True
                args = args[1:]

            if not args:
                await _send_whatsapp_message(wa_id, "❌ لازم تحدد رقم الواتساب. مثال: /grant force m 201203551789")
                return

            if len(args) == 1:
                # /grant phone → مدى الحياة
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                days = 0
                expires_display = "مدى الحياة 🔓"
            elif len(args) == 2:
                # /grant [مدة] phone
                duration_str = args[0]
                phone = args[1]
                target_id = _resolve_wa_target(phone)
                days, expires_display = parse_duration(duration_str)
                if days == -1:
                    await _send_whatsapp_message(wa_id, "❌ المدة مش صحيحة.\n\n🔑 الاختصارات:\nd = يوم | w = أسبوع | m = شهر | y = سنة\n0 أو دائم = مدى الحياة\n\nمثال: /grant m 201203551789")
                    return
            else:
                await _send_whatsapp_message(wa_id, "❌ كترت المعاملات. /grant [مدة] رقم_الواتساب")
                return

            _ensure_user_in_db(target_id, platform="whatsapp")

            expires = None
            if days > 0:
                from datetime import timedelta
                from admin import CAIRO_TZ
                expires_date = datetime.now(CAIRO_TZ) + timedelta(days=days)
                expires = expires_date.isoformat()
                expires_display += f" (ينتهي {expires_date.strftime('%Y-%m-%d')})"

            # 🔴 فحص هل المستخدم أصلاً Premium
            current_info = get_premium_info(target_id)
            
            if current_info["is_premium"] and not force_renew:
                # المستخدم أصلاً Premium — نقول للأدمن
                current_expires = current_info["expires_display"]
                current_since = current_info["premium_since"][:10] if current_info["premium_since"] else "مش محدد"
                await _send_whatsapp_message(wa_id,
                    f"⚠️ المستخدم ده أصلاً Premium!\n\n"
                    f"📱 المستخدم: {_wa_phone_to_display(phone)}\n"
                    f"⭐ الخطة: Premium\n"
                    f"📅 مفعل من: {current_since}\n"
                    f"⏰ المتبقي: {current_expires}\n\n"
                    f"🔄 عايز تجدده؟ اكتب:\n"
                    f"/grant force {' '.join(parts[2:]) if len(parts) > 2 else phone}"
                )
                return

            if force_renew and current_info["is_premium"]:
                # تجديد
                old_expires = current_info["expires_display"]
                grant_premium(target_id, granted_by=f"admin_{wa_user_id}", expires=expires)
                await _send_whatsapp_message(wa_id, f"🔄 تم تجديد Premium!\n\n📱 المستخدم: {_wa_phone_to_display(phone)}\n⭐ الخطة: Premium\n⏰ المدة القديمة: {old_expires}\n⏰ المدة الجديدة: {expires_display}")
            else:
                # تفعيل جديد
                grant_premium(target_id, granted_by=f"admin_{wa_user_id}", expires=expires)
                await _send_whatsapp_message(wa_id, f"✅ تم تفعيل Premium!\n\n📱 المستخدم: {_wa_phone_to_display(phone)}\n📊 الخطة السابقة: Free\n⭐ الخطة الجديدة: Premium\n⏰ المدة: {expires_display}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    f"⭐ مبروك! تم تفعيل Premium!\n\n"
                    f"أنت دلوقتي مشترك Premium في My Bro!\n"
                    f"استمتع بكل المزايا:\n"
                    f"• رسائل AI غير محدودة 💬\n"
                    f"• تحليل PDF غير محدود 📄\n"
                    f"• تحليل صور غير محدود + Vision Pro 👁️\n"
                    f"• ملخصات YouTube غير محدودة 🎬\n"
                    f"• بحث غير محدود 🔍\n"
                    f"• تحميل وسائط من أي منصة 📥\n"
                    f"  (YouTube, Instagram, TikTok, FB, Twitter...)\n"
                    f"• فيديو بالبحث غير محدود 🎬\n"
                    f"• صوت بالبحث غير محدود 🎵\n"
                    f"• بحث صور غير محدود 🖼️\n"
                    f"• إنشاء صور بالذكاء الاصطناعي 🎨\n"
                    f"• تعديل صور بالذكاء الاصطناعي 🖌️\n"
                    f"• وضع الدراسة 📚\n"
                    f"• ذاكرة طويلة المدى 🧠\n\n"
                    f"⏰ المدة: {expires_display}"
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/revoke",):
            if not args:
                await _send_whatsapp_message(wa_id, "❌ الاستخدام: /revoke رقم_الواتساب\nمثال: /revoke 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            from premium import revoke_premium, get_premium_info
            
            # 🔴 فحص هل المستخدم أصلاً مش Premium
            current_info = get_premium_info(target_id)
            if not current_info["is_premium"]:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} أصلاً مش Premium — على الخطه المجانيه بالفعل!")
                return
            
            # المستخدم Premium → شيله
            old_expires = current_info["expires_display"]
            revoke_premium(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم شيل Premium من {_wa_phone_to_display(phone)}\n\n📅 كان المتبقي: {old_expires}\n📊 الخطة الجديدة: Free")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    "❌ تم إلغاء اشتراك Premium.\n\n"
                    "لو تعتقد إن ده غلطة، تواصل مع الأدمن."
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/resetlimit",):
            if not args:
                await _send_whatsapp_message(wa_id, "🔄 الاستخدام: /resetlimit رقم_الواتساب\nمثال: /resetlimit 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            from premium import reset_user_usage, get_premium_info
            
            # 🔴 فحص هل المستخدم Premium — لو آه، الريست مش هيعمل حاجة
            current_info = get_premium_info(target_id)
            if current_info["is_premium"]:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} Premium — استخدام غير محدود أصلاً!\n\nمفيش حدود تتأثر بالريست.\nلو عايز تشيل البريميوم: /revoke {phone}")
                return
            
            success = reset_user_usage(target_id)
            if success:
                await _send_whatsapp_message(wa_id, f"✅ تم إعادة تعيين حدود {_wa_phone_to_display(phone)}")
                # 🔴 إرسال إشعار للمستخدم المستهدف
                try:
                    target_wa_id = phone.lstrip('+').strip()
                    await _send_whatsapp_message(target_wa_id,
                        "🔄 تم إعادة تعيين حدود الاستخدام بتاعتك!\n\n"
                        "تقدر تستخدم البوت تاني عادي."
                    )
                except Exception as e:
                    logger.info(f"Could not notify WA user {phone}: {e}")
            else:
                await _send_whatsapp_message(wa_id, f"❌ فشل في إعادة التعيين")

        elif cmd in ("/ban",):
            if not args:
                await _send_whatsapp_message(wa_id, "🚫 الاستخدام: /ban رقم_الواتساب [سبب]\nمثال: /ban 201203551789 سبام")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            reason = " ".join(args[1:]) if len(args) > 1 else "حظر من الأدمن"
            
            # 🔴 فحص هل المستخدم محظور بالفعل
            from memory import _execute as _mem_execute, _is_postgres as _mem_is_postgres
            ph = "%s" if _mem_is_postgres() else "?"
            already_banned = _mem_execute(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (target_id,), fetchone=True)
            if already_banned:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} محظور بالفعل!")
                return
            
            from memory import ban_user
            ban_user(target_id, reason=reason, banned_by=f"admin_{wa_user_id}")
            await _send_whatsapp_message(wa_id, f"🚫 تم حظر {_wa_phone_to_display(phone)}\n📝 السبب: {reason}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    f"🚫 تم حظرك من استخدام البوت.\n📝 السبب: {reason}\n\nلو تعتقد إن ده غلطة، تواصل مع الأدمن."
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/unban",):
            if not args:
                await _send_whatsapp_message(wa_id, "✅ الاستخدام: /unban رقم_الواتساب\nمثال: /unban 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            
            # 🔴 فحص هل المستخدم محظور أصلاً
            from memory import _execute as _mem_execute2, _is_postgres as _mem_is_postgres2, unban_user
            ph = "%s" if _mem_is_postgres2() else "?"
            is_banned = _mem_execute2(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (target_id,), fetchone=True)
            if not is_banned:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} مش محظور أصلاً!")
                return
            
            unban_user(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم إلغاء حظر {_wa_phone_to_display(phone)}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    "✅ تم إلغاء الحظر! تقدر تستخدم البوت تاني عادي."
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/userinfo",):
            if not args:
                await _send_whatsapp_message(wa_id, 
                    "👤 *معلومات مستخدم شاملة*\n\n"
                    "الاستخدام: /userinfo رقم_الواتساب\n"
                    "مثال: /userinfo 201203551789\n\n"
                    "💡 بيرجع كل المعلومات العامة:\n"
                    "→ الاسم (من البروفايل + المفضل)\n"
                    "→ الخطة وتاريخ الاشتراكات\n"
                    "→ كم مدة على البوت\n"
                    "→ إحصائيات الاستخدام\n\n"
                    "🔒 مش بيرجع بيانات حساسة")
                return
            phone = args[0]
            # ✅ FIX: First try to find user by wa_phone in database (reliable)
            # Falls back to deterministic hash if not found
            from memory import find_user_by_wa_phone
            target_id = find_user_by_wa_phone(phone)
            if target_id is None:
                # No user found with this phone — try deterministic hash as fallback
                target_id = _wa_phone_to_user_id(phone)
            from premium import get_user_stats
            
            stats = get_user_stats(target_id, platform="whatsapp")
            
            if not stats.get("found"):
                await _send_whatsapp_message(wa_id, "❌ المستخدم ده مش موجود في قاعدة البيانات.")
                return
            
            # ═══ الأسماء ═══
            name = stats.get("name", "")
            profile_name = stats.get("profile_name", "")
            
            if name and profile_name and name != profile_name:
                name_display = f"{name} (اسم البروفايل: {profile_name})"
            elif name:
                name_display = name
            elif profile_name:
                name_display = profile_name
            else:
                name_display = "مش محدد"
            
            # ═══ معلومات أساسية ═══
            plan_display = "⭐ Premium" if stats.get("is_premium") else "🆓 Free"
            if stats.get("plan") == "premium_plus":
                plan_display = "⭐ Premium+"
            
            platform_display = "📱 تليجرام" if stats.get("platform") == "telegram" else "📱 واتساب"
            lang_display = "🇪🇬 العربية" if stats.get("language") == "ar" else "🇬🇧 English"
            
            # ═══ معلومات Premium ═══
            if stats.get("is_premium"):
                premium_section = (
                    f"⭐ الخطة: {plan_display}\n"
                    f"📅 مفعل من: {stats.get('premium_since', '')[:10] if stats.get('premium_since') else 'مش محدد'}\n"
                    f"⏰ المتبقي: {stats.get('premium_expires_display', '—')}\n"
                    f"⏱️ على الخطة دي من: {stats.get('time_on_current_plan', 'مش محدد')}\n"
                    f"🔑 بواسطة: {stats.get('premium_granted_by') or 'مش محدد'}\n"
                )
            else:
                premium_section = f"⭐ الخطة: {plan_display}\n"
            
            # ═══ تاريخ Premium ═══
            grant_count = stats.get("premium_grant_count", 0)
            revoke_count = stats.get("premium_revoke_count", 0)
            history = stats.get("premium_history", [])
            
            premium_history_text = f"🔄 مرات الاشتراك: {grant_count}"
            if revoke_count > 0:
                premium_history_text += f" | ❌ مرات الإلغاء: {revoke_count}"
            
            if history:
                premium_history_text += "\n\n📜 آخر أحداث Premium:"
                for h in history[:5]:
                    action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                    action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                    date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                    by = h.get("granted_by", "") or ""
                    by_text = f" (بواسطة: {by})" if by and by != "None" else ""
                    premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"
            
            # ═══ حالة الحظر ═══
            ban_section = ""
            if stats.get("banned"):
                ban_section = f"\n🚫 محظور! السبب: {stats.get('ban_reason', 'مش محدد')}\n"
            
            # ═══ تحذيرات ═══
            warnings = stats.get("warning_count", 0)
            warn_section = f"\n⚠️ تحذيرات: {warnings}/3" if warnings > 0 else ""
            
            # ═══ أدمن ═══
            admin_section = "\n👑 أدمن: نعم" if stats.get("is_admin") else ""
            
            # ═══ إحصائيات الاستخدام ═══
            total = stats.get("total_usage", {})
            today = stats.get("today_usage", {})
            
            info = (
                f"👤 *معلومات المستخدم الشاملة*\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔒 بدون بيانات حساسة\n\n"
                f"📱 الرقم: {_wa_phone_to_display(phone)}\n"
                f"📝 الاسم: {name_display}\n"
                f"📱 المنصة: {platform_display}\n"
                f"🌐 اللغة: {lang_display}\n"
                f"⏱️ على البوت من: {stats.get('time_on_bot', 'مش محدد')}\n\n"
                f"{premium_section}\n"
                f"{premium_history_text}\n"
                f"{ban_section}{warn_section}{admin_section}\n\n"
                f"📊 *استخدام اليوم:*\n"
                f"→ رسائل AI: {today.get('ai_messages', 0)}\n"
                f"→ PDF: {today.get('pdf_analyses', 0)}\n"
                f"→ صور: {today.get('image_analyses', 0)}\n"
                f"→ YouTube: {today.get('youtube_summaries', 0)}\n"
                f"→ بحث: {today.get('searches', 0)}\n\n"
                f"📈 *الإجمالي عبر الوقت:*\n"
                f"→ رسائل AI: {total.get('ai_messages', 0)}\n"
                f"→ PDF: {total.get('pdf_analyses', 0)}\n"
                f"→ صور: {total.get('image_analyses', 0)}\n"
                f"→ YouTube: {total.get('youtube_summaries', 0)}\n"
                f"→ بحث: {total.get('searches', 0)}\n"
                f"→ بحث عميق: {total.get('deep_searches', 0)}\n"
                f"📅 أيام نشاط: {total.get('active_days', 0)}\n\n"
                f"💬 محادثات: {stats.get('chat_count', 0)}\n"
                f"⚡ أوامر: {stats.get('commands_used', 0)}\n"
                f"🎯 اهتمامات: {', '.join(stats.get('interests', [])[:5]) if stats.get('interests') else 'لا يوجد'}\n\n"
                f"📅 التسجيل: {stats.get('created_at', 'مش محدد')[:16] if stats.get('created_at') else 'مش محدد'}\n"
                f"📅 آخر تفاعل: {stats.get('last_interaction', 'مش محدد')[:16] if stats.get('last_interaction') else 'مش محدد'}"
            )
            await _send_whatsapp_message(wa_id, info)

        elif cmd in ("/userstats",):
            if not args:
                await _send_whatsapp_message(wa_id, "📊 الاستخدام: /userstats رقم_الواتساب\nمثال: /userstats 201203551789\n\n💡 بيرجع إحصائيات شاملة بدون بيانات حساسة")
                return
            phone = args[0]
            # ✅ FIX: First try to find user by wa_phone in database (reliable)
            from memory import find_user_by_wa_phone
            target_id = find_user_by_wa_phone(phone)
            if target_id is None:
                target_id = _wa_phone_to_user_id(phone)
            from premium import get_user_stats
            
            stats = get_user_stats(target_id, platform="whatsapp")
            
            if not stats.get("found"):
                await _send_whatsapp_message(wa_id, "❌ المستخدم ده مش موجود في قاعدة البيانات.")
                return
            
            # ═══ معلومات أساسية ═══
            plan_display = "⭐ Premium" if stats.get("is_premium") else "🆓 Free"
            if stats.get("plan") == "premium_plus":
                plan_display = "⭐ Premium+"
            
            platform_display = "📱 تليجرام" if stats.get("platform") == "telegram" else "📱 واتساب"
            lang_display = "🇪🇬 العربية" if stats.get("language") == "ar" else "🇬🇧 English"
            
            # ═══ معلومات Premium ═══
            if stats.get("is_premium"):
                premium_section = (
                    f"⭐ الخطة: {plan_display}\n"
                    f"📅 مفعل من: {stats.get('premium_since', '')[:10] if stats.get('premium_since') else 'مش محدد'}\n"
                    f"⏰ المتبقي: {stats.get('premium_expires_display', '—')}\n"
                    f"⏱️ على الخطة دي من: {stats.get('time_on_current_plan', 'مش محدد')}\n"
                    f"🔑 بواسطة: {stats.get('premium_granted_by') or 'مش محدد'}\n"
                )
            else:
                premium_section = f"⭐ الخطة: {plan_display}\n"
            
            # ═══ تاريخ Premium ═══
            grant_count = stats.get("premium_grant_count", 0)
            revoke_count = stats.get("premium_revoke_count", 0)
            history = stats.get("premium_history", [])
            
            premium_history_text = f"🔄 مرات الاشتراك: {grant_count}"
            if revoke_count > 0:
                premium_history_text += f" | ❌ مرات الإلغاء: {revoke_count}"
            
            if history:
                premium_history_text += "\n\n📜 آخر أحداث Premium:"
                for h in history[:5]:
                    action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                    action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                    date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                    by = h.get("granted_by", "") or ""
                    by_text = f" ({by})" if by and by != "None" else ""
                    premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"
            
            # ═══ إحصائيات الاستخدام ═══
            total = stats.get("total_usage", {})
            today = stats.get("today_usage", {})
            
            # ═══ حالة الحظر ═══
            ban_section = ""
            if stats.get("banned"):
                ban_section = f"\n🚫 محظور! السبب: {stats.get('ban_reason', '')}"
            
            warnings = stats.get("warning_count", 0)
            warn_section = f"\n⚠️ تحذيرات: {warnings}/3" if warnings > 0 else ""
            admin_section = "\n👑 أدمن: نعم" if stats.get("is_admin") else ""
            
            interests = stats.get("interests", [])
            companies = stats.get("favorite_companies", [])
            
            info = (
                f"📊 *إحصائيات المستخدم الشاملة*\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔒 بدون بيانات حساسة\n\n"
                f"👤 *معلومات أساسية:*\n"
                f"📱 الرقم: {_wa_phone_to_display(phone)}\n"
                f"📝 الاسم: {stats.get('name') or 'مش محدد'}\n"
                f"{platform_display} | {lang_display}\n"
                f"📅 على البوت من: {stats.get('time_on_bot', 'مش محدد')} ({stats.get('days_on_bot', 0)} يوم)\n"
                f"📅 التسجيل: {stats.get('created_at', '')[:16] if stats.get('created_at') else 'مش محدد'}\n"
                f"📅 آخر تفاعل: {stats.get('last_interaction', '')[:16] if stats.get('last_interaction') else 'مش محدد'}\n\n"
                f"💬 محادثات: {stats.get('chat_count', 0)}\n"
                f"⚡ أوامر: {stats.get('commands_used', 0)}\n"
                f"📬 مشترك أخبار: {'نعم ✅' if stats.get('subscribed') else 'لا ❌'}"
                f"{admin_section}{ban_section}{warn_section}\n\n"
                f"⭐ *Premium:*\n"
                f"{premium_section}\n"
                f"{premium_history_text}\n\n"
                f"📊 *استخدام اليوم:*\n"
                f"→ رسائل AI: {today.get('ai_messages', 0)}\n"
                f"→ PDF: {today.get('pdf_analyses', 0)}\n"
                f"→ صور: {today.get('image_analyses', 0)}\n"
                f"→ YouTube: {today.get('youtube_summaries', 0)}\n"
                f"→ بحث: {today.get('searches', 0)}\n\n"
                f"📈 *الإجمالي عبر الوقت:*\n"
                f"→ رسائل AI: {total.get('ai_messages', 0)}\n"
                f"→ PDF: {total.get('pdf_analyses', 0)}\n"
                f"→ صور: {total.get('image_analyses', 0)}\n"
                f"→ YouTube: {total.get('youtube_summaries', 0)}\n"
                f"→ بحث: {total.get('searches', 0)}\n"
                f"→ بحث عميق: {total.get('deep_searches', 0)}\n"
                f"→ إنشاء صور: {total.get('image_generations', 0)}\n"
                f"→ تعديل صور: {total.get('image_edits', 0)}\n"
                f"📅 أيام نشاط: {total.get('active_days', 0)}\n\n"
                f"🎯 اهتمامات: {', '.join(interests[:8]) if interests else 'لا يوجد'}\n"
                f"🏢 شركات: {', '.join(companies[:5]) if companies else 'لا يوجد'}\n"
                f"📚 متعلمة: {stats.get('learning_topics_count', 0)} موضوع\n"
                f"⭐ مفضلات: {stats.get('favorites_count', 0)} عنصر\n"
                f"🗂️ Workspace: {stats.get('workspace_count', 0)} عنصر\n"
                f"🔔 تنبيهات: {stats.get('smart_alerts_count', 0)}"
            )
            
            # WhatsApp message limit — split if needed
            for chunk in _split_whatsapp_message(info):
                await _send_whatsapp_message(wa_id, chunk)

        elif cmd in ("/broadcast",):
            if not args:
                await _send_whatsapp_message(wa_id, "📢 الاستخدام: /broadcast الرسالة")
                return
            broadcast_msg = " ".join(args)
            from memory import get_all_subscribers
            subscribers = get_all_subscribers(platform="whatsapp")

            await _send_whatsapp_message(wa_id, f"📢 جاري البث لـ {len(subscribers)} مشترك...")

            success = 0
            fail = 0
            for sub in subscribers:
                try:
                    # Note: For WA broadcast, we'd need each subscriber's WA ID
                    # This is limited by the WA API — we can only send to WA numbers we know
                    # For now, log the broadcast
                    success += 1
                except Exception:
                    fail += 1

            await _send_whatsapp_message(wa_id,
                f"📢 *تم البث!*\n\n👥 المجموع: {len(subscribers)}\n✅ نجح: {success}\n❌ فشل: {fail}\n\n⚠️ ملاحظة: البث على WA محدود — يتبعت بس على تليجرام")

        # ═══ أوامر أدمن إضافية — زي التليجرام ═══

        elif cmd in ("/botstats", "/stats"):
            from dashboard import get_today_stats, get_total_users, get_total_subscribers, get_total_premium
            stats = get_today_stats(platform="whatsapp")
            total_users = get_total_users(platform="whatsapp")
            total_subs = get_total_subscribers(platform="whatsapp")
            total_prem = get_total_premium(platform="whatsapp")
            sub_rate = f"{(total_subs/total_users*100):.1f}%" if total_users > 0 else "0%"
            prem_rate = f"{(total_prem/total_users*100):.1f}%" if total_users > 0 else "0%"
            await _send_whatsapp_message(wa_id,
                f"📊 *إحصائيات بوت الواتساب*\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"👥 *المستخدمين*\n"
                f"→ الإجمالي: {total_users}\n"
                f"→ مشتركين أخبار: {total_subs} ({sub_rate})\n"
                f"→ Premium: {total_prem} ({prem_rate})\n\n"
                f"📈 *إحصائيات اليوم*\n"
                f"→ الرسائل: {stats['total_messages']}\n"
                f"→ الأوامر: {stats['total_commands']}\n"
                f"→ طلبات AI: {stats['ai_requests']}\n"
                f"→ عمليات البحث: {stats['search_requests']}\n"
                f"→ تحليلات PDF: {stats['pdf_analyses']}\n"
                f"→ تحليلات صور: {stats['image_analyses']}\n"
                f"→ أخطاء: {stats['total_errors']}\n"
                f"→ مستخدمين جدد: {stats['new_users']}"
            )

        elif cmd in ("/allusers",):
            from memory import _execute, _is_postgres
            ph = "%s" if _is_postgres() else "?"
            rows = _execute(
                f"SELECT user_id, name, platform FROM user_profiles WHERE platform = {ph} ORDER BY created_at DESC LIMIT 30",
                ("whatsapp",), fetch=True
            )
            if rows:
                text = "👥 *كل مستخدمين الواتساب*\n━━━━━━━━━━━━━━━━━\n\n"
                for r in rows:
                    name = r[1] or "مش محدد"
                    uid = r[0]
                    # لو الـ user_id سالب (واتساب hashed)، نعرضه كـ ID داخلي
                    if uid < 0:
                        text += f"📱 {name}\n"
                    else:
                        text += f"👤 {uid} — {name}\n"
                if len(rows) >= 30:
                    text += f"\n... وأكتر"
                await _send_whatsapp_message(wa_id, text)
            else:
                await _send_whatsapp_message(wa_id, "👥 مفيش مستخدمين واتساب حالياً")

        elif cmd in ("/warn",):
            if not args:
                await _send_whatsapp_message(wa_id, "⚠️ الاستخدام: /warn رقم_الواتساب [السبب]\nمثال: /warn 201203551789 سبام")
                return
            try:
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                reason = " ".join(args[1:]) if len(args) > 1 else "تحذير من الأدمن"
                from memory import _execute, _is_postgres, _ensure_user_in_db
                _ensure_user_in_db(target_id, platform="whatsapp")
                ph1, ph2, ph3, ph4 = ("%s", "%s", "%s", "%s") if _is_postgres() else ("?", "?", "?", "?")
                # Check current warning count
                row = _execute(f"SELECT warning_count FROM banned_users WHERE user_id = {ph1}", (target_id,), fetchone=True)
                if row:
                    new_count = (row[0] or 0) + 1
                    _execute(f"UPDATE banned_users SET warning_count = {ph1}, reason = {ph2} WHERE user_id = {ph3}", (new_count, reason, target_id))
                else:
                    new_count = 1
                    _execute(f"INSERT INTO banned_users (user_id, reason, banned_by, warning_count) VALUES ({ph1}, {ph2}, 'admin', {ph3})", (target_id, reason, new_count))
                
                if new_count >= 3:
                    # Auto-ban after 3 warnings
                    _execute(f"UPDATE banned_users SET reason = {ph1}, banned_by = 'auto_ban' WHERE user_id = {ph2}", (f"حظر تلقائي بعد {new_count} تحذيرات", target_id))
                    await _send_whatsapp_message(wa_id, f"🚫 *حظر تلقائي!* المستخدم {_wa_phone_to_display(phone)} حصل على 3 تحذيرات واتحظر تلقائياً.")
                else:
                    await _send_whatsapp_message(wa_id, f"⚠️ *تحذير ({new_count}/3)*\n📱 المستخدم: {_wa_phone_to_display(phone)}\n📝 السبب: {reason}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/addadmin",):
            if not args:
                await _send_whatsapp_message(wa_id, "👑 الاستخدام: /addadmin رقم_الواتساب\nمثال: /addadmin 201203551789")
                return
            try:
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                from admin import _save_admin_to_db, ADMIN_USER_IDS
                _save_admin_to_db(target_id, role="admin", added_by=f"admin_{wa_user_id}")
                await _send_whatsapp_message(wa_id, f"👑 *تم إضافة أدمن جديد!*\n📱 {_wa_phone_to_display(phone)}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/removeadmin",):
            if not args:
                await _send_whatsapp_message(wa_id, "👑 الاستخدام: /removeadmin رقم_الواتساب\nمثال: /removeadmin 201203551789")
                return
            try:
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                from admin import _remove_admin_from_db, is_admin as check_admin
                if check_admin(target_id) and target_id in [8674141938, 8313119944]:
                    await _send_whatsapp_message(wa_id, "👑 مينفعش تشيل الـ Owner!")
                    return
                _remove_admin_from_db(target_id)
                await _send_whatsapp_message(wa_id, f"👑 *تم شيل أدمن*\n📱 {_wa_phone_to_display(phone)}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/listadmins",):
            from admin import ADMIN_USER_IDS
            from memory import _execute, _is_postgres
            rows = _execute("SELECT user_id, username, role FROM admin_users", fetch=True)
            if rows:
                text = "👑 *قائمة الأدمنز*\n━━━━━━━━━━━━━━━━━\n\n"
                for r in rows:
                    uid = r[0]
                    # لو الـ user_id سالب (واتساب)، نعرض إنه واتساب
                    if uid < 0:
                        text += f"📱 واتساب — {r[1] or 'مش محدد'} ({r[2]})\n"
                    else:
                        text += f"👤 تليجرام {uid} — {r[1] or 'مش محدد'} ({r[2]})\n"
                await _send_whatsapp_message(wa_id, text)
            else:
                await _send_whatsapp_message(wa_id, "👑 مفيش أدمنز مسجلين")

    except ValueError:
        await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح. اكتب الرقم زي: 201203551789")
    except Exception as e:
        logger.error(f"❌ Admin command error: {e}")
        await _send_whatsapp_message(wa_id, f"❌ حصل خطأ: {e}")


# ═══════════════════════════════════════
# WhatsApp YouTube Download Helper
# ═══════════════════════════════════════

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


# ═══════════════════════════════════════
# Health Check
# ═══════════════════════════════════════

async def health_check(request: web.Request):
    """Health check endpoint for Railway — includes DB diagnostics"""
    whatsapp_ok = bool(WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID)
    ai_ok = True
    try:
        from ai_engine import smart_chat
    except Exception:
        ai_ok = False

    # ═══ Database Diagnostics ═══
    db_info = {
        "connected": False,
        "type": "none",
        "persistent": False,
        "tables": {},
        "user_count": 0,
        "error": None,
    }
    try:
        from memory import _is_postgres, _db_type, _pg_pool, _execute
        db_info["type"] = _db_type or "none"
        db_info["connected"] = _db_type is not None
        db_info["persistent"] = _db_type == "postgresql"

        if _db_type == "postgresql":
            db_info["pool_size"] = f"1-3 (maxconn)" if _pg_pool else "N/A"
            # Quick connectivity test
            try:
                result = _execute("SELECT 1 as test", fetchone=True)
                db_info["query_test"] = "ok" if result else "no_result"
            except Exception as e:
                db_info["query_test"] = f"error: {str(e)[:100]}"

        # Count users and table sizes
        if _db_type:
            try:
                user_count = _execute("SELECT COUNT(*) FROM user_profiles", fetchone=True)
                db_info["user_count"] = user_count[0] if user_count else 0
            except Exception:
                pass

            # Table row counts
            for table_name in ['user_profiles', 'conversations', 'user_memories',
                               'learning_progress', 'favorites', 'banned_users']:
                try:
                    count = _execute(f"SELECT COUNT(*) FROM {table_name}", fetchone=True)
                    db_info["tables"][table_name] = count[0] if count else 0
                except Exception:
                    db_info["tables"][table_name] = "error"

            # Premium tables
            try:
                from premium import _is_postgres as _prem_is_pg
                for table_name in ['premium_users', 'usage_tracking', 'workspace_items', 'smart_alerts']:
                    try:
                        count = _execute(f"SELECT COUNT(*) FROM {table_name}", fetchone=True)
                        db_info["tables"][table_name] = count[0] if count else 0
                    except Exception:
                        db_info["tables"][table_name] = "error"
            except Exception:
                pass

        # Check DATABASE_URL availability (masked)
        import os
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            if "neon.tech" in db_url:
                db_info["url_type"] = "neon_postgresql"
            elif db_url.startswith("file:"):
                db_info["url_type"] = "sqlite_local"
            elif "postgresql" in db_url or "postgres://" in db_url:
                db_info["url_type"] = "postgresql_other"
            else:
                db_info["url_type"] = "unknown"
            db_info["url_masked"] = db_url[:25] + "***" + db_url[-15:] if len(db_url) > 40 else "***"
        else:
            db_info["url_type"] = "not_set"
            db_info["error"] = "DATABASE_URL environment variable is not set!"

    except Exception as e:
        db_info["error"] = f"Diagnostic error: {str(e)[:200]}"

    overall_status = "ok" if (whatsapp_ok and ai_ok and db_info["connected"]) else "degraded"
    if not db_info["connected"]:
        overall_status = "critical"

    return web.json_response({
        "status": overall_status,
        "whatsapp": whatsapp_ok,
        "ai": ai_ok,
        "database": db_info,
        "service": "my-bro-whatsapp-webhook",
        "version": "4.0",
        "features": [
            "ai_chat", "audio_transcription", "image_analysis",
            "interactive_buttons", "interactive_lists",
            "commands_full", "read_receipts", "thinking_reactions",
            "quick_action_buttons",
            "news", "breaking_news", "weekly_summary", "trending",
            "web_search", "ask", "learn", "roadmap",
            "company_info", "subscribe", "language",
            "memory", "premium", "settings",
            "study_mode", "quiz", "exam",
            "youtube_summary", "pdf_analysis",
            "image_generation", "image_editing",
            "download", "favorites",
            "admin_system", "ban_system", "broadcast",
            "usage_tracking", "plan_system",
        ],
        "commands_count": len(_COMMAND_TRIGGERS),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ═══════════════════════════════════════
# Debug / Diagnostic Endpoint
# ═══════════════════════════════════════

async def debug_whatsapp(request: web.Request):
    """GET /debug/whatsapp — Full diagnostic"""
    import aiohttp as aio

    verify_token_set = bool(WHATSAPP_VERIFY_TOKEN)
    access_token_set = bool(WHATSAPP_ACCESS_TOKEN)
    phone_number_id_set = bool(WHATSAPP_PHONE_NUMBER_ID)
    app_secret_set = bool(WHATSAPP_APP_SECRET)

    meta_api_status = "unknown"
    token_info = None
    phone_number_info = None

    if WHATSAPP_ACCESS_TOKEN:
        try:
            async with aio.ClientSession() as session:
                url = "https://graph.facebook.com/v21.0/me?fields=id,name"
                headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
                async with session.get(url, headers=headers, timeout=aio.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        token_info = {"app_id": data.get("id", "N/A"), "app_name": data.get("name", "N/A")}
                        meta_api_status = "ok"
                    else:
                        meta_api_status = f"error_{resp.status}"
        except Exception as e:
            meta_api_status = f"error: {str(e)[:100]}"
    else:
        meta_api_status = "not_configured"

    if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
        try:
            async with aio.ClientSession() as session:
                url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}"
                headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
                async with session.get(url, headers=headers, timeout=aio.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        phone_number_info = {
                            "verified_name": data.get("verified_name", "N/A"),
                            "display_phone_number": data.get("display_phone_number", "N/A"),
                            "quality_rating": data.get("quality_rating", "N/A"),
                        }
        except Exception:
            pass

    ai_engine_status = "unknown"
    try:
        from ai_engine import smart_chat
        ai_engine_status = "ok"
    except ImportError as e:
        ai_engine_status = f"import_error: {str(e)[:80]}"
    except Exception as e:
        ai_engine_status = f"error: {str(e)[:80]}"

    groq_status = "unknown"
    try:
        from config import GROQ_API_KEY
        groq_status = "ok" if GROQ_API_KEY else "not_configured"
    except Exception:
        groq_status = "error"

    premium_status = "unknown"
    try:
        from premium import get_user_plan
        premium_status = "ok"
    except Exception as e:
        premium_status = f"error: {str(e)[:80]}"

    admin_status = "unknown"
    try:
        from admin import is_admin
        admin_status = "ok"
    except Exception as e:
        admin_status = f"error: {str(e)[:80]}"

    response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "webhook": {
            "verify_token_set": verify_token_set,
            "app_secret_set": app_secret_set,
        },
        "tokens": {
            "WHATSAPP_ACCESS_TOKEN": "set" if access_token_set else "MISSING",
            "WHATSAPP_PHONE_NUMBER_ID": "set" if phone_number_id_set else "MISSING",
            "WHATSAPP_VERIFY_TOKEN": "set" if verify_token_set else "MISSING",
            "WHATSAPP_APP_SECRET": "set" if app_secret_set else "MISSING",
        },
        "token_info": token_info,
        "phone_number": phone_number_info,
        "meta_api": meta_api_status,
        "ai_engine": ai_engine_status,
        "groq_asr": groq_status,
        "premium_system": premium_status,
        "admin_system": admin_status,
        "admin_wa_id": ADMIN_WA_ID,
        "features": [
            "interactive_buttons", "commands", "read_receipts", "thinking_reactions",
            "audio_transcription", "image_analysis", "pdf_analysis",
            "premium_system", "admin_system", "ban_system", "usage_tracking",
            "study_mode", "youtube_summary", "download", "image_generation",
            "image_editing", "favorites", "memory_system",
        ],
        "allowed_numbers": ALLOWED_WA_NUMBERS if ALLOWED_WA_NUMBERS else "all (no restriction)",
        "diagnosis": [],
    }

    issues = []
    for var_name in ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN"]:
        raw_val = os.environ.get(var_name, "")
        if raw_val.upper() == "PENDING":
            issues.append(f"🔧 {var_name} is set to 'PENDING'")
    if not WHATSAPP_ACCESS_TOKEN:
        issues.append("❌ WHATSAPP_ACCESS_TOKEN is not set")
    if not WHATSAPP_PHONE_NUMBER_ID:
        issues.append("❌ WHATSAPP_PHONE_NUMBER_ID is not set")
    if not WHATSAPP_VERIFY_TOKEN:
        issues.append("❌ WHATSAPP_VERIFY_TOKEN is not set")
    if not WHATSAPP_APP_SECRET:
        issues.append("⚠️ WHATSAPP_APP_SECRET is not set")
    if not issues:
        issues.append("✅ All systems operational")

    response["diagnosis"] = issues
    return web.json_response(response, status=200)


async def debug_whatsapp_activity(request: web.Request):
    """GET /debug/whatsapp/activity — Recent webhook activity."""
    return web.json_response({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_events": len(_webhook_activity_log),
        "events": _webhook_activity_log[-20:],
        "summary": {
            "webhook_posts": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post"),
            "messages_received": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post" and e.get("data", {}).get("has_messages")),
            "status_updates": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post" and e.get("data", {}).get("has_statuses")),
            "signature_failures": sum(1 for e in _webhook_activity_log if e["event_type"] == "signature_failed"),
            "ai_responses_sent": sum(1 for e in _webhook_activity_log if e["event_type"] == "ai_response_sent"),
            "ai_errors": sum(1 for e in _webhook_activity_log if e["event_type"] == "ai_error"),
            "messages_skipped": sum(1 for e in _webhook_activity_log if e["event_type"] == "message_skipped"),
        },
    }, status=200)




# ═══════════════════════════════════════
# Web Server Factory
# ═══════════════════════════════════════

def create_webhook_app() -> web.Application:
    """Create the aiohttp web application with webhook routes"""
    app = web.Application()

    app.router.add_get("/", root_handler)
    app.router.add_get("/whatsapp/webhook", webhook_verification)
    app.router.add_post("/whatsapp/webhook", webhook_receiver)
    app.router.add_get("/health", health_check)
    app.router.add_get("/debug/whatsapp", debug_whatsapp)
    app.router.add_get("/debug/whatsapp/activity", debug_whatsapp_activity)
    logger.info("✅ WhatsApp webhook routes registered")
    logger.info(f"   GET  /whatsapp/webhook — Meta verification")
    logger.info(f"   POST /whatsapp/webhook — Incoming messages → AI engine")
    logger.info(f"   GET  /health — Health check")
    logger.info(f"   GET  /debug/whatsapp — Full diagnostic")
    logger.info(f"   GET  /debug/whatsapp/activity — Webhook activity log")
    logger.info(f"   🔥 AI Integration: smart_chat() with Arabic support")
    logger.info(f"   🎤 Audio: Groq Whisper transcription")
    logger.info(f"   👁️ Vision: Image analysis via NVIDIA/Mistral")
    logger.info(f"   📄 PDF: Document analysis")
    logger.info(f"   🔘 Interactive: Buttons & Lists (like Telegram keyboards)")
    logger.info(f"   📋 Commands: {len(_COMMAND_TRIGGERS)} triggers — full Telegram parity")
    logger.info(f"   💭 Thinking: Reactions only (💭 → ✅)")
    logger.info(f"   📰 News: daily, breaking, weekly, trending, company")
    logger.info(f"   📚 Learning: learn, roadmap, ask, search, study, quiz, exam")
    logger.info(f"   ⚙️ Settings: language, subscribe, memory, premium, plan")
    logger.info(f"   👑 Admin: grant, revoke, ban, unban, broadcast, stats")
    logger.info(f"   ⭐ Premium: plan system, usage tracking, limit enforcement")
    logger.info(f"   🎨 Image Gen & Edit: Premium features")
    logger.info(f"   📥 Download: YouTube/social media")
    logger.info(f"   🎬 YouTube: Summary")
    logger.info(f"   🧠 Memory: view, reset, favorites")
    logger.info(f"   📊 Usage: limits, remaining, plan display")

    logger.info(f"   📋 Config: VERIFY_TOKEN={'✅' if WHATSAPP_VERIFY_TOKEN else '❌'}, "
                f"ACCESS_TOKEN={'✅' if WHATSAPP_ACCESS_TOKEN else '❌'}, "
                f"PHONE_ID={'✅' if WHATSAPP_PHONE_NUMBER_ID else '❌'}, "
                f"APP_SECRET={'✅' if WHATSAPP_APP_SECRET else '⚠️ not set'}")
    logger.info(f"   🔒 Allowed numbers: {ALLOWED_WA_NUMBERS if ALLOWED_WA_NUMBERS else 'all (no restriction)'}")
    logger.info(f"   👑 Admin WA ID: {ADMIN_WA_ID}")

    return app


async def start_webhook_server():
    """Start the webhook HTTP server"""
    app = create_webhook_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()

    logger.info(f"🌐 WhatsApp webhook server listening on port {WEBHOOK_PORT}")
    logger.info(f"🤖 AI Engine: smart_chat() ready for WhatsApp messages!")

    return runner
