"""
Media handling handlers: PDF, YouTube, Photos, Voice, and Study commands.
"""

import logging
import asyncio
import base64

from telegram import Update
from telegram.ext import ContextTypes

from config import PDF_MAX_FILE_SIZE
from ai_engine import analyze_image
from memory import (
    get_language, increment_command_count, increment_chat_count,
    save_conversation, save_learning, detect_interests,
)
from formatters import clean_ai_response, smart_split_message
from progress import ProgressManager, AI_STAGES, LEARN_STAGES, ROADMAP_STAGES
from dashboard import track_event

from handlers.keyboards import (
    get_pdf_inline_buttons, get_youtube_inline_buttons, get_image_inline_buttons,
)
from handlers.dedup import _is_duplicate_update, _is_duplicate_user_message
from handlers.callbacks import _check_premium_limit, _user_pdf_context, _user_yt_context

logger = logging.getLogger(__name__)


async def pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /pdf - تعليمات رفع PDF"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    if lang == "ar":
        msg = """📄 <b>تحليل ملفات PDF</b>

ارفع ملف PDF مباشرة في المحادثة وهحللوله!

💡 <b>اللي هعمله:</b>
• تلخيص المحتوى
• استخراج النقاط الرئيسية
• إنشاء كويز من المحتوى
• ملاحظات دراسية
• الإجابة على أسئلتك

⭐ الحد المجاني: 2 ملفات في اليوم"""
    else:
        msg = """📄 <b>PDF File Analysis</b>

Upload a PDF file directly in chat and I'll analyze it!

💡 <b>What I can do:</b>
• Summarize the content
• Extract key points
• Create a quiz from the content
• Generate study notes
• Answer your questions

⭐ Free limit: 2 files per day"""

    await update.message.reply_text(msg, parse_mode="HTML")


async def youtube_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /youtube <url> - تلخيص فيديو YouTube"""
    from premium import increment_usage
    from agents.youtube_agent import YouTubeAgent
    yt_agent = YouTubeAgent()

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check
    if not await _check_premium_limit(update, user_id, "youtube_summaries_per_day", lang):
        return

    url = " ".join(context.args) if context.args else ""

    if not url or not yt_agent.is_youtube_url(url):
        if lang == "ar":
            msg = "🎬 <b>ملخص فيديو YouTube</b>\n\nاستخدم الأمر <code>/youtube</code> قبل الرابط وهلخصلك الفيديو!\n\n💡 <b>مثال:</b>\n<code>/youtube https://youtube.com/watch?v=...</code>\n\n⚠️ <b>ملاحظة:</b> لو بعت الرابط لوحده هيحملهولك فيديو\nلو عايز تلخيص لازم تستخدم /youtube"
        else:
            msg = "🎬 <b>YouTube Video Summary</b>\n\nUse <code>/youtube</code> before the URL to get a summary!\n\n💡 <b>Example:</b>\n<code>/youtube https://youtube.com/watch?v=...</code>\n\n⚠️ <b>Note:</b> Sending just the URL will download the video\nTo summarize, you must use /youtube"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    increment_usage(user_id, "youtube_summaries")
    try:
        track_event("youtube_summaries")
    except Exception:
        pass

    await _process_youtube_url(update, context, url, lang, user_id)


async def _process_youtube_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, lang: str, user_id: int):
    """Process a YouTube URL - summarize and show buttons"""
    from agents.youtube_agent import YouTubeAgent
    from agents.pdf_agent import PDFAgent
    yt_agent = YouTubeAgent()

    video_id = yt_agent.extract_video_id(url)

    stages = AI_STAGES(lang)
    title = "تلخيص فيديو YouTube" if lang == "ar" else "Summarizing YouTube video"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        summary = await yt_agent.summarize_video(url, lang, user_id=user_id)
        summary = clean_ai_response(summary)
        await progress.update_stage(2)

        # Store context for callback buttons
        _user_yt_context[user_id] = {
            "url": url,
            "video_id": video_id or "",
            "title": "",
        }

        inline_keyboard = get_youtube_inline_buttons(lang)
        await progress.complete(final_message=summary, reply_markup=inline_keyboard, delete_progress=False)

    except Exception as e:
        logger.error(f"Error processing YouTube URL: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ في تلخيص الفيديو" if lang == "ar" else "Error summarizing video")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الملفات المرفقة (PDF, Word, TXT, وغيرها)"""
    from premium import increment_usage
    from agents.pdf_agent import PDFAgent
    pdf_agent = PDFAgent()

    if await _is_duplicate_update(update.update_id):
        return

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_chat_count(user_id)

    # Check if document exists
    if not update.message.document:
        return

    doc = update.message.document

    # Check file size
    if doc.file_size and doc.file_size > PDF_MAX_FILE_SIZE:
        if lang == "ar":
            msg = f"❌ حجم الملف كبير جداً! الحد الأقصى {PDF_MAX_FILE_SIZE // (1024*1024)}MB"
        else:
            msg = f"❌ File too large! Maximum size is {PDF_MAX_FILE_SIZE // (1024*1024)}MB"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # Premium check
    if not await _check_premium_limit(update, user_id, "pdf_analyses_per_day", lang):
        return

    filename = doc.file_name or "document.pdf"

    # Per-user dedup
    if await _is_duplicate_user_message(user_id, f"doc_{doc.file_id}"):
        return

    increment_usage(user_id, "pdf_analyses")
    try:
        track_event("pdf_analyses")
    except Exception:
        pass

    # تحديد نوع الملف
    ext = filename.lower().split('.')[-1] if '.' in filename else "pdf"
    supported_exts = ["pdf", "docx", "doc", "txt", "md", "csv", "json", "py", "js", "html", "css", "xml", "log"]
    
    if ext not in supported_exts:
        if lang == "ar":
            msg = f"❌ نوع الملف '.{ext}' مش مدعوم حالياً.\n\nالأنواع المدعومة: PDF, Word (docx), TXT, MD, CSV, JSON\n\n💡 ابعت ملف من الأنواع دي وهحللهولك!"
        else:
            msg = f"❌ File type '.{ext}' is not supported yet.\n\nSupported: PDF, Word (docx), TXT, MD, CSV, JSON\n\n💡 Send a supported file and I'll analyze it!"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    file_type_label = {
        "pdf": "PDF", "docx": "Word", "doc": "Word", "txt": "نصي",
        "md": "Markdown", "csv": "CSV", "json": "JSON",
    }.get(ext, ext.upper())

    stages = AI_STAGES(lang)
    title = f"تحليل {file_type_label}: {filename}" if lang == "ar" else f"Analyzing {file_type_label}: {filename}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)

        # Download file with explicit timeout
        try:
            logger.info(f"📥 Downloading file: {filename} ({doc.file_size} bytes)")
            file = await asyncio.wait_for(
                context.bot.get_file(doc.file_id),
                timeout=30.0
            )
            file_bytes = await asyncio.wait_for(
                file.download_as_bytearray(),
                timeout=60.0
            )
            logger.info(f"✅ File downloaded: {len(file_bytes)} bytes")
        except asyncio.TimeoutError:
            logger.error(f"❌ File download timed out: {filename}")
            await progress.error(
                "❌ انتهى وقت تحميل الملف. جرب تاني." if lang == "ar"
                else "❌ File download timed out. Please try again."
            )
            return
        except Exception as e:
            logger.error(f"❌ Failed to download file: {e}")
            await progress.error(
                "❌ فشل تحميل الملف. جرب تاني." if lang == "ar"
                else "❌ Failed to download file. Please try again."
            )
            return

        await progress.update_stage(1)

        # Extract text with progress indication
        logger.info(f"🔍 Extracting text from {filename}...")
        try:
            text = await asyncio.wait_for(
                pdf_agent.extract_text(bytes(file_bytes), filename=filename),
                timeout=120.0
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ Text extraction timed out for {filename}")
            await progress.error(
                "❌ استخراج النص اخد وقت طويل. الملف ممكن يكون كبير أو معقد. جرب ملف أصغر." if lang == "ar"
                else "❌ Text extraction took too long. The file might be too large or complex. Try a smaller file."
            )
            return

        if not text.strip():
            logger.error(f"❌ No text extracted from {filename} — file may be image-only or protected")
            await progress.error(
                f"❌ لم أتمكن من استخراج النص من الملف.\n\n💡 ممكن الملف محمي أو فيه صور بس.\nجرب تبعتلي محتوى الملف كنص وهلخصهولك!" if lang == "ar"
                else "❌ Couldn't extract text from the file.\n\n💡 The file might be protected or contain only images.\nTry sending the content as text and I'll summarize it!"
            )
            return

        logger.info(f"✅ Extracted {len(text)} chars from {filename}")
        await progress.update_stage(2)

        # Store context for callback buttons
        # 🔴 FIX: تخزين السياق في الذاكرة + الداتابيز عشان يفضل موجود حتى بعد الـ restart
        _user_pdf_context[user_id] = {
            "text": text,
            "filename": filename,
        }
        # حفظ السياق في الداتابيز (persistent) عشان يفضل موجود بعد الـ restart
        try:
            from memory import save_memory
            import json
            # النص ممكن يكون طويل، فنخزنه منفصل
            save_memory(user_id, "pdf_context_filename", filename, "system")
            # لو النص أقل من 50000 حرف نخزنه كله، غير كده نخزن أول جزء
            if len(text) <= 50000:
                save_memory(user_id, "pdf_context_text", text, "system")
            else:
                save_memory(user_id, "pdf_context_text", text[:50000], "system")
            logger.info(f"✅ PDF context saved to database for user {user_id}")
        except Exception as save_err:
            logger.warning(f"⚠️ Failed to save PDF context to DB: {save_err}")

        # Show summary + inline buttons
        logger.info(f"🤖 Generating summary for {filename}...")
        summary = None
        try:
            summary = await asyncio.wait_for(
                pdf_agent.summarize(text, lang, user_id=user_id),
                timeout=180.0  # 🔴 FIX: timeout أعلى لتلخيص الملفات الكبيرة (3 دقائق)
            )
            summary = clean_ai_response(summary)
            logger.info(f"✅ Summary generated: {len(summary)} chars")
        except asyncio.TimeoutError:
            logger.error(f"❌ AI summarization timed out for {filename}")
            summary = None
        except Exception as e:
            logger.error(f"❌ AI summarization failed for {filename}: {e}")
            summary = None

        # 🔴 FIX: لو الـ AI فشل، نجرب تاني بنص أقصر، ولو برضه فشل نعرض النص بشكل منظم
        if not summary:
            # محاولة تانية بنص أقصر (أول 8000 حرف بس)
            logger.info(f"🔄 Retrying AI summarization with shorter text for {filename}...")
            try:
                short_text = text[:8000] if len(text) > 8000 else text
                summary = await asyncio.wait_for(
                    pdf_agent.summarize(short_text, lang, user_id=user_id),
                    timeout=180.0  # 🔴 3 دقائق كمان للretry
                )
                summary = clean_ai_response(summary)
                if summary:
                    logger.info(f"✅ Retry summary succeeded: {len(summary)} chars")
            except Exception as retry_err:
                logger.error(f"❌ Retry summarization also failed: {retry_err}")
                summary = None

        # لو برضه فشل، نعرض النص المستخرج بشكل منظم ومنسق
        if not summary:
            # تنظيف النص المستخرج من الكسر واللزق
            import re as _re
            #先用 fix_broken_lines لإصلاح النص المكسور
            text_fixed = PDFAgent._fix_broken_lines(text[:4000])
            clean_text = _re.sub(r'\n{3,}', '\n\n', text_fixed)
            clean_text = _re.sub(r' +', ' ', clean_text)
            # شيل الأسطر الفاضية المتكررة
            clean_text = _re.sub(r'\n\s*\n', '\n\n', clean_text)
            # حد أقصى عدد الأسطر
            lines = clean_text.split('\n')
            clean_text = '\n'.join(lines[:100])
            
            if lang == "ar":
                long_hint = "\n\n💡 النص طويل — اضغط الأزرار بالأسفل عشان تلخصه أو تستخرج النقاط الرئيسية!"
                short_hint = "\n\n💡 اضغط الأزرار بالأسفل عشان تلخصه أو تعمل كويز!"
                hint = long_hint if len(text) > 4000 else short_hint
                summary = f"📝 <b>المحتوى المستخرج:</b>\n\n{clean_text}{hint}"
            else:
                long_hint = "\n\n💡 Text is long — use buttons below to summarize or extract key points!"
                short_hint = "\n\n💡 Use buttons below to summarize or create a quiz!"
                hint = long_hint if len(text) > 4000 else short_hint
                summary = f"📝 <b>Extracted Content:</b>\n\n{clean_text}{hint}"
            logger.info(f"📄 Showing cleaned text instead of summary for {filename}")

        # Add filename header
        if lang == "ar":
            header = f"📄 <b>تحليل {file_type_label}: {filename}</b>\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            header = f"📄 <b>{file_type_label} Analysis: {filename}</b>\n━━━━━━━━━━━━━━━━━\n\n"

        full_message = header + summary

        inline_keyboard = get_pdf_inline_buttons(lang)

        if len(full_message) > 4000:
            chunks = smart_split_message(full_message)
            await progress.complete(delete_progress=True)
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await update.message.reply_text(chunk, parse_mode="HTML", reply_markup=inline_keyboard)
                else:
                    await update.message.reply_text(chunk, parse_mode="HTML")
        else:
            await progress.complete(final_message=full_message, reply_markup=inline_keyboard, delete_progress=False)

        # Save to memory
        try:
            save_conversation(user_id, "user", f"[{file_type_label}: {filename}]")
            save_conversation(user_id, "bot", summary[:200])
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error in handle_document: {e}", exc_info=True)
        try:
            track_event("total_errors")
        except Exception:
            pass
        try:
            await progress.error("حدث خطأ في تحليل الملف. جرب تاني." if lang == "ar" else "Error analyzing file. Please try again.")
        except Exception:
            # لو حتى الـ progress error فشل، ابعت رسالة عادية
            try:
                await update.message.reply_text("❌ حصل خطأ في تحليل الملف. جرب تاني." if lang == "ar" else "❌ Error analyzing file. Please try again.")
            except Exception:
                pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الصور - Image Analysis"""
    from premium import increment_usage, get_user_plan
    from admin import is_admin

    if await _is_duplicate_update(update.update_id):
        return

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_chat_count(user_id)

    if not update.message.photo:
        return

    # Premium check for image analyses (free: limited, premium: unlimited + Vision Pro)
    if not await _check_premium_limit(update, user_id, "image_analyses_per_day", lang):
        return

    # Vision Pro: Premium users get better vision models
    user_plan = get_user_plan(user_id)
    is_vision_pro = user_plan in ("premium", "premium_plus")
    username = update.effective_user.username if update.effective_user else None
    if is_admin(user_id, username):
        is_vision_pro = True

    photo = update.message.photo[-1]
    user_text = update.message.caption or ""

    if await _is_duplicate_user_message(user_id, f"photo_{photo.file_id}"):
        return

    increment_usage(user_id, "image_analyses")
    try:
        track_event("image_analyses")
    except Exception:
        pass

    try:
        # 🔴 FIX: إضافة Progress system عشان المستخدم يشوف إن البوت بيحلل
        from progress import ProgressManager, AI_STAGES
        stages = AI_STAGES(lang)
        title = "تحليل الصورة" if lang == "ar" else "Analyzing Image"
        progress = ProgressManager(update, context, stages, lang, title)
        await progress.start()

        await progress.update_stage(0)
        await progress.update_stage(1)

        photo_file = await context.bot.get_file(photo.file_id)
        image_bytes = await photo_file.download_as_bytearray()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # 🔴 تخزين سياق الصورة عشان زرار "البحث التفصيلي" يقدر يستخدمه
        from handlers.callbacks import _user_image_context
        _user_image_context[user_id] = {
            "image_base64": image_base64,
            "user_text": user_text,
        }

        # 🖌️ حفظ الصورة تلقائياً عشان المستخدم يقدر يعدلها بـ /edit بعد كده
        try:
            from handlers.image_handlers import _user_edit_images
            import time as _time
            _user_edit_images[user_id] = {
                "image_base64": image_base64,
                "created_at": _time.time(),
            }
        except Exception:
            pass  # non-critical

        # التحليل العام (مش تفصيلي - التفصيلي من الزرار)
        response = await analyze_image(
            image_base64=image_base64,
            language=lang,
            user_message=user_text,
            vision_pro=False,  # 🔴 عام مش تفصيلي - التفصيلي من زرار "البحث التفصيلي"
        )

        # Save to memory
        try:
            save_conversation(user_id, "user", f"[صورة] {user_text[:100]}")
            save_conversation(user_id, "bot", response[:200])
            detect_interests(user_id, user_text)
        except Exception:
            pass

        await progress.update_stage(2)

        # 🔴 إضافة header للتحليل العام
        if lang == "ar":
            header = "👁️ <b>تحليل الصورة</b>\n━━━━━━━━━━━━━━━━━\n\n"
        else:
            header = "👁️ <b>Image Analysis</b>\n━━━━━━━━━━━━━━━━━\n\n"

        full_response = header + response
        inline_keyboard = get_image_inline_buttons(lang)

        if len(full_response) > 4000:
            await progress.complete(delete_progress=True)
            chunks = smart_split_message(full_response)
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await update.message.reply_text(chunk, parse_mode="HTML", reply_markup=inline_keyboard)
                else:
                    await update.message.reply_text(chunk, parse_mode="HTML")
        else:
            await progress.complete(final_message=full_response, reply_markup=inline_keyboard, delete_progress=False)

    except Exception as e:
        logger.error(f"Error in handle_photo: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        if lang == "ar":
            await update.message.reply_text("❌ حصل خطأ في تحليل الصورة. جرب تاني.")
        else:
            await update.message.reply_text("❌ Error analyzing image. Please try again.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل الصوتية - Voice Message Processing"""
    from premium import increment_usage
    from agents.voice_agent import VoiceAgent
    voice_agent = VoiceAgent()

    if await _is_duplicate_update(update.update_id):
        return

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_chat_count(user_id)

    if not update.message.voice:
        return

    # Per-user dedup
    voice = update.message.voice
    if await _is_duplicate_user_message(user_id, f"voice_{voice.file_id}"):
        return

    try:
        track_event("voice_messages")
    except Exception:
        pass

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Download voice file with timeout
        try:
            file = await asyncio.wait_for(context.bot.get_file(voice.file_id), timeout=15.0)
            file_bytes = await asyncio.wait_for(file.download_as_bytearray(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.error("❌ Voice file download timed out")
            if lang == "ar":
                await update.message.reply_text("❌ انتهى وقت تحميل الصوت. جرب تاني.")
            else:
                await update.message.reply_text("❌ Voice download timed out. Please try again.")
            return

        # Transcribe
        if lang == "ar":
            status_msg = await update.message.reply_text("🎤 جاري تحويل الصوت لنص...")
        else:
            status_msg = await update.message.reply_text("🎤 Transcribing voice message...")

        # تحديد اللغة: العربي افتراضي، غير كده اللغة الأصلية
        lang_hint = "ar" if lang == "ar" else lang
        result = await voice_agent.process_voice_message(bytes(file_bytes), language_hint=lang_hint)

        if result["success"] and result["text"].strip():
            transcribed_text = result["text"].strip()
            await status_msg.delete()

            # Show transcription
            if lang == "ar":
                trans_msg = f'🎤 <b>تم تحويل الصوت:</b>\n\n<i>"{transcribed_text}"</i>\n\n🤖 جاري المعالجة...'
            else:
                trans_msg = f'🎤 <b>Transcribed:</b>\n\n<i>"{transcribed_text}"</i>\n\n🤖 Processing...'
            await update.message.reply_text(trans_msg, parse_mode="HTML")

            # Process the transcribed text as a normal message
            # Premium check for AI messages
            if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
                return

            increment_usage(user_id, "ai_messages")

            stages = AI_STAGES(lang)
            title = "التفكير" if lang == "ar" else "Thinking"
            progress = ProgressManager(update, context, stages, lang, title)
            await progress.start()

            try:
                await progress.update_stage(0)
                await progress.update_stage(1)

                from ai_engine import smart_chat
                detect_interests(user_id, transcribed_text)
                response = await smart_chat(transcribed_text, lang, user_id=user_id, username=update.effective_user.username)
                response = clean_ai_response(response)
                await progress.update_stage(2)

                if len(response) > 4000:
                    chunks = smart_split_message(response)
                    await progress.complete(delete_progress=True)
                    for chunk in chunks:
                        await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
                else:
                    await progress.complete(final_message=response, delete_progress=False)

            except Exception as e:
                logger.error(f"Error processing transcribed voice: {e}")
                await progress.error("حدث خطأ أثناء المعالجة" if lang == "ar" else "Error processing your message")

        else:
            # رسالة خطأ أوضح حسب سبب الفشل
            if result.get("error") == "no_api_key":
                if lang == "ar":
                    error_text = "⚠️ خدمة تحويل الصوت لنص مش متاحة حالياً.\n\n💡 ممكن تكتب رسالتك كنص بدل الصوت وهرد عليك عادي!"
                else:
                    error_text = "⚠️ Voice transcription is currently unavailable.\n\n💡 You can type your message instead and I'll respond normally!"
            else:
                if lang == "ar":
                    error_text = "❌ لم أتمكن من فهم الصوت. ممكن تجرب تاني أو تكتب الرسالة."
                else:
                    error_text = "❌ Couldn't transcribe the voice. Please try again or type your message."
            await status_msg.edit_text(error_text)

    except Exception as e:
        logger.error(f"Error in handle_voice: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        if lang == "ar":
            await update.message.reply_text("❌ حصل خطأ في معالجة الرسالة الصوتية.")
        else:
            await update.message.reply_text("❌ Error processing voice message.")


async def exit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /exit — الخروج من وضع الدراسة أو أي workflow نشط"""
    user_id = update.effective_user.id
    lang = get_language(user_id)

    # محاولة مسح الـ workflow عبر workflow_manager
    workflow_cleared = False
    try:
        from workflow_manager import get_workflow, clear_workflow
        workflow = get_workflow(user_id)
        if workflow:
            clear_workflow(user_id)
            workflow_cleared = True
    except ImportError:
        pass
    except Exception:
        pass

    # محاولة مسح user_states القديم
    from handlers.callbacks import user_states
    if user_id in user_states:
        user_states.pop(user_id, None)
        workflow_cleared = True

    if workflow_cleared:
        if lang == "ar":
            await update.message.reply_text("✅ خرجت من الوضع النشط. اكتب أي حاجة وهرد عليك عادي! 🤖")
        else:
            await update.message.reply_text("✅ Exited active mode. Type anything and I'll respond normally! 🤖")
    else:
        if lang == "ar":
            await update.message.reply_text("ℹ️ مش في أي وضع نشط دلوقتي. اكتب أي حاجة وهرد عليك! 🤖")
        else:
            await update.message.reply_text("ℹ️ You're not in any active mode right now. Type anything and I'll respond! 🤖")


async def study_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /study <topic> - وضع الدراسة (Premium)"""
    from premium import check_limit, premium_required_message, get_premium_keyboard
    from agents.study_agent import StudyAgent
    study_agent = StudyAgent()

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check
    if not check_limit(user_id, "study_mode")["allowed"]:
        await update.message.reply_text(
            premium_required_message("📚 وضع الدراسة / Study Mode", lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "📚 <b>وضع الدراسة</b>\n\nاكتب الموضوع بعد الأمر\nمثال: <code>/study machine learning</code>\n\n💡 هيشرحلك الموضوع بطريقة تعليمية ممتعة!"
        else:
            msg = "📚 <b>Study Mode</b>\n\nType the topic after the command\nExample: <code>/study machine learning</code>\n\n💡 I'll explain the topic in an engaging educational way!"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        track_event("ai_requests")
    except Exception:
        pass

    stages = LEARN_STAGES(lang)
    title = f"دراسة: {topic}" if lang == "ar" else f"Studying: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        explanation = await study_agent.explain_lesson(topic, language=lang, user_id=user_id)
        explanation = clean_ai_response(explanation)
        await progress.update_stage(2)

        try:
            save_learning(user_id, topic, "studied")
            detect_interests(user_id, topic)
        except Exception:
            pass

        # 🔴 FIX: لو الرسالة طويلة أكتر من 4000 حرف، نبعتهأ جزئين
        if len(explanation) > 4000:
            await progress.complete(delete_progress=True)
            chunks = smart_split_message(explanation)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML")
        else:
            await progress.complete(final_message=explanation, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /study: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /quiz <topic> - كويز (Premium)"""
    from premium import check_limit, premium_required_message, get_premium_keyboard
    from agents.study_agent import StudyAgent
    study_agent = StudyAgent()

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check
    if not check_limit(user_id, "study_mode")["allowed"]:
        await update.message.reply_text(
            premium_required_message("📝 كويز / Quiz", lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "📝 <b>كويز</b>\n\nاكتب الموضوع بعد الأمر\nمثال: <code>/quiz python basics</code>"
        else:
            msg = "📝 <b>Quiz</b>\n\nType the topic after the command\nExample: <code>/quiz python basics</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        track_event("ai_requests")
    except Exception:
        pass

    stages = AI_STAGES(lang)
    title = f"كويز: {topic}" if lang == "ar" else f"Quiz: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        quiz = await study_agent.generate_quiz(topic, language=lang, user_id=user_id)
        quiz = clean_ai_response(quiz)
        await progress.update_stage(2)
        # 🔴 FIX: لو الرسالة طويلة أكتر من 4000 حرف، نبعتهأ جزئين
        if len(quiz) > 4000:
            await progress.complete(delete_progress=True)
            chunks = smart_split_message(quiz)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML")
        else:
            await progress.complete(final_message=quiz, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /quiz: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def exam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /exam <topic> - امتحان شامل (Premium)"""
    from premium import check_limit, premium_required_message, get_premium_keyboard
    from agents.study_agent import StudyAgent
    study_agent = StudyAgent()

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check
    if not check_limit(user_id, "study_mode")["allowed"]:
        await update.message.reply_text(
            premium_required_message("📋 امتحان / Exam", lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "📋 <b>امتحان شامل</b>\n\nاكتب الموضوع بعد الأمر\nمثال: <code>/exam deep learning</code>"
        else:
            msg = "📋 <b>Comprehensive Exam</b>\n\nType the topic after the command\nExample: <code>/exam deep learning</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        track_event("ai_requests")
    except Exception:
        pass

    stages = AI_STAGES(lang)
    title = f"امتحان: {topic}" if lang == "ar" else f"Exam: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        exam = await study_agent.generate_exam(topic, language=lang, user_id=user_id)
        exam = clean_ai_response(exam)
        await progress.update_stage(2)
        # 🔴 FIX: لو الرسالة طويلة أكتر من 4000 حرف، نبعتهأ جزئين
        if len(exam) > 4000:
            await progress.complete(delete_progress=True)
            chunks = smart_split_message(exam)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML")
        else:
            await progress.complete(final_message=exam, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /exam: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")


async def studyplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /plan <topic> - خطة دراسية (Premium)"""
    from premium import check_limit, premium_required_message, get_premium_keyboard
    from agents.study_agent import StudyAgent
    study_agent = StudyAgent()

    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check
    if not check_limit(user_id, "study_mode")["allowed"]:
        await update.message.reply_text(
            premium_required_message("📚 خطة دراسية / Study Plan", lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    topic = " ".join(context.args) if context.args else ""

    if not topic:
        if lang == "ar":
            msg = "📚 <b>خطة دراسية</b>\n\nاكتب الموضوع بعد الأمر\nمثال: <code>/plan python</code>"
        else:
            msg = "📚 <b>Study Plan</b>\n\nType the topic after the command\nExample: <code>/plan python</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    try:
        track_event("ai_requests")
    except Exception:
        pass

    stages = ROADMAP_STAGES(lang)
    title = f"خطة دراسية: {topic}" if lang == "ar" else f"Study Plan: {topic}"
    progress = ProgressManager(update, context, stages, lang, title)
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)
        plan = await study_agent.create_study_plan(topic, language=lang, user_id=user_id)
        plan = clean_ai_response(plan)
        await progress.update_stage(2)
        # 🔴 FIX: لو الرسالة طويلة أكتر من 4000 حرف، نبعتهأ جزئين
        if len(plan) > 4000:
            await progress.complete(delete_progress=True)
            chunks = smart_split_message(plan)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML")
        else:
            await progress.complete(final_message=plan, delete_progress=False)
    except Exception as e:
        logger.error(f"Error in /plan (study): {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        await progress.error("حدث خطأ" if lang == "ar" else "Error occurred")
