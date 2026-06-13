"""
News-related command handlers.
"""

import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from config import BOT_NAME
from memory import (
    get_language, increment_command_count,
)
from formatters import (
    format_news_item, format_error, _strip_non_telegram_html, _quick_clean_text,
)
from news_fetcher import fetch_news
from filters import filter_news
from scorer import rank_articles
from summarizer import summarize_articles
from progress import ProgressManager, NEWS_STAGES, SEARCH_STAGES, TelegramThinkingFeedback
from dashboard import track_event

from handlers.keyboards import get_news_inline_buttons, get_trending_inline_buttons
from handlers.dedup import _is_duplicate_update, _is_duplicate_user_message
from handlers.error_monitor import record_error

logger = logging.getLogger(__name__)


def _get_article_title(article: dict, lang: str = "ar") -> str:
    """🔴 FIX: نرجع العنوان العربي لو متاح واللغة عربي، غير كده العنوان الأصلي"""
    if lang == "ar":
        ar_title = article.get("arabic_title", "")
        if ar_title:
            return ar_title
    return article.get("title", "")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /news - أخبار AI اليوم مع نظام تقدم متميز"""
    from premium import check_limit, limit_reached_message, get_premium_keyboard

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # 🔴 FIX: فحص الكوتا — لو المستخدم المجاني خلص حد الرسائل، الأخبار تقف
    quota_check = check_limit(user_id, "ai_messages_per_day", update.effective_user.username if update.effective_user else None)
    if not quota_check["allowed"] and quota_check["plan"] == "free":
        feature_name = "📰 أخبار AI" if lang == "ar" else "📰 AI News"
        await update.message.reply_text(
            limit_reached_message(feature_name, quota_check["remaining"], quota_check["limit"], lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    try:
        track_event("total_commands")
    except Exception:
        pass

    stages = NEWS_STAGES(lang)
    title = "جلب أخبار AI" if lang == "ar" else "Fetching AI News"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        articles = await fetch_news()
        if not articles:
            await progress.error("لا توجد أخبار AI جديدة حاليًا. 🤖" if lang == "ar" else "No new AI news right now. 🤖")
            return

        await progress.update_stage(1)
        filtered = filter_news(articles)
        if not filtered:
            await progress.error("لا توجد أخبار AI مرتبطة اليوم. 🤖" if lang == "ar" else "No AI-related news today. 🤖")
            return

        await progress.update_stage(2)
        ranked = rank_articles(filtered)

        await progress.update_stage(3)
        summarized = await summarize_articles(ranked)

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
            category = article.get("category", "")
            item = format_news_item(
                i + 1,
                _get_article_title(article, lang),  # 🔴 FIX: استخدام العنوان العربي
                article.get("arabic_summary", article.get("description", "")[:200]),
                article.get("link", ""),
                is_top,
                category,
                language=lang,  # 🔴 FIX: اللغة
            )
            items.append(item)

        if lang == "ar":
            footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — مساعدك الذكي</i>"
        else:
            footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Your Smart Assistant</i>"
        message = header + "\n\n".join(items) + footer

        inline_keyboard = get_news_inline_buttons(lang)

        if len(message) > 4000:
            chunks = smart_split_message(message)
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
        try:
            track_event("total_errors")
            await record_error("news_command", str(e))
        except Exception:
            pass
        await progress.error("حدث خطأ أثناء جلب الأخبار" if lang == "ar" else "Error fetching news")


async def breaking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /breaking - أهم خبر حالي"""
    from premium import check_limit, limit_reached_message, get_premium_keyboard

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # 🔴 FIX: فحص الكوتا — لو المستخدم المجاني خلص حد الرسائل، الأخبار العاجلة تقف
    quota_check = check_limit(user_id, "ai_messages_per_day", update.effective_user.username if update.effective_user else None)
    if not quota_check["allowed"] and quota_check["plan"] == "free":
        feature_name = "🔴 أخبار عاجلة" if lang == "ar" else "🔴 Breaking News"
        await update.message.reply_text(
            limit_reached_message(feature_name, quota_check["remaining"], quota_check["limit"], lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    try:
        track_event("total_commands")
    except Exception:
        pass

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
            await progress.error("لا توجد أخبار عاجلة حاليًا. 🤖" if lang == "ar" else "No breaking news right now. 🤖")
            return

        await progress.update_stage(2)
        ranked = rank_articles(filtered)
        top = ranked[0] if ranked else None

        if not top:
            await progress.error("لا توجد أخبار عاجلة حاليًا. 🤖" if lang == "ar" else "No breaking news right now. 🤖")
            return

        summarized = await summarize_articles([top])

        if lang == "ar":
            message = f"""🔴 <b>خبر عاجل</b>
━━━━━━━━━━━━━━━━━

{format_news_item(1, _get_article_title(summarized[0], lang), summarized[0].get('arabic_summary', ''), summarized[0]['link'], True, summarized[0].get('category', ''), language=lang)}

━━━━━━━━━━━━━━━━━
🤖 <i>My Bro — تنبيه عاجل</i>"""
        else:
            message = f"""🔴 <b>Breaking News</b>
━━━━━━━━━━━━━━━━━

{format_news_item(1, _get_article_title(summarized[0], lang), summarized[0].get('arabic_summary', ''), summarized[0]['link'], True, summarized[0].get('category', ''), language=lang)}

━━━━━━━━━━━━━━━━━
🤖 <i>My Bro — Breaking Alert</i>"""

        inline_keyboard = get_news_inline_buttons(lang)
        await progress.complete(final_message=message, reply_markup=inline_keyboard, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in /breaking: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /weekly - ملخص الأسبوع"""
    from premium import check_limit, limit_reached_message, get_premium_keyboard

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # 🔴 FIX: فحص الكوتا — لو المستخدم المجاني خلص حد الرسائل، الملخص الأسبوعي يقف
    quota_check = check_limit(user_id, "ai_messages_per_day", update.effective_user.username if update.effective_user else None)
    if not quota_check["allowed"] and quota_check["plan"] == "free":
        feature_name = "📊 ملخص أسبوعي" if lang == "ar" else "📊 Weekly Summary"
        await update.message.reply_text(
            limit_reached_message(feature_name, quota_check["remaining"], quota_check["limit"], lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    try:
        track_event("total_commands")
    except Exception:
        pass

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
                i + 1, _get_article_title(article, lang),  # 🔴 FIX: استخدام العنوان العربي
                article.get('arabic_summary', ''),
                article['link'],
                article.get('is_top', False),
                article.get('category', ''),
                language=lang,  # 🔴 FIX: اللغة
            ))

        message = header + "\n\n".join(items) + footer
        inline_keyboard = get_news_inline_buttons(lang)

        if len(message) > 4000:
            chunks = smart_split_message(message)
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
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /trending - الترندات"""
    from premium import check_limit, limit_reached_message, get_premium_keyboard

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # 🔴 FIX: فحص الكوتا — لو المستخدم المجاني خلص حد الرسائل، الترندات تقف
    quota_check = check_limit(user_id, "ai_messages_per_day", update.effective_user.username if update.effective_user else None)
    if not quota_check["allowed"] and quota_check["plan"] == "free":
        feature_name = "📈 الترندات" if lang == "ar" else "📈 Trending"
        await update.message.reply_text(
            limit_reached_message(feature_name, quota_check["remaining"], quota_check["limit"], lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    try:
        track_event("total_commands")
    except Exception:
        pass

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
            await progress.error("لا توجد ترندات حاليًا. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
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
            await progress.error("لا توجد ترندات حاليًا. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
            return

        if lang == "ar":
            message = "📈 <b>ترندات الذكاء الاصطناعي</b>\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            message = "📈 <b>AI Trending Topics</b>\n━━━━━━━━━━━━━━━━━\n\n"

        # 🔴 FIX: بناء رسالة الترندات مع ترجمة الكلمات المفتاحية للعربي
        trending_lines = []
        for i, (keyword, count) in enumerate(top_trends, 1):
            if lang == "ar":
                trending_lines.append(f"{i}. 🔥 <b>{keyword.upper()}</b> — ذُكر {count} مرة\n")
            else:
                trending_lines.append(f"{i}. 🔥 <b>{keyword.upper()}</b> — mentioned {count} times\n")

        # 🔴 FIX: لو اللغة عربي، نترجم الكلمات المفتاحية للعربي
        if lang == "ar" and top_trends:
            try:
                from provider_manager import call_ai
                keywords_en = [kw for kw, _ in top_trends]
                translation = await call_ai(
                    f"ترجم الكلمات التالية من الإنجليزية للعربية (عربية فصحى واضحة، أسماء الشركات سيبها بالإنجليزي):\n" + "\n".join(f"{i+1}. {kw}" for i, kw in enumerate(keywords_en)),
                    system_prompt="أنت مترجم محترم. تترجم بدقة. ماتستخدمش Markdown. رجع كل كلمة مترجمة في سطر منفصل بالتنسيق: الرقم. الكلمة_الإنجليزية = الكلمة_العربية",
                    task_type="simple",
                    temperature=0.1,
                    max_tokens=500,
                    user_id=user_id,
                )
                if translation:
                    # بناء dictionary للترجمة
                    keyword_translations = {}
                    for line in translation.strip().split("\n"):
                        line = line.strip()
                        if "=" in line:
                            parts = line.split("=", 1)
                            en = parts[0].strip().lstrip("0123456789. ")
                            ar = parts[1].strip()
                            if en and ar:
                                keyword_translations[en.lower()] = ar
                    
                    # إعادة بناء الرسالة بالعربي
                    if keyword_translations:
                        trending_lines = []
                        for i, (keyword, count) in enumerate(top_trends, 1):
                            ar_keyword = keyword_translations.get(keyword.lower(), "")
                            if ar_keyword:
                                trending_lines.append(f"{i}. 🔥 <b>{ar_keyword}</b> ({keyword.upper()}) — ذُكر {count} مرة\n")
                            else:
                                trending_lines.append(f"{i}. 🔥 <b>{keyword.upper()}</b> — ذُكر {count} مرة\n")
            except Exception as e:
                logger.warning(f"⚠️ Trending keywords translation failed: {e}")

        message += "".join(trending_lines)

        # 🔴 FIX: فوتر الترندات باللغة المناسبة
        if lang == "ar":
            message += "\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — تتبع الترندات</i>\n\n💡 <i>اضغط على رقم الترند عشان تجيب تفاصيله!</i>"
        else:
            message += "\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Trending Tracker</i>\n\n💡 <i>Tap a trend number to get its details!</i>"

        # 🔴 FIX: احفظ الترندات للمستخدم عشان الأزرار المرقمة تشتغل
        from handlers.callbacks import _user_trends
        _user_trends[user_id] = top_trends

        # 🔴 FIX: استخدمنا كيبورد الترندات الجديد (أزرار مرقمة) بدل كيبورد الأخبار
        inline_keyboard = get_trending_inline_buttons(lang, top_trends)
        await progress.complete(final_message=message, reply_markup=inline_keyboard, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in /trending: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /search <query> - بحث في الويب + أخبار RSS"""
    from premium import check_limit, increment_usage, limit_reached_message, get_premium_keyboard
    from handlers.callbacks import _check_premium_limit

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check
    if not await _check_premium_limit(update, user_id, "searches_per_day", lang):
        return

    try:
        track_event("total_commands")
        track_event("search_requests")
    except Exception:
        pass

    query = " ".join(context.args) if context.args else ""

    if not query:
        if lang == "ar":
            msg = "🔍 <b>البحث في أخبار AI والويب</b>\n\nاكتب كلمة البحث بعد الأمر\nمثال: <code>/search الحضارة الإسلامية</code>\n\nأو اضغط على زر 🔍 البحث واكتب ما تريد البحث عنه."
        else:
            msg = "🔍 <b>Search AI News & Web</b>\n\nType your search query after the command\nExample: <code>/search Islamic civilization</code>\n\nOr tap 🔍 Search and type what you want to find."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    increment_usage(user_id, "searches")

    stages = SEARCH_STAGES(lang)
    title = f"بحث: {query}" if lang == "ar" else f"Searching: {query}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
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
        web_results = await search_web(query, max_results=5, language=lang)

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
                    i + 1, _get_article_title(article, lang),  # 🔴 FIX: استخدام العنوان العربي
                    article.get('arabic_summary', ''),
                    article['link'],
                    i == 0,
                    article.get('category', ''),
                    language=lang,  # 🔴 FIX: اللغة
                )
                message += "\n\n"

        if web_results:
            if lang == "ar":
                message += f"🌐 <b>نتائج بحث الويب: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"
            else:
                message += f"🌐 <b>Web Search: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"

            # 🔴 FIX: لو اللغة عربي، نترجم نتائج البحث للعربي
            if lang == "ar" and web_results:
                try:
                    from provider_manager import call_ai
                    # تجميع العناوين والمقتطفات للترجمة
                    texts_to_translate = []
                    for r in web_results[:5]:
                        t = r.get("title", "")
                        s = r.get("snippet", "")[:150]
                        texts_to_translate.append(f"TITLE: {t}\nSNIPPET: {s}")
                    
                    combined = "\n---\n".join(texts_to_translate)
                    translation_prompt = f"""ترجم العناوين والمقتطفات التالية من الإنجليزية للعربية (عربية فصحى واضحة).
⚠️ ماتستخدمش Markdown. استخدم HTML فقط.
⚠️ حافظ على التنسيق: TITLE: [العنوان المترجم] SNIPPET: [المقتطف المترجم]
⚠️ أسماء العلم والشركات سيبها بالإنجليزي زي ما هي

{combined}"""
                    translated = await call_ai(
                        translation_prompt,
                        system_prompt="أنت مترجم محترف من الإنجليزية للعربية. تترجم بدقة ووضوح. ماتستخدمش Markdown.",
                        task_type="simple",
                        temperature=0.2,
                        max_tokens=8192,
                        user_id=user_id,
                    )
                    
                    if translated:
                        # تفكيك الترجمة
                        translated_parts = translated.split("---")
                        for i, r in enumerate(web_results[:5], 1):
                            title_text = _quick_clean_text(r.get("title", ""))
                            snippet = r.get("snippet", "")
                            link = r.get("link", "")
                            
                            # محاولة استخدام النص المترجم
                            if i-1 < len(translated_parts):
                                part = translated_parts[i-1]
                                # استخراج العنوان والمقتطف المترجم
                                trans_title = title_text
                                trans_snippet = _quick_clean_text(_strip_non_telegram_html(snippet))[:200]
                                for line in part.strip().split("\n"):
                                    line = line.strip()
                                    if line.upper().startswith("TITLE:"):
                                        trans_title = _quick_clean_text(line[6:].strip())
                                    elif line.upper().startswith("SNIPPET:"):
                                        trans_snippet = _quick_clean_text(_strip_non_telegram_html(line[8:].strip()))[:200]
                                title_text = trans_title
                                snippet = trans_snippet
                            
                            message += f"{i}. 📄 <b>{title_text}</b>\n"
                            if snippet:
                                message += f"   {snippet}\n"
                            if link:
                                message += f'   🔗 <a href="{link}">اقرأ المزيد</a>\n'
                            message += "\n"
                    else:
                        # fallback: عرض النتائج بدون ترجمة
                        for i, r in enumerate(web_results[:5], 1):
                            title_text = _quick_clean_text(r.get("title", ""))
                            snippet = _quick_clean_text(_strip_non_telegram_html(r.get("snippet", "")))[:200]
                            link = r.get("link", "")
                            message += f"{i}. 📄 <b>{title_text}</b>\n"
                            if snippet:
                                message += f"   {snippet}\n"
                            if link:
                                message += f'   🔗 <a href="{link}">اقرأ المزيد</a>\n'
                            message += "\n"
                except Exception as e:
                    logger.warning(f"⚠️ Translation of search results failed: {e}")
                    # fallback: عرض بدون ترجمة
                    for i, r in enumerate(web_results[:5], 1):
                        title_text = _quick_clean_text(r.get("title", ""))
                        snippet = _quick_clean_text(_strip_non_telegram_html(r.get("snippet", "")))[:200]
                        link = r.get("link", "")
                        message += f"{i}. 📄 <b>{title_text}</b>\n"
                        if snippet:
                            message += f"   {snippet}\n"
                        if link:
                            message += f'   🔗 <a href="{link}">اقرأ المزيد</a>\n'
                        message += "\n"
            else:
                # English: عرض النتائج كما هي
                for i, r in enumerate(web_results[:5], 1):
                    title_text = _quick_clean_text(r.get("title", ""))
                    snippet = _quick_clean_text(_strip_non_telegram_html(r.get("snippet", "")))[:200]
                    link = r.get("link", "")
                    message += f"{i}. 📄 <b>{title_text}</b>\n"
                    if snippet:
                        message += f"   {snippet}\n"
                    if link:
                        message += f'   🔗 <a href="{link}">Read more</a>\n'
                    message += "\n"

        await progress.update_stage(2)

        if not rss_results and not web_results:
            from ai_engine import smart_chat
            ai_response = await smart_chat(f"ابحث عن معلومات عن: {query}" if lang == "ar" else f"Search for information about: {query}", lang, user_id=user_id, username=update.effective_user.username)
            message = ai_response
        else:
            if lang == "ar":
                message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — بحث متقدم</i>"
            else:
                message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Advanced Search</i>"

        if len(message) > 4000:
            chunks = smart_split_message(message)
            await progress.complete(delete_progress=True)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await progress.complete(final_message=message, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in /search: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ في البحث" if lang == "ar" else "Search error")


async def _send_news_callback(query, context, lang):
    """إرسال الأخبار من callback"""
    from datetime import datetime, timezone, timedelta

    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

    loading_msg = await query.message.reply_text(
        f"⏳ {'جاري جلب الأخبار...' if lang == 'ar' else 'Fetching news...'}\n[██░░░░░░░░] 20%"
    )

    try:
        articles = await fetch_news()
        if not articles:
            await loading_msg.edit_text("لا توجد أخبار AI جديدة حاليًا. 🤖" if lang == "ar" else "No new AI news right now. 🤖")
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
            item = format_news_item(i + 1, _get_article_title(article, lang), article.get("arabic_summary", article.get("description", "")[:200]), article.get("link", ""), is_top, article.get("category", ""), language=lang)
            items.append(item)

        if lang == "ar":
            footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — مساعدك الذكي</i>"
        else:
            footer = "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Your Smart Assistant</i>"
        message = header + "\n\n".join(items) + footer

        inline_keyboard = get_news_inline_buttons(lang)

        if len(message) > 4000:
            chunks = smart_split_message(message)
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
            await loading_msg.edit_text("لا توجد ترندات حاليًا. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
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
            await loading_msg.edit_text("لا توجد ترندات حاليًا. 🤖" if lang == "ar" else "No trending topics right now. 🤖")
            return

        if lang == "ar":
            message = "📈 <b>ترندات الذكاء الاصطناعي</b>\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            message = "📈 <b>AI Trending Topics</b>\n━━━━━━━━━━━━━━━━━\n\n"

        # 🔴 FIX: بناء رسالة الترندات مع ترجمة الكلمات المفتاحية للعربي
        trending_lines = []
        for i, (keyword, count) in enumerate(top_trends, 1):
            if lang == "ar":
                trending_lines.append(f"{i}. 🔥 <b>{keyword.upper()}</b> — ذُكر {count} مرة\n")
            else:
                trending_lines.append(f"{i}. 🔥 <b>{keyword.upper()}</b> — mentioned {count} times\n")

        # 🔴 FIX: لو اللغة عربي، نترجم الكلمات المفتاحية
        if lang == "ar" and top_trends:
            try:
                from provider_manager import call_ai
                keywords_en = [kw for kw, _ in top_trends]
                translation = await call_ai(
                    f"ترجم الكلمات التالية من الإنجليزية للعربية (عربية فصحى واضحة، أسماء الشركات سيبها بالإنجليزي):\n" + "\n".join(f"{i+1}. {kw}" for i, kw in enumerate(keywords_en)),
                    system_prompt="أنت مترجم محترم. تترجم بدقة. ماتستخدمش Markdown. رجع كل كلمة مترجمة في سطر منفصل بالتنسيق: الرقم. الكلمة_الإنجليزية = الكلمة_العربية",
                    task_type="simple",
                    temperature=0.1,
                    max_tokens=500,
                    user_id=query.from_user.id,
                )
                if translation:
                    keyword_translations = {}
                    for line in translation.strip().split("\n"):
                        line = line.strip()
                        if "=" in line:
                            parts = line.split("=", 1)
                            en = parts[0].strip().lstrip("0123456789. ")
                            ar = parts[1].strip()
                            if en and ar:
                                keyword_translations[en.lower()] = ar
                    
                    if keyword_translations:
                        trending_lines = []
                        for i, (keyword, count) in enumerate(top_trends, 1):
                            ar_keyword = keyword_translations.get(keyword.lower(), "")
                            if ar_keyword:
                                trending_lines.append(f"{i}. 🔥 <b>{ar_keyword}</b> ({keyword.upper()}) — ذُكر {count} مرة\n")
                            else:
                                trending_lines.append(f"{i}. 🔥 <b>{keyword.upper()}</b> — ذُكر {count} مرة\n")
            except Exception as e:
                logger.warning(f"⚠️ Trending keywords translation in callback failed: {e}")

        message += "".join(trending_lines)

        # 🔴 FIX: فوتر الترندات باللغة المناسبة
        if lang == "ar":
            message += "\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — تتبع الترندات</i>\n\n💡 <i>اضغط على رقم الترند عشان تجيب تفاصيله!</i>"
        else:
            message += "\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Trending Tracker</i>\n\n💡 <i>Tap a trend number to get its details!</i>"

        # 🔴 FIX: احفظ الترندات للمستخدم عشان الأزرار المرقمة تشتغل
        user_id = query.from_user.id
        from handlers.callbacks import _user_trends
        _user_trends[user_id] = top_trends

        # 🔴 FIX: استخدمنا كيبورد الترندات الجديد (أزرار مرقمة) بدل كيبورد الأخبار
        inline_keyboard = get_trending_inline_buttons(lang, top_trends)
        await loading_msg.edit_text(message, parse_mode="HTML", reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"Error in _send_trending_callback: {e}")
        await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))
