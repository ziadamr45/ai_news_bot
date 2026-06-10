"""
Free chat handler with smart intent detection.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ai_engine import smart_chat
from memory import (
    get_language, increment_chat_count, is_subscribed,
    save_conversation, detect_interests,
)
from formatters import clean_ai_response, smart_split_message
from progress import ProgressManager, AI_STAGES
from premium import (
    check_limit, increment_usage, premium_required_message,
    get_premium_keyboard,
)
from dashboard import track_event

from handlers.keyboards import (
    get_settings_keyboard,
    get_roadmap_keyboard,
)
from handlers.dedup import _is_duplicate_update, _is_duplicate_user_message
from handlers.callbacks import _check_premium_limit, user_states, _user_pdf_context

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل العادية - محادثة حرة مع AI + كشف ذكي"""
    try:
        from handlers.memory_handlers import memory_command
        from handlers.news_handlers import news_command, trending_command
        from handlers.basic_handlers import help_command, premium_command
        from handlers.media_handlers import _process_youtube_url
        from agents.youtube_agent import YouTubeAgent
        from agents.pdf_agent import PDFAgent
    except ImportError as ie:
        logger.error(f"❌ Import error in handle_message: {ie}")
        await update.message.reply_text("❌ حصل خطأ في تحميل المكونات. جرب تاني!")
        return

    if await _is_duplicate_update(update.update_id):
        return

    user_id = update.effective_user.id
    user_text = update.message.text or ""
    
    # 🔴 FIX: get_language محتاج try/except عشان لو الداتابيز مفقودة مفيشش crash
    try:
        lang = get_language(user_id)
    except Exception:
        lang = "ar"  # fallback للعربي

    if not user_text.strip():
        return

    if await _is_duplicate_user_message(user_id, user_text):
        return

    # Check if user is banned
    try:
        from memory import is_banned
        if is_banned(user_id):
            return
    except Exception:
        pass  # لو الداتابيز مش شغالة، ممنعش المستخدم

    try:
        track_event("total_messages")
    except Exception:
        pass

    # ═══ Smart Intent: Check for PDF question state ═══
    user_state = user_states.get(user_id, {})
    if user_state.get("waiting_for") == "pdf_question":
        from handlers.callbacks import _get_pdf_context
        ctx = _get_pdf_context(user_id)
        if ctx:
            pdf_agent = PDFAgent()
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                result = await pdf_agent.answer_question(ctx["text"], user_text, lang, user_id=user_id)
                result = clean_ai_response(result)
                if len(result) > 4000:
                    chunks = smart_split_message(result)
                    for chunk in chunks:
                        await update.message.reply_text(chunk, parse_mode="HTML")
                else:
                    await update.message.reply_text(result, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error answering PDF question: {e}")
                await update.message.reply_text("❌ حصل خطأ. جرب تاني." if lang == "ar" else "❌ Error occurred. Please try again.")
            user_states.pop(user_id, None)
            return
        else:
            user_states.pop(user_id, None)

    # ═══ Smart Intent: Check for Image Edit state 🖌️ ═══
    user_state = user_states.get(user_id, {})
    if user_state.get("waiting_for") == "image_edit":
        from handlers.image_handlers import _translate_prompt_to_english
        from provider_manager import get_provider_manager
        from premium import can_use_image_edit
        
        image_base64 = user_state.get("image_base64", "")
        user_states.pop(user_id, None)  # Clear state
        
        if not can_use_image_edit(user_id):
            await update.message.reply_text("❌ الميزة دي Premium بس." if lang == "ar" else "❌ This feature is Premium only.")
            return
        
        if not image_base64:
            if lang == "ar":
                await update.message.reply_text("❌ الصورة مش متاحة. ارفعها تاني.")
            else:
                await update.message.reply_text("❌ Image not available. Please upload it again.")
            return
        
        # Progress
        stages = AI_STAGES(lang)
        title = "تعديل الصورة" if lang == "ar" else "Editing Image"
        progress = ProgressManager(update, context, stages, lang, title)
        await progress.start()
        
        try:
            await progress.update_stage(0)
            await progress.update_stage(1)
            
            # ترجمة الوصف العربي
            original_prompt = user_text
            edit_prompt = await _translate_prompt_to_english(user_text, user_id=user_id)
            was_translated = (edit_prompt != original_prompt)
            
            # تعديل الصورة
            manager = get_provider_manager()
            result = await manager.edit_image_async(
                prompt=edit_prompt,
                image_base64=image_base64,
                user_id=user_id,
            )
            
            await progress.update_stage(2)
            
            if not result:
                await progress.error("❌ حصل خطأ في تعديل الصورة. جرب وصف تاني!" if lang == "ar" else "❌ Error editing image. Try a different description!")
                return
            
            # Caption
            if was_translated:
                caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:150]}</i>\n🌐 <i>{edit_prompt[:150]}</i>"
            else:
                caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:200]}</i>"
            
            # إرسال
            if result.get("base64"):
                import base64, io
                image_bytes = base64.b64decode(result["base64"])
                await progress.complete(delete_progress=True)
                await update.message.reply_photo(photo=io.BytesIO(image_bytes), caption=caption, parse_mode="HTML")
            elif result.get("url"):
                await progress.complete(delete_progress=True)
                await update.message.reply_photo(photo=result["url"], caption=caption, parse_mode="HTML")
            else:
                await progress.error("❌ حصل خطأ في تعديل الصورة. جرب تاني!" if lang == "ar" else "❌ Error editing image. Please try again!")
            
            increment_usage(user_id, "image_edits")
            try: track_event("image_edits")
            except: pass
            
        except Exception as e:
            logger.error(f"Error in image_edit state: {e}")
            await progress.error("❌ حصل خطأ في تعديل الصورة." if lang == "ar" else "❌ Error editing image.")
        
        return

    # ═══ التحقق من أزرار لوحة المفاتيح ═══
    # 🔴 FIX: بنشوف أزرار الكيبورد الأول قبل فحص الكوتا
    # عشان المستخدم المجاني لما يخلص الكوته يقدر يدوس على الإعدادات والخطة والبريميوم
    # الأزرار دي حقه يعرفها حتى لو خلص الكوته — مش لازم يبقى عنده رسائل عشان يشوفها
    keyboard_commands = {
        "📰 الأخبار": "/news", "📰 News": "/news",
        "🤖 اسأل My Bro": "/ask", "🤖 Ask My Bro": "/ask",
        "🔍 البحث": "/search", "🔍 Search": "/search",
        "🔍 بحث الويب": "/search", "🔍 Web Search": "/search",
        # بحث عميق تم إزالته من الواجهة
        "📚 تعلم AI": "/learn", "📚 Learn AI": "/learn",
        "📚 وضع الدراسة": "/study", "📚 Study Mode": "/study",
        # الشركات تم إزالتها من الواجهة
        "⚙️ الإعدادات": "settings", "⚙️ Settings": "settings",
        "ℹ️ المساعدة": "/help", "ℹ️ Help": "/help",
        "⭐ Premium": "/premium", "⭐ Premium": "/premium",
        "📋 الخطة و حدود الإستخدام": "/premium", "📋 Plan & Usage": "/premium",
        "📄 تحليل ملف": "pdf_upload", "📄 Analyze File": "pdf_upload",
        "🎬 ملخص يوتيوب": "youtube_prompt", "🎬 YouTube Summary": "youtube_prompt",
        "🧠 ذاكرتي": "/memory", "🧠 My Memory": "/memory",
        # 🔴 التريندات اتحذف من الواجهة الرئيسية - موجود كزرار في الأخبار
        "📈 التريندات": "/trending", "📈 Trending": "/trending",
        # 🎨 إنشاء صورة + 🖌️ تعديل صورة + 📥 تحميل وسائط
        "🎨 صورة": "/image", "🎨 Image": "/image",
        "🎨 إنشاء صورة": "/image", "🎨 Create Image": "/image",
        "🖌️ عدّل صورة": "edit_prompt", "🖌️ Edit Image": "edit_prompt",
        "🖌️ تعديل": "edit_prompt", "🖌️ Edit": "edit_prompt",
        "📥 تحميل فيديو": "download_prompt", "📥 Download Video": "download_prompt",
        "📥 تحميل": "download_prompt", "📥 Download": "download_prompt",
    }

    # 🔴 FIX: أزرار الكيبورد اللي المستخدم له حق يدوسها حتى لو خلص الكوته
    # الإعدادات + الخطة والبريميوم + المساعدة + الذاكرة — دول مش محتاجين كوتا AI
    quota_free_commands = {"settings", "/premium", "/help", "/memory"}

    if user_text in keyboard_commands:
        cmd = keyboard_commands[user_text]

        # 🔴 FIX: الأزرار اللي مش محتاجة كوتا — المستخدم له حق يدوسها عادي
        if cmd in quota_free_commands:
            if cmd == "settings":
                user_sub = is_subscribed(user_id)
                keyboard = get_settings_keyboard(lang, user_sub)
                from premium import get_user_plan
                plan = get_user_plan(user_id)
                if lang == "ar":
                    sub_status = "✅ مشترك" if user_sub else "❌ مش مشترك"
                    plan_display = "⭐ Premium" if plan == "premium" else "🆓 مجاني"
                    msg = f"⚙️ <b>الإعدادات</b>\n━━━━━━━━━━━━━━━━━\n\n👤 الخطة: {plan_display}\n📬 أخبار يومية: {sub_status}\n\nاختر ما تريد تغييره:"
                else:
                    sub_status_en = "✅ Subscribed" if user_sub else "❌ Not subscribed"
                    plan_display = "⭐ Premium" if plan == "premium" else "🆓 Free"
                    msg = f"⚙️ <b>Settings</b>\n━━━━━━━━━━━━━━━━━\n\n👤 Plan: {plan_display}\n📬 Daily News: {sub_status_en}\n\nChoose what to change:"
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
                return
            elif cmd == "/premium":
                await premium_command(update, context)
                return
            elif cmd == "/help":
                await help_command(update, context)
                return
            elif cmd == "/memory":
                await memory_command(update, context)
                return

        # 🔴 FIX: الأزرار اللي محتاجة كوتا — نفحص الكوتا الأول
        from premium import check_limit as _check_quota
        quota_check = _check_quota(user_id, "ai_messages_per_day", update.effective_user.username if update.effective_user else None)
        if not quota_check["allowed"] and quota_check["plan"] == "free":
            from premium import limit_reached_message, get_premium_keyboard
            feature_name = "💬 رسائل AI" if lang == "ar" else "💬 AI Messages"
            await update.message.reply_text(
                limit_reached_message(feature_name, quota_check["remaining"], quota_check["limit"], lang),
                parse_mode="HTML",
                reply_markup=get_premium_keyboard(lang, user_id=user_id)
            )
            return

        # باقي أزرار الكيبورد (محتاجة كوتا)
        if cmd == "/ask":
            if lang == "ar":
                msg = "🤖 اكتب سؤالك وسأجيبك فوراً!"
            else:
                msg = "🤖 Type your question and I'll answer right away!"
            await update.message.reply_text(msg)
            return
        elif cmd == "/search":
            if lang == "ar":
                msg = "🔍 <b>البحث في أخبار AI والويب</b>\n\nاكتب كلمة البحث بعد الأمر\nمثال: <code>/search الكلام</code>\n\nأو اضغط على زر 🔍 البحث واكتب ما تريد البحث عنه."
            else:
                msg = "🔍 <b>Search AI News & Web</b>\n\nType your search query after the command\nExample: <code>/search OpenAI</code>\n\nOr tap 🔍 Search and type what you want to find."
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        elif cmd == "/learn":
            keyboard = get_roadmap_keyboard(lang)
            if lang == "ar":
                msg = "📚 <b>اختر موضوع للتعلم</b>"
            else:
                msg = "📚 <b>Choose a topic to learn</b>"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
            return
        elif cmd == "/study":
            # Study mode via keyboard
            if not check_limit(user_id, "study_mode")["allowed"]:
                await update.message.reply_text(
                    premium_required_message("📚 وضع الدراسة / Study Mode", lang),
                    parse_mode="HTML",
                    reply_markup=get_premium_keyboard(lang, user_id=user_id)
                )
                return
            if lang == "ar":
                msg = "📚 <b>وضع الدراسة</b>\n\nاكتب الموضوع اللي عايز تدرسه!\nمثال: machine learning, python, data science"
            else:
                msg = "📚 <b>Study Mode</b>\n\nType the topic you want to study!\nExample: machine learning, python, data science"
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        elif cmd == "pdf_upload":
            if lang == "ar":
                msg = "📄 <b>تحليل ملفات</b>\n\nابعتلي ملف PDF أو Word أو TXT وهحللهولك!\n\n💡 الملفات المدعومة:\n→ PDF\n→ Word (docx)\n→ TXT, MD, CSV, JSON\n→ ملفات الكود (py, js, html)\n\n📎 ابعت الملف دلوقتي!"
            else:
                msg = "📄 <b>File Analysis</b>\n\nSend me a PDF, Word, or TXT file and I'll analyze it!\n\n💡 Supported files:\n→ PDF\n→ Word (docx)\n→ TXT, MD, CSV, JSON\n→ Code files (py, js, html)\n\n📎 Send the file now!"
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        elif cmd == "youtube_prompt":
            if lang == "ar":
                msg = "🎬 <b>ملخص يوتيوب</b>\n\nاستخدم أمر <code>/youtube</code> قبل الرابط وهلخصلك الفيديو!\n\n💡 <b>مثال:</b>\n<code>/youtube https://youtube.com/watch?v=...</code>\n\n⚠️ <b>ملاحظة:</b> لو بعت الرابط لوحده هيحملهولك فيديو\nلو عايز تلخيص لازم تستخدم /youtube"
            else:
                msg = "🎬 <b>YouTube Summary</b>\n\nUse <code>/youtube</code> before the URL to get a summary!\n\n💡 <b>Example:</b>\n<code>/youtube https://youtube.com/watch?v=...</code>\n\n⚠️ <b>Note:</b> Sending just the URL will download the video\nTo summarize, you must use /youtube"
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        elif cmd == "/image":
            # 🎨 إنشاء صورة
            from handlers.image_handlers import image_command
            context.args = []
            await image_command(update, context)
            return
        elif cmd == "edit_prompt":
            # 🖌️ تعديل صورة
            from handlers.image_handlers import edit_command
            context.args = []
            await edit_command(update, context)
            return
        elif cmd == "download_prompt":
            # 📥 تحميل وسائط
            if lang == "ar":
                msg = "📥 <b>تحميل وسائط من أي منصة</b>\n\n💡 <b>طريقتين:</b>\n1️⃣ ابعت الرابط لوحده وهيحملهولك تلقائي!\n2️⃣ أو استخدم: <code>/download الرابط</code>\n\n<b>المنصات المدعومة:</b>\n→ YouTube, Facebook, Instagram\n→ TikTok, Twitter/X, Telegram\n→ Threads, Reddit, Vimeo\n\n⭐ الميزة دي Premium بس"
            else:
                msg = "📥 <b>Download Media from Any Platform</b>\n\n💡 <b>Two ways:</b>\n1️⃣ Just paste the URL and it will auto-download!\n2️⃣ Or use: <code>/download URL</code>\n\n<b>Supported Platforms:</b>\n→ YouTube, Facebook, Instagram\n→ TikTok, Twitter/X, Telegram\n→ Threads, Reddit, Vimeo\n\n⭐ Premium only feature"
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        else:
            context.args = []
            if cmd == "/news":
                await news_command(update, context)
            elif cmd == "/trending":
                await trending_command(update, context)
            return

    # ═══ فحص الكوتا — لو المستخدم خلص حد الرسائل ═══
    # 🔴 FIX: بنفحص الكوتا بعد أزرار الكيبورد عشان المستخدم يقدر يدوس
    # على الإعدادات والخطة والبريميوم حتى لو خلص الكوته
    from premium import check_limit as _check_quota
    quota_check = _check_quota(user_id, "ai_messages_per_day", update.effective_user.username if update.effective_user else None)
    if not quota_check["allowed"] and quota_check["plan"] == "free":
        from premium import limit_reached_message, get_premium_keyboard
        feature_name = "💬 رسائل AI" if lang == "ar" else "💬 AI Messages"
        await update.message.reply_text(
            limit_reached_message(feature_name, quota_check["remaining"], quota_check["limit"], lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    # ═══ Only increment chat_count for actual AI chat messages ═══
    increment_chat_count(user_id)

    # ═══ Smart Intent: Memory Questions — Redirect to /memory command ═══
    memory_keywords_ar = ["ذاكرتك", "ذاكرتي", "فاكرك", "فاكرة", "تعرف عني", "معلوماتك عني", "ايه اللي فاكره", "بتفكرني", "عامل ايه ذاكرتك"]
    memory_keywords_en = ["your memory", "my memory", "remember me", "what do you know about me", "what you know about me", "do you remember"]
    text_lower = user_text.lower()
    is_memory_question = any(kw in text_lower for kw in memory_keywords_ar + memory_keywords_en)
    if is_memory_question:
        await memory_command(update, context)
        return

    # ═══ Smart Intent: Any Media URL → Auto Download 📥 ═══
    # أي رابط فيديو/صورة/صوت (حتى YouTube) → تحميل تلقائي
    # تلخيص YouTube بالأمر /youtube بس
    extracted_url = None
    try:
        from handlers.download_handlers import _detect_platform, _is_direct_media_url, _extract_url, _process_download_request
        extracted_url = _extract_url(user_text)
    except ImportError as de:
        logger.error(f"❌ Failed to import download_handlers: {de}")
    except Exception as de2:
        logger.error(f"❌ Error in URL detection: {de2}")
    
    if extracted_url:
        platform = _detect_platform(extracted_url)
        direct_type = _is_direct_media_url(extracted_url)
        
        # أي رابط من منصة اجتماعية أو رابط فيديو/صورة/صوت مباشر → تحميل
        is_social = platform != "unknown"
        is_direct_media = direct_type in ("image", "audio", "video")
        
        if is_social or is_direct_media:
            # Premium check
            if not check_limit(user_id, "image_gen")["allowed"]:
                feature_name = "📥 تحميل وسائط / Media Download"
                await update.message.reply_text(
                    premium_required_message(feature_name, lang),
                    parse_mode="HTML",
                    reply_markup=get_premium_keyboard(lang, user_id=user_id)
                )
                return
            await _process_download_request(update, context, extracted_url, lang, user_id)
            return
    
    # 🔴 YouTube summarization = /youtube command ONLY
    # لو المستخدم عايز تلخيص يوتيوب لازم يستخدم /youtube
    # مجرد بعت الرابط في الشات → هيحمله فيديو (مش تلخيص)

    # ═══ محادثة ذكية مع AI ═══
    # Premium check for AI messages
    if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
        return

    increment_usage(user_id, "ai_messages")
    try:
        track_event("ai_requests")
    except Exception:
        pass

    stages = AI_STAGES(lang)
    title = "التفكير" if lang == "ar" else "Thinking"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)

        # v9.4: كشف الاهتمامات + حفظ تلقائي للذكريات يتم داخل build_context_for_ai
        # لا نحتاج detect_interests هنا لأنه يُستدعى داخل memory_context.build_context_for_ai
        # والذي يتم استدعاؤه داخل smart_chat()

        response = await smart_chat(user_text, lang, user_id=user_id, username=update.effective_user.username)
        response = clean_ai_response(response)
        await progress.update_stage(2)

        # v9.4: حفظ تلقائي للذكريات من المحادثة (تفضيلات، معلومات شخصية)
        if user_id and response:
            try:
                from memory_context import auto_save_conversation_memory
                auto_save_conversation_memory(user_id, user_text, response)
            except Exception as e:
                logger.debug(f"Auto-save memory error (non-critical): {e}")

        if len(response) > 4000:
            await progress.complete(delete_progress=True)
            chunks = smart_split_message(response)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await progress.complete(final_message=response, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("مش فاهم رسالتك كويس. ممكن تكتبها بطريقة تانية؟" if lang == "ar" else "I didn't understand your message. Could you rephrase it?")
