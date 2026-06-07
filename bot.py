"""
My Bro - مساعد الذكاء الاصطناعي الشخصي
بوت تيليجرام كامل مع أوامر + محادثة ذكية + بحث ويب
"""

import logging
import sys
import re
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

from config import BOT_TOKEN, BOT_NAME, BOT_VERSION
from ai_engine import smart_chat, ask_question, explain_topic, generate_roadmap, generate_company_report
from memory import (
    get_user, get_language, set_language, get_news_time,
    set_news_time, set_sources, get_sources,
    increment_command_count, increment_chat_count
)
from formatters import (
    welcome_message, help_message, format_news_item,
    format_trending_item, format_error, format_loading,
    language_selection, time_selection, sources_selection
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
# أوامر البوت
# ═══════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    await update.message.reply_text(
        welcome_message(lang),
        parse_mode="HTML",
        disable_web_page_preview=True
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

        # تقسيم لو الرسالة طويلة
        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            await loading_msg.delete()
        else:
            await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True)

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

        await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True)

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
        # جلب أخبار الأسبوع
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

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            await loading_msg.delete()
        else:
            await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True)

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

        # استخراج الترندات من العناوين
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

        await loading_msg.edit_text(message, parse_mode="HTML")

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
        await update.message.reply_text(
            "❌ اكتب كلمة البحث بعد الأمر\nمثال: <code>/search OpenAI</code>" if lang == "ar"
            else "❌ Please provide a search query\nExample: <code>/search OpenAI</code>",
            parse_mode="HTML"
        )
        return

    loading_msg = await update.message.reply_text(
        "🔍 جاري البحث..." if lang == "ar" else "🔍 Searching..."
    )

    try:
        # 1. أولاً: بحث في أخبار RSS المحلية
        articles = fetch_news()
        query_lower = query.lower()
        rss_results = []
        for article in articles:
            title = article.get("title", "").lower()
            desc = article.get("description", "").lower()
            if query_lower in title or query_lower in desc:
                rss_results.append(article)

        # 2. ثانياً: بحث في الويب باستخدام DuckDuckGo
        from web_search import search_web, format_search_results
        web_results = search_web(query, max_results=5)

        # بناء الرسالة
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
            # لو مفيش نتائج خالص، نستخدم AI
            if lang == "ar":
                ai_response = smart_chat(f"ابحث عن معلومات عن: {query}", lang)
            else:
                ai_response = smart_chat(f"Search for information about: {query}", lang)
            message = ai_response
        else:
            message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — بحث متقدم</i>"

        # تقسيم لو الرسالة طويلة
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
        from config import COMPANY_DATA
        available = ", ".join(COMPANY_DATA.keys())
        await update.message.reply_text(
            f"❌ اكتب اسم الشركة بعد الأمر\nالشركات المتاحة: <code>{available}</code>" if lang == "ar"
            else f"❌ Please provide a company name\nAvailable: <code>{available}</code>",
            parse_mode="HTML"
        )
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
        await update.message.reply_text(
            "❌ اكتب سؤالك بعد الأمر\nمثال: <code>/ask What are AI Agents?</code>" if lang == "ar"
            else "❌ Please provide a question\nExample: <code>/ask What are AI Agents?</code>",
            parse_mode="HTML"
        )
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
        await update.message.reply_text(
            "❌ اكتب الموضوع بعد الأمر\nمثال: <code>/learn transformers</code>" if lang == "ar"
            else "❌ Please provide a topic\nExample: <code>/learn transformers</code>",
            parse_mode="HTML"
        )
        return

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        explanation = explain_topic(topic, lang)
        await loading_msg.edit_text(explanation, parse_mode="HTML")
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
        await update.message.reply_text(
            "❌ اكتب الموضوع بعد الأمر\nمثال: <code>/roadmap ai</code>\n\nالمتاح: ai, ml, deep learning, nlp, llm" if lang == "ar"
            else "❌ Please provide a topic\nExample: <code>/roadmap ai</code>\n\nAvailable: ai, ml, deep learning, nlp, llm",
            parse_mode="HTML"
        )
        return

    loading_msg = await update.message.reply_text(format_loading(lang))

    try:
        roadmap = generate_roadmap(topic, lang)
        await loading_msg.edit_text(roadmap, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in /roadmap: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))


# ═══════════════════════════════════════
# إعدادات البوت
# ═══════════════════════════════════════

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /language"""
    user_id = update.effective_user.id
    increment_command_count(user_id)
    user_states[user_id] = "awaiting_language"
    await update.message.reply_text(language_selection(), parse_mode="HTML")


async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /time"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    current = get_news_time(user_id)
    user_states[user_id] = "awaiting_time"
    await update.message.reply_text(time_selection(current, lang), parse_mode="HTML")


async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /sources"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)
    current = get_sources(user_id)
    user_states[user_id] = "awaiting_sources"
    await update.message.reply_text(sources_selection(lang), parse_mode="HTML")


# ═══════════════════════════════════════
# المحادثة الذكية (بدون أوامر)
# ═══════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالجة الرسائل العادية (محادثة ذكية + إعدادات)
    + بحث ويب تلقائي لو المستخدم سأل عن شيء يحتاج معلومات حالية
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()
    lang = get_language(user_id)

    # التحقق من حالة الإعدادات
    state = user_states.get(user_id)

    if state == "awaiting_language":
        if text in ["1", "١", "ar", "عربي", "العربية"]:
            set_language(user_id, "ar")
            user_states.pop(user_id, None)
            await update.message.reply_text("✅ تم تغيير اللغة إلى العربية")
            return
        elif text in ["2", "٢", "en", "english", "إنجليزي"]:
            set_language(user_id, "en")
            user_states.pop(user_id, None)
            await update.message.reply_text("✅ Language changed to English")
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

    # محادثة ذكية عادية (+ بحث ويب تلقائي)
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
# تشغيل البوت
# ═══════════════════════════════════════

def main():
    """تشغيل البوت"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        sys.exit(1)

    logger.info(f"Starting {BOT_NAME} v{BOT_VERSION}...")

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

    # معالجة الرسائل العادية (محادثة ذكية)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # تسجيل أوامر البوت في تيليجرام
    async def post_init(application):
        commands = [
            ("start", "👋 Welcome"),
            ("help", "📖 All commands"),
            ("news", "📰 AI News today"),
            ("breaking", "🔴 Breaking news"),
            ("weekly", "📊 Weekly summary"),
            ("trending", "📈 Trending topics"),
            ("search", "🔍 Search AI news & web"),
            ("company", "🏢 Company report"),
            ("ask", "💬 Ask a question"),
            ("learn", "📚 Learn a topic"),
            ("roadmap", "🗺️ Learning roadmap"),
            ("language", "🌐 Change language"),
            ("time", "⏰ News time"),
            ("sources", "📡 Preferred sources"),
        ]
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands registered")

    app.post_init = post_init

    logger.info(f"{BOT_NAME} v{BOT_VERSION} is running! 🚀")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
