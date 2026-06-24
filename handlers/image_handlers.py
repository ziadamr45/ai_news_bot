"""
Image Generation & Editing Handlers
🎨 /image — إنشاء صور من وصف نصي (بريميوم بس)
🖌️ /edit — تعديل صورة بناءً على وصف نصي (بريميوم بس)
🔴 FIX: ترجمة الوصف العربي تلقائيًا للإنجليزية قبل الإرسال لنماذج الصور
   لأن نماذج الصور (SD 3.5, Flux) مش بتفهم عربي كويس
"""

import logging
import asyncio
import base64
import io
import re

from telegram import Update
from telegram.ext import ContextTypes

from memory import get_language, increment_command_count
from premium import (
    check_limit, increment_usage, premium_required_message,
    get_premium_keyboard, can_use_image_gen, can_use_image_edit,
)
from dashboard import track_event
from provider_manager import get_provider_manager
from progress import ProgressManager, AI_STAGES, TelegramThinkingFeedback
from handlers.dedup import _is_duplicate_update, _is_duplicate_user_message

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# ترجمة الوصف العربي - Arabic Prompt Translation
# ═══════════════════════════════════════

ARABIC_CHAR_PATTERN = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')


def _contains_arabic(text: str) -> bool:
    """كشف هل النص فيه حروف عربية"""
    return bool(ARABIC_CHAR_PATTERN.search(text))


async def _translate_prompt_to_english(prompt: str, user_id: int = None) -> str:
    """
    ترجمة الوصف العربي للإنجليزية عشان نماذج الصور تفهمه صح
    
    نماذج إنشاء الصور (Stable Diffusion, Flux) متدربة بالأساس على نصوص إنجليزية
    فلما المستخدم يكتب وصف بالعربي، النموذج مش بيفهمه وبيطلع حاجة غلط
    الحل: نترجم الوصف للإنجليزية الأول وبعديننبعتله للنموذج
    
    Returns: الوصف بالإنجليزية (أو الأصلي لو مش عربي)
    """
    if not _contains_arabic(prompt):
        return prompt  # مش عربي — نسيبه زي ما هو
    
    try:
        from provider_manager import call_ai
        
        translation_prompt = f"""Translate the following Arabic image description to English. This is for an AI image generation model, so make the translation descriptive and detailed for best image results. Only output the English translation, nothing else.

Arabic: {prompt}

English translation:"""
        
        system = "You are a translator. Translate Arabic image descriptions to English. Make the translation vivid and descriptive for image generation. Output ONLY the English text, no explanations."
        
        translated = await call_ai(
            translation_prompt,
            system_prompt=system,
            task_type="simple",
            temperature=0.3,
            max_tokens=500,
            user_id=user_id,
        )
        
        if translated and translated.strip():
            # تنظيف الرد — أحيانًا النموذج بيضيف حاجات زي "English translation:" أو علامات اقتباس
            translated = translated.strip()
            # شيل علامات اقتباس لو موجودة
            if translated.startswith('"') and translated.endswith('"'):
                translated = translated[1:-1]
            if translated.startswith("'") and translated.endswith("'"):
                translated = translated[1:-1]
            # شيل أي prefix زي "English:" أو "Translation:"
            for prefix in ["English translation:", "English:", "Translation:", "ترجمة:", "الترجمة:"]:
                if translated.lower().startswith(prefix.lower()):
                    translated = translated[len(prefix):].strip()
            
            logger.info(f"🎨 Translated Arabic prompt: '{prompt[:50]}' → '{translated[:50]}'")
            return translated
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to translate Arabic prompt: {e}")
    
    # لو الترجمة فشلت، نرجع الأصلي (أحسن من حاجة غلط)
    return prompt


# ═══════════════════════════════════════
# إنشاء الصور - Image Generation
# ═══════════════════════════════════════

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /image — إنشاء صورة من وصف نصي (بريميوم بس) 🎨"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check — إنشاء الصور بريميوم بس
    if not can_use_image_gen(user_id):
        feature_name = "🎨 إنشاء صور / Image Generation"
        await update.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    prompt = " ".join(context.args) if context.args else ""

    if not prompt:
        if lang == "ar":
            msg = """🎨 <b>إنشاء صورة من وصف</b>

اكتب الوصف بعد الأمر وهعملك صورة!

💡 <b>أمثلة:</b>
→ <code>/image مسجد جميل عند الغروب</code>
→ <code>/image sunset over Al-Aqsa Mosque</code>
→ <code>/image حدائق إسلامية بنافورة</code>

⭐ الميزة دي للمشتركين Premium بس"""
        else:
            msg = """🎨 <b>Generate Image from Description</b>

Type your description after the command and I'll create an image!

💡 <b>Examples:</b>
→ <code>/image beautiful mosque at sunset</code>
→ <code>/image sunset over Al-Aqsa Mosque</code>
→ <code>/image Islamic garden with fountain</code>

⭐ This feature is Premium only"""
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # تتبع الاستخدام
    increment_usage(user_id, "image_generations")
    try:
        track_event("image_generations")
    except Exception:
        pass

    # Progress
    stages = AI_STAGES(lang)
    title = "إنشاء صورة" if lang == "ar" else "Generating Image"
    # 🟢 FIX: استخدام TelegramThinkingFeedback للعمليات السريعة
    feedback = TelegramThinkingFeedback(update, context)
    await feedback.start()

    try:
        # 🔴 FIX: ترجمة الوصف العربي للإنجليزية قبل الإرسال للنموذج
        original_prompt = prompt
        image_prompt = await _translate_prompt_to_english(prompt, user_id=user_id)
        was_translated = (image_prompt != original_prompt)

        # إنشاء الصورة
        manager = get_provider_manager()
        result = await manager.generate_image_async(
            prompt=image_prompt,
            size="1024x1024",
            user_id=user_id,
        )

        if not result:
            error_msg = "❌ حصل خطأ في إنشاء الصورة. جرب وصف تاني!" if lang == "ar" else "❌ Error generating image. Try a different description!"
            await feedback.error()
            await update.message.reply_text(error_msg)
            return

        # بناء الـ caption
        if was_translated:
            caption = f"🎨 <b>{'صورتك جاهزه!' if lang == 'ar' else 'Your image is ready!'}</b>\n\n📝 <i>{original_prompt[:150]}</i>\n🌐 <i>{image_prompt[:150]}</i>"
        else:
            caption = f"🎨 <b>{'صورتك جاهزه!' if lang == 'ar' else 'Your image is ready!'}</b>\n\n📝 <i>{original_prompt[:200]}</i>"

        # إرسال الصورة
        await feedback.success()
        if result.get("base64"):
            image_bytes = base64.b64decode(result["base64"])
            await update.message.reply_photo(
                photo=io.BytesIO(image_bytes),
                caption=caption,
                parse_mode="HTML",
            )
        elif result.get("url"):
            await update.message.reply_photo(
                photo=result["url"],
                caption=caption,
                parse_mode="HTML",
            )
        else:
            error_msg = "❌ حصل خطأ في إنشاء الصورة. جرب تاني!" if lang == "ar" else "❌ Error generating image. Please try again!"
            await update.message.reply_text(error_msg)

    except Exception as e:
        logger.error(f"Error in /image: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        error_msg = "❌ حصل خطأ في إنشاء الصورة. جرب تاني!" if lang == "ar" else "❌ Error generating image. Please try again!"
        await feedback.error()
        await update.message.reply_text(error_msg)


# ═══════════════════════════════════════
# تعديل الصور - Image Editing 🖌️
# ═══════════════════════════════════════

# تخزين مؤقت لصور المستخدمين عشان نستخدمهم في التعديل
_user_edit_images = {}  # {user_id: {"image_base64": str, "created_at": float}}


async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /edit — تعديل صورة بناءً على وصف نصي (بريميوم بس) 🖌️
    
    طريقتين للاستخدام:
    1. رد على صورة بكتابة /edit + الوصف
    2. /edit + الوصف (لو عندك صورة محفوظة من آخر مرة رفعتها)
    """
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    # Premium check — تعديل الصور بريميوم بس
    if not can_use_image_edit(user_id):
        feature_name = "🖌️ تعديل صور / Image Edit"
        await update.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    prompt = " ".join(context.args) if context.args else ""

    # محاولة 1: المستخدم راد على صورة
    image_base64 = None
    
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        # المستخدم رد على صورة — نحملها
        try:
            photo = update.message.reply_to_message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            image_bytes = await photo_file.download_as_bytearray()
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            logger.info(f"🖌️ Got image from reply for editing (user {user_id})")
        except Exception as e:
            logger.error(f"Error downloading replied photo for edit: {e}")
            if lang == "ar":
                await update.message.reply_text("❌ فشل تحميل الصورة. جرب تاني.")
            else:
                await update.message.reply_text("❌ Failed to download image. Try again.")
            return
    
    # محاولة 2: نستخدم صورة محفوظة من آخر مرة
    if not image_base64:
        cached = _user_edit_images.get(user_id)
        if cached and cached.get("image_base64"):
            image_base64 = cached["image_base64"]
            logger.info(f"🖌️ Using cached image for editing (user {user_id})")
    
    # لو مفيش صورة خالص
    if not image_base64:
        if lang == "ar":
            msg = """🖌️ <b>تعديل صورة بالذكاء الاصطناعي</b>

طريقتين للاستخدام:

<b>1️⃣ رد على صورة:</b>
→ رد على أي صورة واكتب <code>/edit غيّر الخلفية لغروب</code>

<b>2️⃣ ارفع صورة وبعدين عدّلها:</b>
→ ارفع صورة عادية (هتحفظ تلقائي)
→ وبعدين اكتب <code>/edit خلي الألوان أدفأ</code>

💡 <b>أمثلة للتعديل:</b>
→ <code>/edit غيّر الخلفية لمسجد</code>
→ <code>/edit add a sunset sky</code>
→ <code>/edit خلي الصورة زي لوحة إسلامية</code>

⭐ الميزة دي للمشتركين Premium بس"""
        else:
            msg = """🖌️ <b>AI Image Editing</b>

Two ways to use:

<b>1️⃣ Reply to an image:</b>
→ Reply to any image and type <code>/edit change background to sunset</code>

<b>2️⃣ Upload then edit:</b>
→ Upload an image normally (it will be saved)
→ Then type <code>/edit make colors warmer</code>

💡 <b>Edit examples:</b>
→ <code>/edit change background to mosque</code>
→ <code>/edit add a sunset sky</code>
→ <code>/edit make it look like Islamic art</code>

⭐ This feature is Premium only"""
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # لو مفيش وصف للتعديل
    if not prompt:
        if lang == "ar":
            await update.message.reply_text("🖌️ اكتب الوصف بعد الأمر!\nمثال: <code>/edit غيّر الخلفية لمسجد</code>", parse_mode="HTML")
        else:
            await update.message.reply_text("🖌️ Type the edit description after the command!\nExample: <code>/edit change background to sunset</code>", parse_mode="HTML")
        return

    # تتبع الاستخدام
    increment_usage(user_id, "image_edits")
    try:
        track_event("image_edits")
    except Exception:
        pass

    # Progress
    stages = AI_STAGES(lang)
    title = "تعديل الصورة" if lang == "ar" else "Editing Image"
    # 🟢 FIX: استخدام TelegramThinkingFeedback للعمليات السريعة
    feedback = TelegramThinkingFeedback(update, context)
    await feedback.start()

    try:
        # ترجمة الوصف العربي للإنجليزية
        original_prompt = prompt
        edit_prompt = await _translate_prompt_to_english(prompt, user_id=user_id)
        was_translated = (edit_prompt != original_prompt)

        # تعديل الصورة
        manager = get_provider_manager()
        result = await manager.edit_image_async(
            prompt=edit_prompt,
            image_base64=image_base64,
            user_id=user_id,
        )

        if not result:
            error_msg = "❌ حصل خطأ في تعديل الصورة. جرب وصف تاني!" if lang == "ar" else "❌ Error editing image. Try a different description!"
            await feedback.error()
            await update.message.reply_text(error_msg)
            return

        # بناء الـ caption
        if was_translated:
            caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:150]}</i>\n🌐 <i>{edit_prompt[:150]}</i>"
        else:
            caption = f"🖌️ <b>{'الصورة المعدّلة جاهزه!' if lang == 'ar' else 'Edited image is ready!'}</b>\n\n📝 <i>{original_prompt[:200]}</i>"

        # إرسال الصورة المعدّلة
        await feedback.success()
        if result.get("base64"):
            image_bytes = base64.b64decode(result["base64"])
            await update.message.reply_photo(
                photo=io.BytesIO(image_bytes),
                caption=caption,
                parse_mode="HTML",
            )
        elif result.get("url"):
            await update.message.reply_photo(
                photo=result["url"],
                caption=caption,
                parse_mode="HTML",
            )
        else:
            error_msg = "❌ حصل خطأ في تعديل الصورة. جرب تاني!" if lang == "ar" else "❌ Error editing image. Please try again!"
            await update.message.reply_text(error_msg)

    except Exception as e:
        logger.error(f"Error in /edit: {e}")
        try:
            track_event("total_errors")
        except Exception:
            pass
        error_msg = "❌ حصل خطأ في تعديل الصورة. جرب تاني!" if lang == "ar" else "❌ Error editing image. Please try again!"
        await feedback.error()
        await update.message.reply_text(error_msg)


async def handle_photo_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حفظ صورة المستخدم تلقائيًا عشان يقدر يعدلها بعد كده بـ /edit
    
    الطريقة: لما المستخدم يبعت صورة مع caption فيه كلمة تعديل أو edit
    أو لما المستخدم يبعت صورة عادية — نحفظها في الكاش عشان يقدر يستخدمها مع /edit
    """
    import time
    
    if not update.message or not update.message.photo:
        return
    
    user_id = update.effective_user.id
    
    try:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        image_bytes = await photo_file.download_as_bytearray()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # حفظ الصورة في الكاش
        _user_edit_images[user_id] = {
            "image_base64": image_base64,
            "created_at": time.time(),
        }
        logger.info(f"🖌️ Cached image for user {user_id} (for /edit)")
    except Exception as e:
        logger.debug(f"Non-critical: failed to cache image for editing: {e}")
