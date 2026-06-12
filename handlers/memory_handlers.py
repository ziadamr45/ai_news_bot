"""
Memory and settings command handlers.
"""

import logging
import time as _time

from telegram import Update
from telegram.ext import ContextTypes

from memory import (
    get_language, increment_command_count,
    set_language, get_news_time,
    set_news_time, set_sources, get_sources,
    increment_chat_count,
    subscribe_user, unsubscribe_user, is_subscribed,
    get_all_subscribers, get_subscriber_count,
    get_subscribers_for_time, get_last_news_delivery, set_last_news_delivery,
    save_conversation, get_recent_conversations, get_conversation_context,
    save_learning, get_learning_progress, get_learned_topics,
    add_favorite, get_favorites, remove_favorite,
    save_memory, get_memories, delete_memory, reset_all_memories,
    add_interest, get_interests, get_interests_context,
    add_favorite_company, get_favorite_companies,
    detect_interests, get_user_memory_summary,
    format_memory_display, format_progress_display, format_favorites_display
)
from formatters import (
    time_selection, sources_selection,
    subscription_prompt, subscription_confirmed, unsubscription_confirmed,
    subscribe_command_message, unsubscribe_command_message, subscribers_info,
)
from dashboard import track_event

from handlers.keyboards import (
    get_main_keyboard, get_language_keyboard,
    get_settings_keyboard, get_subscribe_keyboard,
)
from handlers.dedup import _user_last_memory_response, _MEMORY_RESPONSE_COOLDOWN

logger = logging.getLogger(__name__)


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /memory - عرض ذاكرتي عن المستخدم"""
    user_id = update.effective_user.id
    lang = get_language(user_id)

    # منع تكرار عرض الذاكرة (dedup per user)
    now = _time.time()
    if user_id in _user_last_memory_response:
        if now - _user_last_memory_response[user_id] < _MEMORY_RESPONSE_COOLDOWN:
            return  # تم عرض الذاكرة مؤخراً
    _user_last_memory_response[user_id] = now

    increment_command_count(user_id)

    try:
        message = format_memory_display(user_id, lang)
    except Exception as e:
        logger.error(f"Error in /memory: {e}")
        message = "❌ حصل خطأ في عرض الذاكرة" if lang == "ar" else "❌ Error displaying memory"

    await update.message.reply_text(message, parse_mode="HTML")


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /progress - تقدم التعلم"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        message = format_progress_display(user_id, lang)
    except Exception as e:
        logger.error(f"Error in /progress: {e}")
        message = "❌ حصل خطأ في عرض التقدم" if lang == "ar" else "❌ Error displaying progress"

    await update.message.reply_text(message, parse_mode="HTML")


async def favorite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /favorite - حفظ آخر شيء في المفضلة"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        recent = get_recent_conversations(user_id, 2)
        if recent:
            last_msg = recent[0]
            title = last_msg['content'][:60]
            category = "topic"
            content_lower = last_msg['content'].lower()
            if any(kw in content_lower for kw in ["خبر", "news", "أخبار", "breaking"]):
                category = "news"
            elif any(kw in content_lower for kw in ["شركة", "company", "openai", "google", "anthropic"]):
                category = "company"
            elif any(kw in content_lower for kw in ["أداة", "tool", "api", "sdk"]):
                category = "tool"

            add_favorite(user_id, category, title, last_msg['content'][:500])

            if lang == "ar":
                msg = f"⭐ <b>تم الحفظ في المفضلة!</b>\n\n📌 {title}...\n📂 التصنيف: {category}\n\n💡 شوف كل مفضلاتك: /favorites"
            else:
                msg = f"⭐ <b>Saved to favorites!</b>\n\n📌 {title}...\n📂 Category: {category}\n\n💡 View all favorites: /favorites"
        else:
            msg = "💭 معندكش محادثات لسه أحفظها." if lang == "ar" else "💭 No conversations to save yet."
    except Exception as e:
        logger.error(f"Error in /favorite: {e}")
        msg = "❌ حصل خطأ" if lang == "ar" else "❌ Error occurred"

    await update.message.reply_text(msg, parse_mode="HTML")


async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /favorites - عرض المفضلات"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        message = format_favorites_display(user_id, lang)
    except Exception as e:
        logger.error(f"Error in /favorites: {e}")
        message = "❌ حصل خطأ" if lang == "ar" else "❌ Error occurred"

    await update.message.reply_text(message, parse_mode="HTML")


async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /forget <keyword> - حذف ذكرى محددة"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    keyword = " ".join(context.args) if context.args else ""

    if not keyword:
        if lang == "ar":
            msg = "🧠 <b>حذف ذكرى</b>\n\nاكتب الكلمة اللي عايز تمسحها\nمثال: <code>/forget الرياضة</code>"
        else:
            msg = "🧠 <b>Forget Memory</b>\n\nType the keyword to forget\nExample: <code>/forget sports</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        delete_memory(user_id, key=keyword)
        if lang == "ar":
            msg = f'🗑️ تم مسح الذكريات المتعلقة بـ "{keyword}"'
        else:
            msg = f'🗑️ Memories related to "{keyword}" have been deleted'
    except Exception as e:
        logger.error(f"Error in /forget: {e}")
        msg = "❌ حصل خطأ" if lang == "ar" else "❌ Error occurred"

    await update.message.reply_text(msg, parse_mode="HTML")


async def resetmemory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /resetmemory - حذف كل الذكريات"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        reset_all_memories(user_id)
        if lang == "ar":
            msg = "🧹 <b>تم مسح كل الذكريات!</b>\n\nنظام الذاكرة نضيف دلوقتي. هيبدأ يتعلم عنك من جديد مع كل محادثة."
        else:
            msg = "🧹 <b>All memories deleted!</b>\n\nMemory system is now clean. It will learn about you again from each conversation."
    except Exception as e:
        logger.error(f"Error in /resetmemory: {e}")
        msg = "❌ حصل خطأ" if lang == "ar" else "❌ Error occurred"

    await update.message.reply_text(msg, parse_mode="HTML")


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    if lang == "ar":
        msg = "🌐 <b>اختر اللغة</b>"
    else:
        msg = "🌐 <b>Choose Language</b>"

    keyboard = get_language_keyboard()
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)


async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    current = get_news_time(user_id)
    await update.message.reply_text(time_selection(current, lang), parse_mode="HTML")


async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    await update.message.reply_text(sources_selection(lang), parse_mode="HTML")


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /subscribe - الاشتراك في الأخبار اليومية"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    if is_subscribed(user_id):
        if lang == "ar":
            msg = "✅ أنت مشترك بالفعل في الأخبار اليومية!\n\n📬 هابعتلك الأخبار كل يوم الساعة 9 الصبح\n💡 ممكن تلغي الاشتراك من ⚙️ الإعدادات أو أمر /unsubscribe"
        else:
            msg = "✅ You're already subscribed to daily news!\n\n📬 I'll send you news every day at 9 AM\n💡 You can unsubscribe from ⚙️ Settings or /unsubscribe"
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        sub_keyboard = get_subscribe_keyboard(lang)
        await update.message.reply_text(
            subscribe_command_message(lang),
            parse_mode="HTML",
            reply_markup=sub_keyboard
        )


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /unsubscribe - إلغاء الاشتراك"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    if not is_subscribed(user_id):
        if lang == "ar":
            msg = "❌ أنت مش مشترك في الأخبار اليومية أصلاً!\n\n💡 ممكن تشترك من ⚙️ الإعدادات أو أمر /subscribe"
        else:
            msg = "❌ You're not subscribed to daily news!\n\n💡 You can subscribe from ⚙️ Settings or /subscribe"
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        unsubscribe_user(user_id)
        await update.message.reply_text(
            unsubscription_confirmed(lang),
            parse_mode="HTML"
        )


async def subscribers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /subscribers - عدد المشتركين"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    count = get_subscriber_count()
    await update.message.reply_text(
        subscribers_info(count, lang),
        parse_mode="HTML"
    )
