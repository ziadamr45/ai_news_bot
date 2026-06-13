"""
WhatsApp Audio/Video Processing & Analysis
============================================
Audio transcription, image/document analysis, and photo search
functions for WhatsApp bot.

Extracted from whatsapp/media.py for modularity.
"""

import re
import json
import logging
import asyncio
import base64
import aiohttp

from whatsapp.state import (
    WHATSAPP_ACCESS_TOKEN,
    _wa_user_pdf_context,
)

from whatsapp.api import (
    _send_whatsapp_message,
    _send_whatsapp_image,
)

from content_safety import (
    check_search_results_safety,
    get_no_safe_results_message,
)

logger = logging.getLogger(__name__)

async def _transcribe_audio(media_id: str, wa_user_id: int = 0) -> str:
    """Download audio from WhatsApp and transcribe using VoiceAgent.
    
    Uses the same VoiceAgent as Telegram bot:
    1. Google Speech Recognition (free, reliable — primary)
    2. Groq Whisper (fast fallback)
    3. OpenRouter Whisper
    4. OpenAI Whisper
    """
    import aiohttp

    if not WHATSAPP_ACCESS_TOKEN:
        return ""

    try:
        # Step 1: Download audio from WhatsApp
        audio_bytes = None
        async with aiohttp.ClientSession() as session:
            media_url_resp = await session.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if media_url_resp.status != 200:
                logger.error(f"❌ Could not get media URL: {media_url_resp.status}")
                return ""

            media_data = await media_url_resp.json()
            download_url = media_data.get("url", "")
            if not download_url:
                return ""

            audio_resp = await session.get(
                download_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if audio_resp.status != 200:
                logger.error(f"❌ Could not download audio: {audio_resp.status}")
                return ""

            audio_bytes = await audio_resp.read()

        if not audio_bytes:
            return ""

        # Step 2: Detect user language
        lang_hint = "ar"  # Default Arabic
        if wa_user_id:
            try:
                from memory import get_language
                user_lang = get_language(wa_user_id)
                if user_lang and user_lang != "ar":
                    lang_hint = user_lang
            except Exception:
                pass

        # Step 3: Transcribe using VoiceAgent (Google Speech primary + 3 fallbacks)
        try:
            from agents.voice_agent import VoiceAgent
            voice_agent = VoiceAgent()
            
            result = await voice_agent.process_voice_message(bytes(audio_bytes), language_hint=lang_hint)
            
            if result.get("success") and result.get("text", "").strip():
                text = result["text"].strip()
                logger.info(f"✅ VoiceAgent transcription successful: {text[:100]}")
                return text
            else:
                logger.warning(f"⚠️ VoiceAgent transcription failed: {result.get('error', 'unknown')}")
                return ""
                
        except ImportError:
            logger.error("❌ VoiceAgent not available, falling back to direct Groq")
            # Fallback: direct Groq Whisper if VoiceAgent is unavailable
            from config import GROQ_API_KEY, GROQ_BASE_URL
            if not GROQ_API_KEY:
                return ""
            
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("model", "whisper-large-v3")
                form.add_field("language", lang_hint)
                form.add_field("file", audio_bytes, filename="audio.ogg", content_type="audio/ogg")

                groq_resp = await session.post(
                    f"{GROQ_BASE_URL}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    data=form,
                )

                if groq_resp.status == 200:
                    result = await groq_resp.json()
                    return result.get("text", "")
                else:
                    error_text = await groq_resp.text()
                    logger.error(f"❌ Groq fallback transcription failed: {error_text[:200]}")
                    return ""

    except Exception as e:
        logger.error(f"❌ Audio transcription error: {e}")
        return ""



async def _download_wa_media_base64(media_id: str) -> str:
    """Download media from WhatsApp and return as base64 string
    
    Used for caching images for later editing (like Telegram's photo caching).
    """
    import aiohttp
    
    if not WHATSAPP_ACCESS_TOKEN:
        return ""
    
    try:
        async with aiohttp.ClientSession() as session:
            # Get media URL
            media_url_resp = await session.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if media_url_resp.status != 200:
                return ""
            
            media_data = await media_url_resp.json()
            download_url = media_data.get("url", "")
            if not download_url:
                return ""
            
            # Download the media
            media_resp = await session.get(
                download_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if media_resp.status != 200:
                return ""
            
            media_bytes = await media_resp.read()
            return base64.b64encode(media_bytes).decode("utf-8")
    
    except Exception as e:
        logger.debug(f"Error downloading WA media for caching: {e}")
        return ""



async def _analyze_image(media_id: str, caption: str = "", wa_user_id: int = None) -> str:
    """Download image from WhatsApp and analyze using Vision models."""
    import aiohttp
    from provider_manager import get_provider_manager

    if not WHATSAPP_ACCESS_TOKEN:
        return ""

    try:
        async with aiohttp.ClientSession() as session:
            media_url_resp = await session.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if media_url_resp.status != 200:
                return ""

            media_data = await media_url_resp.json()
            download_url = media_data.get("url", "")
            if not download_url:
                return ""

            image_resp = await session.get(
                download_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if image_resp.status != 200:
                return ""

            image_bytes = await image_resp.read()

        import base64
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        manager = get_provider_manager()
        prompt = "وصف هذه الصورة بالتفصيل باللغة العربية. اشرح ما تراه فيها."
        if caption and caption != "[Image]":
            prompt += f"\n\nملاحظة المستخدم: {caption}"

        result = await manager.analyze_image_async(
            text_prompt=prompt,
            image_base64=image_base64,
            user_id=wa_user_id,
        )

        return result or ""

    except Exception as e:
        logger.error(f"❌ Image analysis error: {e}")
        return ""



async def _analyze_document(media_id: str, caption: str = "", wa_user_id: int = None, filename: str = "", mime_type: str = "") -> str:
    """Download document from WhatsApp and analyze using PDFAgent (same as Telegram)"""
    import aiohttp

    if not WHATSAPP_ACCESS_TOKEN:
        return ""

    try:
        async with aiohttp.ClientSession() as session:
            # Get media URL
            media_url_resp = await session.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if media_url_resp.status != 200:
                return ""

            media_data = await media_url_resp.json()
            download_url = media_data.get("url", "")
            if not download_url:
                return ""

            # Download the document
            doc_resp = await session.get(
                download_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
            if doc_resp.status != 200:
                return ""

            doc_bytes = await doc_resp.read()

        # 🔴 FIX: Determine filename properly from WhatsApp message data
        # WhatsApp provides filename and mime_type in the document message
        # Without this, all files default to "document.pdf" which breaks
        # Word/TXT/CSV/JSON processing in PDFAgent
        if not filename:
            # Try from caption
            if caption and caption != "[Document]":
                if "." in caption.split()[0]:
                    filename = caption.split()[0]
            else:
                # Try to guess from mime_type
                mime_to_ext = {
                    "application/pdf": "pdf",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                    "application/msword": "doc",
                    "text/plain": "txt",
                    "text/markdown": "md",
                    "text/csv": "csv",
                    "application/json": "json",
                    "text/html": "html",
                    "application/xml": "xml",
                }
                ext = mime_to_ext.get(mime_type, "")
                if ext:
                    filename = f"document.{ext}"
        
        if not filename:
            filename = "document.pdf"
        
        # 🔴 FIX: Check supported file types (same as Telegram)
        ext = filename.lower().split('.')[-1] if '.' in filename else "pdf"
        supported_exts = ["pdf", "docx", "doc", "txt", "md", "csv", "json", "py", "js", "html", "css", "xml", "log"]
        if ext not in supported_exts:
            return f"❌ نوع الملف '.{ext}' مش مدعوم حالياً.\n\nالأنواع المدعومة: PDF, Word (docx), TXT, MD, CSV, JSON\n\n💡 ابعت ملف من الأنواع دي وهحللهولك!"

        # Use PDFAgent for extraction (same as Telegram)
        from agents.pdf_agent import PDFAgent
        pdf_agent = PDFAgent()

        # extract_text is synchronous — run in executor to avoid blocking the event loop
        # and to allow timeout enforcement
        import functools
        loop = asyncio.get_event_loop()
        text = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(pdf_agent.extract_text, doc_bytes, filename=filename)),
            timeout=120.0
        )

        if not text or not text.strip():
            return "⚠️ مش قادر أقرا محتوى الملف. ممكن يكون ملف محمي أو بصيغة مش مدعومة."

        # Truncate for AI processing
        text_content = text[:50000]

        # Store PDF context for follow-up questions (same as Telegram)
        _wa_user_pdf_context[wa_user_id or 0] = {
            "text": text_content,
            "filename": filename,
        }
        # Save to DB for persistence
        if wa_user_id:
            try:
                from memory import save_memory
                save_memory(wa_user_id, "pdf_context_filename", filename, "system")
                save_memory(wa_user_id, "pdf_context_text", text_content[:50000], "system")
            except Exception:
                pass

        # Use PDFAgent for summarization (same as Telegram)
        summary = None
        try:
            summary = await asyncio.wait_for(
                pdf_agent.summarize(text_content, "ar", user_id=wa_user_id),
                timeout=180.0
            )
            from formatters import clean_ai_response
            summary = clean_ai_response(summary) or None
        except Exception as e:
            logger.error(f"❌ PDFAgent summarization failed: {e}")

        # Fallback: retry with shorter text
        if not summary:
            try:
                short_text = text_content[:8000]
                summary = await asyncio.wait_for(
                    pdf_agent.summarize(short_text, "ar", user_id=wa_user_id),
                    timeout=180.0
                )
                from formatters import clean_ai_response
                summary = clean_ai_response(summary) or None
            except Exception:
                pass

        # Final fallback: show extracted text
        if not summary:
            import re as _re
            text_fixed = PDFAgent._fix_broken_lines(text_content[:4000])
            clean_text = _re.sub(r'\n{3,}', '\n\n', text_fixed)
            summary = f"📝 المحتوى المستخرج:\n\n{clean_text}\n\n💡 اسألني عن الملف!"

        # Add filename header
        header = f"📄 تحليل: {filename}\n━━━━━━━━━━━━━━━━━\n\n"
        return header + summary

    except Exception as e:
        logger.error(f"❌ Document analysis error: {e}")
        return ""



async def _execute_photo_search(wa_id: str, query: str, count: int, wa_user_id: int,
                                 contact_name: str, message_id: str, is_admin: bool,
                                 cache_key: str = ""):
    """تنفيذ بحث الصور بعد ما المستخدم حدد العدد
    
    🔴 FIX v2:
    - بنبحث عن count * 3 نتائج عشان نعوض عن فشل تحميل بعض الصور
    - بنكمل نحمل لحد ما نوصل للعدد المطلوب بالظبط
    - بنستخدم safesearch=on عشان نمنع الصور غير المناسبة
    - بنستخدم download_image_bytes() لكل صورة لوحدها عشان نوقف عند العدد المطلوب
    """
    await _send_whatsapp_message(wa_id, f"🖼️ جاري البحث عن {count} صور لـ: {query}...")
    
    try:
        from image_search import search_images, download_image_bytes
        
        # 🔴 FIX: بنبحث عن عدد أكبر عشان نوفر بدائل لو فشل تحميل بعض الصور
        # search_images داخلياً بيزود count * 3 في DuckDuckGo
        results = await search_images(query, count=count)
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش صور! جرب كلمات بحث تانية.")
            return
        
        # 🛡️ L2: فلترة نتائج البحث — استبعاد الصور غير الآمنة
        try:
            results = await check_search_results_safety(results, platform="whatsapp", user_id=str(wa_user_id))
            if not results:
                await _send_whatsapp_message(wa_id, get_no_safe_results_message("ar"))
                return
        except Exception as e:
            logger.warning(f"🛡️ Image search results safety check failed (allowing): {e}")
        
        await _send_whatsapp_message(wa_id, f"📥 جاري تحميل {count} صور (وصلت {len(results)} نتيجة بحث)...")
        
        # 🔴 FIX: بنحمل من كل النتائج لحد ما نوصل للعدد المطلوب
        # مش بس أول count نتائج — لأن ممكن فشل تحميل بعض الصور
        sent = 0
        for i, r in enumerate(results):
            # 🔴 وقفنا لما وصلنا للعدد المطلوب
            if sent >= count:
                break
            
            url = r.get("full_url") or r.get("url") or r.get("thumbnail", "")
            if not url:
                continue
            
            # 🔴 محاولة تحميل الصورة الكاملة أولاً
            img_bytes = await download_image_bytes(url)
            
            # 🔴 FIX: لو الصورة الكاملة فشلت، جرب الـ thumbnail كبديل
            if not img_bytes:
                thumb_url = r.get("thumbnail", "")
                if thumb_url and thumb_url != url:
                    logger.info(f"🖼️ Full image failed, trying thumbnail for result {i+1}")
                    img_bytes = await download_image_bytes(thumb_url)
            
            if not img_bytes:
                continue
            
            # 🛡️ Safety: Check image before sending
            try:
                from content_safety import check_image_safety
                img_is_safe, img_reason, img_score = await check_image_safety(
                    image_bytes=img_bytes,
                    platform="whatsapp",
                    user_id=str(wa_user_id),
                )
                if not img_is_safe:
                    logger.info(f"🛡️ Image {i+1} blocked by safety check: {img_reason}")
                    continue  # Skip this image, move to next
            except Exception as e:
                logger.warning(f"🛡️ Image safety check failed (allowing): {e}")
            
            try:
                img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                desc = r.get('description', '')[:80]
                source = r.get('source', '')
                
                caption = f"🖼️ صورة {sent + 1}/{count}"
                if desc:
                    caption += f"\n📝 {desc}"
                if source:
                    caption += f"\n📁 {source}"
                
                await _send_whatsapp_image(wa_id, img_b64, caption)
                sent += 1
                
                # تأخير بسيط بين الصور عشان واتساب متبلوكناش
                if sent < count:
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Failed to send image {i}: {e}")
        
        if sent > 0:
            await _send_whatsapp_message(wa_id, f"✅ تم إرسال {sent}/{count} صورة!")
        else:
            await _send_whatsapp_message(wa_id, "❌ فشل تحميل الصور. جرب تاني!")
        
    except Exception as e:
        logger.error(f"WA photo search error: {e}", exc_info=True)
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ. جرب تاني!")



