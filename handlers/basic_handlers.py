"""
Basic command handlers: start, help, about, status, premium, plan, dashboard.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import BOT_NAME, BOT_VERSION
from memory import get_language, increment_command_count
from formatters import welcome_message, help_message, about_message
from premium import (
    get_user_plan, get_premium_keyboard,
    premium_features_message,
)
from admin import is_admin, ensure_admin_premium
from dashboard import track_event, format_dashboard

from handlers.keyboards import (
    get_main_keyboard, get_subscribe_keyboard,
)
from handlers.dedup import _is_duplicate_update, _is_duplicate_user_message

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start - شاشة ترحيب احترافية مع تفرقة بين جديد وقديم"""
    from memory import update_user, is_new_user, get_language, is_subscribed, increment_command_count
    from formatters import subscription_prompt

    if await _is_duplicate_update(update.update_id):
        return

    user_id = update.effective_user.id
    if await _is_duplicate_user_message(user_id, "/start"):
        return

    user_name = update.effective_user.first_name or "صديقي"

    # ═══ Bug Fix: Check if user is new BEFORE calling update_user ═══
    new_user = is_new_user(user_id)

    lang = get_language(user_id)
    update_user(user_id, {"name": user_name})

    increment_command_count(user_id)

    # Dashboard tracking
    try:
        track_event("total_commands")
        track_event("total_messages")
        if new_user:
            track_event("new_users")
    except Exception:
        pass

    keyboard = get_main_keyboard(lang)

    # ═══ Auto-grant Premium for Admin (@ziadamr) ═══
    if is_admin(user_id, update.effective_user.username):
        ensure_admin_premium(user_id)

    # ═══ فحص الكوتا — لو المستخدم المجاني خلص حد الرسائل ═══
    from premium import check_limit as _check_quota, get_user_plan as _get_plan
    user_plan = _get_plan(user_id)
    quota_msg = ""
    if user_plan == "free" and not is_admin(user_id, update.effective_user.username):
        quota_check = _check_quota(user_id, "ai_messages_per_day", update.effective_user.username)
        if not quota_check["allowed"]:
            from premium import limit_reached_message, get_premium_keyboard
            feature_name = "💬 رسائل AI" if lang == "ar" else "💬 AI Messages"
            quota_msg = "\n\n⚠️ " + (f"خلصت حد الرسائل اليوم ({quota_check['limit']} رسالة). هيرجع بكرة!" if lang == "ar" else f"You've reached the daily message limit ({quota_check['limit']} messages). Resets tomorrow!")

    if new_user:
        await update.message.reply_text(
            welcome_message(lang, user_name),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )

        if not is_subscribed(user_id):
            import asyncio
            await asyncio.sleep(1.5)
            sub_keyboard = get_subscribe_keyboard(lang)
            await update.message.reply_text(
                subscription_prompt(lang),
                parse_mode="HTML",
                reply_markup=sub_keyboard
            )
    else:
        from premium import get_user_plan
        subscribed = is_subscribed(user_id)
        plan = get_user_plan(user_id)
        is_user_admin = is_admin(user_id, update.effective_user.username)

        if lang == "ar":
            msg = f"أهلاً تاني يا {user_name}! 👋\n\nأنا فاكرك طبعاً — اختار اللي عايزه من الأزرار أو اكتبلي أي حاجة! 🤖"
            if is_user_admin:
                msg += "\n👑 <i>أنت الأدمن — كل حاجة مفتوحة ليك!</i>"
            if not subscribed:
                msg += "\n\n💡 <i>ممكن تشترك في الأخبار اليومية من ⚙️ الإعدادات</i>"
            if plan == "premium" and not is_user_admin:
                msg += "\n⭐ <i>أنت مشترك Premium — استمتع بكل المزايا!</i>"
            if quota_msg:
                msg += quota_msg
        else:
            msg = f"Welcome back {user_name}! 👋\n\nI remember you — choose from the buttons or just type anything! 🤖"
            if is_user_admin:
                msg += "\n👑 <i>You're the admin — everything is open for you!</i>"
            if not subscribed:
                msg += "\n\n💡 <i>You can subscribe to daily news from ⚙️ Settings</i>"
            if plan == "premium" and not is_user_admin:
                msg += "\n⭐ <i>You're a Premium subscriber — enjoy all features!</i>"
            if quota_msg:
                msg += quota_msg

        await update.message.reply_text(
            msg,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /help"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        track_event("total_commands")
    except Exception:
        pass

    await update.message.reply_text(
        help_message(lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /about - عن البوت والمؤسس"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    await update.message.reply_text(
        about_message(lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /status - حالة المزودين"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        from provider_manager import get_provider_manager
        manager = get_provider_manager()

        status = manager.get_status()
        chat_routes = manager.get_available_routes("chat")
        simple_routes = manager.get_available_routes("simple")
        coding_routes = manager.get_available_routes("coding")

        if lang == "ar":
            message = f"""🔧 <b>حالة المزودين - {BOT_NAME} v{BOT_VERSION}</b>
━━━━━━━━━━━━━━━━━

📡 <b>المزودين:</b>
{status}

🧠 <b>مسارات المحادثة:</b>
{chat_routes}

⚡ <b>مسارات سريعة:</b>
{simple_routes}

👨‍💻 <b>مسارات البرمجة:</b>
{coding_routes}

━━━━━━━━━━━━━━━━━
🤖 <i>النظام يبدل تلقائياً بين المزودين عند الفشل</i>"""
        else:
            message = f"""🔧 <b>Provider Status - {BOT_NAME} v{BOT_VERSION}</b>
━━━━━━━━━━━━━━━━━

📡 <b>Providers:</b>
{status}

🧠 <b>Chat Routes:</b>
{chat_routes}

⚡ <b>Fast Routes:</b>
{simple_routes}

👨‍💻 <b>Coding Routes:</b>
{coding_routes}

━━━━━━━━━━━━━━━━━
🤖 <i>System automatically switches providers on failure</i>"""

    except Exception as e:
        logger.error(f"Error in /status: {e}")
        message = "❌ حصل خطأ" if lang == "ar" else "❌ Error occurred"

    await update.message.reply_text(message, parse_mode="HTML")


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /premium - عرض حالة الاشتراك مع حدود الاستخدام"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    plan = get_user_plan(user_id)
    usage = {}
    try:
        from premium import get_usage
        usage = get_usage(user_id)
    except Exception:
        pass

    # Admin check
    is_user_admin = is_admin(user_id, update.effective_user.username if update.effective_user else None)

    if lang == "ar":
        plan_display = "⭐ Premium" if plan == "premium" else "🆓 مجاني"
        if is_user_admin:
            plan_display = "👑 أدمن"

        if plan == "premium" or is_user_admin:
            message = f"""⭐ <b>حالة الاشتراك</b>
━━━━━━━━━━━━━━━━━

👤 الخطة: {plan_display}

{"👑 أنت الأدمن — كل حاجة مفتوحة ليك!" if is_user_admin else "⭐ أنت مشترك Premium — استمتع بكل المزايا!"}

📊 <b>استخدام اليوم:</b>
💬 رسائل AI: {usage.get('ai_messages', 0)}
📄 تحليلات PDF: {usage.get('pdf_analyses', 0)}
🖼️ تحليلات الصور: {usage.get('image_analyses', 0)}
🎬 ملخصات YouTube: {usage.get('youtube_summaries', 0)}
🔍 عمليات البحث: {usage.get('searches', 0)}
📥 تحميل وسائط: {usage.get('downloads', 0)}
🎬 فيديو بالبحث: {usage.get('video_searches', 0)}
🎵 صوت بالبحث: {usage.get('audio_searches', 0)}
🖼️ بحث صور: {usage.get('photo_searches', 0)}"""
        else:
            # Free user — show limits with usage
            from premium import PLAN_LIMITS
            limits = PLAN_LIMITS["free"]
            ai_msg_used = usage.get('ai_messages', 0)
            ai_msg_limit = limits['ai_messages_per_day']
            pdf_used = usage.get('pdf_analyses', 0)
            pdf_limit = limits['pdf_analyses_per_day']
            img_used = usage.get('image_analyses', 0)
            img_limit = limits['image_analyses_per_day']
            yt_used = usage.get('youtube_summaries', 0)
            yt_limit = limits['youtube_summaries_per_day']
            search_used = usage.get('searches', 0)
            search_limit = limits['searches_per_day']

            message = f"""⭐ <b>حالة الاشتراك</b>
━━━━━━━━━━━━━━━━━

👤 الخطة: {plan_display}

📊 <b>استخدام اليوم:</b>
💬 رسائل AI: {ai_msg_used} من {ai_msg_limit}
📄 تحليلات PDF: {pdf_used} من {pdf_limit}
🖼️ تحليلات الصور: {img_used} من {img_limit}
🎬 ملخصات YouTube: {yt_used} من {yt_limit}
🔍 عمليات البحث: {search_used} من {search_limit}
🖼️ بحث صور: {usage.get('photo_searches', 0)} من {limits.get('photo_searches_per_day', 3)}

📥 تحميل فيديو: ❌ بريميوم
🎬 فيديو بالبحث: ❌ بريميوم
🎵 صوت بالبحث: ❌ بريميوم
🎨 إنشاء صور: ❌ بريميوم
🖌️ تعديل صور: ❌ بريميوم
📚 وضع الدراسة: ❌ بريميوم

💡 الحد بيرجع تاني بكرة!
⭐ ترقية لـ Premium عشان استخدام غير محدود!
📩 تواصل مع المطور: @ziadamr"""
    else:
        plan_display = "⭐ Premium" if plan == "premium" else "🆓 Free"
        if is_user_admin:
            plan_display = "👑 Admin"

        if plan == "premium" or is_user_admin:
            message = f"""⭐ <b>Subscription Status</b>
━━━━━━━━━━━━━━━━━

👤 Plan: {plan_display}

{"👑 You're the admin — everything is open for you!" if is_user_admin else "⭐ You're a Premium subscriber — enjoy all features!"}

📊 <b>Today's Usage:</b>
💬 AI Messages: {usage.get('ai_messages', 0)}
📄 PDF Analyses: {usage.get('pdf_analyses', 0)}
🖼️ Image Analyses: {usage.get('image_analyses', 0)}
🎬 YouTube Summaries: {usage.get('youtube_summaries', 0)}
🔍 Searches: {usage.get('searches', 0)}
📥 Media Downloads: {usage.get('downloads', 0)}
🎬 Video Searches: {usage.get('video_searches', 0)}
🎵 Audio Searches: {usage.get('audio_searches', 0)}
🖼️ Photo Searches: {usage.get('photo_searches', 0)}"""
        else:
            from premium import PLAN_LIMITS
            limits = PLAN_LIMITS["free"]
            ai_msg_used = usage.get('ai_messages', 0)
            ai_msg_limit = limits['ai_messages_per_day']
            pdf_used = usage.get('pdf_analyses', 0)
            pdf_limit = limits['pdf_analyses_per_day']
            img_used = usage.get('image_analyses', 0)
            img_limit = limits['image_analyses_per_day']
            yt_used = usage.get('youtube_summaries', 0)
            yt_limit = limits['youtube_summaries_per_day']
            search_used = usage.get('searches', 0)
            search_limit = limits['searches_per_day']

            message = f"""⭐ <b>Subscription Status</b>
━━━━━━━━━━━━━━━━━

👤 Plan: {plan_display}

📊 <b>Today's Usage:</b>
💬 AI Messages: {ai_msg_used} of {ai_msg_limit}
📄 PDF Analyses: {pdf_used} of {pdf_limit}
🖼️ Image Analyses: {img_used} of {img_limit}
🎬 YouTube Summaries: {yt_used} of {yt_limit}
🔍 Searches: {search_used} of {search_limit}
🖼️ Photo Searches: {usage.get('photo_searches', 0)} of {limits.get('photo_searches_per_day', 3)}

📥 Video Downloads: ❌ Premium
🎬 Video Search: ❌ Premium
🎵 Audio Search: ❌ Premium
🎨 Image Generation: ❌ Premium
🖌️ Image Editing: ❌ Premium
📚 Study Mode: ❌ Premium

💡 Limits reset tomorrow!
⭐ Upgrade to Premium for unlimited usage!
📩 Contact developer: @ziadamr"""

    keyboard = get_premium_keyboard(lang, user_id=user_id) if plan != "premium" and not is_user_admin else None
    await update.message.reply_text(
        message,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /plan - عرض خطط الاشتراك"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    message = premium_features_message(lang, user_id=user_id)
    keyboard = get_premium_keyboard(lang, user_id=user_id)
    await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /dashboard - لوحة تحكم (الأدمن @ziadamr فقط)"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    # Admin check
    if not is_admin(user_id, username):
        lang = get_language(user_id)
        if lang == "ar":
            msg = "❌ هذا الأمر متاح للمطور فقط."
        else:
            msg = "❌ This command is for the developer only."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # تأكد إن الأدمن Premium
    ensure_admin_premium(user_id)

    try:
        message = format_dashboard("ar")
        await update.message.reply_text(message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in /dashboard: {e}")
        await update.message.reply_text(f"❌ Error: {e}", parse_mode="HTML")
