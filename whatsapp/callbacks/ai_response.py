"""
AI Response Helper & Contextual Buttons
========================================
Extracted from whatsapp/callbacks.py — contains:
- _send_ai_response: Send AI response with full pipeline
- _send_contextual_buttons: Send contextual quick action buttons
"""

import asyncio
import logging

from whatsapp.state import (
    DEVELOPER_WHATSAPP_URL,
    _is_wa_admin,
    _strip_html_for_whatsapp,
    _split_whatsapp_message,
)

from whatsapp.api import (
    _send_whatsapp_message,
    _send_whatsapp_reaction,
    _send_interactive_buttons,
    ThinkingFeedback,
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
        # 🐦 Sentry — capture WhatsApp AI errors
        try:
            from sentry_config import capture_exception, set_context
            set_context("whatsapp", {"wa_id": wa_id, "user_id": wa_user_id, "context_type": context_type})
            capture_exception(e)
        except Exception:
            pass
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
