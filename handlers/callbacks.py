"""
Callback query handler and settings state management.
"""

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ai_engine import generate_company_report, generate_roadmap
from memory import (
    get_language, set_language, get_news_time,
    subscribe_user, unsubscribe_user, is_subscribed,
)
from formatters import (
    welcome_message, format_error,
    time_selection, sources_selection,
    subscription_confirmed, unsubscription_confirmed,
)
from premium import (
    check_limit, premium_features_message, get_premium_keyboard,
)
from admin import is_admin, handle_admin_callback

from handlers.keyboards import (
    get_main_keyboard, get_news_inline_buttons, get_trending_inline_buttons,
    get_language_keyboard, get_settings_keyboard, get_roadmap_keyboard,
)
from handlers.error_monitor import record_error

logger = logging.getLogger(__name__)

# ═══ User state management ═══
user_states = {}  # {user_id: {"state": str, "data": dict}}

# ═══ Temporary storage for PDF/YouTube/Image context per user ═══
_user_pdf_context = {}   # {user_id: {"text": str, "filename": str}}
_user_yt_context = {}    # {user_id: {"url": str, "video_id": str, "title": str}}
_user_image_context = {} # {user_id: {"image_base64": str, "user_text": str}}
_user_trends = {}       # {user_id: [(keyword, count), ...]} — ترندات المستخدم عشان الأزرار المرقمة
_user_truncated = {}    # {user_id: {"response": str, "user_message": str, "lang": str}} — آخر رد مقطوع عشان نكمله


def _get_pdf_context(user_id: int) -> dict:
    """استرجاع سياق PDF - أولاً من الذاكرة، وبعدين من الداتابيز"""
    # محاولة 1: من الذاكرة (أسرع)
    ctx = _user_pdf_context.get(user_id)
    if ctx and ctx.get("text"):
        return ctx

    # محاولة 2: من الداتابيز (دائم - يشتغل حتى بعد الـ restart)
    try:
        from memory import get_memories
        memories = get_memories(user_id, "system")
        text = None
        filename = None
        for m in memories:
            if m["key"] == "pdf_context_text":
                text = m["value"]
            elif m["key"] == "pdf_context_filename":
                filename = m["value"]
        if text:
            ctx = {"text": text, "filename": filename or "document.pdf"}
            _user_pdf_context[user_id] = ctx  # cache في الذاكرة
            logger.info(f"✅ PDF context restored from database for user {user_id}")
            return ctx
    except Exception as e:
        logger.warning(f"⚠️ Failed to load PDF context from DB: {e}")

    return None


def _save_user_state(user_id: int, state: str, data: dict = None):
    """حفظ حالة المستخدم في الـ DB عشان متتمسحش عند الـ restart"""
    from memory import save_memory
    try:
        save_memory(user_id, f"user_state_{state}", json.dumps(data or {}), "system")
    except Exception:
        pass  # non-critical


def _load_user_state(user_id: int) -> dict:
    """تحميل حالة المستخدم من الـ DB"""
    from memory import get_memories
    try:
        memories = get_memories(user_id, "system")
        for m in memories:
            if m["key"].startswith("user_state_"):
                state_name = m["key"].replace("user_state_", "")
                try:
                    state_data = json.loads(m["value"])
                except (json.JSONDecodeError, TypeError):
                    state_data = {}
                return {"state": state_name, "data": state_data}
    except Exception:
        pass
    return {}


async def _check_premium_limit(update: Update, user_id: int, feature: str, lang: str) -> bool:
    """
    Check premium limit. Returns True if allowed, False if blocked.
    If blocked, sends the limit-reached message automatically.
    الأدمن (@ziadamr) يتجاوز كل الحدود
    """
    from premium import check_limit, limit_reached_message

    # Admin bypass — الأدمن مبيتحكمش فيه أي Limits
    username = update.effective_user.username if update.effective_user else None
    if is_admin(user_id, username):
        return True

    limit_check = check_limit(user_id, feature)
    if not limit_check["allowed"]:
        feature_names = {
            "ai_messages_per_day": "💬 رسائل AI" if lang == "ar" else "💬 AI Messages",
            "pdf_analyses_per_day": "📄 تحليلات PDF" if lang == "ar" else "📄 PDF Analyses",
            "image_analyses_per_day": "🖼️ تحليلات الصور" if lang == "ar" else "🖼️ Image Analyses",
            "youtube_summaries_per_day": "🎬 ملخصات YouTube" if lang == "ar" else "🎬 YouTube Summaries",
            "searches_per_day": "🔍 عمليات البحث" if lang == "ar" else "🔍 Searches",
        }
        feature_display = feature_names.get(feature, feature)
        await update.message.reply_text(
            limit_reached_message(feature_display, limit_check["remaining"], limit_check["limit"], lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return False
    return True


async def _check_quota_callback(query, user_id: int, feature: str, lang: str) -> bool:
    """
    فحص الكوتا لأزرار الـ Callback — يرجع True لو مسموح، False لو ممنوع
    لو ممنوع بيبعت رسالة إن الكوتا خلصت تلقائي
    الأدمن (@ziadamr) يتجاوز كل الحدود
    """
    from premium import check_limit, limit_reached_message, get_premium_keyboard

    # Admin bypass
    username = query.from_user.username if query.from_user else None
    if is_admin(user_id, username):
        return True

    limit_check = check_limit(user_id, feature)
    if not limit_check["allowed"]:
        feature_names = {
            "ai_messages_per_day": "💬 رسائل AI" if lang == "ar" else "💬 AI Messages",
            "pdf_analyses_per_day": "📄 تحليلات PDF" if lang == "ar" else "📄 PDF Analyses",
            "image_analyses_per_day": "🖼️ تحليلات الصور" if lang == "ar" else "🖼️ Image Analyses",
            "youtube_summaries_per_day": "🎬 ملخصات YouTube" if lang == "ar" else "🎬 YouTube Summaries",
            "searches_per_day": "🔍 عمليات البحث" if lang == "ar" else "🔍 Searches",
        }
        feature_display = feature_names.get(feature, feature)
        await query.message.reply_text(
            limit_reached_message(feature_display, limit_check["remaining"], limit_check["limit"], lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return False
    return True


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ضغطات الأزرار التفاعلية"""
    from agents.pdf_agent import PDFAgent
    from agents.youtube_agent import YouTubeAgent
    from handlers.news_handlers import _send_news_callback, _send_trending_callback
    from handlers.memory_handlers import memory_command

    pdf_agent = PDFAgent()
    yt_agent = YouTubeAgent()

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    lang = get_language(user_id)

    logger.info(f"Button callback: user={user_id}, data={data}")

    # ═══ Admin Callbacks — أزرار لوحة تحكم الأدمن ═══
    if data.startswith("admin_"):
        await handle_admin_callback(update, context)
        return

    # ═══ Premium Features ═══
    if data == "premium_features":
        message = premium_features_message(lang, user_id=user_id)
        keyboard = get_premium_keyboard(lang, user_id=user_id)
        try:
            await query.message.edit_text(message, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)

    # ═══ PDF Processing Buttons ═══
    elif data == "pdf_summarize":
        # 🔴 فحص الكوتا — لو المستخدم خلص حد PDF مش هيرد
        if not await _check_quota_callback(query, user_id, "pdf_analyses_per_day", lang):
            return

        ctx = _get_pdf_context(user_id)
        if not ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الملف. ارفع الملف مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the file context. Please upload the file again.")
            return

        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        try:
            from formatters import clean_ai_response, smart_split_message
            result = await pdf_agent.summarize(ctx["text"], lang, user_id=user_id)
            result = clean_ai_response(result)
            if len(result) > 4000:
                chunks = smart_split_message(result)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await query.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in pdf_summarize callback: {e}")
            await query.message.reply_text("❌ حصل خطأ في التلخيص. جرب تاني." if lang == "ar" else "❌ Error in summarization. Please try again.")

    elif data == "pdf_keypoints":
        # 🔴 فحص الكوتا — لو المستخدم خلص حد PDF مش هيرد
        if not await _check_quota_callback(query, user_id, "pdf_analyses_per_day", lang):
            return

        ctx = _get_pdf_context(user_id)
        if not ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الملف. ارفع الملف مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the file context. Please upload the file again.")
            return

        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        try:
            from formatters import clean_ai_response, smart_split_message
            result = await pdf_agent.extract_key_points(ctx["text"], lang, user_id=user_id)
            result = clean_ai_response(result)
            if len(result) > 4000:
                chunks = smart_split_message(result)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await query.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in pdf_keypoints callback: {e}")
            await query.message.reply_text("❌ حصل خطأ. جرب تاني." if lang == "ar" else "❌ Error occurred. Please try again.")

    elif data == "pdf_quiz":
        # 🔴 فحص الكوتا — لو المستخدم خلص حد PDF مش هيرد
        if not await _check_quota_callback(query, user_id, "pdf_analyses_per_day", lang):
            return

        ctx = _get_pdf_context(user_id)
        if not ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الملف. ارفع الملف مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the file context. Please upload the file again.")
            return

        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        try:
            from formatters import clean_ai_response, smart_split_message
            result = await pdf_agent.create_quiz(ctx["text"], language=lang, user_id=user_id)
            result = clean_ai_response(result)
            if len(result) > 4000:
                chunks = smart_split_message(result)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await query.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in pdf_quiz callback: {e}")
            await query.message.reply_text("❌ حصل خطأ في إنشاء الكويز. جرب تاني." if lang == "ar" else "❌ Error creating quiz. Please try again.")

    elif data == "pdf_notes":
        # 🔴 فحص الكوتا — لو المستخدم خلص حد PDF مش هيرد
        if not await _check_quota_callback(query, user_id, "pdf_analyses_per_day", lang):
            return

        ctx = _get_pdf_context(user_id)
        if not ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الملف. ارفع الملف مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the file context. Please upload the file again.")
            return

        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        try:
            from formatters import clean_ai_response, smart_split_message
            result = await pdf_agent.generate_study_notes(ctx["text"], lang, user_id=user_id)
            result = clean_ai_response(result)
            if len(result) > 4000:
                chunks = smart_split_message(result)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await query.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in pdf_notes callback: {e}")
            await query.message.reply_text("❌ حصل خطأ في إنشاء الملاحظات. جرب تاني." if lang == "ar" else "❌ Error creating notes. Please try again.")

    elif data == "pdf_ask":
        if lang == "ar":
            msg = "❓ اكتب سؤالك عن الملف وأنا هجاوبك بناءً على محتواه!"
        else:
            msg = "❓ Type your question about the file and I'll answer based on its content!"
        # Set user state to expect PDF question
        user_states[user_id] = {"waiting_for": "pdf_question"}
        # 🔴 FIX: حفظ الـ workflow في الداتابيز كمان عشان يفضل بعد الـ restart
        try:
            from workflow_manager import set_workflow
            set_workflow(user_id, "pdf_question", "waiting_for_question")
        except Exception:
            pass
        await query.message.reply_text(msg, parse_mode="HTML")

    # ═══ YouTube Processing Buttons ═══
    elif data == "yt_summary":
        # 🔴 فحص الكوتا — لو المستخدم خلص حد YouTube مش هيرد
        if not await _check_quota_callback(query, user_id, "youtube_summaries_per_day", lang):
            return

        ctx = _user_yt_context.get(user_id)
        if not ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الفيديو. ابعث الرابط مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the video context. Please send the URL again.")
            return

        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        try:
            from formatters import clean_ai_response, smart_split_message
            result = await yt_agent.summarize_video(ctx["url"], lang, user_id=user_id)
            result = clean_ai_response(result)
            if len(result) > 4000:
                chunks = smart_split_message(result)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await query.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in yt_summary callback: {e}")
            await query.message.reply_text("❌ حصل خطأ" if lang == "ar" else "❌ Error occurred")

    elif data == "yt_keypoints":
        # 🔴 فحص الكوتا — لو المستخدم خلص حد YouTube مش هيرد
        if not await _check_quota_callback(query, user_id, "youtube_summaries_per_day", lang):
            return

        ctx = _user_yt_context.get(user_id)
        if not ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الفيديو. ابعث الرابط مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the video context. Please send the URL again.")
            return

        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        try:
            from formatters import clean_ai_response, smart_split_message
            info = await yt_agent.get_video_info(ctx["video_id"])
            transcript = info.get("transcript", "")
            if not transcript:
                await query.message.reply_text(
                    "❌ مش قادر أجيب نص الفيديو لاستخراج النقاط." if lang == "ar"
                    else "❌ Can't get video transcript for key points."
                )
                return
            result = await pdf_agent.extract_key_points(transcript, lang)
            result = clean_ai_response(result)
            if len(result) > 4000:
                chunks = smart_split_message(result)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await query.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in yt_keypoints callback: {e}")
            await query.message.reply_text("❌ حصل خطأ" if lang == "ar" else "❌ Error occurred")

    elif data == "yt_quiz":
        # 🔴 فحص الكوتا — لو المستخدم خلص حد YouTube مش هيرد
        if not await _check_quota_callback(query, user_id, "youtube_summaries_per_day", lang):
            return

        ctx = _user_yt_context.get(user_id)
        if not ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الفيديو. ابعث الرابط مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the video context. Please send the URL again.")
            return

        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        try:
            from formatters import clean_ai_response, smart_split_message
            result = await yt_agent.create_quiz_from_video(ctx["url"], language=lang, user_id=user_id)
            result = clean_ai_response(result)
            if len(result) > 4000:
                chunks = smart_split_message(result)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await query.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in yt_quiz callback: {e}")
            await query.message.reply_text("❌ حصل خطأ" if lang == "ar" else "❌ Error occurred")

    # ═══ Main Menu Commands ═══
    elif data == "cmd_start":
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

    # ═══ ترند محدد - لما المستخدم يدوس على رقم الترند ═══
    elif data.startswith("trend_"):
        trend_index = int(data.replace("trend_", ""))
        user_trends = _user_trends.get(user_id, [])
        
        # 🔴 FIX: الترندات مش موجودة (البوت عمل restart أو المستخدم لسه ما جابش ترندات)
        if not user_trends:
            if lang == "ar":
                await query.message.reply_text("❌ الترندات مش متاحة دلوقتي. جرب /trending تاني!")
            else:
                await query.message.reply_text("❌ Trends not available right now. Try /trending again!")
            return
        
        # 🔴 FIX: index خارج النطاق
        if trend_index >= len(user_trends):
            if lang == "ar":
                await query.message.reply_text("❌ الترند ده مش متاح دلوقتي. جرب تجيب الترندات تاني!")
            else:
                await query.message.reply_text("❌ This trend is no longer available. Try fetching trends again!")
            return
        
        keyword, count = user_trends[trend_index]
        
        # 🔴 FIX: تنظيف الكلمة المفتاحية من أي حروف بتكسر HTML
        import html as html_module
        safe_keyword = html_module.escape(keyword)
        safe_keyword_upper = html_module.escape(keyword.upper())
        
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        
        # رسالة تحميل - بنستخدم safe_keyword عشان الـ HTML متكسرش
        if lang == "ar":
            loading_msg = await query.message.reply_text(f"⏳ جاري البحث عن أخبار <b>{safe_keyword}</b>...\n[████████░░] 80%", parse_mode="HTML")
        else:
            loading_msg = await query.message.reply_text(f"⏳ Searching for <b>{safe_keyword}</b> news...\n[████████░░] 80%", parse_mode="HTML")
        
        try:
            # بنبحث عن الأخبار المتعلقة بالكلمة المفتاحية دي
            from news_fetcher import fetch_news
            from filters import filter_news
            from scorer import rank_articles
            from summarizer import summarize_articles
            from formatters import format_news_item, clean_ai_response, smart_split_message
            
            articles = await fetch_news()
            filtered = filter_news(articles)
            
            # فلترة الأخبار اللي فيها الكلمة المفتاحية
            keyword_lower = keyword.lower()
            related = []
            for article in filtered:
                title = article.get("title", "").lower()
                desc = article.get("description", "").lower()
                if keyword_lower in title or keyword_lower in desc:
                    related.append(article)
            
            if related:
                # رتب ولخص أهم 5 أخبار
                ranked = rank_articles(related)[:5]
                try:
                    summarized = await summarize_articles(ranked)
                except Exception as sum_err:
                    logger.error(f"⚠️ Summarization failed for trend {keyword}: {sum_err}")
                    # fallback: نستخدم الأوصاف الأصلية بدون تلخيص
                    summarized = ranked
                    for a in summarized:
                        if "arabic_summary" not in a:
                            a["arabic_summary"] = a.get("description", "")[:200]
                        if "arabic_title" not in a:
                            a["arabic_title"] = ""
                
                if lang == "ar":
                    message = f"📈 <b>أخبار {safe_keyword_upper}</b>\n━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message = f"📈 <b>{safe_keyword_upper} News</b>\n━━━━━━━━━━━━━━━━━\n\n"
                
                from handlers.news_handlers import _get_article_title
                items = []
                for i, article in enumerate(summarized):
                    try:
                        item = format_news_item(
                            i + 1,
                            _get_article_title(article, lang),
                            article.get("arabic_summary", article.get("description", "")[:200]),
                            article.get("link", ""),
                            i == 0,
                            article.get("category", ""),
                            language=lang,
                        )
                        items.append(item)
                    except Exception as fmt_err:
                        logger.warning(f"⚠️ format_news_item failed for article {i}: {fmt_err}")
                        # fallback: عرض بسيط
                        title = _get_article_title(article, lang)
                        summary = article.get("arabic_summary", article.get("description", "")[:200])
                        link = article.get("link", "")
                        safe_title = html_module.escape(str(title))
                        safe_summary = html_module.escape(str(summary))
                        item = f"{i+1}. 📄 <b>{safe_title}</b>\n{safe_summary}"
                        if link:
                            read_more = "اقرأ المزيد" if lang == "ar" else "Read more"
                            item += f'\n🔗 <a href="{link}">{read_more}</a>'
                        items.append(item)
                
                message += "\n\n".join(items)
                if lang == "ar":
                    message += "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — تتبع الترندات</i>"
                else:
                    message += "\n\n━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Trending Tracker</i>"
                
                # 🔴 FIX: تنظيف الـ message من أي HTML متكسر قبل الإرسال
                try:
                    if len(message) > 4000:
                        chunks = smart_split_message(message)
                        await loading_msg.delete()
                        for chunk in chunks:
                            await query.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
                    else:
                        await loading_msg.edit_text(message, parse_mode="HTML", disable_web_page_preview=True)
                except Exception as html_err:
                    logger.error(f"⚠️ HTML parse error in trend results: {html_err}")
                    # fallback: إرسال بدون HTML
                    plain_message = message.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<a href=', '').replace('</a>', '').replace('<code>', '').replace('</code>', '')
                    try:
                        await loading_msg.edit_text(plain_message[:4000])
                    except Exception:
                        await query.message.reply_text(plain_message[:4000])
            else:
                # مفيش أخبار RSS - نعمل بحث في الويب مباشرة
                if lang == "ar":
                    await loading_msg.edit_text(f"⏳ جاري البحث في الويب عن <b>{safe_keyword}</b>...", parse_mode="HTML")
                else:
                    await loading_msg.edit_text(f"⏳ Searching the web for <b>{safe_keyword}</b>...", parse_mode="HTML")
                
                # بحث في الويب
                try:
                    from web_search import search_web
                    web_results = await search_web(keyword, max_results=5, language=lang)
                    
                    if web_results:
                        result_message = ""
                        if lang == "ar":
                            result_message = f"🌐 <b>نتائج بحث الويب: {safe_keyword}</b>\n━━━━━━━━━━━━━━━━━\n\n"
                        else:
                            result_message = f"🌐 <b>Web Search: {safe_keyword}</b>\n━━━━━━━━━━━━━━━━━\n\n"
                        
                        for i, r in enumerate(web_results[:5], 1):
                            title_text = html_module.escape(str(r.get("title", "")))
                            snippet = html_module.escape(str(r.get("snippet", "")[:200]))
                            link = r.get("link", "")
                            result_message += f"{i}. 📄 <b>{title_text}</b>\n"
                            if snippet:
                                result_message += f"   {snippet}\n"
                            if link:
                                read_more = "اقرأ المزيد" if lang == "ar" else "Read more"
                                result_message += f'   🔗 <a href="{link}">{read_more}</a>\n'
                            result_message += "\n"
                        
                        if lang == "ar":
                            result_message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — تتبع الترندات</i>"
                        else:
                            result_message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — Trending Tracker</i>"
                        
                        try:
                            await loading_msg.edit_text(result_message, parse_mode="HTML", disable_web_page_preview=True)
                        except Exception:
                            # fallback: إرسال رسالة جديدة بدون HTML معقد
                            try:
                                await loading_msg.delete()
                            except Exception:
                                pass
                            await query.message.reply_text(result_message, parse_mode="HTML", disable_web_page_preview=True)
                    else:
                        # مفيش نتائج ويب كمان
                        if lang == "ar":
                            no_result = f"📈 <b>{safe_keyword_upper}</b>\n━━━━━━━━━━━━━━━━━\n\nمفيش أخبار عن {safe_keyword} دلوقتي.\nجرب تاني بعد كده! 🤖"
                        else:
                            no_result = f"📈 <b>{safe_keyword_upper}</b>\n━━━━━━━━━━━━━━━━━\n\nNo news about {safe_keyword} right now.\nTry again later! 🤖"
                        try:
                            await loading_msg.edit_text(no_result, parse_mode="HTML")
                        except Exception:
                            try:
                                await loading_msg.delete()
                            except Exception:
                                pass
                            await query.message.reply_text(no_result, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Error in trend web search: {e}")
                    error_msg = "❌ حصل خطأ في البحث. جرب تاني!" if lang == "ar" else "❌ Search error. Please try again!"
                    try:
                        await loading_msg.edit_text(error_msg)
                    except Exception:
                        await query.message.reply_text(error_msg)
        except Exception as e:
            logger.error(f"Error in trend_{trend_index} callback: {e}")
            error_msg = "❌ حصل خطأ. جرب تاني!" if lang == "ar" else "❌ Error occurred. Please try again."
            try:
                await loading_msg.edit_text(error_msg)
            except Exception:
                try:
                    await loading_msg.delete()
                except Exception:
                    pass
                await query.message.reply_text(error_msg)

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
        # 🔴 فحص الكوتا — لو المستخدم خلص حد الرسائل مش هيرد
        if not await _check_quota_callback(query, user_id, "ai_messages_per_day", lang):
            return

        from premium import increment_usage
        increment_usage(user_id, "ai_messages")

        from formatters import clean_ai_response, smart_split_message
        company_key = data.replace("company_", "")
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

        loading_msg = await query.message.reply_text(
            f"⏳ {'جاري تجهيز تقرير الشركة...' if lang == 'ar' else 'Preparing company report...'}\n[████████░░] 80%"
        )

        try:
            report = await generate_company_report(company_key, lang, user_id=user_id)
            report = clean_ai_response(report)
            # 🔴 FIX: لو التقرير طويل، نقسمه على رسائل بدل ما نحاول edit_text وفشل
            if len(report) > 4000:
                await loading_msg.delete()
                chunks = smart_split_message(report)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            else:
                await loading_msg.edit_text(report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in company callback: {e}")
            await loading_msg.edit_text(format_error("حدث خطأ" if lang == "ar" else "Error occurred"))

    # ═══ البحث التفصيلي في الصور ═══
    elif data == "image_detail":
        """البحث التفصيلي - تحليل عميق للصورة مع كل التفاصيل (ألوان، نصوص، بيانات)"""
        # 🔴 فحص الكوتا — لو المستخدم خلص حد تحليل الصور مش هيرد
        if not await _check_quota_callback(query, user_id, "image_analyses_per_day", lang):
            return

        from ai_engine import analyze_image
        from formatters import clean_ai_response, smart_split_message
        from progress import ProgressManager, AI_STAGES

        img_ctx = _user_image_context.get(user_id)
        if not img_ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الصورة. ارفع الصورة مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the image context. Please upload the image again.")
            return

        stages = AI_STAGES(lang)
        title = "تحليل تفصيلي للصورة" if lang == "ar" else "Detailed Image Analysis"
        progress = ProgressManager(query, context, stages, lang, title, timeout=ProgressManager.DEFAULT_TIMEOUT)
        # ProgressManager needs update.message, use query.message as fallback
        progress.update = type('obj', (object,), {
            'message': query.message,
            'effective_user': query.from_user,
            'effective_chat': query.message.chat,
        })()
        await progress.start()

        try:
            await progress.update_stage(0)
            await progress.update_stage(1)

            # Detailed analysis with vision_pro style
            response = await analyze_image(
                image_base64=img_ctx["image_base64"],
                language=lang,
                user_message=img_ctx.get("user_text", ""),
                vision_pro=True,  # Full detail mode
            )
            response = clean_ai_response(response)

            # Add detailed header
            if lang == "ar":
                header = "🔬 <b>تحليل تفصيلي للصورة</b>\n━━━━━━━━━━━━━━━━━\n\n"
            else:
                header = "🔬 <b>Detailed Image Analysis</b>\n━━━━━━━━━━━━━━━━━\n\n"

            full_response = header + response
            await progress.update_stage(2)

            if len(full_response) > 4000:
                await progress.complete(delete_progress=True)
                chunks = smart_split_message(full_response)
                for chunk in chunks:
                    await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await progress.complete(final_message=full_response, delete_progress=False)

        except Exception as e:
            logger.error(f"Error in image_detail callback: {e}")
            await progress.error("حدث خطأ في التحليل التفصيلي" if lang == "ar" else "Error in detailed analysis")

    # ═══ تعديل الصور بالذكاء الاصطناعي 🖌️ ═══
    elif data == "image_edit":
        """تعديل الصورة — المستخدم يكتب الوصف وهنعدّل الصورة"""
        from premium import can_use_image_edit, premium_required_message
        # 🔴 FIX: get_premium_keyboard مستورد فوق في السطر 22 — لو استوردناه تاني هنا Python هتعتبه متغير محلي ويحصل UnboundLocalError
        
        # Premium check
        if not can_use_image_edit(user_id):
            feature_name = "🖌️ تعديل صور / Image Edit"
            await query.message.reply_text(
                premium_required_message(feature_name, lang),
                parse_mode="HTML",
                reply_markup=get_premium_keyboard(lang, user_id=user_id)
            )
            return
        
        img_ctx = _user_image_context.get(user_id)
        if not img_ctx:
            if lang == "ar":
                await query.message.reply_text("❌ لم أعد أملك سياق الصورة. ارفع الصورة مرة أخرى.")
            else:
                await query.message.reply_text("❌ I no longer have the image context. Please upload the image again.")
            return
        
        # نحفظ حالة المستخدم عشان نعرف إنه عايز يعدّل الصورة
        user_states[user_id] = {
            "waiting_for": "image_edit",
            "image_base64": img_ctx.get("image_base64", ""),
        }
        # 🔴 FIX: حفظ الـ workflow في الداتابيز كمان عشان يفضل بعد الـ restart
        try:
            from workflow_manager import set_workflow
            set_workflow(user_id, "image_edit", "waiting_for_description", {"image_base64": img_ctx.get("image_base64", "")})
        except Exception:
            pass
        
        if lang == "ar":
            msg = "🖌️ <b>تعديل الصورة بالذكاء الاصطناعي</b>\n\nاكتب الوصف اللي عايز تعدّل بيه الصورة!\n\n💡 <b>أمثلة:</b>\n→ غيّر الخلفية لمسجد\n→ خلي الألوان أدفأ\n→ ضيف إضاءة مسائية\n→ add a sunset sky\n→ make it look like Islamic art"
        else:
            msg = "🖌️ <b>AI Image Editing</b>\n\nType how you want to edit the image!\n\n💡 <b>Examples:</b>\n→ change background to mosque\n→ make colors warmer\n→ add evening lighting\n→ add a sunset sky\n→ make it look like Islamic art"
        await query.message.reply_text(msg, parse_mode="HTML")

    # ═══ خرائط الطريق ═══
    elif data.startswith("roadmap_"):
        # 🔴 فحص الكوتا — لو المستخدم خلص حد الرسائل مش هيرد
        if not await _check_quota_callback(query, user_id, "ai_messages_per_day", lang):
            return

        from premium import increment_usage
        increment_usage(user_id, "ai_messages")

        from formatters import clean_ai_response, smart_split_message
        topic = data.replace("roadmap_", "")
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

        loading_msg = await query.message.reply_text(
            f"⏳ {'جاري تجهيز خارطة الطريق...' if lang == 'ar' else 'Preparing roadmap...'}\n[████████░░] 80%"
        )

        try:
            roadmap = await generate_roadmap(topic, lang, user_id=user_id)
            roadmap = clean_ai_response(roadmap)
            inline_keyboard = get_learn_inline_buttons(lang)
            # 🔴 FIX: لو خارطة الطريق طويلة، نقسمها على رسائل
            if len(roadmap) > 4000:
                await loading_msg.delete()
                chunks = smart_split_message(roadmap)
                for i, chunk in enumerate(chunks):
                    if i == len(chunks) - 1:
                        await query.message.reply_text(chunk, parse_mode="HTML", reply_markup=inline_keyboard, disable_web_page_preview=True)
                    else:
                        await query.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            else:
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
        from premium import get_user_plan
        plan = get_user_plan(user_id)
        if lang == "ar":
            plan_display = "⭐ Premium" if plan == "premium" else "🆓 مجاني"
            sub_status = "✅ مشترك" if user_sub else "❌ مش مشترك"
            msg = f"⚙️ <b>الإعدادات</b>\n━━━━━━━━━━━━━━━━━\n\n👤 الخطة: {plan_display}\n📬 أخبار يومية: {sub_status}\n\nاختر ما تريد تغييره:"
        else:
            plan_display = "⭐ Premium" if plan == "premium" else "🆓 Free"
            sub_status_en = "✅ Subscribed" if user_sub else "❌ Not subscribed"
            msg = f"⚙️ <b>Settings</b>\n━━━━━━━━━━━━━━━━━\n\n👤 Plan: {plan_display}\n📬 Daily News: {sub_status_en}\n\nChoose what to change:"
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
        msg = "✅ Language changed to English"
        await query.message.edit_text(msg)
        await query.message.reply_text(
            welcome_message("en", query.from_user.first_name or ""),
            parse_mode="HTML",
            reply_markup=keyboard
        )
