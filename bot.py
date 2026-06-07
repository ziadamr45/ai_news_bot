"""
My Bro - مساعد الذكاء الاصطناعي الشخصي
بوت تيليجرام كامل مع أوامر + محادثة ذكية + بحث ويب + أزرار تفاعلية
"""

import logging
import sys
import re
import asyncio
from datetime import datetime, timezone, timedelta

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import BOT_TOKEN, BOT_NAME, BOT_VERSION, COMPANY_DATA, DAILY_NEWS_HOUR, DAILY_NEWS_MINUTE, DAILY_NEWS_TIMEZONE, BROADCAST_DELAY_SECONDS
from ai_engine import smart_chat, ask_question, explain_topic, generate_roadmap, generate_company_report
from memory import (
    get_user, get_language, set_language, get_news_time,
    set_news_time, set_sources, get_sources,
    increment_command_count, increment_chat_count,
    subscribe_user, unsubscribe_user, is_subscribed,
    get_all_subscribers, get_subscriber_count
)
from formatters import (
    welcome_message, help_message, format_news_item,
    format_trending_item, format_error, format_loading,
    language_selection, time_selection, sources_selection,
    subscription_prompt, subscription_confirmed, unsubscription_confirmed,
    daily_news_header, daily_news_footer, subscribe_command_message,
    unsubscribe_command_message, subscribers_info
)
from news_fetcher import fetch_news
from filters import filter_news, is_ai_related
from scorer import rank_articles
from summarizer import summarize_articles

# إعداد الـ Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# حالة انتظار المستخدم (للإعدادات)
user_states = {}


# ═══════════════════════════════════════
# لوحة المفاتيح الرئيسية - Main Keyboard
# ═══════════════════════════════════════

def get_main_keyboard(language: str = "ar") -> ReplyKeyboardMarkup:
    """لوحة المفاتيح الرئيسية اللي بتظهر أسفل الشات"""
    if language == "ar":
        keyboard = [
            ["📰 الأخبار", "🤖 اسأل My Bro"],
            ["📈 التريندات", "🔍 البحث"],
            ["📚 تعلم AI", "🏢 الشركات"],
            ["⚙️ الإعدادات", "ℹ️ المساعدة"],
        ]
    else:
        keyboard = [
            ["📰 News", "🤖 Ask My Bro"],
            ["📈 Trending", "🔍 Search"],
            ["📚 Learn AI", "🏢 Companies"],
            ["⚙️ Settings", "ℹ️ Help"],
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_news_inline_buttons(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار تظهر بعد الأخبار"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("📰 آخر الأخبار", callback_data="cmd_news"),
                InlineKeyboardButton("📈 التريندات", callback_data="cmd_trending"),
            ],
            [
                InlineKeyboardButton("🏢 OpenAI", callback_data="company_openai"),
                InlineKeyboardButton("🏢 Google", callback_data="company_google"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📰 Latest News", callback_data="cmd_news"),
                InlineKeyboardButton("📈 Trending", callback_data="cmd_trending"),
            ],
            [
                InlineKeyboardButton("🏢 OpenAI", callback_data="company_openai"),
                InlineKeyboardButton("🏢 Google", callback_data="company_google"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_learn_inline_buttons(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار تظهر بعد المحتوى التعليمي"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("📚 تعلم المزيد", callback_data="cmd_learn"),
                InlineKeyboardButton("🗺️ Roadmap", callback_data="cmd_roadmap"),
            ],
            [
                InlineKeyboardButton("🤖 اسأل My Bro", callback_data="cmd_ask"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📚 Learn More", callback_data="cmd_learn"),
                InlineKeyboardButton("🗺️ Roadmap", callback_data="cmd_roadmap"),
            ],
            [
                InlineKeyboardButton("🤖 Ask My Bro", callback_data="cmd_ask"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard(language: str = "ar", user_subscribed: bool = False) -> InlineKeyboardMarkup:
    """أزرار لوحة الإعدادات"""
    if language == "ar":
        sub_btn_text = "❌ إلغاء الاشتراك" if user_subscribed else "📬 اشترك في الأخبار"
        sub_btn_data = "settings_unsubscribe" if user_subscribed else "settings_subscribe"
        keyboard = [
            [
                InlineKeyboardButton("🌐 اللغة", callback_data="settings_language"),
                InlineKeyboardButton("⏰ وقت الأخبار", callback_data="settings_time"),
            ],
            [
                InlineKeyboardButton("📡 المصادر", callback_data="settings_sources"),
                InlineKeyboardButton(sub_btn_text, callback_data=sub_btn_data),
            ],
            [
                InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="cmd_start"),
            ],
        ]
    else:
        sub_btn_text = "❌ Unsubscribe" if user_subscribed else "📬 Subscribe to News"
        sub_btn_data = "settings_unsubscribe" if user_subscribed else "settings_subscribe"
        keyboard = [
            [
                InlineKeyboardButton("🌐 Language", callback_data="settings_language"),
                InlineKeyboardButton("⏰ News Time", callback_data="settings_time"),
            ],
            [
                InlineKeyboardButton("📡 Sources", callback_data="settings_sources"),
                InlineKeyboardButton(sub_btn_text, callback_data=sub_btn_data),
            ],
            [
                InlineKeyboardButton("🔙 Main Menu", callback_data="cmd_start"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_subscribe_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار الاشتراك"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("✅ اشترك الآن", callback_data="settings_subscribe"),
                InlineKeyboardButton("لا شكراً", callback_data="skip_subscribe"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("✅ Subscribe Now", callback_data="settings_subscribe"),
                InlineKeyboardButton("No Thanks", callback_data="skip_subscribe"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_language_keyboard() -> InlineKeyboardMarkup:
    """أزرار اختيار اللغة"""
    keyboard = [
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
            InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_companies_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار اختيار الشركة"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("🏢 OpenAI", callback_data="company_openai"),
                InlineKeyboardButton("🏢 Google", callback_data="company_google"),
            ],
            [
                InlineKeyboardButton("🏢 Anthropic", callback_data="company_anthropic"),
                InlineKeyboardButton("🏢 Microsoft", callback_data="company_microsoft"),
            ],
            [
                InlineKeyboardButton("🏢 Meta", callback_data="company_meta"),
                InlineKeyboardButton("🏢 xAI", callback_data="company_xai"),
            ],
            [
                InlineKeyboardButton("🏢 NVIDIA", callback_data="company_nvidia"),
                InlineKeyboardButton("🏢 DeepMind", callback_data="company_deepmind"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🏢 OpenAI", callback_data="company_openai"),
                InlineKeyboardButton("🏢 Google", callback_data="company_google"),
            ],
            [
                InlineKeyboardButton("🏢 Anthropic", callback_data="company_anthropic"),
                InlineKeyboardButton("🏢 Microsoft", callback_data="company_microsoft"),
            ],
            [
                InlineKeyboardButton("🏢 Meta", callback_data="company_meta"),
                InlineKeyboardButton("🏢 xAI", callback_data="company_xai"),
            ],
            [
                InlineKeyboardButton("🏢 NVIDIA", callback_data="company_nvidia"),
                InlineKeyboardButton("🏢 DeepMind", callback_data="company_deepmind"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_roadmap_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار اختيار خارطة الطريق"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("🤖 AI", callback_data="roadmap_ai"),
                InlineKeyboardButton("🧠 ML", callback_data="roadmap_machine learning"),
            ],
            [
                InlineKeyboardButton("🔬 Deep Learning", callback_data="roadmap_deep learning"),
                InlineKeyboardButton("💬 NLP", callback_data="roadmap_nlp"),
            ],
            [
                InlineKeyboardButton("📝 LLM", callback_data="roadmap_llm"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🤖 AI", callback_data="roadmap_ai"),
                InlineKeyboardButton("🧠 ML", callback_data="roadmap_machine learning"),
            ],
            [
                InlineKeyboardButton("🔬 Deep Learning", callback_data="roadmap_deep learning"),
                InlineKeyboardButton("💬 NLP", callback_data="roadmap_nlp"),
            ],
            [
                InlineKeyboardButton("📝 LLM", callback_data="roadmap_llm"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


# ═══════════════════════════════════════
# أوامر البوت
# ═══════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start - شاشة ترحيب احترافية"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "صديقي"
    lang = get_language(user_id)
    increment_command_count(user_id)

    # حفظ اسم المستخدم
    from memory import update_user
    update_user(user_id, {"name": user_name})

    keyboard = get_main_keyboard(lang)

    await update.message.reply_text(
        welcome_message(lang, user_name),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=keyboard
    )

    # لو المستخدم مش مشترك، اسأله يشترك
    if not is_subscribed(user_id):
        import asyncio
        await asyncio.sleep(1.5)  # انتظر شوية عشان الرسالة الترحيبية تظهر الأول
        sub_keyboard = get_subscribe_keyboard(lang)
        await update.message.reply_text(
            subscription_prompt(lang),
            parse_mode="HTML",
            reply_markup=sub_keyboard
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /help"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    await update.message.reply_text(
        help_message(lang),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /news - أخبار AI اليوم"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        articles = fetch_news()
        if not articles:
            await loading_msg.edit_text(
                "لا توجد أخبار AI جديدة حالياً. 🤖" if lang == "ar" else "No new AI news right now. 🤖"
            )
            return

        filtered = filter_news(articles)
        if not filtered:
            await loading_msg.edit_text(
                "لا توجد أخبار AI مرتبطة اليوم. 🤖" if lang == "ar" else "No AI-related news today. 🤖"
            )
            return

        ranked = rank_articles(filtered)
        summarized = summarize_articles(ranked)

        # تنسيق الرسالة
        now = datetime.now(timezone(timedelta(hours=2)))
        days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        months_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

        if lang == "ar":
            date_str = f"{days_ar[now.weekday()]}, {now.day} {months_ar[now.month]} {now.year}"
            header = f"📰 <b>أخبار الذكاء الاصطناعي اليوم</b>\n📅 {date_str}\n\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            date_str = now.strftime("%A, %B %d, %Y")
            header = f"📰 <b>Today's AI News</b>\n📅 {date_str}\n\n━━━━━━━━━━━━━━━━━\n\n"

        items = []
        for i, article in enumerate(summarized):
            is_top = article.get("is_top", False)
            item = format_news_item(
                i + 1,
                article.get("title", ""),
                article.get("arabic_summary", article.get("description", "")[:200]),
                article.get("link", ""),
                is_top
            )
            items.append(item)

        footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — مساعدك الذكي</i>"
        message = header + "\n\n".join(items) + footer

        inline_keyboard = get_news_inline_buttons(lang)

        # تقسيم لو الرسالة طويلة
        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:  # آخر جزء مع الأزرار
                    await update.message.reply_text(
                        chunk, parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=inline_keyboard
                    )
                else:
                    await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            await loading_msg.delete()
        else:
            await loading_msg.edit_text(
                message, parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_keyboard
            )

    except Exception as e:
        logger.error(f"Error in /news: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ أثناء جلب الأخبار" if lang == "ar" else "Error fetching news"))


async def breaking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /breaking - أهم خبر حالي"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        articles = fetch_news()
        filtered = filter_news(articles)

        if not filtered:
            await loading_msg.edit_text(
                "لا توجد أخبار عاجلة حالياً. 🤖" if lang == "ar" else "No breaking news right now. 🤖"
            )
            return

        ranked = rank_articles(filtered)
        top = ranked[0] if ranked else None

        if not top:
            await loading_msg.edit_text(
                "لا توجد أخبار عاجلة حالياً. 🤖" if lang == "ar" else "No breaking news right now. 🤖"
            )
            return

        summarized = summarize_articles([top])

        if lang == "ar":
            message = f"""🔴 <b>خبر عاجل</b>
━━━━━━━━━━━━━━━━━

{format_news_item(1, summarized[0]['title'], summarized[0].get('arabic_summary', ''), summarized[0]['link'], True)}

━━━━━━━━━━━━━━━━━
🤖 <i>My Bro — تنبيه عاجل</i>"""
        else:
            message = f"""🔴 <b>Breaking News</b>
━━━━━━━━━━━━━━━━━

{format_news_item(1, summarized[0]['title'], summarized[0].get('arabic_summary', ''), summarized[0]['link'], True)}

━━━━━━━━━━━━━━━━━
🤖 <i>My Bro — Breaking Alert</i>"""

        inline_keyboard = get_news_inline_buttons(lang)
        await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"Error in /breaking: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /weekly - ملخص الأسبوع"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        from config import NEWS_FETCH_HOURS
        import config
        original_hours = config.NEWS_FETCH_HOURS
        config.NEWS_FETCH_HOURS = 168  # أسبوع

        articles = fetch_news()
        config.NEWS_FETCH_HOURS = original_hours  # إرجاع

        filtered = filter_news(articles)

        if not filtered:
            await loading_msg.edit_text(
                "لا توجد أخبار AI هذا الأسبوع. 🤖" if lang == "ar" else "No AI news this week. 🤖"
            )
            return

        ranked = rank_articles(filtered)
        summarized = summarize_articles(ranked)

        if lang == "ar":
            header = "📊 <b>ملخص أخبار AI الأسبوعي</b>\n━━━━━━━━━━━━━━━━━\n\n"
            footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — ملخص أسبوعي</i>"
        else:
            header = "📊 <b>Weekly AI News Summary</b>\n━━━━━━━━━━━━━━━━━\n\n"
            footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Weekly Summary</i>"

        items = []
        for i, article in enumerate(summarized):
            items.append(format_news_item(
                i + 1, article['title'],
                article.get('arabic_summary', ''),
                article['link'],
                article.get('is_top', False)
            ))

        message = header + "\n\n".join(items) + footer
        inline_keyboard = get_news_inline_buttons(lang)

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)
                else:
                    await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            await loading_msg.delete()
        else:
            await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"Error in /weekly: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /trending - الترندات"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        articles = fetch_news()
        filtered = filter_news(articles)

        if not filtered:
            await loading_msg.edit_text(
                "لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖"
            )
            return

        from collections import Counter
        from config import AI_KEYWORDS

        keyword_counter = Counter()
        for article in filtered:
            title = article.get("title", "").lower()
            desc = article.get("description", "").lower()
            text = f"{title} {desc}"

            for keyword in AI_KEYWORDS:
                if len(keyword) > 3 and keyword in text:
                    keyword_counter[keyword] += 1

        top_trends = keyword_counter.most_common(10)

        if not top_trends:
            await loading_msg.edit_text(
                "لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖"
            )
            return

        if lang == "ar":
            message = "📈 <b>ترندات الذكاء الاصطناعي</b>\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            message = "📈 <b>AI Trending Topics</b>\n━━━━━━━━━━━━━━━━━\n\n"

        for i, (keyword, count) in enumerate(top_trends, 1):
            if lang == "ar":
                message += f"{i}. 🔥 <b>{keyword.upper()}</b> — ذُكر {count} مرة\n"
            else:
                message += f"{i}. 🔥 <b>{keyword.upper()}</b> — mentioned {count} times\n"

        message += "\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — تتبع الترندات</i>"

        inline_keyboard = get_news_inline_buttons(lang)
        await loading_msg.edit_text(message, parse_mode="HTML", reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"Error in /trending: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /search <query> - بحث في الويب + أخبار RSS"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    query = " ".join(context.args) if context.args else ""

    if not query:
        if lang == "ar":
            msg = "🔍 <b>البحث في أخبار AI والويب</b>\n\nاكتب كلمة البحث بعد الأمر\nمثال: <code>/search OpenAI</code>\n\nأو اضغط على زر 🔍 البحث واكتب ما تريد البحث عنه."
        else:
            msg = "🔍 <b>Search AI News & Web</b>\n\nType your search query after the command\nExample: <code>/search OpenAI</code>\n\nOr tap 🔍 Search and type what you want to find."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    loading_msg = await update.message.reply_text(
        "🔍 جاري البحث..." if lang == "ar" else "🔍 Searching..."
    )

    try:
        articles = fetch_news()
        query_lower = query.lower()
        rss_results = []
        for article in articles:
            title = article.get("title", "").lower()
            desc = article.get("description", "").lower()
            if query_lower in title or query_lower in desc:
                rss_results.append(article)

        from web_search import search_web
        web_results = search_web(query, max_results=5)

        message = ""

        if rss_results:
            if lang == "ar":
                message += f"📰 <b>أخبار RSS عن: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"
            else:
                message += f"📰 <b>RSS News about: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"

            summarized_rss = summarize_articles(rss_results[:5])
            for i, article in enumerate(summarized_rss):
                message += format_news_item(
                    i + 1, article['title'],
                    article.get('arabic_summary', ''),
                    article['link'],
                    i == 0
                )
                message += "\n\n"

        if web_results:
            if lang == "ar":
                message += f"🌐 <b>نتائج بحث الويب: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"
            else:
                message += f"🌐 <b>Web Search: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"

            for i, r in enumerate(web_results[:5], 1):
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                link = r.get("link", "")
                message += f"{i}. 📄 <b>{title}</b>\n"
                if snippet:
                    message += f"   {snippet[:200]}\n"
                if link:
                    message += f'   🔗 <a href="{link}">اقرأ المزيد</a>\n' if lang == "ar" else f'   🔗 <a href="{link}">Read more</a>\n'
                message += "\n"

        if not rss_results and not web_results:
            if lang == "ar":
                ai_response = smart_chat(f"ابحث عن معلومات عن: {query}", lang)
            else:
                ai_response = smart_chat(f"Search for information about: {query}", lang)
            message = ai_response
        else:
            message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — بحث متقدم</i>"

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            await loading_msg.delete()
        else:
            await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error in /search: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ في البحث" if lang == "ar" else "Search error"))


async def company_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /company <name>"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    company_name = " ".join(context.args) if context.args else ""

    if not company_name:
        if lang == "ar":
            msg = "🏢 <b>تقارير شركات الذكاء الاصطناعي</b>\n\nاختر شركة من الأزرار بالأسفل أو اكتب اسمها بعد الأمر"
        else:
            msg = "🏢 <b>AI Company Reports</b>\n\nChoose a company from buttons below or type its name after the command"

        keyboard = get_companies_keyboard(lang)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
        return

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        report = generate_company_report(company_name, lang)
        await loading_msg.edit_text(report, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in /company: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /ask <question>"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    question = " ".join(context.args) if context.args else ""

    if not question:
        if lang == "ar":
            msg = "🤖 <b>اسأل My Bro</b>\n\nاكتب سؤالك مباشرة أو بعد الأمر\nمثال: <code>/ask ما هي AI Agents؟</code>\n\n💡 يمكنك أيضاً الكتابة مباشرة بدون أوامر وسأفهمك!"
        else:
            msg = "🤖 <b>Ask My Bro</b>\n\nType your question directly or after the command\nExample: <code>/ask What are AI Agents?</code>\n\n💡 You can also just type naturally without commands!"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        response = ask_question(question, lang)
        await loading_msg.edit_text(response, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in /ask: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


async def learn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /learn <topic>"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "📚 <b>تعلم الذكاء الاصطناعي</b>\n\nاكتب الموضوع بعد الأمر\nمثال: <code>/learn transformers</code>\n\n💡 أو اختر من خرائط الطريق بالأسفل"
        else:
            msg = "📚 <b>Learn AI</b>\n\nType the topic after the command\nExample: <code>/learn transformers</code>\n\n💡 Or choose from roadmaps below"

        keyboard = get_roadmap_keyboard(lang)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
        return

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        explanation = explain_topic(topic, lang)
        inline_keyboard = get_learn_inline_buttons(lang)
        await loading_msg.edit_text(explanation, parse_mode="HTML", reply_markup=inline_keyboard)
    except Exception as e:
        logger.error(f"Error in /learn: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


async def roadmap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /roadmap <topic>"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "🗺️ <b>خرائط طريق التعلم</b>\n\nاختر خارطة طريق من الأزرار بالأسفل"
        else:
            msg = "🗺️ <b>Learning Roadmaps</b>\n\nChoose a roadmap from buttons below"

        keyboard = get_roadmap_keyboard(lang)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
        return

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        roadmap = generate_roadmap(topic, lang)
        inline_keyboard = get_learn_inline_buttons(lang)
        await loading_msg.edit_text(roadmap, parse_mode="HTML", reply_markup=inline_keyboard)
    except Exception as e:
        logger.error(f"Error in /roadmap: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


# ═══════════════════════════════════════
# إعدادات البوت
# ═══════════════════════════════════════

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /language"""
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
    """أمر /time"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    current = get_news_time(user_id)
    await update.message.reply_text(time_selection(current, lang), parse_mode="HTML")


async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /sources"""
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


# ═══════════════════════════════════════
# معالجة أزرار Inline - Callback Query
# ═══════════════════════════════════════

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ضغطات الأزرار التفاعلية"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    lang = get_language(user_id)

    logger.info(f"Button callback: user={user_id}, data={data}")

    # ═══ أوامر من الأزرار ═══
    if data == "cmd_start":
        keyboard = get_main_keyboard(lang)
        user_name = query.from_user.first_name or ""
        await query.message.reply_text(
            welcome_message(lang, user_name),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )

    elif data == "cmd_news":
        await _send_news(query, lang)

    elif data == "cmd_trending":
        await _send_trending(query, lang)

    elif data == "cmd_ask":
        if lang == "ar":
            msg = "🤖 اكتب سؤالك وسأجيبك فوراً!"
        else:
            msg = "🤖 Type your question and I'll answer right away!"
        await query.message.reply_text(msg)

    elif data == "cmd_learn":
        keyboard = get_roadmap_keyboard(lang)
        if lang == "ar":
            msg = "📚 <b>اختر موضوع للتعلم</b>"
        else:
            msg = "📚 <b>Choose a topic to learn</b>"
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)

    elif data == "cmd_roadmap":
        keyboard = get_roadmap_keyboard(lang)
        if lang == "ar":
            msg = "🗺️ <b>اختر خارطة طريق</b>"
        else:
            msg = "🗺️ <b>Choose a roadmap</b>"
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)

    # ═══ تقارير الشركات ═══
    elif data.startswith("company_"):
        company_key = data.replace("company_", "")
        loading_msg = await query.message.reply_text(format_loading(lang))
        try:
            report = generate_company_report(company_key, lang)
            await loading_msg.edit_text(report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in company callback: {e}")
            await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))

    # ═══ خرائط الطريق ═══
    elif data.startswith("roadmap_"):
        topic = data.replace("roadmap_", "")
        loading_msg = await query.message.reply_text(format_loading(lang))
        try:
            roadmap = generate_roadmap(topic, lang)
            inline_keyboard = get_learn_inline_buttons(lang)
            await loading_msg.edit_text(roadmap, parse_mode="HTML", reply_markup=inline_keyboard)
        except Exception as e:
            logger.error(f"Error in roadmap callback: {e}")
            await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))

    # ═══ الإعدادات ═══
    elif data == "settings_language":
        keyboard = get_language_keyboard()
        if lang == "ar":
            msg = "🌐 <b>اختر اللغة</b>"
        else:
            msg = "🌐 <b>Choose Language</b>"
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)

    elif data == "settings_time":
        current = get_news_time(user_id)
        await query.message.reply_text(time_selection(current, lang), parse_mode="HTML")

    elif data == "settings_sources":
        await query.message.reply_text(sources_selection(lang), parse_mode="HTML")

    elif data == "settings_menu":
        user_sub = is_subscribed(user_id)
        keyboard = get_settings_keyboard(lang, user_sub)
        sub_status = "✅ مشترك" if user_sub else "❌ مش مشترك"
        if lang == "ar":
            msg = f"⚙️ <b>الإعدادات</b>\n\n📬 حالة الاشتراك: {sub_status}\n\nاختر ما تريد تغييره:"
        else:
            sub_status_en = "✅ Subscribed" if user_sub else "❌ Not subscribed"
            msg = f"⚙️ <b>Settings</b>\n\n📬 Subscription: {sub_status_en}\n\nChoose what to change:"
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)

    # ═══ الاشتراك في الأخبار ═══
    elif data == "settings_subscribe":
        subscribe_user(user_id)
        keyboard = get_main_keyboard(lang)
        await query.message.edit_text(
            subscription_confirmed(lang),
            parse_mode="HTML"
        )

    elif data == "settings_unsubscribe":
        unsubscribe_user(user_id)
        await query.message.edit_text(
            unsubscription_confirmed(lang),
            parse_mode="HTML"
        )

    elif data == "skip_subscribe":
        if lang == "ar":
            await query.message.edit_text("👌 لا مشكلة! ممكن تشترك أي وقت من ⚙️ الإعدادات")
        else:
            await query.message.edit_text("👌 No problem! You can subscribe anytime from ⚙️ Settings")

    # ═══ تغيير اللغة ═══
    elif data == "lang_ar":
        set_language(user_id, "ar")
        keyboard = get_main_keyboard("ar")
        await query.message.reply_text(
            "✅ تم تغيير اللغة إلى العربية",
            reply_markup=keyboard
        )

    elif data == "lang_en":
        set_language(user_id, "en")
        keyboard = get_main_keyboard("en")
        await query.message.reply_text(
            "✅ Language changed to English",
            reply_markup=keyboard
        )


async def _send_news(query, lang: str):
    """إرسال الأخبار عبر callback (من الأزرار)"""
    loading_msg = await query.message.reply_text(format_loading(lang))

    try:
        articles = fetch_news()
        if not articles:
            await loading_msg.edit_text(
                "لا توجد أخبار AI جديدة حالياً. 🤖" if lang == "ar" else "No new AI news right now. 🤖"
            )
            return

        filtered = filter_news(articles)
        if not filtered:
            await loading_msg.edit_text(
                "لا توجد أخبار AI مرتبطة اليوم. 🤖" if lang == "ar" else "No AI-related news today. 🤖"
            )
            return

        ranked = rank_articles(filtered)
        summarized = summarize_articles(ranked)

        now = datetime.now(timezone(timedelta(hours=2)))
        days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        months_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

        if lang == "ar":
            date_str = f"{days_ar[now.weekday()]}, {now.day} {months_ar[now.month]} {now.year}"
            header = f"📰 <b>أخبار الذكاء الاصطناعي اليوم</b>\n📅 {date_str}\n\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            date_str = now.strftime("%A, %B %d, %Y")
            header = f"📰 <b>Today's AI News</b>\n📅 {date_str}\n\n━━━━━━━━━━━━━━━━━\n\n"

        items = []
        for i, article in enumerate(summarized):
            is_top = article.get("is_top", False)
            item = format_news_item(
                i + 1,
                article.get("title", ""),
                article.get("arabic_summary", article.get("description", "")[:200]),
                article.get("link", ""),
                is_top
            )
            items.append(item)

        footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — مساعدك الذكي</i>"
        message = header + "\n\n".join(items) + footer

        inline_keyboard = get_news_inline_buttons(lang)

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await query.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)
                else:
                    await query.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            await loading_msg.delete()
        else:
            await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"Error in _send_news: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


async def _send_trending(query, lang: str):
    """إرسال الترندات عبر callback"""
    loading_msg = await query.message.reply_text(format_loading(lang))

    try:
        articles = fetch_news()
        filtered = filter_news(articles)

        if not filtered:
            await loading_msg.edit_text(
                "لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖"
            )
            return

        from collections import Counter
        from config import AI_KEYWORDS

        keyword_counter = Counter()
        for article in filtered:
            title = article.get("title", "").lower()
            desc = article.get("description", "").lower()
            text = f"{title} {desc}"

            for keyword in AI_KEYWORDS:
                if len(keyword) > 3 and keyword in text:
                    keyword_counter[keyword] += 1

        top_trends = keyword_counter.most_common(10)

        if not top_trends:
            await loading_msg.edit_text(
                "لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖"
            )
            return

        if lang == "ar":
            message = "📈 <b>ترندات الذكاء الاصطناعي</b>\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            message = "📈 <b>AI Trending Topics</b>\n━━━━━━━━━━━━━━━━━\n\n"

        for i, (keyword, count) in enumerate(top_trends, 1):
            if lang == "ar":
                message += f"{i}. 🔥 <b>{keyword.upper()}</b> — ذُكر {count} مرة\n"
            else:
                message += f"{i}. 🔥 <b>{keyword.upper()}</b> — mentioned {count} times\n"

        message += "\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — تتبع الترندات</i>"

        inline_keyboard = get_news_inline_buttons(lang)
        await loading_msg.edit_text(message, parse_mode="HTML", reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"Error in _send_trending: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


# ═══════════════════════════════════════
# المحادثة الذكية (بدون أوامر)
# ═══════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالجة الرسائل العادية
    + أزرار الكيبورد الرئيسية
    + محادثة ذكية
    + بحث ويب تلقائي
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()
    lang = get_language(user_id)

    # ═══ معالجة أزرار الكيبورد الرئيسية ═══
    keyboard_triggers = {
        # العربية
        "📰 الأخبار": "news",
        "🤖 اسأل My Bro": "ask",
        "📈 التريندات": "trending",
        "🔍 البحث": "search",
        "📚 تعلم AI": "learn",
        "🏢 الشركات": "companies",
        "⚙️ الإعدادات": "settings",
        "ℹ️ المساعدة": "help",
        # الإنجليزية
        "📰 News": "news",
        "🤖 Ask My Bro": "ask",
        "📈 Trending": "trending",
        "🔍 Search": "search",
        "📚 Learn AI": "learn",
        "🏢 Companies": "companies",
        "⚙️ Settings": "settings",
        "ℹ️ Help": "help",
    }

    if text in keyboard_triggers:
        action = keyboard_triggers[text]
        increment_command_count(user_id)

        if action == "news":
            # تنفيذ أمر الأخبار مباشرة
            loading_msg = await update.message.reply_text(format_loading(lang))
            try:
                articles = fetch_news()
                filtered = filter_news(articles)
                if not filtered:
                    await loading_msg.edit_text(
                        "لا توجد أخبار AI جديدة حالياً. 🤖" if lang == "ar" else "No new AI news right now. 🤖"
                    )
                    return

                ranked = rank_articles(filtered)
                summarized = summarize_articles(ranked)

                now = datetime.now(timezone(timedelta(hours=2)))
                days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
                months_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

                if lang == "ar":
                    date_str = f"{days_ar[now.weekday()]}, {now.day} {months_ar[now.month]} {now.year}"
                    header = f"📰 <b>أخبار الذكاء الاصطناعي اليوم</b>\n📅 {date_str}\n\n━━━━━━━━━━━━━━━━━\n\n"
                else:
                    date_str = now.strftime("%A, %B %d, %Y")
                    header = f"📰 <b>Today's AI News</b>\n📅 {date_str}\n\n━━━━━━━━━━━━━━━━━\n\n"

                items = []
                for i, article in enumerate(summarized):
                    is_top = article.get("is_top", False)
                    item = format_news_item(
                        i + 1,
                        article.get("title", ""),
                        article.get("arabic_summary", article.get("description", "")[:200]),
                        article.get("link", ""),
                        is_top
                    )
                    items.append(item)

                footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — مساعدك الذكي</i>"
                message = header + "\n\n".join(items) + footer

                inline_keyboard = get_news_inline_buttons(lang)

                if len(message) > 4000:
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for i, chunk in enumerate(chunks):
                        if i == len(chunks) - 1:
                            await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)
                        else:
                            await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
                    await loading_msg.delete()
                else:
                    await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)
            except Exception as e:
                logger.error(f"Error in keyboard news: {e}")
                await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))

        elif action == "ask":
            if lang == "ar":
                msg = "🤖 <b>اسأل My Bro</b>\n\nاكتب سؤالك مباشرة وسأجيبك فوراً!\n\n💡 يمكنك سؤالي عن أي شيء:\n→ ما هو Gemini؟\n→ اشرح AI Agents\n→ ما الفرق بين GPT و Claude؟"
            else:
                msg = "🤖 <b>Ask My Bro</b>\n\nType your question and I'll answer right away!\n\n💡 You can ask me anything:\n→ What is Gemini?\n→ Explain AI Agents\n→ What's the difference between GPT and Claude?"
            await update.message.reply_text(msg, parse_mode="HTML")

        elif action == "trending":
            loading_msg = await update.message.reply_text(format_loading(lang))
            try:
                articles = fetch_news()
                filtered = filter_news(articles)
                from collections import Counter
                from config import AI_KEYWORDS

                keyword_counter = Counter()
                for article in filtered:
                    title = article.get("title", "").lower()
                    desc = article.get("description", "").lower()
                    text_content = f"{title} {desc}"
                    for keyword in AI_KEYWORDS:
                        if len(keyword) > 3 and keyword in text_content:
                            keyword_counter[keyword] += 1

                top_trends = keyword_counter.most_common(10)

                if not top_trends:
                    await loading_msg.edit_text("لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
                    return

                if lang == "ar":
                    message = "📈 <b>ترندات الذكاء الاصطناعي</b>\n━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message = "📈 <b>AI Trending Topics</b>\n━━━━━━━━━━━━━━━━━\n\n"

                for i, (keyword, count) in enumerate(top_trends, 1):
                    if lang == "ar":
                        message += f"{i}. 🔥 <b>{keyword.upper()}</b> — ذُكر {count} مرة\n"
                    else:
                        message += f"{i}. 🔥 <b>{keyword.upper()}</b> — mentioned {count} times\n"

                message += "\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — تتبع الترندات</i>"

                inline_keyboard = get_news_inline_buttons(lang)
                await loading_msg.edit_text(message, parse_mode="HTML", reply_markup=inline_keyboard)
            except Exception as e:
                logger.error(f"Error in keyboard trending: {e}")
                await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))

        elif action == "search":
            if lang == "ar":
                msg = "🔍 <b>البحث في أخبار AI والويب</b>\n\nاكتب ما تريد البحث عنه مباشرة!\n\n💡 أمثلة:\n→ أحدث أخبار OpenAI\n→ ما هو Sora؟\n→ NVIDIA stock"
            else:
                msg = "🔍 <b>Search AI News & Web</b>\n\nType what you want to search for!\n\n💡 Examples:\n→ Latest OpenAI news\n→ What is Sora?\n→ NVIDIA stock"
            await update.message.reply_text(msg, parse_mode="HTML")

        elif action == "learn":
            keyboard = get_roadmap_keyboard(lang)
            if lang == "ar":
                msg = "📚 <b>تعلم الذكاء الاصطناعي</b>\n\nاختر خارطة طريق من الأزرار بالأسفل\nأو اكتب أي موضوع تريد تعلمه!\n\n💡 أمثلة:\n→ /learn transformers\n→ /learn RAG\n→ /learn AI Agents"
            else:
                msg = "📚 <b>Learn AI</b>\n\nChoose a roadmap from buttons below\nOr type any topic you want to learn!\n\n💡 Examples:\n→ /learn transformers\n→ /learn RAG\n→ /learn AI Agents"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)

        elif action == "companies":
            keyboard = get_companies_keyboard(lang)
            if lang == "ar":
                msg = "🏢 <b>تقارير شركات الذكاء الاصطناعي</b>\n\nاختر شركة من الأزرار بالأسفل"
            else:
                msg = "🏢 <b>AI Company Reports</b>\n\nChoose a company from buttons below"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)

        elif action == "settings":
            user_sub = is_subscribed(user_id)
            keyboard = get_settings_keyboard(lang, user_sub)
            sub_status = "✅ مشترك" if user_sub else "❌ مش مشترك"
            if lang == "ar":
                msg = f"⚙️ <b>الإعدادات</b>\n\n📬 حالة الاشتراك: {sub_status}\n\nاختر ما تريد تغييره:"
            else:
                sub_status_en = "✅ Subscribed" if user_sub else "❌ Not subscribed"
                msg = f"⚙️ <b>Settings</b>\n\n📬 Subscription: {sub_status_en}\n\nChoose what to change:"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)

        elif action == "help":
            await update.message.reply_text(
                help_message(lang),
                parse_mode="HTML",
                disable_web_page_preview=True
            )

        return

    # ═══ التحقق من حالة الإعدادات ═══
    state = user_states.get(user_id)

    if state == "awaiting_language":
        if text in ["1", "١", "ar", "عربي", "العربية"]:
            set_language(user_id, "ar")
            user_states.pop(user_id, None)
            keyboard = get_main_keyboard("ar")
            await update.message.reply_text("✅ تم تغيير اللغة إلى العربية", reply_markup=keyboard)
            return
        elif text in ["2", "٢", "en", "english", "إنجليزي"]:
            set_language(user_id, "en")
            user_states.pop(user_id, None)
            keyboard = get_main_keyboard("en")
            await update.message.reply_text("✅ Language changed to English", reply_markup=keyboard)
            return
        else:
            await update.message.reply_text("❌ اختر 1 أو 2 / Choose 1 or 2")
            return

    elif state == "awaiting_time":
        time_pattern = r'^[0-2]?[0-9]:[0-5][0-9]$'
        if re.match(time_pattern, text):
            set_news_time(user_id, text)
            user_states.pop(user_id, None)
            if lang == "ar":
                await update.message.reply_text(f"✅ تم تغيير وقت الأخبار إلى {text}")
            else:
                await update.message.reply_text(f"✅ News time changed to {text}")
            return
        else:
            await update.message.reply_text(
                "❌ صيغة الوقت غير صحيحة. استخدم: <code>09:00</code>" if lang == "ar"
                else "❌ Invalid time format. Use: <code>09:00</code>",
                parse_mode="HTML"
            )
            return

    elif state == "awaiting_sources":
        try:
            numbers = [int(n) for n in text.split()]
            source_map = {
                1: "openai.com", 2: "blog.google", 3: "techcrunch.com",
                4: "theverge.com", 5: "arstechnica.com", 6: "venturebeat.com",
                7: "wired.com"
            }
            selected = [source_map[n] for n in numbers if n in source_map]
            if selected:
                set_sources(user_id, selected)
                user_states.pop(user_id, None)
                if lang == "ar":
                    await update.message.reply_text("✅ تم تحديث المصادر المفضلة")
                else:
                    await update.message.reply_text("✅ Preferred sources updated")
            else:
                await update.message.reply_text(
                    "❌ أرقام غير صحيحة" if lang == "ar" else "❌ Invalid numbers"
                )
        except ValueError:
            await update.message.reply_text(
                "❌ أرسل أرقام فقط" if lang == "ar" else "❌ Send numbers only"
            )
        return

    # ═══ محادثة ذكية عادية (+ بحث ويب تلقائي) ═══
    increment_chat_count(user_id)

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        response = smart_chat(text, lang)
        await loading_msg.edit_text(response, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in smart chat: {e}")
        await loading_msg.edit_text(
            format_error("حدث خطأ أثناء المعالجة" if lang == "ar" else "Error processing your message")
        )


# ═══════════════════════════════════════
# بث الأخبار اليومية - Daily News Broadcast
# ═══════════════════════════════════════

async def broadcast_daily_news(context: ContextTypes.DEFAULT_TYPE):
    """
    بث الأخبار اليومية لكل المشتركين
    بيشتغل تلقائياً كل يوم الساعة 9 الصبح بتوقيت القاهرة
    """
    logger.info("📬 Starting daily news broadcast...")

    subscribers = get_all_subscribers()
    if not subscribers:
        logger.info("📭 No subscribers found. Skipping broadcast.")
        return

    logger.info(f"📬 Broadcasting to {len(subscribers)} subscribers")

    # جلب وتجهيز الأخبار
    try:
        articles = fetch_news()
        if not articles:
            logger.info("📭 No news found today. Skipping broadcast.")
            return

        filtered = filter_news(articles)
        if not filtered:
            logger.info("📭 No AI-related news today. Skipping broadcast.")
            return

        ranked = rank_articles(filtered)
        summarized = summarize_articles(ranked)

        now = datetime.now(timezone(timedelta(hours=2)))
        days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        months_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

        # تجهيز الرسائل لكل لغة
        messages = {}
        for lang_code in ["ar", "en"]:
            if lang_code == "ar":
                date_str = f"{days_ar[now.weekday()]}, {now.day} {months_ar[now.month]} {now.year}"
            else:
                date_str = now.strftime("%A, %B %d, %Y")

            header = daily_news_header(lang_code, date_str)

            items = []
            for i, article in enumerate(summarized):
                item = format_news_item(
                    i + 1,
                    article.get("title", ""),
                    article.get("arabic_summary", article.get("description", "")[:200]),
                    article.get("link", ""),
                    article.get("is_top", False)
                )
                items.append(item)

            footer = daily_news_footer("", lang_code)
            full_msg = header + "\n\n".join(items) + footer
            messages[lang_code] = full_msg

        # إرسال لكل مشترك
        success_count = 0
        fail_count = 0

        for subscriber in subscribers:
            chat_id = subscriber["user_id"]
            lang = subscriber.get("language", "ar")
            message = messages.get(lang, messages["ar"])

            try:
                # تقسيم الرسالة لو طويلة
                if len(message) > 4000:
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for chunk in chunks:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                success_count += 1
                logger.info(f"✅ News sent to {chat_id}")

                # تأخير بسيط عشان منحصلش spam
                await asyncio.sleep(BROADCAST_DELAY_SECONDS)

            except Exception as e:
                fail_count += 1
                logger.error(f"❌ Failed to send to {chat_id}: {e}")

                # لو المستخدم حظر البوت، ألغي اشتراكه تلقائياً
                if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                    unsubscribe_user(chat_id)
                    logger.info(f"🗑️ Auto-unsubscribed blocked user {chat_id}")

        logger.info(f"📬 Broadcast complete: {success_count} sent, {fail_count} failed out of {len(subscribers)} subscribers")

    except Exception as e:
        logger.error(f"❌ Error in broadcast: {e}")


def main():
    """التشغيل الرئيسي للبوت"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()

    # تسجيل الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("breaking", breaking_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("trending", trending_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("company", company_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("learn", learn_command))
    app.add_handler(CommandHandler("roadmap", roadmap_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("time", time_command))
    app.add_handler(CommandHandler("sources", sources_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CommandHandler("subscribers", subscribers_command))

    # أزرار تفاعلية
    app.add_handler(CallbackQueryHandler(button_callback))

    # الرسائل العادية (محادثة ذكية)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ═══ إعداد المجدول - Scheduler Setup ═══
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    scheduler = AsyncIOScheduler(timezone=pytz.timezone(DAILY_NEWS_TIMEZONE))
    scheduler.add_job(
        broadcast_daily_news,
        CronTrigger(
            hour=DAILY_NEWS_HOUR,
            minute=DAILY_NEWS_MINUTE,
            timezone=pytz.timezone(DAILY_NEWS_TIMEZONE)
        ),
        args=[app],
        id="daily_news_broadcast",
        name="Daily AI News Broadcast",
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"⏰ Scheduler started: Daily news at {DAILY_NEWS_HOUR}:{DAILY_NEWS_MINUTE:02d} {DAILY_NEWS_TIMEZONE}")

    async def post_init(application):
        """تعيين أوامر البوت بعد التهيئة"""
        from telegram import BotCommand
        commands = [
            BotCommand("start", "🚀 ابدأ البوت"),
            BotCommand("help", "ℹ️ المساعدة"),
            BotCommand("news", "📰 أخبار AI اليوم"),
            BotCommand("breaking", "🔴 أهم خبر"),
            BotCommand("weekly", "📊 ملخص الأسبوع"),
            BotCommand("trending", "📈 الترندات"),
            BotCommand("search", "🔍 بحث"),
            BotCommand("company", "🏢 تقرير شركة"),
            BotCommand("ask", "🤖 اسأل سؤال"),
            BotCommand("learn", "📚 تعلم"),
            BotCommand("roadmap", "🗺️ خارطة طريق"),
            BotCommand("language", "🌐 تغيير اللغة"),
            BotCommand("subscribe", "📬 اشترك في الأخبار"),
            BotCommand("unsubscribe", "❌ إلغاء الاشتراك"),
            BotCommand("subscribers", "📊 عدد المشتركين"),
        ]
        await application.bot.set_my_commands(commands)
        sub_count = get_subscriber_count()
        logger.info(f"🤖 My Bro v{BOT_VERSION} started! 📬 {sub_count} subscribers")

    app.post_init = post_init

    logger.info(f"Starting My Bro v{BOT_VERSION}...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
