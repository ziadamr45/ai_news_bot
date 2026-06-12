"""
WhatsApp API Communication Module
===================================
Functions for sending messages, reactions, media, and interactive elements
via the WhatsApp Cloud API.

Extracted from whatsapp_webhook.py for modularity.
All functions use shared state from whatsapp.state.
"""

import os
import logging
import asyncio
import base64
import time
import aiohttp

from whatsapp.state import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WA_MAX_MSG,
    WHATSAPP_API_URL,
    _log_event,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# WhatsApp API Helpers
# ═══════════════════════════════════════

async def _wa_api_post(payload: dict) -> dict:
    """Send a POST to the WhatsApp Cloud API and return the result"""

    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("⚠️ WhatsApp credentials not configured — cannot send")
        return {"error": "not_configured"}

    url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                result = await resp.json()
                if resp.status == 200:
                    return result
                else:
                    error_msg = result.get("error", {}).get("message", "Unknown")
                    error_code = result.get("error", {}).get("code", "unknown")
                    logger.error(f"❌ WA API error ({resp.status}): code={error_code}, msg={error_msg}")
                    return {"error": error_msg, "status": resp.status}
    except asyncio.TimeoutError:
        logger.error("❌ WA API timeout")
        return {"error": "timeout"}
    except Exception as e:
        logger.error(f"❌ WA API error: {e}")
        return {"error": str(e)}


async def _send_whatsapp_message(recipient_wa_id: str, text: str):
    """Send a text message via WhatsApp Cloud API"""
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_wa_id,
        "type": "text",
        "text": {"body": text[:WA_MAX_MSG]},
    }

    result = await _wa_api_post(payload)
    if "error" not in result:
        _log_event("OUT", "message_sent", {
            "to": recipient_wa_id,
            "text_preview": text[:50],
            "meta_message_id": result.get("messages", [{}])[0].get("id", "unknown") if result.get("messages") else "unknown",
        })
        logger.info(f"📤 WA Message sent to {recipient_wa_id}")
    else:
        _log_event("OUT", "message_failed", {"to": recipient_wa_id, "error": str(result.get("error", ""))[:100]})


async def _send_whatsapp_reaction(recipient_wa_id: str, message_id: str, emoji: str = "💭"):
    """Send a reaction to a message (thinking indicator)"""
    if not message_id:
        return {"error": "no_message_id"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_wa_id,
        "type": "reaction",
        "reaction": {
            "message_id": message_id,
            "emoji": emoji,
        },
    }
    result = await _wa_api_post(payload)
    if "error" not in result:
        logger.debug(f"💭 Reaction sent to {recipient_wa_id}")
    return result


async def _mark_message_read(message_id: str):
    """Mark a message as read — gives user visual feedback"""

    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return
    if not message_id:
        return

    url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    logger.debug(f"✅ Marked message {message_id} as read")
    except Exception:
        pass


async def _send_interactive_buttons(recipient_wa_id: str, body_text: str, buttons: list, header_text: str = None, footer_text: str = None):
    """Send an interactive button message (up to 3 buttons)."""
    buttons = buttons[:3]

    action = {
        "buttons": [
            {
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["title"][:20],
                }
            }
            for btn in buttons
        ]
    }

    interactive = {
        "type": "button",
        "body": {"text": body_text[:1024]},
        "action": action,
    }

    if header_text:
        interactive["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive["footer"] = {"text": footer_text[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_wa_id,
        "type": "interactive",
        "interactive": interactive,
    }

    result = await _wa_api_post(payload)
    if "error" not in result:
        logger.info(f"📤 WA Interactive buttons sent to {recipient_wa_id}")
    else:
        logger.warning(f"⚠️ Interactive failed, falling back to text: {result.get('error', '')[:80]}")
        btn_text = body_text + "\n\n" + "\n".join(f"│ {btn['title']}" for btn in buttons)
        await _send_whatsapp_message(recipient_wa_id, btn_text)


async def _send_interactive_list(recipient_wa_id: str, body_text: str, button_text: str, sections: list, header_text: str = None, footer_text: str = None):
    """Send an interactive list message."""
    action = {
        "button": button_text[:20],
        "sections": [],
    }

    for section in sections[:1]:
        sec = {
            "title": section.get("title", "Options")[:24],
            "rows": [],
        }
        for row in section.get("rows", [])[:10]:
            sec["rows"].append({
                "id": row["id"][:200],
                "title": row["title"][:24],
                "description": row.get("description", "")[:72],
            })
        action["sections"].append(sec)

    interactive = {
        "type": "list",
        "body": {"text": body_text[:1024]},
        "action": action,
    }

    if header_text:
        interactive["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive["footer"] = {"text": footer_text[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_wa_id,
        "type": "interactive",
        "interactive": interactive,
    }

    result = await _wa_api_post(payload)
    if "error" not in result:
        logger.info(f"📤 WA Interactive list sent to {recipient_wa_id}")
    else:
        logger.warning(f"⚠️ Interactive list failed, falling back to text: {result.get('error', '')[:80]}")
        list_text = body_text + "\n\n"
        for section in sections:
            list_text += f"*{section.get('title', '')}*\n"
            for row in section.get("rows", []):
                desc = f" — {row['description']}" if row.get("description") else ""
                list_text += f"  {row['title']}{desc}\n"
            list_text += "\n"
        await _send_whatsapp_message(recipient_wa_id, list_text)


# ═══════════════════════════════════════
# WhatsApp Typing Indicator (Professional UX)
# ═══════════════════════════════════════

async def _send_typing_indicator(wa_id: str):
    """Send WhatsApp 'typing' indicator — shows 'typing...' bubble to user
    
    This uses the WhatsApp Cloud API 'mark as read' endpoint trick:
    POST /messages with status "read" marks the message,
    but the actual typing indicator is sent via a different mechanism.
    
    WhatsApp Cloud API doesn't have a direct "typing" endpoint like Telegram.
    The closest equivalent is:
    1. Marking messages as read (blue ticks) — immediate feedback
    2. Sending quick status messages — visual feedback during processing
    
    We implement a smart tiered system:
    - Fast responses (<3s): Just read receipt + reaction
    - Medium responses (3-10s): Read receipt + reaction + thinking text
    - Long responses (>10s): Read receipt + reaction + progressive status messages
    """
    # Mark as read is already done via _mark_message_read
    # The typing indicator in WhatsApp Cloud API is not directly available
    # But we simulate it through quick status messages
    pass


class ThinkingFeedback:
    """Simple reaction-only feedback for WhatsApp — no text messages during processing
    
    🟢 v9.20: شيلنا رسائل "بفكر" — بس reactions صامتة
    - 💭 reaction عند بداية المعالجة
    - ✅ reaction عند الانتهاء
    - ❌ reaction عند الخطأ
    - مفيش أي رسائل نصية أثناء التحميل أو التفكير
    """
    
    def __init__(self, wa_id: str, message_id: str, context_type: str = "general"):
        self.wa_id = wa_id
        self.message_id = message_id
        self.context_type = context_type
        self._start_time = None
    
    async def start(self):
        """Start — send 💭 reaction only"""
        self._start_time = time.time()
        
        if self.message_id:
            try:
                await _send_whatsapp_reaction(self.wa_id, self.message_id, "💭")
            except Exception:
                pass
    
    async def complete(self):
        """Complete — change reaction to ✅"""
        if self.message_id:
            try:
                await _send_whatsapp_reaction(self.wa_id, self.message_id, "✅")
            except Exception:
                pass
    
    async def success(self):
        """Success — alias for complete() (backward compat)"""
        await self.complete()
    
    async def error(self):
        """Error — change reaction to ❌"""
        if self.message_id:
            try:
                await _send_whatsapp_reaction(self.wa_id, self.message_id, "❌")
            except Exception:
                pass


# ═══════════════════════════════════════
# WhatsApp Media Sending Helpers
# ═══════════════════════════════════════


async def _send_whatsapp_image(recipient_wa_id: str, image_base64: str, caption: str = ""):
    """Send an image via WhatsApp Cloud API using base64 image data
    
    WhatsApp Cloud API supports sending images via:
    1. URL (type: image, image.link)  
    2. Media upload (type: image, image.id) — requires uploading to WhatsApp first
    
    Since we have base64, we need to:
    1. Upload the image to WhatsApp Media API
    2. Get the media ID
    3. Send the image message with the media ID
    """
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("⚠️ WhatsApp credentials not configured — cannot send image")
        return {"error": "not_configured"}
    
    try:
        # Step 1: Upload image to WhatsApp Media API
        image_bytes = base64.b64decode(image_base64)
        
        upload_url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
        form_data = aiohttp.FormData()
        form_data.add_field('file', image_bytes, filename='image.png', content_type='image/png')
        form_data.add_field('messaging_product', 'whatsapp')
        form_data.add_field('type', 'image/png')
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                upload_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as upload_resp:
                upload_result = await upload_resp.json()
                
                if upload_resp.status != 200:
                    error_msg = upload_result.get("error", {}).get("message", "Upload failed")
                    logger.error(f"❌ WA Media upload error: {error_msg}")
                    return {"error": error_msg}
                
                media_id = upload_result.get("id")
                if not media_id:
                    logger.error("❌ WA Media upload: no media ID returned")
                    return {"error": "no_media_id"}
                
                logger.info(f"📤 WA Image uploaded: media_id={media_id}")
            
            # Step 2: Send the image message with the media ID
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient_wa_id,
                "type": "image",
                "image": {
                    "id": media_id,
                },
            }
            
            if caption:
                payload["image"]["caption"] = caption[:1024]
            
            result = await _wa_api_post(payload)
            
            if "error" not in result:
                _log_event("OUT", "image_sent", {
                    "to": recipient_wa_id,
                    "media_id": media_id,
                    "caption_preview": caption[:50] if caption else "",
                })
                logger.info(f"📤 WA Image sent to {recipient_wa_id}")
            
            return result
            
    except Exception as e:
        logger.error(f"❌ WA Image send error: {e}")
        return {"error": str(e)}


async def _send_whatsapp_document(recipient_wa_id: str, file_bytes: bytes, filename: str, 
                                   caption: str = "", content_type: str = "video/mp4"):
    """Send a document/file via WhatsApp Cloud API
    
    Uploads the file to WhatsApp Media API first, then sends it as a document message.
    Used for video downloads and other file sharing.
    """
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "not_configured"}
    
    try:
        # Step 1: Upload file to WhatsApp Media API
        upload_url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
        form_data = aiohttp.FormData()
        form_data.add_field('file', file_bytes, filename=filename, content_type=content_type)
        form_data.add_field('messaging_product', 'whatsapp')
        form_data.add_field('type', content_type)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                upload_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=300)  # 5 min for large files
            ) as upload_resp:
                upload_result = await upload_resp.json()
                
                if upload_resp.status != 200:
                    error_msg = upload_result.get("error", {}).get("message", "Upload failed")
                    logger.error(f"❌ WA Document upload error: {error_msg}")
                    return {"error": error_msg}
                
                media_id = upload_result.get("id")
                if not media_id:
                    return {"error": "no_media_id"}
                
                logger.info(f"📤 WA Document uploaded: media_id={media_id}, filename={filename}")
            
            # Step 2: Send the document message
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient_wa_id,
                "type": "document",
                "document": {
                    "id": media_id,
                    "filename": filename[:240],
                },
            }
            
            if caption:
                payload["document"]["caption"] = caption[:1024]
            
            result = await _wa_api_post(payload)
            
            if "error" not in result:
                _log_event("OUT", "document_sent", {
                    "to": recipient_wa_id,
                    "filename": filename,
                    "media_id": media_id,
                })
                logger.info(f"📤 WA Document sent to {recipient_wa_id}: {filename}")
            
            return result
            
    except Exception as e:
        logger.error(f"❌ WA Document send error: {e}")
        return {"error": str(e)}


async def _send_whatsapp_document_from_file(recipient_wa_id: str, file_path: str,
                                               filename: str, caption: str = "", 
                                               content_type: str = "video/mp4"):
    """Send a document via WhatsApp Cloud API — STREAMING from file (no memory loading)
    
    🔴 FIX: ده بيبعت الملف مباشرة من الديسك من غير ما يحمله كله في الرام
    عشان نتجنب Out of Memory على Railway
    """
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "not_configured"}
    
    file_size = os.path.getsize(file_path)
    logger.info(f"📤 WA Document streaming upload: {filename} ({file_size / 1024 / 1024:.1f}MB)")
    
    try:
        upload_url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
        # 🔴 Stream the file in chunks instead of loading it all into memory
        CHUNK_SIZE = 2 * 1024 * 1024  # 2MB chunks
        
        async def _file_chunk_generator():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
        
        form_data = aiohttp.FormData()
        form_data.add_field('file', _file_chunk_generator(), filename=filename, content_type=content_type)
        form_data.add_field('messaging_product', 'whatsapp')
        form_data.add_field('type', content_type)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                upload_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as upload_resp:
                upload_result = await upload_resp.json()
                
                if upload_resp.status != 200:
                    error_msg = upload_result.get("error", {}).get("message", "Upload failed")
                    logger.error(f"❌ WA Document streaming upload error: {error_msg}")
                    return {"error": error_msg}
                
                media_id = upload_result.get("id")
                if not media_id:
                    return {"error": "no_media_id"}
                
                logger.info(f"📤 WA Document streaming uploaded: media_id={media_id}")
            
            # Step 2: Send the document message
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient_wa_id,
                "type": "document",
                "document": {
                    "id": media_id,
                    "filename": filename[:240],
                },
            }
            
            if caption:
                payload["document"]["caption"] = caption[:1024]
            
            result = await _wa_api_post(payload)
            
            if "error" not in result:
                _log_event("OUT", "document_sent", {
                    "to": recipient_wa_id,
                    "filename": filename,
                    "media_id": media_id,
                })
                logger.info(f"📤 WA Document sent to {recipient_wa_id}: {filename}")
            
            return result
            
    except Exception as e:
        logger.error(f"❌ WA Document streaming send error: {e}")
        return {"error": str(e)}


async def _send_whatsapp_audio(recipient_wa_id: str, audio_bytes: bytes, 
                                filename: str = "audio.mp3", content_type: str = "audio/mpeg"):
    """Send an audio file via WhatsApp Cloud API"""
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "not_configured"}
    
    try:
        # Upload to Media API
        upload_url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
        form_data = aiohttp.FormData()
        form_data.add_field('file', audio_bytes, filename=filename, content_type=content_type)
        form_data.add_field('messaging_product', 'whatsapp')
        form_data.add_field('type', content_type)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                upload_url,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as upload_resp:
                upload_result = await upload_resp.json()
                
                if upload_resp.status != 200:
                    return {"error": upload_result.get("error", {}).get("message", "Upload failed")}
                
                media_id = upload_result.get("id")
                if not media_id:
                    return {"error": "no_media_id"}
            
            # Send audio message
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient_wa_id,
                "type": "audio",
                "audio": {
                    "id": media_id,
                },
            }
            
            result = await _wa_api_post(payload)
            if "error" not in result:
                logger.info(f"📤 WA Audio sent to {recipient_wa_id}")
            return result
            
    except Exception as e:
        logger.error(f"❌ WA Audio send error: {e}")
        return {"error": str(e)}


async def _send_whatsapp_video(recipient_wa_id: str, media_id: str, caption: str = ""):
    """Send a video message via WhatsApp Cloud API using an already-uploaded media ID
    
    Args:
        recipient_wa_id: WhatsApp ID of the recipient
        media_id: Already-uploaded media ID from WhatsApp Media API
        caption: Optional caption for the video
    """
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "not_configured"}
    
    try:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_wa_id,
            "type": "video",
            "video": {
                "id": media_id,
            },
        }
        
        if caption:
            payload["video"]["caption"] = caption[:1024]
        
        result = await _wa_api_post(payload)
        
        if "error" not in result:
            _log_event("OUT", "video_sent", {
                "to": recipient_wa_id,
                "media_id": media_id,
            })
            logger.info(f"📤 WA Video sent to {recipient_wa_id}: media_id={media_id}")
        else:
            logger.warning(f"⚠️ WA Video send failed: {result}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ WA Video send error: {e}")
        return {"error": str(e)}
