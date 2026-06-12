"""
WhatsApp Command Handlers Module
==================================
Command handler functions for the WhatsApp bot.

Extracted from whatsapp_webhook.py for modularity.

Contents:
  - _handle_command: Main command dispatcher (start, help, news, settings, etc.)
  - _handle_command_with_arg: Commands that require arguments (download, youtube, etc.)
  - _wa_download_youtube: YouTube video/audio download helper
  - _cleanup_wa_file: Temporary file cleanup utility
"""

import os
import re
import logging
import asyncio
import time
from datetime import datetime, timezone

from whatsapp.state import (
    WA_MAX_MSG,
    ADMIN_WA_ID,
    DEVELOPER_WHATSAPP_URL,
    _wa_user_state,
    _set_user_state,
    _get_user_state,
    _clear_user_state,
    _wa_user_yt_url,
    _wa_user_pdf_context,
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
    _is_wa_admin,
    _ensure_wa_admin_premium,
    _wa_phone_to_user_id,
    _wa_phone_to_display,
    _COMMAND_TRIGGERS,
)

from whatsapp.api import (
    _send_whatsapp_message,
    _send_whatsapp_reaction,
    _mark_message_read,
    _send_interactive_buttons,
    _send_interactive_list,
    _send_typing_indicator,
    ThinkingFeedback,
)

from i18n import t

logger = logging.getLogger(__name__)


async def _handle_command(wa_id: str, command: str, wa_user_id: int, contact_name: str, message_id: str = ""):
    """Handle WhatsApp commands and send interactive responses — full Telegram parity"""

    is_admin = _is_wa_admin(wa_id)

    # ── Ensure admin is always premium ──
    if is_admin:
        _ensure_wa_admin_premium(wa_id)

    # ══════════════════════════════════════
    # ADMIN COMMANDS
    # ══════════════════════════════════════

    if command == "admin" or command == "admin_stats":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True

        try:
            from dashboard import format_dashboard
            from premium import get_all_premium_users
            from memory import get_all_subscribers, get_user

            dashboard = format_dashboard("ar", platform="whatsapp")
            total_subs = len(get_all_subscribers(platform="whatsapp"))
            total_prem = len(get_all_premium_users(platform="whatsapp"))

            admin_text = (
                f"👑 *لوحة تحكم الأدمن*\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"{_strip_html_for_whatsapp(dashboard)}\n\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"👑 *صلاحياتك:*\n"
                f"→ مفيش أي Limits — كل حاجة مفتوحة\n"
                f"→ تفعيل Premium لأي حد\n"
                f"→ شيل Premium من أي حد\n"
                f"→ بث رسالة لكل المشتركين\n"
                f"→ معلومات أي يوزر\n\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔧 *أوامر الأدمن:*\n"
                f"→ /grant [مدة] رقم_الواتساب — تفعيل Premium (m=شهر, w=أسبوع, y=سنة)\n"
                f"→ /revoke user_id — شيل Premium\n"
                f"→ /resetlimit user_id — ريست الحدود\n"
                f"→ /ban user_id — حظر مستخدم\n"
                f"→ /unban user_id — إلغاء حظر\n"
                f"→ /userinfo رقم_الواتساب — معلومات يوزر شاملة (بدون بيانات حساسة)\n"
                f"→ /userstats رقم_الواتساب — إحصائيات يوزر مفصلة\n"
                f"→ /broadcast رسالة — بث لكل المشتركين\n"
                f"→ /stats — الإحصائيات"
            )
            await _send_whatsapp_message(wa_id, admin_text)
        except Exception as e:
            logger.error(f"❌ Admin command error: {e}")
            await _send_whatsapp_message(wa_id, f"⚠️ خطأ في لوحة التحكم: {e}")
        return True

    elif command == "admin_grant":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "⭐ *تفعيل Premium*\n\n"
            "الاستخدام:\n"
            "/grant رقم_الواتساب — تفعيل مدى الحياة\n"
            "/grant 30 رقم_الواتساب — تفعيل 30 يوم\n"
            "/grant m رقم_الواتساب — تفعيل شهر\n"
            "/grant w رقم_الواتساب — تفعيل أسبوع\n"
            "/grant y رقم_الواتساب — تفعيل سنة\n\n"
            "🔑 *اختصارات المدة:*\n"
            "d = يوم | w = أسبوع | m = شهر | y = سنة\n"
            "0 أو دائم = مدى الحياة\n\n"
            "مثال: /grant m 201203551789\n"
            "مثال: /grant w2 201203551789")
        return True

    elif command == "admin_revoke":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "❌ *شيل Premium*\n\n"
            "الاستخدام: /revoke user_id\n"
            "مثال: /revoke 123456789")
        return True

    elif command == "admin_resetlimit":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "🔄 *ريست الحدود*\n\n"
            "الاستخدام: /resetlimit user_id\n"
            "مثال: /resetlimit 123456789")
        return True

    elif command == "admin_ban":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "🚫 *حظر مستخدم*\n\n"
            "الاستخدام: /ban user_id [سبب]\n"
            "مثال: /ban 123456789 سبام")
        return True

    elif command == "admin_unban":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "✅ *إلغاء حظر*\n\n"
            "الاستخدام: /unban user_id\n"
            "مثال: /unban 123456789")
        return True

    elif command == "admin_userinfo":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
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
        return True

    elif command == "admin_userstats":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "📊 *إحصائيات مستخدم شاملة*\n\n"
            "الاستخدام: /userstats رقم_الواتساب\n\n"
            "💡 بيرجع كل المعلومات العامة:\n"
            "→ الخطة وتاريخ الاشتراكات\n"
            "→ كم مرة اشترك Premium\n"
            "→ إحصائيات الاستخدام الإجمالي\n"
            "→ حالة الحظر والتحذيرات\n\n"
            "🔒 مش بيرجع بيانات حساسة:\n"
            "→ محتوى المحادثات\n"
            "→ ذكريات المستخدم\n\n"
            "مثال: /userstats 201203551789")
        return True

    elif command == "admin_broadcast":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "📢 *بث رسالة*\n\n"
            "الاستخدام: /broadcast الرسالة\n"
            "مثال: /broadcast تحديث جديد في البوت!")
        return True

    elif command == "admin_stats":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "📊 *إحصائيات البوت*\n\n"
            "الاستخدام: /botstats أو /stats")
        return True

    elif command == "admin_allusers":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👥 *كل المستخدمين*\n\n"
            "الاستخدام: /allusers")
        return True

    elif command == "admin_warn":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "⚠️ *تحذير مستخدم*\n\n"
            "الاستخدام: /warn user_id [سبب]\n"
            "3 تحذيرات = حظر تلقائي\n"
            "مثال: /warn 123456789 سبام")
        return True

    elif command == "admin_addadmin":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👑 *إضافة أدمن*\n\n"
            "الاستخدام: /addadmin user_id\n"
            "مثال: /addadmin 123456789")
        return True

    elif command == "admin_removeadmin":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👑 *شيل أدمن*\n\n"
            "الاستخدام: /removeadmin user_id\n"
            "مثال: /removeadmin 123456789")
        return True

    elif command == "admin_listadmins":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👑 *قائمة الأدمنز*\n\n"
            "الاستخدام: /listadmins")
        return True

    # ══════════════════════════════════════
    # START — Enhanced Multi-Page Menu
    # ══════════════════════════════════════

    if command == "start":
        # Welcome message with FULL category list like Telegram keyboard
        # 🔴 FIX v3: كالتليجرام بالظبط — لو المستخدم جديد ومش مشترك، نسأله هل عايز يشترك في الأخبار
        
        from memory import is_new_user, is_subscribed, get_language
        user_lang = get_language(wa_user_id)
        user_is_new = is_new_user(wa_user_id)
        user_subscribed = is_subscribed(wa_user_id)
        
        # Send welcome text first
        if user_lang == "en":
            await _send_whatsapp_message(wa_id,
                "Welcome! 🤖 I'm *My Bro* — your personal AI assistant\n\n"
                "I can help you with many things!\nChoose from the menu or just type anything")
        else:
            await _send_whatsapp_message(wa_id,
                "أهلاً بيك! 🤖 أنا *My Bro* — مساعدك الذكي الشخصي\n\n"
                "ممكن أساعدك في حاجات كتير!\nاختار من القائمة أو ابعت أي رسالة")

        # Then send interactive list with all categories
        admin_row = []
        if is_admin:
            admin_row = [{"id": "cmd_admin", "title": t("wa.menu_admin", user_lang), "description": t("wa.menu_admin_desc", user_lang)}]

        await _send_interactive_list(
            wa_id,
            body_text=t("wa.menu_choose_feature", user_lang),
            button_text=t("wa.menu_features", user_lang),
            sections=[{
                "title": t("wa.menu_main_features", user_lang),
                "rows": [
                    {"id": "cmd_chat", "title": t("wa.menu_chat", user_lang), "description": t("wa.menu_chat_desc", user_lang)},
                    {"id": "cmd_news", "title": t("wa.menu_news", user_lang), "description": t("wa.menu_news_desc", user_lang)},
                    {"id": "cmd_download", "title": t("wa.menu_download", user_lang), "description": t("wa.menu_download_desc", user_lang)},
                    {"id": "video_search", "title": t("wa.menu_video_search", user_lang), "description": t("wa.menu_video_search_desc", user_lang)},
                    {"id": "audio_search", "title": t("wa.menu_audio_search", user_lang), "description": t("wa.menu_audio_search_desc", user_lang)},
                    {"id": "photo_search", "title": t("wa.menu_photo_search", user_lang), "description": t("wa.menu_photo_search_desc", user_lang)},
                    {"id": "cmd_search", "title": t("wa.menu_web_search", user_lang), "description": t("wa.menu_web_search_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_learning", user_lang),
                "rows": [
                    {"id": "cmd_study", "title": t("wa.menu_study", user_lang), "description": t("wa.menu_study_desc", user_lang)},
                    {"id": "cmd_memory", "title": t("wa.menu_memory", user_lang), "description": t("wa.menu_memory_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_media", user_lang),
                "rows": [
                    {"id": "cmd_image_gen", "title": t("wa.menu_image_gen", user_lang), "description": t("wa.menu_image_gen_desc", user_lang)},
                    {"id": "cmd_image_edit", "title": t("wa.menu_image_edit", user_lang), "description": t("wa.menu_image_edit_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_documents", user_lang),
                "rows": [
                    {"id": "cmd_youtube", "title": t("wa.menu_youtube_summary", user_lang), "description": t("wa.menu_youtube_summary_desc", user_lang)},
                    {"id": "cmd_pdf", "title": t("wa.menu_pdf", user_lang), "description": t("wa.menu_pdf_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_settings_section", user_lang),
                "rows": [
                    {"id": "cmd_settings", "title": t("wa.menu_settings", user_lang), "description": t("wa.menu_settings_desc", user_lang)},
                    {"id": "cmd_plan", "title": t("wa.menu_plan", user_lang), "description": t("wa.menu_plan_desc", user_lang)},
                ] + admin_row,
            }],
            header_text="🤖 My Bro",
            footer_text=t("wa.menu_footer", user_lang),
        )
        
        # 🔴 FIX v3: زي التليجرام بالظبط — لو المستخدم جديد ومش مشترك، نبعتله سؤال الاشتراك
        if user_is_new and not user_subscribed:
            import asyncio as _aio
            await _aio.sleep(1.5)  # انتظر شوية عشان الرسالة اللي فاتت توصل الأول
            if user_lang == "en":
                await _send_interactive_buttons(
                    wa_id,
                    body_text="📬 *Subscribe to Daily News!*\n━━━━━━━━━━━━━━━━━\n\n"
                              "I'll send you the most important AI news every day at 12:00 PM Cairo time 🌅\n\n"
                              "✅ Latest AI news from global sources\n"
                              "✅ Clear and simple summaries\n"
                              "✅ Completely free\n\n"
                              "👇 Choose below!",
                    buttons=[
                        {"id": "cmd_subscribe_confirm", "title": "✅ Subscribe"},
                        {"id": "cmd_skip_subscribe", "title": "No Thanks"},
                    ],
                    header_text="📬 Daily News",
                )
            else:
                await _send_interactive_buttons(
                    wa_id,
                    body_text="📬 *اشترك في الأخبار اليومية!*\n━━━━━━━━━━━━━━━━━\n\n"
                              "هابعتلك أهم أخبار الذكاء الاصطناعي كل يوم الساعة 12 الظهر بتوقيت القاهرة 🌅\n\n"
                              "✅ آخر أخبار AI من مصادر عالمية\n"
                              "✅ ملخص بالعربية مفهوم وبسيط\n"
                              "✅ مجاني تماماً\n\n"
                              "👇 اختار من تحت!",
                    buttons=[
                        {"id": "cmd_subscribe_confirm", "title": "✅ اشترك"},
                        {"id": "cmd_skip_subscribe", "title": "لا شكراً"},
                    ],
                    header_text="📬 أخبار يومية",
                )

    # ══════════════════════════════════════
    # HELP / COMMANDS
    # ══════════════════════════════════════

    elif command == "help" or command == "commands":
        await _send_interactive_list(
            wa_id,
            body_text="📋 كل الأوامر والميزات المتاحة:",
            button_text="عرض الأوامر",
            sections=[{
                "title": "🤖 المحادثة و الذكاء الاصطناعي",
                "rows": [
                    {"id": "cmd_chat", "title": "💬 محادثة AI", "description": "تحدث مع الذكاء الاصطناعي"},
                    {"id": "cmd_ask", "title": "❓ اسأل سؤال", "description": "اسأل أي سؤال وهجاوبك"},
                    {"id": "cmd_search", "title": "🔍 بحث ويب", "description": "ابحث في الإنترنت"},
                    {"id": "cmd_learn", "title": "📚 تعلم", "description": "تعلم أي موضوع بالتفصيل"},
                    {"id": "cmd_roadmap", "title": "🗺️ خريطة تعلم", "description": "خريطة طريق لتعلم أي تقنية"},
                    {"id": "cmd_study", "title": "📚 وضع الدراسة", "description": "ادرس واختبر نفسك"},
                    {"id": "cmd_news", "title": "📰 أخبار AI", "description": "آخر أخبار الذكاء الاصطناعي"},
                    {"id": "cmd_youtube", "title": "🎬 ملخص يوتيوب", "description": "لخص أي فيديو يوتيوب"},
                    {"id": "cmd_download", "title": "📥 تحميل فيديو", "description": "حمّل من يوتيوب"},
                    {"id": "cmd_cookies", "title": "🍪 رفع كوكيز", "description": "ارفع ملف كوكيز YouTube"},
                    {"id": "video_search", "title": "🎬 فيديو بالبحث", "description": "ابحث Dailymotion وحمّل فيديو"},
                    {"id": "audio_search", "title": "🎵 صوت بالبحث", "description": "ابحث SoundCloud وحمّل صوت"},
                    {"id": "photo_search", "title": "🖼️ بحث صور", "description": "ابحث عن صور"},
                    {"id": "cmd_memory", "title": "🧠 ذاكرتي", "description": "عرض وإدارة الذاكرة"},
                ],
            }],
            header_text="📋 أوامر My Bro",
            footer_text="أو ابعت أي رسالة وهرد عليك!",
        )

    # ══════════════════════════════════════
    # NEWS COMMANDS
    # ══════════════════════════════════════

    elif command == "news":
        # Lazy import to avoid circular dependency with whatsapp_webhook
        from whatsapp_webhook import _send_ai_response
        await _send_ai_response(wa_id, "اعطني اخر اخبار الذكاء الاصطناعي اليوم باختصار",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command == "breaking":
        from whatsapp_webhook import _send_ai_response
        await _send_ai_response(wa_id,
            "ما هي اهم الاخبار العاجلة في مجال الذكاء الاصطناعي اليوم؟ اذكر أهم التطورات والاعلانات الجديدة",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command == "weekly":
        from whatsapp_webhook import _send_ai_response
        await _send_ai_response(wa_id,
            "لخص لي أهم أخبار وتطورات الذكاء الاصطناعي خلال هذا الأسبوع بشكل شامل. اذكر أهم الاعلانات والمنتجات والأخبار",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command == "trending":
        from whatsapp_webhook import _send_ai_response
        await _send_ai_response(wa_id,
            "ما هي أهم المواضيع الترند في مجال الذكاء الاصطناعي اليوم؟ اذكر أهم 5 مواضيع أو تقنيات يتكلم عنها الناس حالياً",
            wa_user_id, contact_name, message_id, context_type="news")

    # ══════════════════════════════════════
    # SEARCH & ASK
    # ══════════════════════════════════════

    elif command == "search":
        await _send_interactive_buttons(
            wa_id,
            body_text="🔍 *بحث الويب*\n\nاكتب كلمة البحث بعد الأمر\nمثال: *بحث الحضارة الإسلامية*\n\nأو اختار من الاقتراحات:",
            buttons=[
                {"id": "cmd_search_ai", "title": "🤖 أخبار AI"},
                {"id": "cmd_search_code", "title": "👨‍💻 برمجة"},
            ],
            header_text="🔍 بحث ويب",
        )

    elif command == "ask":
        await _send_interactive_buttons(
            wa_id,
            body_text="❓ *اسأل أي سؤال*\n\nاكتب سؤالك مباشرة وهجاوبك بإذن الله\n\nأو اختار من الأسئلة الشائعة:",
            buttons=[
                {"id": "cmd_ask_ai", "title": "🤖 ما هو AI؟"},
                {"id": "cmd_ask_code", "title": "👨‍💻 برمجة"},
            ],
            header_text="❓ اسأل سؤال",
        )

    # ══════════════════════════════════════
    # LEARN & ROADMAP
    # ══════════════════════════════════════

    elif command == "learn":
        await _send_interactive_list(
            wa_id,
            body_text="📚 *تعلم أي موضوع*\n\nاختار الموضوع اللي عايز تتعلمه:",
            button_text="اختار موضوع",
            sections=[{
                "title": "📚 مواضيع التعلم",
                "rows": [
                    {"id": "cmd_learn_ai", "title": "🤖 الذكاء الاصطناعي", "description": "تعلم أساسيات AI"},
                    {"id": "cmd_learn_ml", "title": "🧠 تعلم الآلة", "description": "Machine Learning"},
                    {"id": "cmd_learn_dl", "title": "🔬 التعلم العميق", "description": "Deep Learning"},
                    {"id": "cmd_learn_nlp", "title": "💬 معالجة اللغة", "description": "NLP"},
                    {"id": "cmd_learn_llm", "title": "📝 النماذج اللغوية", "description": "LLMs"},
                    {"id": "cmd_learn_python", "title": "🐍 بايثون", "description": "Python programming"},
                    {"id": "cmd_learn_web", "title": "🌐 تطوير الويب", "description": "Web Development"},
                ],
            }],
            header_text="📚 تعلم",
        )

    elif command == "roadmap":
        await _send_interactive_list(
            wa_id,
            body_text="🗺️ *خريطة التعلم*\n\nاختار المجال اللي عايز تشوف خريطته:",
            button_text="اختار خريطة",
            sections=[{
                "title": "🗺️ خرائط التعلم",
                "rows": [
                    {"id": "cmd_roadmap_ai", "title": "🤖 AI", "description": "خريطة الذكاء الاصطناعي"},
                    {"id": "cmd_roadmap_ml", "title": "🧠 ML", "description": "خريطة تعلم الآلة"},
                    {"id": "cmd_roadmap_dl", "title": "🔬 Deep Learning", "description": "خريطة التعلم العميق"},
                    {"id": "cmd_roadmap_nlp", "title": "💬 NLP", "description": "خريطة معالجة اللغة"},
                    {"id": "cmd_roadmap_llm", "title": "📝 LLM", "description": "خريطة النماذج اللغوية"},
                ],
            }],
            header_text="🗺️ خريطة تعلم",
        )

    # ══════════════════════════════════════
    # COMPANY
    # ══════════════════════════════════════

    elif command == "company":
        await _send_interactive_list(
            wa_id,
            body_text="🏢 *أخبار الشركات*\n\nاختار الشركة اللي عايز تعرف آخر أخبارها:",
            button_text="اختار شركة",
            sections=[{
                "title": "🏢 شركات AI",
                "rows": [
                    {"id": "cmd_company_openai", "title": "🏢 OpenAI", "description": "آخر أخبار OpenAI"},
                    {"id": "cmd_company_google", "title": "🏢 Google", "description": "آخر أخبار Google AI"},
                    {"id": "cmd_company_anthropic", "title": "🏢 Anthropic", "description": "آخر أخبار Anthropic"},
                    {"id": "cmd_company_meta", "title": "🏢 Meta", "description": "آخر أخبار Meta AI"},
                    {"id": "cmd_company_xai", "title": "🏢 xAI", "description": "آخر أخبار xAI"},
                    {"id": "cmd_company_nvidia", "title": "🏢 NVIDIA", "description": "آخر أخبار NVIDIA"},
                ],
            }],
            header_text="🏢 شركات",
        )

    # ══════════════════════════════════════
    # CHAT
    # ══════════════════════════════════════

    elif command == "chat":
        await _send_whatsapp_message(wa_id,
            "💬 اكتب أي حاجة وهرد عليك!\n\n"
            "ممكن تسألني أي سؤال أو نتكلم عن أي موضوع 🤖\n\n"
            "نصايح:\n"
            "• اسألني عن أي موضوع\n"
            "• ابعتلي صوت وهحوله لنص\n"
            "• ابعتلي صورة وهحللها\n"
            "• ابعتلي ملف PDF وهحلله")

    # ══════════════════════════════════════
    # ABOUT
    # ══════════════════════════════════════

    elif command == "about":
        try:
            from config import BOT_NAME, BOT_VERSION, CREATOR_INFO
            # If admin asks "who made you?" — special response
            if is_admin:
                about_text = (
                    f"🤖 *{BOT_NAME}* v{BOT_VERSION}\n\n"
                    f"أنت اللي عملتني! 😄🫡\n\n"
                    f"👨‍💻 المطور: *{CREATOR_INFO['name_ar']}* — ده أنت!\n"
                    f"🏢 {CREATOR_INFO['company_ar']}\n\n"
                    f"👑 أنت الأدمن — مفيش أي Limits عليك!\n"
                    f"⭐ Premium مدى الحياة تلقائي\n"
                    f"🔧 كل أوامر الأدمن متاحة ليك"
                )
            else:
                about_text = (
                    f"🤖 *{BOT_NAME}* v{BOT_VERSION}\n\n"
                    f"مساعد ذكي شخصي بيشتغل على واتساب وتليجرام\n\n"
                    f"👨‍💻 المطور: {CREATOR_INFO['name_ar']}\n"
                    f"🏢 الشركة: {CREATOR_INFO['company_ar']}\n"
                    f"📧 {CREATOR_INFO['email']}\n"
                    f"🌐 {CREATOR_INFO['website']}\n\n"
                    f"المميزات:\n"
                    f"💬 محادثة ذكية بالعربي والإنجليزي\n"
                    f"🎤 تحويل الصوت لنص\n"
                    f"👁️ تحليل الصور\n"
                    f"📰 أخبار AI يومية وعاجلة\n"
                    f"🔍 بحث ويب\n"
                    f"📥 تحميل فيديو\n"
                    f"📚 وضع الدراسة\n"
                    f"🧠 ذاكرة ذكية\n"
                    f"🎨 إنشاء وتعديل صور\n"
                    f"📈 ترندات وأخبار شركات"
                )
            await _send_whatsapp_message(wa_id, about_text)
        except Exception:
            await _send_whatsapp_message(wa_id, "🤖 My Bro v9.15 — مساعدك الذكي الشخصي")

    # ══════════════════════════════════════
    # SUBSCRIBE / UNSUBSCRIBE
    # ══════════════════════════════════════

    elif command == "subscribe":
        await _send_interactive_buttons(
            wa_id,
            body_text="📬 *اشتراك الأخبار*\n\nهتبقي مشترك في الأخبار اليومية!\nهنبعتلك أخبار AI على مدار اليوم\n\nاختار:",
            buttons=[
                {"id": "cmd_subscribe_confirm", "title": "✅ اشترك"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ],
            header_text="📬 اشتراك",
        )

    elif command == "unsubscribe":
        await _send_interactive_buttons(
            wa_id,
            body_text="❌ *إلغاء اشتراك الأخبار*\n\nمتأكد إنك عايز تلغي اشتراك الأخبار اليومية؟",
            buttons=[
                {"id": "cmd_unsubscribe_confirm", "title": "❌ إلغاء الاشتراك"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ],
            header_text="❌ إلغاء اشتراك",
        )

    elif command == "subscribe_confirm":
        try:
            from memory import subscribe_user, get_news_time, set_news_time
            subscribe_user(wa_user_id)
            # 🔴 FIX: نتأكد إن news_time = "12:00" (الافتراضي الجديد)
            # لو المستخدم كان عنده "09:00" من الوقت القديم، نحدثه
            current_time = get_news_time(wa_user_id)
            if current_time == "09:00":
                set_news_time(wa_user_id, "12:00")
            await _send_whatsapp_message(wa_id, "✅ تم الاشتراك بنجاح! 🎉\n\n📬 هنبعتلك أخبار AI كل يوم الساعة 12 الظهر (توقيت القاهرة).\n\n⏰ لو عايز تغير الوقت ابعت بصيغة HH:MM\nمثال: 14:30\n\nلو عايز تلغي الاشتراك ابعت: إلغاء")
        except Exception:
            await _send_whatsapp_message(wa_id, "✅ تم الاشتراك بنجاح! 🎉")

    elif command == "skip_subscribe":
        # 🔴 FIX v3: المستخدم ضغط "لا شكراً" على سؤال الاشتراك — نحترم اختياره بس نقوله ممكن يشترك بعدين
        from memory import get_language
        skip_lang = get_language(wa_user_id)
        if skip_lang == "en":
            await _send_whatsapp_message(wa_id, "👍 No problem! You can subscribe anytime by sending: subscribe")
        else:
            await _send_whatsapp_message(wa_id, "👍 مفيش مشكلة! ممكن تشترك أي وقت لو ابعتت: اشترك")

    elif command == "unsubscribe_confirm":
        from memory import get_language
        unsub_lang = get_language(wa_user_id)
        try:
            from memory import unsubscribe_user
            unsubscribe_user(wa_user_id)
            await _send_whatsapp_message(wa_id, t("wa.unsubscribe_success", unsub_lang))
        except Exception:
            await _send_whatsapp_message(wa_id, t("wa.unsubscribe_error", unsub_lang))

    # ══════════════════════════════════════
    # LANGUAGE
    # ══════════════════════════════════════

    elif command == "language":
        await _send_interactive_buttons(
            wa_id,
            body_text="🌐 *اختار اللغة*\n\nاختار اللغة اللي عايز تتكلم بيها معايا:",
            buttons=[
                {"id": "cmd_lang_ar", "title": "🇸🇦 العربية"},
                {"id": "cmd_lang_en", "title": "🇺🇸 English"},
            ],
            header_text="🌐 اللغة",
        )

    elif command == "lang_ar":
        try:
            from memory import set_language
            set_language(wa_user_id, "ar")
            await _send_whatsapp_message(wa_id, "🇸🇦 تم تغيير اللغة للعربية!\n\nمن الآن هرد عليك بالعربي 🤖")
        except Exception:
            await _send_whatsapp_message(wa_id, "🇸🇦 تم تغيير اللغة للعربية!")

    elif command == "lang_en":
        try:
            from memory import set_language
            set_language(wa_user_id, "en")
            await _send_whatsapp_message(wa_id, "🇺🇸 Language changed to English!\n\nI'll respond in English from now on 🤖")
        except Exception:
            await _send_whatsapp_message(wa_id, "🇺🇸 Language changed to English!")

    # ══════════════════════════════════════
    # MEMORY
    # ══════════════════════════════════════

    elif command == "memory":
        # Check if free user — memory is premium
        if not is_admin:
            try:
                from premium import can_use_memory
                if not can_use_memory(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        "⭐ الذاكرة الطويلة مميزة Premium بس!\n\n"
                        "🆓 الخطة المجانية:\n"
                        "• 20 رسالة AI/يوم\n"
                        "• ذاكرة قصيرة المدى فقط\n\n"
                        "⭐ Premium:\n"
                        "• رسائل غير محدودة\n"
                        "• ذاكرة طويلة المدى 🧠\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_interactive_buttons(
            wa_id,
            body_text="🧠 *الذاكرة*\n\nأنا بفتكر المحادثات معاك عشان أرد أحسن!\n\nاختار:",
            buttons=[
                {"id": "cmd_memory_view", "title": "👁️ عرض الذاكرة"},
                {"id": "cmd_memory_reset", "title": "🗑️ مسح الذاكرة"},
                {"id": "cmd_favorites", "title": "⭐ المفضلات"},
            ],
            header_text="🧠 الذاكرة",
        )

    elif command == "memory_view":
        try:
            from memory import get_memories, get_user, get_favorites
            from formatters import clean_ai_response
            
            # Get user profile
            user_data = get_user(wa_user_id) or {}
            user_name = user_data.get("name", "")
            
            # Get memories
            memories = get_memories(wa_user_id)
            
            # Get favorites
            favs = get_favorites(wa_user_id)
            
            # Build structured display
            mem_text = "🧠 *الذاكرة*\n━━━━━━━━━━━━━━━━━\n\n"
            
            if user_name:
                mem_text += f"👤 الاسم: {user_name}\n\n"
            
            if memories:
                mem_text += "📝 *الأشياء اللي فاكرها:*\n"
                for key, value in list(memories.items())[:15]:
                    if key.startswith("pdf_context") or key.startswith("_"):
                        continue
                    val_preview = str(value)[:80]
                    mem_text += f"  • {key}: {val_preview}\n"
                mem_text += "\n"
            
            if favs:
                mem_text += "⭐ *المفضلات:*\n"
                for fav in favs[:10]:
                    fav_text = fav.get("content", "")[:60]
                    mem_text += f"  • {fav_text}\n"
                mem_text += "\n"
            
            if not memories and not favs:
                mem_text += "💭 لسه مفيش ذاكرة محفوظة!\n\nكل ما نتكلم أكتر هبدأ أفكر فيك 🧠\n"
            
            await _send_whatsapp_message(wa_id, mem_text)
        except Exception as e:
            logger.error(f"❌ Memory view error: {e}")
            # Fallback to AI-based memory display
            from whatsapp_webhook import _send_ai_response
            await _send_ai_response(wa_id, "ماذا تتذكر عني؟ اذكر الأشياء المهمة التي تعرفها عني",
                wa_user_id, contact_name, message_id, context_type="memory")

    elif command == "memory_reset":
        await _send_interactive_buttons(
            wa_id,
            body_text="🗑️ *مسح الذاكرة*\n\nمتأكد إنك عايز تمسح كل اللي فاكره عنك؟\nده مش هيترجع!",
            buttons=[
                {"id": "cmd_memory_reset_confirm", "title": "🗑️ امسح"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ],
        )

    elif command == "memory_reset_confirm":
        try:
            from memory import reset_all_memories
            reset_all_memories(wa_user_id)
            # Also clear PDF context
            _wa_user_pdf_context.pop(wa_user_id, None)
            # ⚡ مسح الكاش عشان السياق يتحدث
            try:
                from memory_context import invalidate_context_cache
                invalidate_context_cache(wa_user_id)
            except Exception:
                pass
            await _send_whatsapp_message(wa_id, "🗑️ تم مسح كل الذاكرة.\n\nهبدأ أعرفك من الأول!")
        except Exception as e:
            logger.error(f"❌ Memory reset error: {e}")
            await _send_whatsapp_message(wa_id, "🗑️ تم مسح الذاكرة.\n\nهبدأ أعرفك من الأول!")

    elif command == "forget":
        # /forget <keyword> — delete specific memory
        # The keyword comes from the message text
        await _send_whatsapp_message(wa_id, 
            "🗑️ *مسح ذاكرة محددة*\n\n"
            "اكتب الكلمة اللي عايز أمسحها من ذاكرتي\n"
            "مثال: /forget الرياضة\n\n"
            "أو اختار:")
        await _send_interactive_buttons(wa_id, body_text="🗑️ عايز تمسح إيه؟",
            buttons=[
                {"id": "cmd_memory_reset", "title": "🗑️ مسح الكل"},
                {"id": "cmd_memory_view", "title": "👁️ عرض الذاكرة"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ])

    elif command == "favorite":
        try:
            from ai_engine import smart_chat
            from formatters import clean_ai_response
            # Get last conversation topic
            # 🔴 لو المستخدم هو الأدمن، نمرر username=ziadamr
            _fav_is_admin = _is_wa_admin(wa_id)
            ai_response = await smart_chat(
                user_message="ما هو آخر موضوع تحدثنا عنه؟ اذكره باختصار",
                language="ar",
                user_id=wa_user_id,
                username="ziadamr" if _fav_is_admin else (contact_name if contact_name != "Unknown" else None),
            )
            ai_response = clean_ai_response(ai_response)
            topic = _strip_html_for_whatsapp(ai_response)[:100]

            from memory import add_favorite
            add_favorite(wa_user_id, "topic", topic)
            await _send_whatsapp_message(wa_id, f"⭐ تم حفظ في المفضلات!\n\n📝 {topic}")
        except Exception as e:
            logger.error(f"❌ Favorite save error: {e}")
            await _send_whatsapp_message(wa_id, "⭐ تم الحفظ في المفضلات!")

    elif command == "favorites":
        try:
            from memory import get_favorites
            favs = get_favorites(wa_user_id)
            if favs:
                fav_text = "⭐ *المفضلات*\n━━━━━━━━━━━━━━━━━\n\n"
                for fav in favs[:10]:
                    fav_text += f"• {fav.get('title', '')}\n"
                await _send_whatsapp_message(wa_id, fav_text)
            else:
                await _send_whatsapp_message(wa_id, "⭐ معندكش مفضلات لسه.\n\n💡 احفظ أي موضوع باستخدام /favorite")
        except Exception as e:
            logger.error(f"❌ Favorites error: {e}")
            await _send_whatsapp_message(wa_id, "⭐ معندكش مفضلات لسه.")

    # ══════════════════════════════════════
    # PREMIUM / PLAN / USAGE
    # ══════════════════════════════════════

    elif command == "premium":
        try:
            from premium import get_user_plan

            if is_admin:
                await _send_whatsapp_message(wa_id,
                    "👑 *أنت الأدمن*\n\n"
                    "⭐ كل حاجة مفتوحة — مفيش Limits!\n"
                    "كل مزايا Premium متاحة ليك تلقائياً.")
                return True

            plan = get_user_plan(wa_user_id)

            if plan in ("premium", "premium_plus"):
                await _send_whatsapp_message(wa_id,
                    "⭐ *أنت مشترك Premium!*\n\n"
                    "كل المزايا مفتوحة ليك:\n"
                    "💬 رسائل غير محدودة\n"
                    "📄 PDF غير محدود\n"
                    "🖼️ صور غير محدودة + Vision Pro\n"
                    "🎬 يوتيوب غير محدود\n"
                    "🔍 بحث غير محدود\n"
                    "📥 تحميل من أي منصة (YouTube, Insta, TikTok...)\n"
                    "🎬 فيديو بالبحث غير محدود\n"
                    "🎵 صوت بالبحث غير محدود\n"
                    "🖼️ بحث صور غير محدود\n"
                    "🎨 إنشاء وتعديل صور\n"
                    "📚 وضع الدراسة\n"
                    "🧠 ذاكرة طويلة المدى\n"
                    "🤖 نماذج AI أقوى")
                return True

            # Free user — show comparison
            await _send_whatsapp_message(wa_id,
                "🆓 *أنت على الخطة المجانية*\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                "🆓 *المجانية:*\n"
                "• 20 رسالة AI/يوم\n"
                "• 3 تحليلات PDF/يوم\n"
                "• 5 تحليلات صور/يوم\n"
                "• 3 ملخصات يوتيوب/يوم\n"
                "• 5 عمليات بحث/يوم\n"
                "• 3 بحث صور/يوم 🖼️\n\n"
                "⭐ *Premium:*\n"
                "• كل حاجة غير محدودة!\n"
                "• تحميل من أي منصة 📥\n"
                "  (YouTube, Insta, TikTok, FB, Twitter...)\n"
                "• فيديو بالبحث 🎬\n"
                "• صوت بالبحث 🎵\n"
                "• بحث صور غير محدود 🖼️\n"
                "• إنشاء وتعديل صور 🎨🖌️\n"
                "• وضع الدراسة 📚\n"
                "• ذاكرة طويلة المدى 🧠\n"
                "• Vision Pro 👁️\n"
                "• نماذج AI أقوى 🤖\n\n"
                f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
        except Exception as e:
            logger.error(f"❌ Premium command error: {e}")
        return True

    elif command == "plan":
        try:
            from premium import get_user_plan, get_usage, PLAN_LIMITS
            plan = get_user_plan(wa_user_id)
            usage = get_usage(wa_user_id)
            limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

            if is_admin:
                plan_text = (
                    "👑 *خطة الأدمن*\n"
                    "━━━━━━━━━━━━━━━━━\n\n"
                    "⭐ كل حاجة غير محدودة!\n"
                    "💬 رسائل: غير محدود\n"
                    "📄 PDF: غير محدود\n"
                    "🖼️ صور: غير محدود\n"
                    "🎬 يوتيوب: غير محدود\n"
                    "🔍 بحث: غير محدود\n"
                    "🎨 إنشاء صور: مفتوح\n"
                    "🖌️ تعديل صور: مفتوح\n"
                    "📚 وضع الدراسة: مفتوح\n"
                    "🧠 ذاكرة طويلة المدى: مفتوح"
                )
            elif plan in ("premium", "premium_plus"):
                plan_text = (
                    "⭐ *خطة Premium*\n"
                    "━━━━━━━━━━━━━━━━━\n\n"
                    "✅ أنت مشترك Premium!\n\n"
                    "💬 رسائل: غير محدود\n"
                    "📄 PDF: غير محدود\n"
                    "🖼️ صور: غير محدود + Vision Pro\n"
                    "🎬 يوتيوب: غير محدود\n"
                    "🔍 بحث: غير محدود\n"
                    "📥 تحميل من أي منصة: مفتوح\n"
                    "🎬 فيديو بالبحث: مفتوح\n"
                    "🎵 صوت بالبحث: مفتوح\n"
                    "🖼️ بحث صور: مفتوح\n"
                    "🎨 إنشاء صور: مفتوح\n"
                    "🖌️ تعديل صور: مفتوح\n"
                    "📚 وضع الدراسة: مفتوح\n"
                    "🧠 ذاكرة طويلة المدى: مفتوح\n"
                    "🤖 نماذج AI أقوى: مفتوح"
                )
            else:
                # Free plan — show usage with limits
                ai_rem = max(0, limits["ai_messages_per_day"] - usage.get("ai_messages", 0))
                pdf_rem = max(0, limits["pdf_analyses_per_day"] - usage.get("pdf_analyses", 0))
                img_rem = max(0, limits["image_analyses_per_day"] - usage.get("image_analyses", 0))
                yt_rem = max(0, limits["youtube_summaries_per_day"] - usage.get("youtube_summaries", 0))
                search_rem = max(0, limits["searches_per_day"] - usage.get("searches", 0))
                photo_rem = max(0, limits.get("photo_searches_per_day", 3) - usage.get("photo_searches", 0))

                ai_used = usage.get("ai_messages", 0)
                pdf_used = usage.get("pdf_analyses", 0)
                img_used = usage.get("image_analyses", 0)
                yt_used = usage.get("youtube_summaries", 0)
                search_used = usage.get("searches", 0)
                photo_used = usage.get("photo_searches", 0)

                plan_text = (
                    "🆓 *الخطة المجانية*\n"
                    "━━━━━━━━━━━━━━━━━\n\n"
                    f"💬 رسائل: {ai_used}/{limits['ai_messages_per_day']} (متبقي {ai_rem})\n"
                    f"📄 PDF: {pdf_used}/{limits['pdf_analyses_per_day']} (متبقي {pdf_rem})\n"
                    f"🖼️ تحليل صور: {img_used}/{limits['image_analyses_per_day']} (متبقي {img_rem})\n"
                    f"🎬 يوتيوب: {yt_used}/{limits['youtube_summaries_per_day']} (متبقي {yt_rem})\n"
                    f"🔍 بحث: {search_used}/{limits['searches_per_day']} (متبقي {search_rem})\n"
                    f"🖼️ بحث صور: {photo_used}/{limits.get('photo_searches_per_day', 3)} (متبقي {photo_rem})\n\n"
                    "📥 تحميل فيديو: ❌ بريميوم\n"
                    "🎬 فيديو بالبحث: ❌ بريميوم\n"
                    "🎵 صوت بالبحث: ❌ بريميوم\n"
                    "🎨 إنشاء صور: ❌ بريميوم\n"
                    "🖌️ تعديل صور: ❌ بريميوم\n"
                    "📚 وضع الدراسة: ❌ بريميوم\n"
                    "🧠 ذاكرة طويلة: ❌ بريميوم\n\n"
                    "💡 الحدود بتتجدد كل يوم الساعة 12:00 منتصف الليل\n\n"
                    "⭐ ترقية لـ Premium عشان استخدام غير محدود!\n"
                    f"📩 تواصل مع المطور:\n📱 {DEVELOPER_WHATSAPP_URL}"
                )

            await _send_whatsapp_message(wa_id, plan_text)
        except Exception as e:
            logger.error(f"❌ Plan command error: {e}")
            await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في عرض الخطة.")

    # ══════════════════════════════════════
    # SETTINGS
    # ══════════════════════════════════════

    elif command == "settings":
        await _send_interactive_list(
            wa_id,
            body_text="⚙️ *الإعدادات*\n\nاختار اللي عايز تغيره:",
            button_text="الإعدادات",
            sections=[{
                "title": "⚙️ الإعدادات",
                "rows": [
                    {"id": "cmd_language", "title": "🌐 اللغة", "description": "عربي أو English"},
                    {"id": "cmd_subscribe", "title": "📬 اشتراك الأخبار", "description": "أخبار يومية"},
                    {"id": "cmd_premium", "title": "⭐ Premium", "description": "خطة ومزايا"},
                    {"id": "cmd_plan", "title": "📋 حدود الاستخدام", "description": "شوف استخدامك"},
                    {"id": "cmd_memory", "title": "🧠 الذاكرة", "description": "عرض ومسح الذاكرة"},
                ],
            }],
            header_text="⚙️ الإعدادات",
        )

    # ══════════════════════════════════════
    # DOWNLOAD
    # ══════════════════════════════════════

    elif command == "download":
        await _send_whatsapp_message(wa_id,
            "📥 *تحميل فيديو*\n\n"
            "ابعتلي رابط الفيديو وهحاول أحملهلك!\n\n"
            "مثال:\n"
            "/download https://youtube.com/watch?v=...\n"
            "أو ابعت الرابط مباشرة وهفهم\n\n"
            "💡 ممكن تحميل من:\n"
            "• YouTube\n"
            "• Twitter/X\n"
            "• Instagram\n"
            "• TikTok")

    elif command == "download_yt":
        # 🍪 تحميل فيديو YouTube اللي اتلخص ده — بنستخدم الرابط المخزّن
        from whatsapp.media import _download_and_send_video
        cached_url = _wa_user_yt_url.get(wa_id, "")
        if cached_url:
            await _download_and_send_video(wa_id, cached_url, wa_user_id, contact_name, message_id, is_admin)
        else:
            await _send_whatsapp_message(wa_id, "❌ مش قادر ألاقي رابط الفيديو. جرب /download مع الرابط مباشرة.")

    # ══════════════════════════════════════
    # VIDEO SEARCH / AUDIO SEARCH / PHOTO SEARCH
    # ══════════════════════════════════════

    elif command == "video_search":
        # 🔴 فحص Premium — فيديو بالبحث مميزة بريميوم بس
        if not is_admin:
            try:
                from premium import get_user_plan, PLAN_LIMITS
                plan = get_user_plan(wa_user_id)
                if plan not in ("premium", "premium_plus"):
                    await _send_whatsapp_message(wa_id,
                        f"🎬 فيديو بالبحث مميزة Premium بس!\n\n"
                        f"📥 تحميل من أي منصة 📥\n"
                        f"🎬 فيديو بالبحث\n"
                        f"🎵 صوت بالبحث\n"
                        f"🎨 إنشاء وتعديل صور 🎨🖌️\n"
                        f"📚 وضع الدراسة\n"
                        f"🧠 ذاكرة طويلة المدى\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "video_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🎬 *تحميل فيديو بالبحث*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك النتائج!\n\n"
            "مثال: قرآن ماهر المعيقلي\n\n"
            "💡 أو استخدم: /video كلمات البحث")
        return True

    elif command == "audio_search":
        # 🔴 فحص Premium — صوت بالبحث مميزة بريميوم بس
        if not is_admin:
            try:
                from premium import get_user_plan
                plan = get_user_plan(wa_user_id)
                if plan not in ("premium", "premium_plus"):
                    await _send_whatsapp_message(wa_id,
                        f"🎵 صوت بالبحث مميزة Premium بس!\n\n"
                        f"📥 تحميل من أي منصة 📥\n"
                        f"🎬 فيديو بالبحث\n"
                        f"🎵 صوت بالبحث\n"
                        f"🎨 إنشاء وتعديل صور 🎨🖌️\n"
                        f"📚 وضع الدراسة\n"
                        f"🧠 ذاكرة طويلة المدى\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "audio_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🎵 *تحميل صوت بالبحث*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك النتائج!\n\n"
            "مثال: قرآن عبد الباسط\n\n"
            "💡 أو استخدم: /audio كلمات البحث")
        return True

    elif command == "photo_search":
        # 🔴 فحص Premium — بحث صور (مجاني 3/يوم، بريميوم غير محدود)
        if not is_admin:
            try:
                from premium import get_user_plan, check_limit, increment_usage
                plan = get_user_plan(wa_user_id)
                if plan not in ("premium", "premium_plus"):
                    can_search, _ = check_limit(wa_user_id, "photo_searches_per_day")
                    if not can_search:
                        await _send_whatsapp_message(wa_id,
                            "🖼️ وصلت حد بحث الصور اليوم (3/يوم)\n\n"
                            "⭐ Premium: بحث صور غير محدود!\n\n"
                            f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                        return True
            except Exception:
                pass

        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "photo_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🖼️ *بحث عن صور*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك صور!\n\n"
            "مثال: المسجد الأقصى\n\n"
            "💡 أو استخدم: /photo كلمات البحث")
        return True

    # ══════════════════════════════════════
    # EXIT (الخروج من وضع الدراسة أو أي workflow)
    # ══════════════════════════════════════

    elif command == "exit":
        workflow_cleared = False
        try:
            from workflow_manager import get_workflow, clear_workflow
            workflow = get_workflow(wa_user_id)
            if workflow:
                clear_workflow(wa_user_id)
                workflow_cleared = True
        except Exception:
            pass
        # مسح user_states القديم
        if wa_user_id in _wa_user_state:
            _wa_user_state.pop(wa_user_id, None)
            workflow_cleared = True
        if workflow_cleared:
            await _send_whatsapp_message(wa_id, "✅ خرجت من الوضع النشط. اكتب أي حاجة وهرد عليك عادي! 🤖")
        else:
            await _send_whatsapp_message(wa_id, "ℹ️ مش في أي وضع نشط دلوقتي. اكتب أي حاجة وهرد عليك! 🤖")
        return True

    # ══════════════════════════════════════
    # STUDY MODE
    # ══════════════════════════════════════

    elif command == "study":
        # Check premium for study mode
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        f"⭐ وضع الدراسة مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_interactive_list(
            wa_id,
            body_text="📚 *وضع الدراسة*\n\nاختار اللي عايزه:",
            button_text="وضع الدراسة",
            sections=[{
                "title": "📚 وضع الدراسة",
                "rows": [
                    {"id": "cmd_study_learn", "title": "📚 ادرس موضوع", "description": "شرح مفصل مع أمثلة"},
                    {"id": "cmd_study_quiz", "title": "📝 كويز", "description": "اختبر نفسك"},
                    {"id": "cmd_study_exam", "title": "📋 امتحان", "description": "امتحان شامل"},
                    {"id": "cmd_study_notes", "title": "📒 ملاحظات مراجعة", "description": "ملخص للمراجعة"},
                    {"id": "cmd_study_flash", "title": "🃏 كروت ذاكرة", "description": "Flashcards"},
                ],
            }],
            header_text="📚 وضع الدراسة",
        )

    elif command == "quiz":
        # Check premium
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, "⭐ الكويز مميزة Premium بس!")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            "📝 *كويز*\n\nاكتب الموضوع اللي عايز تتested فيه\n\nمثال:\n/quiz Python\n/quiz الذكاء الاصطناعي")

    elif command == "exam":
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, "⭐ الامتحان مميز Premium بس!")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            "📋 *امتحان*\n\nاكتب الموضوع اللي عايز تمتحن فيه\n\nمثال:\n/exam Machine Learning\n/exam JavaScript")

    # ══════════════════════════════════════
    # YOUTUBE SUMMARY
    # ══════════════════════════════════════

    elif command == "youtube":
        await _send_whatsapp_message(wa_id,
            "🎬 *ملخص يوتيوب*\n\nابعتلي رابط فيديو يوتيوب وهلخصلك محتواه!\n\nمثال:\n/youtube https://youtube.com/watch?v=...")

    # ══════════════════════════════════════
    # COOKIES
    # ══════════════════════════════════════

    elif command == "cookies":
        # 🍪 أمر الكوكيز — كل المستخدمين يقدروا يرفعوا كوكيز
        if is_admin:
            # الأدمن يشوف التفاصيل الكاملة
            cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            if os.path.exists(cookies_file):
                try:
                    size = os.path.getsize(cookies_file)
                    with open(cookies_file, 'r') as f:
                        lines = f.readlines()
                    cookie_lines = [l for l in lines if l.strip() and not l.strip().startswith('#')]
                    yt_cookies = [l for l in cookie_lines if 'youtube.com' in l.lower()]
                    msg = (
                        f"🍪 *حالة ملف الكوكيز*\n\n"
                        f"📊 الحجم: {size} bytes\n"
                        f"🔢 عدد الكوكيز: {len(cookie_lines)}\n"
                        f"▶️ كوكيز YouTube: {len(yt_cookies)}\n"
                        f"🔴 لا كوكيز تلقائية — بس كوكيز مرفوعة من المستخدمين\n\n"
                        f"✅ الملف موجود وشغال!\n\n"
                        f"💡 لرفع ملف جديد: ابعت ملف cookies.txt كـ document مع كتابة *cookies* في الرسالة\n"
                        f"🗑️ لمسح الملف: /cookies delete"
                    )
                except Exception as e:
                    msg = f"🍪 ❌ خطأ في قراءة الملف: {e}"
            else:
                msg = (
                    "🍪 *ملف الكوكيز مش موجود*\n\n"
                    "⚠️ بدون ملف كوكيز، YouTube ممكن يمنع التحميل.\n"
                    "🔴 مفيش كوكيز تلقائية — بس كوكيز مرفوعة من المستخدمين!\n\n"
                    "💡 ابعت ملف cookies.txt كـ document مع كتابة *cookies* في الرسالة\n\n"
                    "إزاي تجيب الملف:\n"
                    "1️⃣ افتح Chrome على الكمبيوتر\n"
                    "2️⃣ ثبّت إضافة Get cookies.txt LOCALLY\n"
                    "3️⃣ افتح youtube.com واعمل login\n"
                    "4️⃣ اضغط على الإضافة واختار Export\n"
                    "5️⃣ ابعت الملف هنا مع كتابة cookies في الرسالة"
                )
        else:
            # المستخدم العادي — رسالة بسيطة
            msg = (
                "🍪 *ارفع ملف الكوكيز بتاعك*\n\n"
                "ابعت ملف cookies.txt من جهازك وهنسخه للبوت عشان نساعد في تحميل الفيديوهات.\n\n"
                "💡 إزاي تجيب الملف:\n"
                "1️⃣ افتح Chrome على الكمبيوتر\n"
                "2️⃣ ثبّت إضافة Get cookies.txt LOCALLY\n"
                "3️⃣ افتح youtube.com واعمل login\n"
                "4️⃣ اضغط على الإضافة واختار Export\n"
                "5️⃣ ابعت الملف هنا كـ document مع كتابة *cookies* في الرسالة"
            )
        await _send_whatsapp_message(wa_id, msg)

    # ══════════════════════════════════════
    # PDF
    # ══════════════════════════════════════

    elif command == "pdf":
        await _send_whatsapp_message(wa_id,
            "📄 *تحليل PDF*\n\nابعتلي ملف PDF (Document) وهحللهلك!\n\n"
            "ممكن أساعدك في:\n"
            "• تلخيص المحتوى\n"
            "• استخراج النقاط الرئيسية\n"
            "• كويز على المحتوى\n"
            "• ملاحظات دراسية\n\n"
            "💡 ابعت الملف مباشرة هنا")

    elif command == "pdf_keypoints":
        # Extract key points from stored PDF context
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
        
        if not pdf_ctx:
            await _send_whatsapp_message(wa_id, "📄 مفيش ملف محفوظ. ابعت ملف PDF الأول!")
            return True
        
        from agents.pdf_agent import PDFAgent
        pdf_agent = PDFAgent()
        try:
            result = await asyncio.wait_for(
                pdf_agent.key_points(pdf_ctx["text"][:30000], "ar", user_id=wa_user_id),
                timeout=120.0
            )
            from formatters import clean_ai_response
            result = clean_ai_response(result)
            if result:
                response_text = _strip_html_for_whatsapp(result)
                chunks = _split_whatsapp_message(response_text)
                for chunk in chunks:
                    await _send_whatsapp_message(wa_id, chunk)
                
                await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية مع الملف؟",
                    buttons=[
                        {"id": "cmd_study", "title": "📚 ادرسه"},
                        {"id": "cmd_chat", "title": "💬 اسأل سؤال"},
                        {"id": "cmd_commands", "title": "📋 الأوامر"},
                    ])
            else:
                await _send_whatsapp_message(wa_id, "⚠️ مش قادر أستخرج النقاط. جرب تاني!")
        except Exception as e:
            logger.error(f"❌ PDF key points error: {e}")
            await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ. جرب تاني!")
        return True

    elif command == "pdf_ask":
        await _send_whatsapp_message(wa_id, 
            "💬 *اسأل عن الملف*\n\n"
            "اكتب سؤالك عن الملف وانا هجاوبك!\n"
            "مثال: ايه أهم النتائج في الملف ده؟")
        return True

    # ══════════════════════════════════════
    # IMAGE GENERATION (Premium)
    # ══════════════════════════════════════

    elif command == "image_gen":
        if not is_admin:
            try:
                from premium import can_use_image_gen
                if not can_use_image_gen(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        "🎨 إنشاء الصور مميزة Premium بس!\n\n"
                        "⭐ Premium:\n"
                        "• إنشاء صور غير محدود 🎨\n"
                        "• تعديل صور 🖌️\n"
                        "• Vision Pro 👁️\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                # If premium check fails, allow for now
                pass

        await _send_whatsapp_message(wa_id,
            "🎨 *إنشاء صورة*\n\nاكتب وصف الصورة اللي عايزها!\n\n"
            "مثال:\n"
            "/image مسجد جميل عند الغروب\n"
            "/image sunset over mosque\n\n"
            "💡 كل ما الوصف يكون أدق، الصورة تكون أحسن!")

    # ══════════════════════════════════════
    # IMAGE EDITING (Premium)
    # ══════════════════════════════════════

    elif command == "image_edit":
        if not is_admin:
            try:
                from premium import can_use_image_edit
                if not can_use_image_edit(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        f"🖌️ تعديل الصور مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            "🖌️ *تعديل صورة*\n\n"
            "1️⃣ ابعت الصورة اللي عايز تعدلها\n"
            "2️⃣ اكتب التعديل المطلوب في الـ Caption\n\n"
            "مثال: ابعت صورة واكتب في الـ Caption:\n"
            "خلي الخلفية زرقاء زي السماء")

    # ══════════════════════════════════════
    # ADMIN BUTTON HANDLER
    # ══════════════════════════════════════

    elif command == "admin_button":
        if is_admin:
            await _handle_command(wa_id, "admin", wa_user_id, contact_name, message_id)
        else:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
        return True

    # ── Dynamic AI-powered sub-commands ──
    elif command.startswith("search_") or command in ("cmd_search_ai", "cmd_search_code"):
        from whatsapp_webhook import _send_ai_response
        search_queries = {
            "cmd_search_ai": "أحدث تطورات الذكاء الاصطناعي",
            "cmd_search_code": "أحدث تقنيات البرمجة وتطوير البرمجيات",
        }
        query = search_queries.get(command, "أحدث التطورات التقنية")
        await _send_ai_response(wa_id, f"ابحث لي عن: {query}",
            wa_user_id, contact_name, message_id, context_type="search", increment_feature="searches")

    elif command.startswith("ask_") or command in ("cmd_ask_ai", "cmd_ask_code"):
        from whatsapp_webhook import _send_ai_response
        questions = {
            "cmd_ask_ai": "اشرح لي الذكاء الاصطناعي بشكل مبسط مع أمثلة عملية",
            "cmd_ask_code": "ما أهم لغات البرمجة للمبتدئين وكيف أبدأ؟",
        }
        question = questions.get(command, "اشرح لي بالتفصيل")
        await _send_ai_response(wa_id, question,
            wa_user_id, contact_name, message_id, context_type="general")

    elif command.startswith("learn_") or command.startswith("cmd_learn_"):
        from whatsapp_webhook import _send_ai_response
        topic_map = {
            "cmd_learn_ai": "الذكاء الاصطناعي",
            "cmd_learn_ml": "تعلم الآلة Machine Learning",
            "cmd_learn_dl": "التعلم العميق Deep Learning",
            "cmd_learn_nlp": "معالجة اللغة الطبيعية NLP",
            "cmd_learn_llm": "النماذج اللغوية الكبيرة LLMs",
            "cmd_learn_python": "برمجة بايثون Python",
            "cmd_learn_web": "تطوير الويب Web Development",
        }
        topic = topic_map.get(command, "الذكاء الاصطناعي")
        await _send_ai_response(wa_id,
            f"علمني عن {topic} من الصفر للمحترف. ابدأ بالأساسيات وشرح مبسط مع أمثلة عملية",
            wa_user_id, contact_name, message_id, context_type="learn")

    elif command.startswith("roadmap_") or command.startswith("cmd_roadmap_"):
        from whatsapp_webhook import _send_ai_response
        roadmap_map = {
            "cmd_roadmap_ai": "الذكاء الاصطناعي AI",
            "cmd_roadmap_ml": "تعلم الآلة Machine Learning",
            "cmd_roadmap_dl": "التعلم العميق Deep Learning",
            "cmd_roadmap_nlp": "معالجة اللغة الطبيعية NLP",
            "cmd_roadmap_llm": "النماذج اللغوية الكبيرة LLMs",
        }
        topic = roadmap_map.get(command, "الذكاء الاصطناعي")
        await _send_ai_response(wa_id,
            f"ارسم لي خريطة طريق تعلم {topic} من الصفر للمحترف. قسمها لمراحل (مبتدئ - متوسط - متقدم) مع المصادر والخطوات العملية",
            wa_user_id, contact_name, message_id, context_type="learn")

    elif command.startswith("company_") or command.startswith("cmd_company_"):
        from whatsapp_webhook import _send_ai_response
        company_map = {
            "cmd_company_openai": "OpenAI",
            "cmd_company_google": "Google AI",
            "cmd_company_anthropic": "Anthropic",
            "cmd_company_meta": "Meta AI",
            "cmd_company_xai": "xAI",
            "cmd_company_nvidia": "NVIDIA",
        }
        company = company_map.get(command, "AI")
        await _send_ai_response(wa_id,
            f"ما هي آخر أخبار وتطورات شركة {company}؟ اذكر أهم المنتجات والاعلانات والمشاريع",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command.startswith("study_") or command.startswith("cmd_study_"):
        study_map = {
            "cmd_study_learn": "علمني",
            "cmd_study_quiz": "اعملني كويز",
            "cmd_study_exam": "اعملني امتحان شامل",
            "cmd_study_notes": "اعملني ملاحظات مراجعة مختصرة",
            "cmd_study_flash": "اعملني كروت ذاكرة Flashcards",
        }
        study_action = study_map.get(command, "علمني")
        # Check premium
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, f"⭐ وضع الدراسة مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            f"📚 {study_action}\n\nاكتب الموضوع اللي عايز {study_action} فيه\n\nمثال: {study_action} الفقه الإسلامي")

    else:
        return False  # Not a command

    return True  # Command was handled


# ═══════════════════════════════════════
# Commands with Arguments
# ═══════════════════════════════════════

async def _handle_command_with_arg(wa_id: str, cmd_name: str, arg: str, wa_user_id: int,
                                   contact_name: str, message_id: str, is_admin: bool):
    """Handle commands that have arguments (e.g., /download URL, /study topic)"""

    if cmd_name == "download":
        # Download video — REAL download using yt-dlp (like Telegram)
        # Check if the argument is a URL
        url = arg.strip()
        if not _extract_url(url):
            # Not a URL — ask AI for help
            from whatsapp_webhook import _send_ai_response
            await _send_ai_response(wa_id,
                f"المستخدم عايز يحمل حاجة: {arg}\n\nلو ده رابط فيديو، قدم المساعدة. لو مش رابط، اشرح له ازاي يستخدم أمر التحميل مع رابط صحيح.",
                wa_user_id, contact_name, message_id, context_type="download")
        else:
            # It's a URL — actually download it!
            from whatsapp.media import _download_and_send_video
            await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "image_gen":
        # Image generation (Premium) — REAL image generation (like Telegram)
        if not is_admin:
            try:
                from premium import can_use_image_gen
                if not can_use_image_gen(wa_user_id):
                    await _send_whatsapp_message(wa_id, f"🎨 إنشاء الصور مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return
            except Exception:
                pass

        # Actually generate and send the image
        from whatsapp.media import _generate_and_send_image
        await _generate_and_send_image(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "cookies":
        # 🍪 /cookies delete — أدمن بس
        if is_admin and arg.lower() in ("delete", "remove", "مسح", "حذف"):
            cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            try:
                if os.path.exists(cookies_file):
                    os.remove(cookies_file)
                    await _send_whatsapp_message(wa_id, "✅ تم حذف ملف الكوكيز.")
                    logger.info(f"🍪 WA Cookies file deleted by admin {wa_id}")
                else:
                    await _send_whatsapp_message(wa_id, "❌ ملف الكوكيز مش موجود أصلاً.")
            except Exception as e:
                await _send_whatsapp_message(wa_id, f"❌ فشل الحذف: {e}")
        elif not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
        else:
            await _handle_command(wa_id, "cookies", wa_user_id, contact_name, message_id)

    elif cmd_name == "image_edit":
        if not is_admin:
            try:
                from premium import can_use_image_edit
                if not can_use_image_edit(wa_user_id):
                    await _send_whatsapp_message(wa_id, "🖌️ تعديل الصور مميزة Premium بس!")
                    return
            except Exception:
                pass

        # Check if user has a cached image
        cached_img = _wa_user_edit_images.get(wa_user_id)
        if cached_img and cached_img.get("image_base64"):
            # User has a cached image — edit it with the prompt
            from whatsapp.media import _edit_and_send_image
            await _edit_and_send_image(wa_id, arg, cached_img["image_base64"], wa_user_id, contact_name, message_id, is_admin)
        else:
            await _send_whatsapp_message(wa_id,
                "🖌️ عايز تعدّل صورة؟\n\n1️⃣ ابعت الصورة اللي عايز تعدلها\n2️⃣ بعد ما تبعتها، اكتب التعديل\n\n"
                "📝 أمثلة:\n→ /edit غيّر الخلفية لمسجد\n→ /edit خلي الصورة زي لوحة إسلامية")

    elif cmd_name == "youtube":
        # YouTube summary — REAL YouTubeAgent (same as Telegram)
        from agents.youtube_agent import YouTubeAgent
        yt_agent = YouTubeAgent()
        
        # Start thinking feedback
        feedback = ThinkingFeedback(wa_id, message_id, context_type="youtube")
        await feedback.start()
        
        try:
            summary = await yt_agent.summarize_video(arg, language="ar", user_id=wa_user_id)
            if summary:
                _wa_user_yt_url[wa_id] = arg  # 🍪 خزّن رابط YouTube عشان زر التحميل
                summary_text = _strip_html_for_whatsapp(summary)
                chunks = _split_whatsapp_message(summary_text)
                for chunk in chunks:
                    await _send_whatsapp_message(wa_id, chunk)
                
                # Increment usage
                if not is_admin:
                    try:
                        from premium import increment_usage
                        increment_usage(wa_user_id, "youtube_summaries")
                    except Exception:
                        pass
                
                await feedback.complete()
                
                # Quick action buttons
                await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                    buttons=[
                        {"id": "cmd_youtube", "title": "🎬 فيديو تاني"},
                        {"id": "cmd_download_yt", "title": "📥 حمّله"},
                        {"id": "cmd_chat", "title": "💬 محادثة"},
                    ])
            else:
                await _send_whatsapp_message(wa_id, "❌ مش قادر ألخص الفيديو ده. جرب رابط تاني! 🎬")
                await feedback.error()
        except Exception as e:
            logger.error(f"❌ YouTube summary error: {e}", exc_info=True)
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في تلخيص الفيديو. جرب تاني! 🎬")
            await feedback.error()

    elif cmd_name in ("quiz", "exam", "study"):
        # Study mode
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, f"⭐ وضع الدراسة مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return
            except Exception:
                pass

        if cmd_name == "quiz":
            prompt = f"اعمل كويز في موضوع: {arg}. اسأل 5 أسئلة اختيار متعدد مع الخيارات وانتظر الإجابة قبل ما تدي الحل."
        elif cmd_name == "exam":
            prompt = f"اعمل امتحان شامل في: {arg}. اسأل 10 أسئلة متنوعة (اختيار متعدد، صح وغلط، أكمل) وانتظر الإجابة قبل التصحيح."
        else:
            prompt = f"علمني عن {arg} من الصفر للمحترف. ابدأ بالأساسيات وشرح مبسط مع أمثلة عملية."

        from whatsapp_webhook import _send_ai_response
        await _send_ai_response(wa_id, prompt,
            wa_user_id, contact_name, message_id, context_type="study")

    elif cmd_name == "search":
        from whatsapp_webhook import _send_ai_response
        await _send_ai_response(wa_id, f"ابحث لي عن: {arg}",
            wa_user_id, contact_name, message_id, context_type="search",
            increment_feature="searches")

    # ══════════════════════════════════════
    # VIDEO SEARCH / AUDIO SEARCH / PHOTO SEARCH (with args)
    # ══════════════════════════════════════

    elif cmd_name == "video_search_query":
        # /video <query> — بحث Dailymotion + عرض نتائج + تحميل فيديو
        from whatsapp_webhook import _handle_wa_video_search
        await _handle_wa_video_search(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "audio_search_query":
        # /audio <query> — بحث SoundCloud + عرض نتائج + تحميل صوت
        from whatsapp_webhook import _handle_wa_audio_search
        await _handle_wa_audio_search(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "photo_search_query":
        # /photo <query> — بحث صور
        from whatsapp_webhook import _handle_wa_photo_search
        await _handle_wa_photo_search(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)


async def _wa_download_youtube(wa_id: str, url: str, wa_user_id: int,
                                 contact_name: str, message_id: str, is_admin: bool,
                                 format: str = "720"):
    """تحميل فيديو/صوت YouTube عبر yt-dlp مباشرة للواتساب
    
    format: "720" لفيديو 720p, "mp3" لصوت, الخ
    """
    # تحويل الفورمات لجودة yt-dlp
    is_audio = (format == "mp3")
    quality_map = {"1080": "best", "720": "medium", "360": "low", "mp3": "audio"}
    yt_quality = quality_map.get(format, "medium")
    
    logger.info(f"🎬 WA YouTube download: format={format} → yt_quality={yt_quality} for {url[:80]}")
    from whatsapp.media import _download_and_send_video
    await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=yt_quality, force_audio=is_audio)


def _cleanup_wa_file(file_path: str):
    """حذف ملف مؤقت"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
