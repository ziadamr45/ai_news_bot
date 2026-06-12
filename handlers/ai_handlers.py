"""
AI chat and learning command handlers.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ai_engine import (
    ask_question, explain_topic,
    generate_roadmap, generate_company_report
)
from memory import get_language, increment_command_count
from formatters import clean_ai_response, smart_split_message
from progress import ProgressManager, AI_STAGES, LEARN_STAGES, ROADMAP_STAGES, COMPANY_STAGES, DEEP_SEARCH_STAGES
from dashboard import track_event

from handlers.keyboards import get_learn_inline_buttons, get_roadmap_keyboard, get_companies_keyboard
from handlers.error_monitor import record_error

logger = logging.getLogger(__name__)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /ask <question>"""
    from premium import increment_usage
    from handlers.callbacks import _check_premium_limit

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check
    if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
        return

    try:
        track_event("total_commands")
        track_event("ai_requests")
    except Exception:
        pass

    question = " ".join(context.args) if context.args else ""

    if not question:
        if lang == "ar":
            msg = "🤖 <b>اسأل My Bro</b>\n\nاكتب سؤالك مباشرة أو بعد الأمر\nمثال: <code>/ask ما هي علوم القرآن؟</code>\n\n💡 يمكنك أيضاً الكتابة مباشرة بدون أوامر وسأفهمك!"
        else:
            msg = "🤖 <b>Ask My Bro</b>\n\nType your question directly or after the command\nExample: <code>/ask What are the sciences of the Quran?</code>\n\n💡 You can also just type naturally without commands!"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    increment_usage(user_id, "ai_messages")

    stages = AI_STAGES(lang)
    title = "التفكير" if lang == "ar" else "Thinking"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        response = await ask_question(question, lang, user_id=user_id)
        response = clean_ai_response(response)
        await progress.update_stage(2)
        await progress.complete(final_message=response, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /ask: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def learn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /learn <topic>"""
    from memory import save_learning, detect_interests
    from handlers.callbacks import _check_premium_limit
    from premium import increment_usage

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        track_event("total_commands")
        track_event("ai_requests")
    except Exception:
        pass

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "📚 <b>تعلم الذكاء الاصطناعي</b>\n\nاكتب الموضوع بعد الأمر\nمثال: <code>/learn الفقه الإسلامي</code>\n\n💡 أو اختر من خرائط الطريق بالأسفل"
        else:
            msg = "📚 <b>Learn AI</b>\n\nType the topic after the command\nExample: <code>/learn Islamic jurisprudence</code>\n\n💡 Or choose from roadmaps below"

        keyboard = get_roadmap_keyboard(lang)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
        return

    # 🔴 فحص الكوتا — لو المستخدم خلص حد الرسائل مش هيرد
    if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
        return

    increment_usage(user_id, "ai_messages")

    stages = LEARN_STAGES(lang)
    title = f"تعلم: {topic}" if lang == "ar" else f"Learning: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        explanation = await explain_topic(topic, lang, user_id=user_id)
        explanation = clean_ai_response(explanation)
        await progress.update_stage(2)

        try:
            save_learning(user_id, topic, "explored")
            detect_interests(user_id, topic)
        except Exception:
            pass

        inline_keyboard = get_learn_inline_buttons(lang)
        await progress.complete(final_message=explanation, reply_markup=inline_keyboard, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /learn: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def roadmap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /roadmap <topic>"""
    from handlers.callbacks import _check_premium_limit
    from premium import increment_usage

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        track_event("total_commands")
    except Exception:
        pass

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "🗺️ <b>خرائط طريق التعلم</b>\n\nاختر خارطة طريق من الأزرار بالأسفل"
        else:
            msg = "🗺️ <b>Learning Roadmaps</b>\n\nChoose a roadmap from buttons below"

        keyboard = get_roadmap_keyboard(lang)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
        return

    # 🔴 فحص الكوتا — لو المستخدم خلص حد الرسائل مش هيرد
    if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
        return

    increment_usage(user_id, "ai_messages")

    stages = ROADMAP_STAGES(lang)
    title = f"خارطة طريق: {topic}" if lang == "ar" else f"Roadmap: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        roadmap = await generate_roadmap(topic, lang, user_id=user_id)
        roadmap = clean_ai_response(roadmap)
        await progress.update_stage(2)
        inline_keyboard = get_learn_inline_buttons(lang)
        await progress.complete(final_message=roadmap, reply_markup=inline_keyboard, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /roadmap: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def deepsearch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /deepsearch <query> - بحث عميق"""
    from premium import check_limit, premium_required_message, get_premium_keyboard

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check - deep search is premium only
    if not check_limit(user_id, "deep_searches_per_day")["allowed"]:
        await update.message.reply_text(
            premium_required_message("🔬 بحث عميق / Deep Search", lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    try:
        track_event("total_commands")
        track_event("search_requests")
    except Exception:
        pass

    query = " ".join(context.args) if context.args else ""

    if not query:
        if lang == "ar":
            msg = "🔬 <b>البحث العميق</b>\n\nاكتب ما تريد البحث عنه بعمق\nمثال: <code>/deepsearch تاريخ الحضارة الإسلامية</code>\n\n💡 البحث العميق بيستخدم نماذج أقوى وبيبحث في أكتر من مصدر.\n⭐ متاح للمشتركين Premium فقط."
        else:
            msg = "🔬 <b>Deep Search</b>\n\nType what you want to search in depth\nExample: <code>/deepsearch history of Islamic civilization</code>\n\n💡 Deep search uses more powerful models and searches multiple sources.\n⭐ Premium only feature."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    stages = DEEP_SEARCH_STAGES(lang)
    title = f"بحث عميق: {query}" if lang == "ar" else f"Deep Search: {query}"
    from progress import ProgressManager
    progress = ProgressManager(update, context, stages, lang, title, timeout=ProgressManager.DEEP_SEARCH_TIMEOUT)
    await progress.start()

    from premium import increment_usage
    increment_usage(user_id, "deep_searches")

    try:
        # 🔴 FIX: تحديث المراحل في الوقت الفعلي أثناء البحث
        # بدل ما نحدّث كل المراحل قبل البحث (كان بيخلي الـ progress مش دقيق)
        # بنمرر الـ progress callback عشان كل مرحلة تتحدث لما تخلص فعلاً
        from web_search import deep_search_and_summarize_async
        import asyncio

        async def _update_stage(stage_idx: int):
            """تحديث مرحلة التقدم بشكل آمن"""
            try:
                await progress.update_stage(stage_idx)
            except Exception:
                pass  # تجاهل أخطاء تحديث التقدم

        # 🔴 FIX: إضافة timeout صريح للبحث العميق (180 ثانية)
        # عشان لو الـ AI call علق، ميفضلش يستهلك موارد للأبد
        try:
            response = await asyncio.wait_for(
                deep_search_and_summarize_async(
                    query, lang,
                    user_id=user_id,
                    username=update.effective_user.username,
                    progress_callback=_update_stage,
                ),
                timeout=180,  # أقصى وقت 3 دقايق
            )
        except asyncio.TimeoutError:
            logger.error(f"⏰ Deep search timed out after 180s for: {query}")
            await progress.error("انتهت مهلة البحث العميق — حاول تاني" if lang == "ar" else "Deep search timed out — please try again")
            return

        response = clean_ai_response(response)

        # 🔴 FIX: لو الرد أكتر من 4000 حرف، قسمه على رسائل
        # لأن تيليجرام مش بيقبل أكتر من 4096 حرف في رسالة واحدة
        # ولو حاولنا edit_text برسالة طويلة بيفشل بصمت وبيفصل الـ progress
        if len(response) > 4000:
            await progress.complete(delete_progress=True)
            chunks = smart_split_message(response)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await progress.complete(final_message=response, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /deepsearch: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ في البحث العميق" if lang == "ar" else "Deep search error")


async def company_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /company <name>"""
    from handlers.callbacks import _check_premium_limit
    from premium import increment_usage

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    try:
        track_event("total_commands")
    except Exception:
        pass

    company_name = " ".join(context.args) if context.args else ""

    if not company_name:
        if lang == "ar":
            msg = "🏢 <b>تقارير شركات الذكاء الاصطناعي</b>\n\nاختر شركة من الأزرار بالأسفل أو اكتب اسمها بعد الأمر"
        else:
            msg = "🏢 <b>AI Company Reports</b>\n\nChoose a company from buttons below or type its name after the command"

        keyboard = get_companies_keyboard(lang)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
        return

    # 🔴 فحص الكوتا — لو المستخدم خلص حد الرسائل مش هيرد
    if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
        return

    increment_usage(user_id, "ai_messages")

    stages = COMPANY_STAGES(lang)
    title = f"تقرير: {company_name}" if lang == "ar" else f"Report: {company_name}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        await progress.update_stage(2)
        report = await generate_company_report(company_name, lang, user_id=user_id)
        report = clean_ai_response(report)
        await progress.update_stage(3)
        await progress.complete(final_message=report, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /company: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")
