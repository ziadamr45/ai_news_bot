"""
Free chat handler with smart intent detection + Workflow State Management.

v10.0 FIXES:
1. Workflow State Management: Active workflows are checked FIRST before AI
2. Conversation Saving: User messages + bot responses are saved to DB for context
3. Timeout + Retry: AI calls have timeout, Telegram sends have retry logic
"""

import asyncio
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


# ═══════════════════════════════════════
# دوال مساعدة للإرسال الآمن - Safe Send with Retry
# ═══════════════════════════════════════

async def _safe_send_message(update: Update, text: str, parse_mode: str = "HTML",
                              disable_web_page_preview: bool = False, max_retries: int = 2,
                              reply_markup=None):
    """إرسال رسالة تيليجرام مع retry تلقائي لو فشل
    
    المشاكل اللي بتحل:
    - طول الرسالة أكتر من 4096 حرف → تقسيم تلقائي
    - فشل الإرسال بسبب شبكة → retry تلقائي
    - فشل الإرسال بسبب HTML غلط → إرسال بدون HTML
    """
    # لو الرسالة طويلة، قسمها الأول
    if len(text) > 4000:
        chunks = smart_split_message(text)
        for chunk in chunks:
            await _safe_send_single(update, chunk, parse_mode, disable_web_page_preview, max_retries)
        return
    
    await _safe_send_single(update, text, parse_mode, disable_web_page_preview, max_retries, reply_markup)


async def _safe_send_single(update: Update, text: str, parse_mode: str = "HTML",
                             disable_web_page_preview: bool = False, max_retries: int = 2,
                             reply_markup=None):
    """إرسال رسالة واحدة مع retry"""
    for attempt in range(max_retries + 1):
        try:
            await update.message.reply_text(
                text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
            )
            return
        except Exception as e:
            error_str = str(e).lower()
            
            # لو المشكلة في HTML → إرسال بدون HTML
            if "can't parse" in error_str or "html" in error_str:
                logger.warning(f"⚠️ HTML parse error, retrying without HTML: {e}")
                try:
                    clean_text = text.replace('<b>', '').replace('</b>', '')
                    clean_text = clean_text.replace('<i>', '').replace('</i>', '')
                    clean_text = clean_text.replace('<code>', '').replace('</code>', '')
                    clean_text = clean_text.replace('<a href=', '').replace('</a>', '')
                    await update.message.reply_text(clean_text[:4000])
                    return
                except Exception:
                    pass
            
            # لو المشكلة في طول الرسالة → تقسيم
            if "too long" in error_str or "message is too long" in error_str:
                logger.warning(f"⚠️ Message too long, splitting: {len(text)} chars")
                chunks = smart_split_message(text)
                for chunk in chunks:
                    try:
                        await update.message.reply_text(chunk, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview)
                    except Exception:
                        pass
                return
            
            # retry لو في خطأ شبكة
            if attempt < max_retries:
                logger.warning(f"⚠️ Send failed (attempt {attempt+1}/{max_retries+1}): {e}")
                await asyncio.sleep(1)
            else:
                logger.error(f"❌ Send failed after {max_retries+1} attempts: {e}")


async def _safe_send_with_progress(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                    response: str, lang: str = "ar",
                                    progress: ProgressManager = None,
                                    reply_markup=None):
    """إرسال رد مع progress + retry + تقسيم تلقائي
    
    دي الدالة الأساسية اللي بنستخدمها عشان نبعت رد AI:
    1. لو في progress نشط → نكمله
    2. لو الرسالة طويلة → نقسمها
    3. لو الإرسال فشل → نعمل retry
    """
    try:
        if len(response) > 4000:
            if progress:
                await progress.complete(delete_progress=True)
            chunks = smart_split_message(response)
            for i, chunk in enumerate(chunks):
                try:
                    await update.message.reply_text(
                        chunk,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup if i == len(chunks) - 1 else None,
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send chunk {i}: {e}")
                    # retry بدون HTML
                    try:
                        clean = chunk.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<code>', '').replace('</code>', '')
                        await update.message.reply_text(clean[:4000])
                    except Exception:
                        pass
        else:
            if progress:
                try:
                    await progress.complete(final_message=response, reply_markup=reply_markup, delete_progress=False)
                except Exception as e:
                    # لو progress.complete فشل (مثلاً الرسالة طويلة)، نبعت يدوي
                    logger.warning(f"⚠️ progress.complete failed, sending manually: {e}")
                    try:
                        await progress.complete(delete_progress=True)
                    except Exception:
                        pass
                    await update.message.reply_text(response, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_markup)
            else:
                await update.message.reply_text(response, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"❌ Critical error in _safe_send_with_progress: {e}")
        # آخر محاولة: إرسال بدون أي تنسيق
        try:
            plain = response[:4000].replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<code>', '').replace('</code>', '')
            await update.message.reply_text(plain)
        except Exception:
            pass


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل العادية - محادثة حرة مع AI + كشف ذكي
    
    أولوية التوجيه (Message Routing Priority):
    1. Workflow نشط → توجيه الرسالة للخدمة المسؤولة
    2. أزرار الكيبورد → توجيه للأمر المناسب
    3. أوامر ذكية (URL, ذاكرة) → توجيه للخدمة
    4. الذكاء الاصطناعي → محادثة حرة
    """
    # 🔴 FIX v2: هذه الموديولات تم تحميلها بالفعل في handlers/__init__.py
    try:
        from handlers.memory_handlers import memory_command
    except ImportError:
        memory_command = None
        logger.warning("⚠️ memory_command import failed (non-critical)")

    try:
        from handlers.news_handlers import news_command, trending_command
    except ImportError:
        news_command = None
        trending_command = None
        logger.warning("⚠️ news_handlers import failed (non-critical)")

    try:
        from handlers.basic_handlers import help_command, premium_command
    except ImportError:
        help_command = None
        premium_command = None
        logger.warning("⚠️ basic_handlers import failed (non-critical)")

    # 🔴 FIX: استيراد اختياري — الوكلاء (agents) مش لازم للمحادثة العادية
    _YouTubeAgent = None
    _PDFAgent = None
    try:
        from agents.youtube_agent import YouTubeAgent as _YT
        _YouTubeAgent = _YT
    except ImportError as ie:
        logger.warning(f"⚠️ YouTubeAgent import failed (non-critical): {ie}")

    try:
        from agents.pdf_agent import PDFAgent as _PDF
        _PDFAgent = _PDF
    except ImportError as ie:
        logger.warning(f"⚠️ PDFAgent import failed (non-critical): {ie}")

    # استيراد اختياري — مش لازم يشتغل عشان المحادثة تفضل شغالة
    try:
        from handlers.media_handlers import _process_youtube_url
    except ImportError:
        _process_youtube_url = None

    if await _is_duplicate_update(update.update_id):
        return

    user_id = update.effective_user.id
    user_text = update.message.text or ""
    
    # 🔴 FIX: get_language محتاج try/except
    try:
        lang = get_language(user_id)
    except Exception:
        lang = "ar"

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
        pass

    try:
        track_event("total_messages")
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════
    # 🥇 الأولوية 1: Workflow النشط — توجيه الرسالة للخدمة المسؤولة
    # ═══════════════════════════════════════════════════════════════
    # لو المستخدم داخل workflow نشط (وضع دراسة، سؤال PDF، تعديل صورة)
    # رسالته بتروح للخدمة المسؤولة مش للـ AI
    workflow = None
    try:
        from workflow_manager import get_workflow, clear_workflow, update_workflow_step, touch_workflow
        workflow = get_workflow(user_id)
    except ImportError:
        logger.warning("⚠️ workflow_manager not available, falling back to user_states")
    except Exception as e:
        logger.debug(f"Workflow check error (non-critical): {e}")

    if workflow:
        workflow_name = workflow.get("workflow", "")
        workflow_step = workflow.get("step", "")
        workflow_data = workflow.get("data", {})
        
        logger.info(f"🔄 Active workflow for user {user_id}: {workflow_name}/{workflow_step}")
        
        # ═══ Study Mode Workflow ═══
        if workflow_name == "study_mode":
            # تمديد صلاحية الـ workflow
            try:
                touch_workflow(user_id)
            except Exception:
                pass
            
            if workflow_step == "waiting_for_subject":
                # المستخدم كتب الموضوع اللي عايز يدرسه
                topic = user_text.strip()
                
                # Premium check
                if not check_limit(user_id, "study_mode")["allowed"]:
                    await update.message.reply_text(
                        premium_required_message("📚 وضع الدراسة / Study Mode", lang),
                        parse_mode="HTML",
                        reply_markup=get_premium_keyboard(lang, user_id=user_id)
                    )
                    clear_workflow(user_id)
                    return
                
                # حفظ رسالة المستخدم
                try:
                    save_conversation(user_id, "user", user_text[:1000])
                except Exception:
                    pass
                
                # تحديث الـ workflow للخطوة الجاية
                try:
                    update_workflow_step(user_id, "active", {"subject": topic})
                except Exception:
                    pass
                
                # Premium check for AI
                if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
                    return
                
                increment_usage(user_id, "ai_messages")
                try:
                    track_event("ai_requests")
                except Exception:
                    pass
                
                # شرح الموضوع
                try:
                    from agents.study_agent import StudyAgent
                    study_agent = StudyAgent()
                except ImportError:
                    study_agent = None
                
                if study_agent:
                    stages = AI_STAGES(lang)
                    title = f"دراسة: {topic}" if lang == "ar" else f"Studying: {topic}"
                    progress = ProgressManager(update, context, stages, lang, title)
                    await progress.start()
                    
                    try:
                        await progress.update_stage(0)
                        await progress.update_stage(1)
                        
                        # 🔴 FIX: إضافة timeout للـ AI call
                        explanation = await asyncio.wait_for(
                            study_agent.explain_lesson(topic, language=lang, user_id=user_id),
                            timeout=120  # أقصى وقت 2 دقيقة
                        )
                        explanation = clean_ai_response(explanation)
                        await progress.update_stage(2)
                        
                        # حفظ رد البوت
                        try:
                            save_conversation(user_id, "bot", explanation[:1000])
                        except Exception:
                            pass
                        
                        try:
                            from memory import save_learning
                            save_learning(user_id, topic, "studied")
                            detect_interests(user_id, topic)
                        except Exception:
                            pass
                        
                        await _safe_send_with_progress(update, context, explanation, lang, progress)
                        
                        # المستخدم يقدر يكمل سؤال في وضع الدراسة
                        if lang == "ar":
                            followup = "\n\n📚 <i>أنت في وضع الدراسة — اكتب أي سؤال عن الموضوع أو اكتب /exit عشان تخرج</i>"
                        else:
                            followup = "\n\n📚 <i>You're in Study Mode — ask any question or type /exit to leave</i>"
                        await update.message.reply_text(followup, parse_mode="HTML")
                        
                    except asyncio.TimeoutError:
                        logger.error(f"⏰ Study mode AI timed out for: {topic}")
                        await progress.error("⏰ استغرق الشرح وقت طويل. جرب تاني!" if lang == "ar" else "⏰ Explanation timed out. Please try again!")
                        try:
                            track_event("total_errors")
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(f"Error in study_mode workflow: {e}")
                        try:
                            track_event("total_errors")
                        except Exception:
                            pass
                        await progress.error("❌ حصل خطأ في الشرح. جرب تاني!" if lang == "ar" else "❌ Error explaining. Please try again!")
                else:
                    # fallback للـ AI العادي
                    clear_workflow(user_id)
                
                return  # لا تكمل — الرسالة اتعالجت بواسطة الـ workflow
            
            elif workflow_step == "active":
                # المستخدم داخل وضع الدراسة وبيسأل سؤال
                subject = workflow_data.get("subject", "")
                
                # لو عايز يخرج من وضع الدراسة
                if user_text.strip().lower() in ("/exit", "خروج", "exit", "الغاء", "إلغاء", "cancel"):
                    clear_workflow(user_id)
                    if lang == "ar":
                        await update.message.reply_text("✅ خرجت من وضع الدراسة. اكتب أي حاجة وهرد عليك عادي! 🤖")
                    else:
                        await update.message.reply_text("✅ Exited Study Mode. Type anything and I'll respond normally! 🤖")
                    return
                
                # حفظ رسالة المستخدم
                try:
                    save_conversation(user_id, "user", f"[دراسة: {subject}] {user_text[:800]}")
                except Exception:
                    pass
                
                # Premium check
                if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
                    return
                
                increment_usage(user_id, "ai_messages")
                
                # بنبني سؤال فيه سياق الموضوع
                if subject:
                    contextual_message = f"المستخدم بيدرس {subject} وسأل: {user_text}" if lang == "ar" else f"User is studying {subject} and asked: {user_text}"
                else:
                    contextual_message = user_text
                
                stages = AI_STAGES(lang)
                title = "وضع الدراسة" if lang == "ar" else "Study Mode"
                progress = ProgressManager(update, context, stages, lang, title)
                await progress.start()
                
                try:
                    await progress.update_stage(0)
                    await progress.update_stage(1)
                    
                    # 🔴 FIX: إضافة timeout
                    response = await asyncio.wait_for(
                        smart_chat(contextual_message, lang, user_id=user_id, username=update.effective_user.username),
                        timeout=120
                    )
                    response = clean_ai_response(response)
                    await progress.update_stage(2)
                    
                    # حفظ رد البوت
                    try:
                        save_conversation(user_id, "bot", response[:1000])
                    except Exception:
                        pass
                    
                    # حفظ ذكريات تلقائية
                    if user_id and response:
                        try:
                            from memory_context import auto_save_conversation_memory
                            auto_save_conversation_memory(user_id, user_text, response)
                        except Exception:
                            pass
                    
                    await _safe_send_with_progress(update, context, response, lang, progress)
                    
                    # تذكير إنه في وضع الدراسة
                    if lang == "ar":
                        reminder = "\n\n📚 <i>وضع الدراسة — اكتب سؤال تاني أو /exit للخروج</i>"
                    else:
                        reminder = "\n\n📚 <i>Study Mode — ask another question or /exit to leave</i>"
                    await update.message.reply_text(reminder, parse_mode="HTML")
                    
                except asyncio.TimeoutError:
                    logger.error(f"⏰ Study mode chat timed out for user {user_id}")
                    await progress.error("⏰ الرد استغرق وقت طويل. جرب تاني!" if lang == "ar" else "⏰ Response timed out. Please try again!")
                except Exception as e:
                    logger.error(f"Error in study_mode active chat: {e}")
                    await progress.error("❌ حصل خطأ. جرب تاني!" if lang == "ar" else "❌ Error occurred. Please try again!")
                
                return  # لا تكمل — الرسالة اتعالجت
        
        # ═══ PDF Question Workflow ═══
        elif workflow_name == "pdf_question":
            try:
                touch_workflow(user_id)
            except Exception:
                pass
            
            from handlers.callbacks import _get_pdf_context
            ctx = _get_pdf_context(user_id)
            if ctx and _PDFAgent:
                pdf_agent = _PDFAgent()
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                try:
                    # حفظ سؤال المستخدم
                    try:
                        save_conversation(user_id, "user", f"[PDF سؤال] {user_text[:800]}")
                    except Exception:
                        pass
                    
                    result = await asyncio.wait_for(
                        pdf_agent.answer_question(ctx["text"], user_text, lang, user_id=user_id),
                        timeout=120
                    )
                    result = clean_ai_response(result)
                    
                    # حفظ رد البوت
                    try:
                        save_conversation(user_id, "bot", result[:1000])
                    except Exception:
                        pass
                    
                    await _safe_send_message(update, result)
                except asyncio.TimeoutError:
                    logger.error(f"⏰ PDF question timed out for user {user_id}")
                    if lang == "ar":
                        await update.message.reply_text("⏰ استغرق الرد وقت طويل. جرب تاني!")
                    else:
                        await update.message.reply_text("⏰ Response timed out. Please try again!")
                except Exception as e:
                    logger.error(f"Error answering PDF question: {e}")
                    await update.message.reply_text("❌ حصل خطأ. جرب تاني." if lang == "ar" else "❌ Error occurred. Please try again.")
            
            # لا نمسح الـ workflow — المستخدم يقدر يسأل أسئلة كتير عن نفس PDF
            return
        
        # ═══ Image Edit Workflow ═══
        elif workflow_name == "image_edit":
            try:
                touch_workflow(user_id)
            except Exception:
                pass
            
            from handlers.image_handlers import _translate_prompt_to_english
            from provider_manager import get_provider_manager
            from premium import can_use_image_edit
            
            image_base64 = workflow_data.get("image_base64", "")
            clear_workflow(user_id)  # Clear after use
            
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
                
                original_prompt = user_text
                edit_prompt = await _translate_prompt_to_english(user_text, user_id=user_id)
                was_translated = (edit_prompt != original_prompt)
                
                manager = get_provider_manager()
                result = await asyncio.wait_for(
                    manager.edit_image_async(
                        prompt=edit_prompt,
                        image_base64=image_base64,
                        user_id=user_id,
                    ),
                    timeout=120
                )
                
                await progress.update_stage(2)
                
                if not result:
                    await progress.error("❌ حصل خطأ في تعديل الصورة. جرب وصف تاني!" if lang == "ar" else "❌ Error editing image. Try a different description!")
                    return
                
                # حفظ المحادثة
                try:
                    save_conversation(user_id, "user", f"[تعديل صورة] {user_text[:500]}")
                except Exception:
                    pass
                
                caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:200]}</i>"
                if was_translated:
                    caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:150]}</i>\n🌐 <i>{edit_prompt[:150]}</i>"
                
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
                
            except asyncio.TimeoutError:
                logger.error(f"⏰ Image edit timed out for user {user_id}")
                await progress.error("⏰ تعديل الصورة استغرق وقت طويل. جرب تاني!" if lang == "ar" else "⏰ Image edit timed out. Please try again!")
            except Exception as e:
                logger.error(f"Error in image_edit workflow: {e}")
                await progress.error("❌ حصل خطأ في تعديل الصورة." if lang == "ar" else "❌ Error editing image.")
            
            return

    # ═══════════════════════════════════════════════════════════════
    # 🥈 الأولوية 1.5: Backward compatibility — user_states القديم
    # ═══════════════════════════════════════════════════════════════
    # لو الـ workflow_manager مش متاح، بنستخدم user_states القديم
    user_state = user_states.get(user_id, {})
    if user_state.get("waiting_for") == "pdf_question":
        from handlers.callbacks import _get_pdf_context
        ctx = _get_pdf_context(user_id)
        if ctx and _PDFAgent:
            pdf_agent = _PDFAgent()
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                try:
                    save_conversation(user_id, "user", f"[PDF سؤال] {user_text[:800]}")
                except Exception:
                    pass
                
                result = await asyncio.wait_for(
                    pdf_agent.answer_question(ctx["text"], user_text, lang, user_id=user_id),
                    timeout=120
                )
                result = clean_ai_response(result)
                
                try:
                    save_conversation(user_id, "bot", result[:1000])
                except Exception:
                    pass
                
                await _safe_send_message(update, result)
            except asyncio.TimeoutError:
                if lang == "ar":
                    await update.message.reply_text("⏰ استغرق الرد وقت طويل. جرب تاني!")
                else:
                    await update.message.reply_text("⏰ Response timed out. Please try again!")
            except Exception as e:
                logger.error(f"Error answering PDF question: {e}")
                await update.message.reply_text("❌ حصل خطأ. جرب تاني." if lang == "ar" else "❌ Error occurred. Please try again.")
            # لا نمسح — المستخدم يقدر يسأل كتير
            return
        else:
            user_states.pop(user_id, None)

    if user_states.get(user_id, {}).get("waiting_for") == "image_edit":
        from handlers.image_handlers import _translate_prompt_to_english
        from provider_manager import get_provider_manager
        from premium import can_use_image_edit
        
        img_state = user_states.get(user_id, {})
        image_base64 = img_state.get("image_base64", "")
        user_states.pop(user_id, None)
        
        if not can_use_image_edit(user_id):
            await update.message.reply_text("❌ الميزة دي Premium بس." if lang == "ar" else "❌ This feature is Premium only.")
            return
        
        if not image_base64:
            if lang == "ar":
                await update.message.reply_text("❌ الصورة مش متاحة. ارفعها تاني.")
            else:
                await update.message.reply_text("❌ Image not available. Please upload it again.")
            return
        
        stages = AI_STAGES(lang)
        title = "تعديل الصورة" if lang == "ar" else "Editing Image"
        progress = ProgressManager(update, context, stages, lang, title)
        await progress.start()
        
        try:
            await progress.update_stage(0)
            await progress.update_stage(1)
            original_prompt = user_text
            edit_prompt = await _translate_prompt_to_english(user_text, user_id=user_id)
            was_translated = (edit_prompt != original_prompt)
            manager = get_provider_manager()
            result = await asyncio.wait_for(
                manager.edit_image_async(prompt=edit_prompt, image_base64=image_base64, user_id=user_id),
                timeout=120
            )
            await progress.update_stage(2)
            
            if not result:
                await progress.error("❌ حصل خطأ في تعديل الصورة. جرب وصف تاني!" if lang == "ar" else "❌ Error editing image.")
                return
            
            caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:200]}</i>"
            if was_translated:
                caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:150]}</i>\n🌐 <i>{edit_prompt[:150]}</i>"
            
            if result.get("base64"):
                import base64, io
                image_bytes = base64.b64decode(result["base64"])
                await progress.complete(delete_progress=True)
                await update.message.reply_photo(photo=io.BytesIO(image_bytes), caption=caption, parse_mode="HTML")
            elif result.get("url"):
                await progress.complete(delete_progress=True)
                await update.message.reply_photo(photo=result["url"], caption=caption, parse_mode="HTML")
            else:
                await progress.error("❌ حصل خطأ في تعديل الصورة." if lang == "ar" else "❌ Error editing image.")
            
            increment_usage(user_id, "image_edits")
            try: track_event("image_edits")
            except: pass
        except asyncio.TimeoutError:
            await progress.error("⏰ تعديل الصورة استغرق وقت طويل. جرب تاني!" if lang == "ar" else "⏰ Image edit timed out.")
        except Exception as e:
            logger.error(f"Error in image_edit state: {e}")
            await progress.error("❌ حصل خطأ في تعديل الصورة." if lang == "ar" else "❌ Error editing image.")
        return

    # ═══════════════════════════════════════════════════════════════
    # 🥈 الأولوية 2: أزرار لوحة المفاتيح
    # ═══════════════════════════════════════════════════════════════
    keyboard_commands = {
        "📰 الأخبار": "/news", "📰 News": "/news",
        "🤖 اسأل My Bro": "/ask", "🤖 Ask My Bro": "/ask",
        "🔍 البحث": "/search", "🔍 Search": "/search",
        "🔍 بحث الويب": "/search", "🔍 Web Search": "/search",
        "📚 تعلم AI": "/learn", "📚 Learn AI": "/learn",
        "📚 وضع الدراسة": "/study", "📚 Study Mode": "/study",
        "⚙️ الإعدادات": "settings", "⚙️ Settings": "settings",
        "ℹ️ المساعدة": "/help", "ℹ️ Help": "/help",
        "⭐ Premium": "/premium", "⭐ Premium": "/premium",
        "📋 الخطة و حدود الإستخدام": "/premium", "📋 Plan & Usage": "/premium",
        "📄 تحليل ملف": "pdf_upload", "📄 Analyze File": "pdf_upload",
        "🎬 ملخص يوتيوب": "youtube_prompt", "🎬 YouTube Summary": "youtube_prompt",
        "🧠 ذاكرتي": "/memory", "🧠 My Memory": "/memory",
        "📈 التريندات": "/trending", "📈 Trending": "/trending",
        "🎨 صورة": "/image", "🎨 Image": "/image",
        "🎨 إنشاء صورة": "/image", "🎨 Create Image": "/image",
        "🖌️ عدّل صورة": "edit_prompt", "🖌️ Edit Image": "edit_prompt",
        "🖌️ تعديل": "edit_prompt", "🖌️ Edit": "edit_prompt",
        "📥 تحميل فيديو": "download_prompt", "📥 Download Video": "download_prompt",
        "📥 تحميل": "download_prompt", "📥 Download": "download_prompt",
    }

    quota_free_commands = {"settings", "/premium", "/help", "/memory"}

    if user_text in keyboard_commands:
        cmd = keyboard_commands[user_text]

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
                if premium_command:
                    await premium_command(update, context)
                return
            elif cmd == "/help":
                if help_command:
                    await help_command(update, context)
                return
            elif cmd == "/memory":
                if memory_command:
                    await memory_command(update, context)
                return

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
            # 🔴 FIX: وضع الدراسة — نحفظ الـ workflow عشان الرسالة الجاية تتوجه صح
            if not check_limit(user_id, "study_mode")["allowed"]:
                await update.message.reply_text(
                    premium_required_message("📚 وضع الدراسة / Study Mode", lang),
                    parse_mode="HTML",
                    reply_markup=get_premium_keyboard(lang, user_id=user_id)
                )
                return
            # حفظ حالة وضع الدراسة
            try:
                from workflow_manager import set_workflow
                set_workflow(user_id, "study_mode", "waiting_for_subject")
            except Exception:
                pass  # fallback: الكيبورد بس هيقول يكتب الموضوع
            
            if lang == "ar":
                msg = "📚 <b>وضع الدراسة</b>\n\nاكتب الموضوع اللي عايز تدرسه!\nمثال: machine learning, python, data science\n\n💡 اكتب /exit عشان تخرج من وضع الدراسة"
            else:
                msg = "📚 <b>Study Mode</b>\n\nType the topic you want to study!\nExample: machine learning, python, data science\n\n💡 Type /exit to leave Study Mode"
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
            from handlers.image_handlers import image_command
            context.args = []
            await image_command(update, context)
            return
        elif cmd == "edit_prompt":
            from handlers.image_handlers import edit_command
            context.args = []
            await edit_command(update, context)
            return
        elif cmd == "download_prompt":
            if lang == "ar":
                msg = "📥 <b>تحميل وسائط من أي منصة</b>\n\n💡 <b>طريقتين:</b>\n1️⃣ ابعت الرابط لوحده وهيحملهولك تلقائي!\n2️⃣ أو استخدم: <code>/download الرابط</code>\n\n<b>المنصات المدعومة:</b>\n→ YouTube, Facebook, Instagram\n→ TikTok, Twitter/X, Telegram\n→ Threads, Reddit, Vimeo\n\n⭐ الميزة دي Premium بس"
            else:
                msg = "📥 <b>Download Media from Any Platform</b>\n\n💡 <b>Two ways:</b>\n1️⃣ Just paste the URL and it will auto-download!\n2️⃣ Or use: <code>/download URL</code>\n\n<b>Supported Platforms:</b>\n→ YouTube, Facebook, Instagram\n→ TikTok, Twitter/X, Telegram\n→ Threads, Reddit, Vimeo\n\n⭐ Premium only feature"
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        else:
            context.args = []
            if cmd == "/news":
                if news_command:
                    await news_command(update, context)
            elif cmd == "/trending":
                if trending_command:
                    await trending_command(update, context)
            return

    # ═══════════════════════════════════════════════════════════════
    # 🥉 الأولوية 3: فحص الكوتا
    # ═══════════════════════════════════════════════════════════════
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

    # ═══════════════════════════════════════════════════════════════
    # 🥉 الأولوية 3.5: أوامر ذكية (ذاكرة، روابط)
    # ═══════════════════════════════════════════════════════════════
    # Smart Intent: Memory Questions
    memory_keywords_ar = ["ذاكرتك", "ذاكرتي", "فاكرك", "فاكرة", "تعرف عني", "معلوماتك عني", "ايه اللي فاكره", "بتفكرني", "عامل ايه ذاكرتك"]
    memory_keywords_en = ["your memory", "my memory", "remember me", "what do you know about me", "what you know about me", "do you remember"]
    text_lower = user_text.lower()
    is_memory_question = any(kw in text_lower for kw in memory_keywords_ar + memory_keywords_en)
    if is_memory_question:
        if memory_command:
            await memory_command(update, context)
            return

    # Smart Intent: Any Media URL → Auto Download
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
        is_social = platform != "unknown"
        is_direct_media = direct_type in ("image", "audio", "video")
        
        if is_social or is_direct_media:
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

    # ═══════════════════════════════════════════════════════════════
    # 🏅 الأولوية 4: محادثة ذكية مع AI (المرحلة الأخيرة)
    # ═══════════════════════════════════════════════════════════════
    if not await _check_premium_limit(update, user_id, "ai_messages_per_day", lang):
        return

    increment_usage(user_id, "ai_messages")
    try:
        track_event("ai_requests")
    except Exception:
        pass

    # 🔴 NOTE: رسالة المستخدم بتتحفظ جوا smart_chat() تلقائي
    # لو الـ AI timeout، بنحفظ الرسالة في الـ timeout handler

    stages = AI_STAGES(lang)
    title = "التفكير" if lang == "ar" else "Thinking"
    progress = ProgressManager(update, context, stages, lang, title, timeout=180)  # 🔴 FIX: timeout 3 دقائق
    await progress.start()

    try:
        await progress.update_stage(0)
        await progress.update_stage(1)

        # 🔴 FIX (Problem 3): إضافة timeout صريح للـ AI call
        # لو الـ AI استغرق أكتر من 120 ثانية، نبعت رسالة خطأ بدل ما يعلق
        try:
            response = await asyncio.wait_for(
                smart_chat(user_text, lang, user_id=user_id, username=update.effective_user.username),
                timeout=120  # أقصى وقت 2 دقيقة للـ AI
            )
        except asyncio.TimeoutError:
            logger.error(f"⏰ AI chat timed out after 120s for user {user_id}: {user_text[:50]}")
            # 🔴 FIX: حفظ رسالة المستخدم حتى لو timeout — عشان السياق ما يضيعش
            try:
                save_conversation(user_id, "user", user_text[:1000])
            except Exception:
                pass
            try:
                track_event("total_errors")
            except Exception:
                pass
            await progress.error(
                "⏰ استغرق الرد وقت طويل. جرب تاني أو اختصر سؤالك!" if lang == "ar"
                else "⏰ Response took too long. Please try again or simplify your question!"
            )
            return

        response = clean_ai_response(response)
        await progress.update_stage(2)

        # 🔴 NOTE: رد البوت بيتحفظ جوا smart_chat() تلقائي — مش محتاجين نحفظه تاني

        # حفظ ذكريات تلقائية (تفضيلات، معلومات شخصية)
        if user_id and response:
            try:
                from memory_context import auto_save_conversation_memory
                auto_save_conversation_memory(user_id, user_text, response)
            except Exception as e:
                logger.debug(f"Auto-save memory error (non-critical): {e}")

        # 🔴 FIX (Problem 3): إرسال آمن مع retry + تقسيم
        await _safe_send_with_progress(update, context, response, lang, progress)

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        try:
            track_event("total_errors")
        except Exception:
            pass
        try:
            await progress.error("مش فاهم رسالتك كويس. ممكن تكتبها بطريقة تانية؟" if lang == "ar" else "I didn't understand your message. Could you rephrase it?")
        except Exception:
            # لو حتى الـ progress error فشل
            try:
                await update.message.reply_text("❌ حصل خطأ. جرب تاني!" if lang == "ar" else "❌ Error occurred. Please try again.")
            except Exception:
                pass
