"""
My Bro - مساعد الذكاء الاصطناعي الشخصي
بوت تيليجرام كامل مع أوامر + محادثة ذكية + بحث ويب + أزرار تفاعلية
+ تجربة متميزة مع مؤشرات الكتابة + نظام تقدم مباشر + جدولة الأخبار
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

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import BOT_TOKEN, BOT_NAME, BOT_VERSION, COMPANY_DATA, DAILY_NEWS_HOUR, DAILY_NEWS_MINUTE, DAILY_NEWS_TIMEZONE, BROADCAST_DELAY_SECONDS, CREATOR_INFO
from ai_engine import smart_chat, ask_question, explain_topic, generate_roadmap, generate_company_report, analyze_image
from memory import (
    get_user, get_language, set_language, get_news_time,
    set_news_time, set_sources, get_sources,
    increment_command_count, increment_chat_count,
    subscribe_user, unsubscribe_user, is_subscribed,
    get_all_subscribers, get_subscriber_count,
    # نظام الذاكرة الجديد
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
    welcome_message, help_message, format_news_item,
    format_trending_item, format_error, format_loading,
    language_selection, time_selection, sources_selection,
    subscription_prompt, subscription_confirmed, unsubscription_confirmed,
    daily_news_header, daily_news_footer, subscribe_command_message,
    unsubscribe_command_message, subscribers_info, about_message,
    clean_ai_response
)
from news_fetcher import fetch_news
from filters import filter_news, is_ai_related
from scorer import rank_articles
from summarizer import summarize_articles
from progress import (
    ProgressManager, TypingIndicator, send_typing,
    NEWS_STAGES, AI_STAGES, SEARCH_STAGES, COMPANY_STAGES,
    LEARN_STAGES, ROADMAP_STAGES
)

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
    keyboard = [
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
            InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_companies_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    if language == "ar":
        keyboard = [
            [InlineKeyboardButton("🏢 OpenAI", callback_data="company_openai"), InlineKeyboardButton("🏢 Google", callback_data="company_google")],
            [InlineKeyboardButton("🏢 Anthropic", callback_data="company_anthropic"), InlineKeyboardButton("🏢 Microsoft", callback_data="company_microsoft")],
            [InlineKeyboardButton("🏢 Meta", callback_data="company_meta"), InlineKeyboardButton("🏢 xAI", callback_data="company_xai")],
            [InlineKeyboardButton("🏢 NVIDIA", callback_data="company_nvidia"), InlineKeyboardButton("🏢 DeepMind", callback_data="company_deepmind")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🏢 OpenAI", callback_data="company_openai"), InlineKeyboardButton("🏢 Google", callback_data="company_google")],
            [InlineKeyboardButton("🏢 Anthropic", callback_data="company_anthropic"), InlineKeyboardButton("🏢 Microsoft", callback_data="company_microsoft")],
            [InlineKeyboardButton("🏢 Meta", callback_data="company_meta"), InlineKeyboardButton("🏢 xAI", callback_data="company_xai")],
            [InlineKeyboardButton("🏢 NVIDIA", callback_data="company_nvidia"), InlineKeyboardButton("🏢 DeepMind", callback_data="company_deepmind")],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_roadmap_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    if language == "ar":
        keyboard = [
            [InlineKeyboardButton("🤖 AI", callback_data="roadmap_ai"), InlineKeyboardButton("🧠 ML", callback_data="roadmap_machine learning")],
            [InlineKeyboardButton("🔬 Deep Learning", callback_data="roadmap_deep learning"), InlineKeyboardButton("💬 NLP", callback_data="roadmap_nlp")],
            [InlineKeyboardButton("📝 LLM", callback_data="roadmap_llm")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🤖 AI", callback_data="roadmap_ai"), InlineKeyboardButton("🧠 ML", callback_data="roadmap_machine learning")],
            [InlineKeyboardButton("🔬 Deep Learning", callback_data="roadmap_deep learning"), InlineKeyboardButton("💬 NLP", callback_data="roadmap_nlp")],
            [InlineKeyboardButton("📝 LLM", callback_data="roadmap_llm")],
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

    from memory import update_user
    update_user(user_id, {"name": user_name})

    keyboard = get_main_keyboard(lang)

    await update.message.reply_text(
        welcome_message(lang, user_name),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=keyboard
    )

    if not is_subscribed(user_id):
        await asyncio.sleep(1.5)
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
    """أمر /news - أخبار AI اليوم مع نظام تقدم متميز"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    stages = NEWS_STAGES(lang)
    title = "جلب أخبار AI" if lang == "ar" else "Fetching AI News"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        # المرحلة 1: جلب الأخبار
        await progress.update_stage(0)
        articles = await fetch_news()
        if not articles:
            await progress.error("لا توجد أخبار AI جديدة حالياً. 🤖" if lang == "ar" else "No new AI news right now. 🤖")
            return

        # المرحلة 2: فلترة
        await progress.update_stage(1)
        filtered = filter_news(articles)
        if not filtered:
            await progress.error("لا توجد أخبار AI مرتبطة اليوم. 🤖" if lang == "ar" else "No AI-related news today. 🤖")
            return

        # المرحلة 3: ترتيب
        await progress.update_stage(2)
        ranked = rank_articles(filtered)

        # المرحلة 4: تلخيص
        await progress.update_stage(3)
        summarized = await summarize_articles(ranked)

        # المرحلة 5: تنسيق
        await progress.update_stage(4)

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

        # إرسال النتيجة النهائية
        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            await progress.complete(delete_progress=True)
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await update.message.reply_text(
                        chunk, parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=inline_keyboard
                    )
                else:
                    await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await progress.complete(
                final_message=message,
                reply_markup=inline_keyboard,
                delete_progress=False
            )

    except Exception as e:
        logger.error(f"Error in /news: {e}")
        await progress.error("حدث خطأ أثناء جلب الأخبار" if lang == "ar" else "Error fetching news")


async def breaking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /breaking - أهم خبر حالي"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    stages = NEWS_STAGES(lang)
    title = "خبر عاجل" if lang == "ar" else "Breaking News"
    progress = ProgressManager(update, context, stages[:3], lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        articles = await fetch_news()

        await progress.update_stage(1)
        filtered = filter_news(articles)

        if not filtered:
            await progress.error("لا توجد أخبار عاجلة حالياً. 🤖" if lang == "ar" else "No breaking news right now. 🤖")
            return

        await progress.update_stage(2)
        ranked = rank_articles(filtered)
        top = ranked[0] if ranked else None

        if not top:
            await progress.error("لا توجد أخبار عاجلة حالياً. 🤖" if lang == "ar" else "No breaking news right now. 🤖")
            return

        summarized = await summarize_articles([top])

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
        await progress.complete(final_message=message, reply_markup=inline_keyboard, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in /breaking: {e}")
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /weekly - ملخص الأسبوع"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    stages = NEWS_STAGES(lang)
    title = "ملخص أسبوعي" if lang == "ar" else "Weekly Summary"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        from config import NEWS_FETCH_HOURS
        import config
        original_hours = config.NEWS_FETCH_HOURS
        config.NEWS_FETCH_HOURS = 168

        await progress.update_stage(0)
        articles = await fetch_news()
        config.NEWS_FETCH_HOURS = original_hours

        await progress.update_stage(1)
        filtered = filter_news(articles)

        if not filtered:
            await progress.error("لا توجد أخبار AI هذا الأسبوع. 🤖" if lang == "ar" else "No AI news this week. 🤖")
            return

        await progress.update_stage(2)
        ranked = rank_articles(filtered)

        await progress.update_stage(3)
        summarized = await summarize_articles(ranked)

        await progress.update_stage(4)

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
            await progress.complete(delete_progress=True)
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)
                else:
                    await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await progress.complete(final_message=message, reply_markup=inline_keyboard, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in /weekly: {e}")
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /trending - الترندات"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    stages = NEWS_STAGES(lang)
    title = "جلب الترندات" if lang == "ar" else "Fetching Trending"
    progress = ProgressManager(update, context, stages[:3], lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        articles = await fetch_news()

        await progress.update_stage(1)
        filtered = filter_news(articles)

        if not filtered:
            await progress.error("لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
            return

        await progress.update_stage(2)

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
            await progress.error("لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
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
        await progress.complete(final_message=message, reply_markup=inline_keyboard, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in /trending: {e}")
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


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

    stages = SEARCH_STAGES(lang)
    title = f"بحث: {query}" if lang == "ar" else f"Searching: {query}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        # المرحلة 1: البحث
        await progress.update_stage(0)
        articles = await fetch_news()
        query_lower = query.lower()
        rss_results = []
        for article in articles:
            title_text = article.get("title", "").lower()
            desc = article.get("description", "").lower()
            if query_lower in title_text or query_lower in desc:
                rss_results.append(article)

        from web_search import search_web
        web_results = await search_web(query, max_results=5)

        # المرحلة 2: تحليل
        await progress.update_stage(1)

        message = ""

        if rss_results:
            if lang == "ar":
                message += f"📰 <b>أخبار RSS عن: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"
            else:
                message += f"📰 <b>RSS News about: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"

            summarized_rss = await summarize_articles(rss_results[:5])
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
                title_text = r.get("title", "")
                snippet = r.get("snippet", "")
                link = r.get("link", "")
                message += f"{i}. 📄 <b>{title_text}</b>\n"
                if snippet:
                    message += f"   {snippet[:200]}\n"
                if link:
                    message += f'   🔗 <a href="{link}">اقرأ المزيد</a>\n' if lang == "ar" else f'   🔗 <a href="{link}">Read more</a>\n'
                message += "\n"

        # المرحلة 3: تجهيز الرد
        await progress.update_stage(2)

        if not rss_results and not web_results:
            ai_response = await smart_chat(f"ابحث عن معلومات عن: {query}" if lang == "ar" else f"Search for information about: {query}", lang)
            message = ai_response
        else:
            message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — بحث متقدم</i>"

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            await progress.complete(delete_progress=True)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await progress.complete(final_message=message, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in /search: {e}")
        await progress.error("حدث خطأ في البحث" if lang == "ar" else "Search error")


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

    stages = COMPANY_STAGES(lang)
    title = f"تقرير: {company_name}" if lang == "ar" else f"Report: {company_name}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        await progress.update_stage(2)
        report = await generate_company_report(company_name, lang)
        report = clean_ai_response(report)
        await progress.update_stage(3)
        await progress.complete(final_message=report, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /company: {e}")
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


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

    stages = AI_STAGES(lang)
    title = "التفكير" if lang == "ar" else "Thinking"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        response = await ask_question(question, lang)
        response = clean_ai_response(response)
        await progress.update_stage(2)
        await progress.complete(final_message=response, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /ask: {e}")
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


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

    stages = LEARN_STAGES(lang)
    title = f"تعلم: {topic}" if lang == "ar" else f"Learning: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        explanation = await explain_topic(topic, lang)
        explanation = clean_ai_response(explanation)
        await progress.update_stage(2)

        # حفظ تقدم التعلم
        try:
            save_learning(user_id, topic, "explored")
            detect_interests(user_id, topic)
        except Exception:
            pass

        inline_keyboard = get_learn_inline_buttons(lang)
        await progress.complete(final_message=explanation, reply_markup=inline_keyboard, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /learn: {e}")
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


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

    stages = ROADMAP_STAGES(lang)
    title = f"خارطة طريق: {topic}" if lang == "ar" else f"Roadmap: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        roadmap = await generate_roadmap(topic, lang)
        roadmap = clean_ai_response(roadmap)
        await progress.update_stage(2)
        inline_keyboard = get_learn_inline_buttons(lang)
        await progress.complete(final_message=roadmap, reply_markup=inline_keyboard, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /roadmap: {e}")
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


# ═══════════════════════════════════════
# إعدادات البوت
# ═══════════════════════════════════════

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


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /memory - عرض ذاكرتي عن المستخدم"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
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

    # محاولة الحصول على آخر محادثة
    try:
        recent = get_recent_conversations(user_id, 2)
        if recent:
            last_msg = recent[0]
            title = last_msg['content'][:60]
            category = "topic"
            # تحديد الفئة تلقائياً
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
            msg = "🧠 <b>حذف ذكرى</b>\n\nاكتب الكلمة اللي عايز تمسحها\nمثال: <code>/forget openai</code>"
        else:
            msg = "🧠 <b>Forget Memory</b>\n\nType the keyword to forget\nExample: <code>/forget openai</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        delete_memory(user_id, key=keyword)
        if lang == "ar":
            msg = f"🗑️ تم مسح الذكريات المتعلقة بـ \"{keyword}\""
        else:
            msg = f"🗑️ Memories related to \"{keyword}\" have been deleted"
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


# ═══════════════════════════════════════
# أوامر جديدة - New Commands (v6.0)
# ═══════════════════════════════════════

async def deepsearch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /deepsearch <query> - بحث عميق"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    query = " ".join(context.args) if context.args else ""

    if not query:
        if lang == "ar":
            msg = "🔬 <b>البحث العميق</b>\n\nاكتب ما تريد البحث عنه بعمق\nمثال: <code>/deepsearch مستقبل الذكاء الاصطناعي</code>\n\n💡 البحث العميق بيستخدم نماذج أقوى وبيبحث في أكتر من مصدر."
        else:
            msg = "🔬 <b>Deep Search</b>\n\nType what you want to search in depth\nExample: <code>/deepsearch future of artificial intelligence</code>\n\n💡 Deep search uses more powerful models and searches multiple sources."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    stages = SEARCH_STAGES(lang)
    title = f"بحث عميق: {query}" if lang == "ar" else f"Deep Search: {query}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        from web_search import deep_search_and_summarize_async
        response = await deep_search_and_summarize_async(query, lang)
        response = clean_ai_response(response)
        await progress.update_stage(2)
        await progress.complete(final_message=response, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /deepsearch: {e}")
        await progress.error("حدث خطأ في البحث العميق" if lang == "ar" else "Deep search error")


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
            message = f"""🔧 <b>حالة المزودين - My Bro v6.0</b>
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
            message = f"""🔧 <b>Provider Status - My Bro v6.0</b>
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


async def image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الصور - Image Analysis"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_chat_count(user_id)

    # التحقق من وجود صورة
    if not update.message.photo:
        return

    # الحصول على أكبر حجم صورة
    photo = update.message.photo[-1]

    # الحصول على نص المستخدم (إن وُجد)
    user_text = update.message.caption or ""

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # تحميل الصورة
        file = await context.bot.get_file(photo.file_id)
        image_url = file.file_path

        # تحليل الصورة
        response = await analyze_image(
            image_url=image_url,
            language=lang,
            user_message=user_text,
        )

        # حفظ في الذاكرة
        try:
            save_conversation(user_id, "user", f"[صورة] {user_text[:100]}")
            save_conversation(user_id, "bot", response[:200])
            detect_interests(user_id, user_text)
        except Exception:
            pass

        await update.message.reply_text(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in image_handler: {e}")
        if lang == "ar":
            await update.message.reply_text("❌ حصل خطأ في تحليل الصورة. جرب تاني.")
        else:
            await update.message.reply_text("❌ Error analyzing image. Please try again.")


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
        await _send_news_callback(query, context, lang)

    elif data == "cmd_trending":
        await _send_trending_callback(query, context, lang)

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
        # إرسال مؤشر الكتابة
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

        stages = COMPANY_STAGES(lang)
        progress = ProgressManager.__new__(ProgressManager)
        progress.update = update
        progress.context = context
        progress.stages = stages
        progress.lang = lang
        progress.title = f"تقرير: {company_key}" if lang == "ar" else f"Report: {company_key}"
        progress.progress_msg = None
        progress.typing_task = None
        progress.start_time = datetime.now().timestamp()
        progress._current_stage_idx = 0

        # نستخدم رسالة عادية كبداية
        loading_msg = await query.message.reply_text(
            f"⏳ {'جاري تجهيز تقرير الشركة...' if lang == 'ar' else 'Preparing company report...'}\n[████████░░] 80%"
        )

        try:
            report = await generate_company_report(company_key, lang)
            report = clean_ai_response(report)
            await loading_msg.edit_text(report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in company callback: {e}")
            await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))

    # ═══ خرائط الطريق ═══
    elif data.startswith("roadmap_"):
        topic = data.replace("roadmap_", "")
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

        loading_msg = await query.message.reply_text(
            f"⏳ {'جاري تجهيز خارطة الطريق...' if lang == 'ar' else 'Preparing roadmap...'}\n[████████░░] 80%"
        )

        try:
            roadmap = await generate_roadmap(topic, lang)
            roadmap = clean_ai_response(roadmap)
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

    # ═══ الاشتراك ═══
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
            msg = "👍 لا مشكلة! ممكن تشترك أي وقت من ⚙️ الإعدادات"
        else:
            msg = "👍 No problem! You can subscribe anytime from ⚙️ Settings"
        await query.message.edit_text(msg)

    # ═══ تغيير اللغة ═══
    elif data == "lang_ar":
        set_language(user_id, "ar")
        keyboard = get_main_keyboard("ar")
        if lang == "ar":
            msg = "✅ تم تغيير اللغة إلى العربية"
        else:
            msg = "✅ Language changed to Arabic"
        await query.message.edit_text(msg)
        await query.message.reply_text(
            welcome_message("ar", query.from_user.first_name or ""),
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "lang_en":
        set_language(user_id, "en")
        keyboard = get_main_keyboard("en")
        if lang == "ar":
            msg = "✅ Language changed to English"
        else:
            msg = "✅ Language changed to English"
        await query.message.edit_text(msg)
        await query.message.reply_text(
            welcome_message("en", query.from_user.first_name or ""),
            parse_mode="HTML",
            reply_markup=keyboard
        )


async def _send_news_callback(query, context, lang):
    """إرسال الأخبار من callback"""
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

    loading_msg = await query.message.reply_text(
        f"⏳ {'جاري جلب الأخبار...' if lang == 'ar' else 'Fetching news...'}\n[██░░░░░░░░] 20%"
    )

    try:
        articles = await fetch_news()
        if not articles:
            await loading_msg.edit_text("لا توجد أخبار AI جديدة حالياً. 🤖" if lang == "ar" else "No new AI news right now. 🤖")
            return

        await loading_msg.edit_text(
            f"⏳ {'فلترة وترتيب الأخبار...' if lang == 'ar' else 'Filtering & ranking...'}\n[██████░░░░] 60%"
        )

        filtered = filter_news(articles)
        if not filtered:
            await loading_msg.edit_text("لا توجد أخبار AI مرتبطة اليوم. 🤖" if lang == "ar" else "No AI-related news today. 🤖")
            return

        ranked = rank_articles(filtered)

        await loading_msg.edit_text(
            f"⏳ {'تلخيص الأخبار...' if lang == 'ar' else 'Summarizing news...'}\n[████████░░] 80%"
        )

        summarized = await summarize_articles(ranked)

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
            item = format_news_item(i + 1, article.get("title", ""), article.get("arabic_summary", article.get("description", "")[:200]), article.get("link", ""), is_top)
            items.append(item)

        footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — مساعدك الذكي</i>"
        message = header + "\n\n".join(items) + footer

        inline_keyboard = get_news_inline_buttons(lang)

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            await loading_msg.delete()
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await query.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)
                else:
                    await query.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True, reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"Error in _send_news_callback: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ أثناء جلب الأخبار" if lang == "ar" else "Error fetching news"))


async def _send_trending_callback(query, context, lang):
    """إرسال الترندات من callback"""
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

    loading_msg = await query.message.reply_text(
        f"⏳ {'جاري جلب الترندات...' if lang == 'ar' else 'Fetching trending...'}\n[████░░░░░░] 40%"
    )

    try:
        articles = await fetch_news()
        filtered = filter_news(articles)

        if not filtered:
            await loading_msg.edit_text("لا توجد ترندات حالياً. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
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
        logger.error(f"Error in _send_trending_callback: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


# ═══════════════════════════════════════
# المحادثة الحرة - Free Chat
# ═══════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل العادية - محادثة حرة مع AI"""
    user_id = update.effective_user.id
    user_text = update.message.text or ""
    lang = get_language(user_id)

    # تجاهل الرسائل الفارغة
    if not user_text.strip():
        return

    increment_chat_count(user_id)

    # التحقق من أزرار لوحة المفاتيح
    keyboard_commands = {
        "📰 الأخبار": "/news", "📰 News": "/news",
        "🤖 اسأل My Bro": "/ask", "🤖 Ask My Bro": "/ask",
        "📈 التريندات": "/trending", "📈 Trending": "/trending",
        "🔍 البحث": "/search", "🔍 Search": "/search",
        "📚 تعلم AI": "/learn", "📚 Learn AI": "/learn",
        "🏢 الشركات": "/company", "🏢 Companies": "/company",
        "⚙️ الإعدادات": "settings", "⚙️ Settings": "settings",
        "ℹ️ المساعدة": "/help", "ℹ️ Help": "/help",
    }

    if user_text in keyboard_commands:
        cmd = keyboard_commands[user_text]
        if cmd == "settings":
            user_sub = is_subscribed(user_id)
            keyboard = get_settings_keyboard(lang, user_sub)
            sub_status = "✅ مشترك" if user_sub else "❌ مش مشترك"
            if lang == "ar":
                msg = f"⚙️ <b>الإعدادات</b>\n\n📬 حالة الاشتراك: {sub_status}\n\nاختر ما تريد تغييره:"
            else:
                sub_status_en = "✅ Subscribed" if user_sub else "❌ Not subscribed"
                msg = f"⚙️ <b>Settings</b>\n\n📬 Subscription: {sub_status_en}\n\nChoose what to change:"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
            return
        elif cmd == "/ask":
            if lang == "ar":
                msg = "🤖 اكتب سؤالك وسأجيبك فوراً!"
            else:
                msg = "🤖 Type your question and I'll answer right away!"
            await update.message.reply_text(msg)
            return
        elif cmd == "/search":
            if lang == "ar":
                msg = "🔍 <b>البحث في أخبار AI والويب</b>\n\nاكتب ما تريد البحث عنه!"
            else:
                msg = "🔍 <b>Search AI News & Web</b>\n\nType what you want to search for!"
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        elif cmd == "/company":
            keyboard = get_companies_keyboard(lang)
            if lang == "ar":
                msg = "🏢 <b>اختر شركة</b>"
            else:
                msg = "🏢 <b>Choose a company</b>"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
            return
        elif cmd == "/learn":
            keyboard = get_roadmap_keyboard(lang)
            if lang == "ar":
                msg = "📚 <b>اختر موضوع للتعلم</b>"
            else:
                msg = "📚 <b>Choose a topic to learn</b>"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
            return
        else:
            # Simulate command
            context.args = []
            if cmd == "/news":
                await news_command(update, context)
            elif cmd == "/trending":
                await trending_command(update, context)
            elif cmd == "/help":
                await help_command(update, context)
            return

    # محادثة ذكية مع AI
    stages = AI_STAGES(lang)
    title = "التفكير" if lang == "ar" else "Thinking"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)

        # حفظ المحادثة + كشف الاهتمامات
        try:
            save_conversation(user_id, "user", user_text)
            detect_interests(user_id, user_text)
        except Exception as e:
            logger.debug(f"Memory save error (non-critical): {e}")

        response = await smart_chat(user_text, lang, user_id=user_id)
        # تنظيف رد AI من Markdown
        response = clean_ai_response(response)
        await progress.update_stage(2)

        # حفظ رد البوت
        try:
            save_conversation(user_id, "bot", response[:500])
        except Exception:
            pass

        # لو الرسالة طويلة، نحذف رسالة التقدم ونرسل جديدة
        if len(response) > 4000:
            await progress.complete(delete_progress=True)
            chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await progress.complete(final_message=response, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await progress.error("حدث خطأ أثناء المعالجة" if lang == "ar" else "Error processing your message")


# ═══════════════════════════════════════
# بث الأخبار اليومية - Daily News Broadcast
# ═══════════════════════════════════════

async def broadcast_daily_news(context: ContextTypes.DEFAULT_TYPE):
    """
    بث الأخبار اليومية لكل المشتركين
    يتم استدعاؤها تلقائياً من APScheduler
    """
    logger.info("=" * 50)
    logger.info("Starting daily news broadcast")
    logger.info("=" * 50)

    try:
        # جلب الأخبار
        articles = await fetch_news()
        if not articles:
            logger.warning("No articles fetched. Skipping broadcast.")
            return

        # فلترة
        filtered = filter_news(articles)
        if not filtered:
            logger.warning("No AI-related articles found. Skipping broadcast.")
            return

        # ترتيب
        ranked = rank_articles(filtered)

        # تلخيص
        summarized = await summarize_articles(ranked)

        # تجهيز الرسائل
        now = datetime.now(timezone(timedelta(hours=2)))
        days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        months_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

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

        # بث لكل المشتركين
        subscribers = get_all_subscribers()

        if not subscribers:
            logger.warning("No subscribers found. Skipping broadcast.")
            return

        logger.info(f"Broadcasting to {len(subscribers)} subscribers")

        success_count = 0
        fail_count = 0

        for subscriber in subscribers:
            chat_id = subscriber["user_id"]
            lang = subscriber.get("language", "ar")
            message = messages.get(lang, messages["ar"])

            try:
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
        logger.error(f"❌ Critical error in broadcast: {e}", exc_info=True)


# ═══════════════════════════════════════
# تشغيل البوت - Main
# ═══════════════════════════════════════

# متغير عام للـ scheduler
_scheduler = None


def main():
    """تشغيل البوت مع الجدولة"""
    global _scheduler

    logger.info("=" * 60)
    logger.info(f"🤖 {BOT_NAME} v{BOT_VERSION} Starting...")
    logger.info("=" * 60)

    # التأكد من إن BOT_TOKEN موجود
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set! Set it as environment variable.")
        sys.exit(1)

    # بناء التطبيق
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
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("favorite", favorite_command))
    app.add_handler(CommandHandler("favorites", favorites_command))
    app.add_handler(CommandHandler("forget", forget_command))
    app.add_handler(CommandHandler("resetmemory", resetmemory_command))
    app.add_handler(CommandHandler("deepsearch", deepsearch_command))
    app.add_handler(CommandHandler("status", status_command))

    # أزرار Inline
    app.add_handler(CallbackQueryHandler(button_callback))

    # المحادثة الحرة
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # معالجة الصور - Image handler
    app.add_handler(MessageHandler(filters.PHOTO, image_handler))

    # ═══ إعداد الجدولة (APScheduler) - يتم تشغيله داخل event loop ═══
    _scheduler = AsyncIOScheduler(timezone=pytz.timezone(DAILY_NEWS_TIMEZONE))

    async def scheduled_broadcast():
        """بث مجدول مع context البوت"""
        # إنشاء context وهمي فيه bot فقط عشان broadcast_daily_news يشتغل
        class FakeContext:
            def __init__(self, bot):
                self.bot = bot
        await broadcast_daily_news(FakeContext(app.bot))

    _scheduler.add_job(
        scheduled_broadcast,
        trigger="cron",
        hour=DAILY_NEWS_HOUR,
        minute=DAILY_NEWS_MINUTE,
        id="daily_news_broadcast",
        name="Daily AI News Broadcast",
    )

    # تعيين أوامر البوت + تشغيل الجدولة بعد بدء event loop
    async def post_init(application):
        """بعد تشغيل البوت - inside event loop"""
        # تسجيل الأوامر في تيليجرام - Register commands with Telegram
        try:
            from telegram import BotCommand
            await application.bot.set_my_commands([
                BotCommand("start", "بدء البوت / Start the bot"),
                BotCommand("help", "المساعدة / Help"),
                BotCommand("news", "أخبار AI / AI News"),
                BotCommand("breaking", "خبر عاجل / Breaking news"),
                BotCommand("weekly", "ملخص أسبوعي / Weekly summary"),
                BotCommand("trending", "الترندات / Trending"),
                BotCommand("search", "بحث / Search"),
                BotCommand("deepsearch", "بحث عميق / Deep search"),
                BotCommand("ask", "سؤال / Ask question"),
                BotCommand("learn", "تعلم / Learn topic"),
                BotCommand("roadmap", "خارطة طريق / Roadmap"),
                BotCommand("company", "تقرير شركة / Company report"),
                BotCommand("subscribe", "اشترك / Subscribe"),
                BotCommand("unsubscribe", "إلغاء اشتراك / Unsubscribe"),
                BotCommand("memory", "ذاكرتي / My memory"),
                BotCommand("progress", "تقدم التعلم / Learning progress"),
                BotCommand("favorite", "مفضلة / Favorite"),
                BotCommand("favorites", "المفضلات / Favorites"),
                BotCommand("forget", "امسح ذكرى / Forget memory"),
                BotCommand("resetmemory", "مسح الكل / Reset memory"),
                BotCommand("language", "اللغة / Language"),
                BotCommand("about", "عن البوت / About"),
                BotCommand("status", "حالة النظام / System status"),
            ])
            logger.info("Bot commands registered with Telegram successfully")
        except Exception as e:
            logger.warning(f"Failed to register commands with Telegram: {e}")

        # تشغيل الجدولة هنا (داخل event loop)
        _scheduler.start()
        logger.info(f"📅 Scheduler started - Daily broadcast at {DAILY_NEWS_HOUR}:{DAILY_NEWS_MINUTE:02d} ({DAILY_NEWS_TIMEZONE})")

    app.post_init = post_init

    # تشغيل البوت
    logger.info("🚀 Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
