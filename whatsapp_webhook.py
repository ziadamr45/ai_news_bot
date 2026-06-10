"""
WhatsApp Cloud API Webhook Server
Handles Meta verification (GET) and incoming messages (POST).
Runs alongside the Telegram bot on the same event loop.
+ Full AI integration: routes messages to smart_chat() and sends responses
+ WhatsApp-optimized message splitting (4096 char limit)
+ Deduplication: prevents processing the same message twice
+ Audio transcription support via Groq Whisper
+ Image analysis support via Vision models
+ Interactive buttons & lists (like Telegram inline keyboards)
+ Full commands system matching Telegram bot features
+ Typing indicator while AI is processing
+ Read receipts (mark messages as read)
+ Thinking feedback while AI processes
+ Quick action buttons after responses
+ Multi-page menu system
+ Premium/Free plan system with usage tracking
+ Admin system (grant, revoke, ban, broadcast, stats)
+ Memory system (view, reset, favorites)
+ Download, Study mode, YouTube summary, PDF analysis
+ Image generation & editing (Premium)
+ Contextual quick action buttons
+ Usage limit notifications for free users
"""

import os
import json
import logging
import hashlib
import hmac
import re
import asyncio
import base64
import io
import tempfile
import shutil
import time
from datetime import datetime, timezone

from aiohttp import web

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# Configuration
# ═══════════════════════════════════════

# Helper: treat "PENDING" as unset (placeholder from initial Railway setup)
def _get_env(key: str, default: str = "") -> str:
    """Get env var, treating 'PENDING' as unset"""
    val = os.environ.get(key, default)
    if val.upper() == "PENDING":
        logger.warning(f"⚠️ {key} is set to 'PENDING' — treating as not configured")
        return default
    return val

WHATSAPP_VERIFY_TOKEN = _get_env("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = _get_env("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _get_env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = _get_env("WHATSAPP_APP_SECRET")
# Railway sets PORT automatically — use it if available, otherwise fallback to WEBHOOK_PORT or 8080
WEBHOOK_PORT = int(os.environ.get("PORT", os.environ.get("WEBHOOK_PORT", "8080")))

# Allowed WhatsApp numbers (for security — only respond to allowed numbers)
# Leave empty to allow all numbers (anyone can message the bot)
ALLOWED_WA_NUMBERS = os.environ.get("ALLOWED_WA_NUMBERS", "").split(",") if os.environ.get("ALLOWED_WA_NUMBERS") else []

# ═══════════════════════════════════════
# Admin Configuration
# ═══════════════════════════════════════

ADMIN_WA_ID = "201203551789"  # Ziad Amr's WhatsApp ID (+201203551789)

# Developer WhatsApp contact for premium/subscription messages
DEVELOPER_WHATSAPP = "01203551789"
DEVELOPER_WHATSAPP_URL = "https://wa.me/201203551789"


def _wa_phone_to_user_id(phone: str) -> int:
    """تحويل رقم واتساب (موبايل) لـ user_id داخلي
    
    الواتساب بيتعامل برقم الموبايل (زي 201203551789)
    بس الدوال الداخلية بتستخدم hashed user_id
    الدالة دي بتاخد الرقم وترجع الـ user_id الصح
    """
    # إزالة + من البداية لو موجود
    clean = phone.lstrip('+')
    # إزالة مسافات
    clean = clean.strip()
    return -abs(hash(f"wa_{clean}")) % (2**31)


def _wa_phone_to_display(phone: str) -> str:
    """تنسيق رقم الموبايل للعرض"""
    clean = phone.lstrip('+').strip()
    return f"+{clean}"


def _is_wa_admin(wa_id: str) -> bool:
    """Check if WhatsApp ID belongs to the admin (Ziad Amr)"""
    if wa_id == ADMIN_WA_ID:
        return True
    # Also check via admin.py using the hashed user_id
    try:
        from admin import is_admin
        wa_user_id = -abs(hash(f"wa_{wa_id}")) % (2**31)
        return is_admin(wa_user_id)
    except Exception:
        return False


def _ensure_wa_admin_premium(wa_id: str):
    """Ensure the WhatsApp admin is always premium"""
    if wa_id == ADMIN_WA_ID:
        try:
            from admin import ensure_admin_premium
            wa_user_id = -abs(hash(f"wa_{wa_id}")) % (2**31)
            ensure_admin_premium(wa_user_id)
        except Exception as e:
            logger.warning(f"Could not ensure admin premium: {e}")


# ═══════════════════════════════════════
# Message Deduplication
# ═══════════════════════════════════════

from collections import OrderedDict

_processed_message_ids = OrderedDict()
_MAX_DEDUP_CACHE = 1000

_wa_user_pdf_context = {}  # PDF context per user for follow-up Q&A

# ═══════════════════════════════════════
# نظام حالة المستخدم — Workflow State Management
# ═══════════════════════════════════════
# بيحفظ حالة المستخدم النشطة عشان الرسائل توصل للخدمة الصح
# الأنواع المدعومة:
#   photo_search  → في انتظار عدد الصور
#   video_search  → في انتظار اختيار فيديو من القائمة
#   audio_search  → في انتظار اختيار صوت من القائمة
#   image_edit    → في انتظار وصف التعديل على صورة
#   pdf_qa        → في انتظار سؤال عن PDF
#   download      → في انتظار اختيار جودة التحميل
_wa_user_state = {}  # {wa_id: {"flow": str, "data": dict, "expires": float}}
_WA_STATE_TTL = 300  # 5 دقائق — بعد كده الحالة تنتهي تلقائياً

def _set_user_state(wa_id: str, flow: str, data: dict = None):
    """حفظ حالة المستخدم النشطة"""
    _wa_user_state[wa_id] = {
        "flow": flow,
        "data": data or {},
        "expires": time.time() + _WA_STATE_TTL,
    }

def _get_user_state(wa_id: str) -> dict:
    """الحصول على حالة المستخدم النشطة (أو None لو مفيش)"""
    state = _wa_user_state.get(wa_id)
    if not state:
        return None
    if time.time() > state.get("expires", 0):
        # الحالة انتهت — امسحها
        del _wa_user_state[wa_id]
        return None
    return state

def _clear_user_state(wa_id: str):
    """مسح حالة المستخدم"""
    _wa_user_state.pop(wa_id, None)

# URL cache for multi-quality downloads (like Telegram's _url_cache)
import hashlib as _hashlib_mod
_url_cache = {}  # {key: {"url": str, "expires": float}}
_URL_CACHE_TTL = 600  # 10 minutes

# User image cache for image editing (like Telegram's _user_edit_images)
_wa_user_edit_images = {}  # {wa_user_id: {"image_base64": str, "created_at": float}}

# ═══════════════════════════════════════
# Webhook Activity Log (for diagnostics)
# ═══════════════════════════════════════

_webhook_activity_log = []
_MAX_ACTIVITY_LOG = 50


def _log_activity(event_type: str, data: dict, status: str = "received"):
    """Log webhook activity for the /debug/whatsapp/activity endpoint"""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "status": status,
        "data": data,
    }
    _webhook_activity_log.append(entry)
    while len(_webhook_activity_log) > _MAX_ACTIVITY_LOG:
        _webhook_activity_log.pop(0)


def _is_duplicate_wa_message(message_id: str) -> bool:
    """Check if we already processed this WhatsApp message ID"""
    if message_id in _processed_message_ids:
        return True
    _processed_message_ids[message_id] = True
    while len(_processed_message_ids) > _MAX_DEDUP_CACHE:
        _processed_message_ids.popitem(last=False)
    return False


# ═══════════════════════════════════════
# Webhook Event Logging
# ═══════════════════════════════════════

def _log_event(direction: str, event_type: str, data: dict):
    """Log webhook events in a structured format"""
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": direction,
        "type": event_type,
        "data": data,
    }
    logger.info(f"📲 WA Webhook [{direction}] {event_type}: {json.dumps(data, ensure_ascii=False)[:500]}")


# ═══════════════════════════════════════
# Signature Verification
# ═══════════════════════════════════════

def _verify_signature(payload: bytes, signature_header: str) -> bool:
    """Verify the X-Hub-Signature-256 header from Meta"""
    if not WHATSAPP_APP_SECRET:
        logger.warning("⚠️ WHATSAPP_APP_SECRET not set — skipping signature verification")
        return True

    if not signature_header:
        return False

    try:
        if not signature_header.startswith("sha256="):
            return False

        expected = hmac.new(
            WHATSAPP_APP_SECRET.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        received = signature_header.split("=", 1)[1]
        return hmac.compare_digest(expected, received)
    except Exception as e:
        logger.error(f"❌ Signature verification error: {e}")
        return False


# ═══════════════════════════════════════
# WhatsApp Message Formatting
# ═══════════════════════════════════════

def _strip_html_for_whatsapp(text: str) -> str:
    """
    Strip HTML tags from AI response for WhatsApp.
    WhatsApp doesn't support HTML — only plain text and *bold*, _italic_, ~strikethrough~, ```code```
    """
    if not text:
        return text

    text = re.sub(r'<b>(.*?)</b>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<i>(.*?)</i>', r'_\1_', text, flags=re.DOTALL)
    text = re.sub(r'<code>(.*?)</code>', r'```\1```', text, flags=re.DOTALL)
    text = re.sub(r'<s>(.*?)</s>', r'~\1~', text, flags=re.DOTALL)
    text = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', r'\2 (\1)', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()


def _split_whatsapp_message(text: str, max_length: int = 4000) -> list:
    """Split a long message for WhatsApp (4096 char limit per message)."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    split_markers = ['\n\n', '\n', ' • ', ' — ', ' ']

    remaining = text
    while len(remaining) > max_length:
        split_pos = -1
        search_end = min(max_length, len(remaining))

        for marker in split_markers:
            pos = remaining.rfind(marker, 0, search_end)
            if pos > 0:
                split_pos = pos + len(marker)
                break

        if split_pos <= 0:
            for end_char in ['؟', '،', '؛', '.']:
                pos = remaining.rfind(end_char, 0, search_end)
                if pos > 0:
                    split_pos = pos + 1
                    break

        if split_pos <= 0:
            split_pos = max_length

        chunk = remaining[:split_pos].rstrip()
        remaining = remaining[split_pos:].lstrip()

        if chunk:
            chunks.append(chunk)

    if remaining.strip():
        chunks.append(remaining.strip())

    return chunks if chunks else [text]


# ═══════════════════════════════════════
# WhatsApp API Helpers
# ═══════════════════════════════════════

async def _wa_api_post(payload: dict) -> dict:
    """Send a POST to the WhatsApp Cloud API and return the result"""
    import aiohttp

    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("⚠️ WhatsApp credentials not configured — cannot send")
        return {"error": "not_configured"}

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
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
        "text": {"body": text[:4096]},
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
    import aiohttp

    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return
    if not message_id:
        return

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
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
    import aiohttp
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("⚠️ WhatsApp credentials not configured — cannot send image")
        return {"error": "not_configured"}
    
    try:
        # Step 1: Upload image to WhatsApp Media API
        image_bytes = base64.b64decode(image_base64)
        
        upload_url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
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
    import aiohttp
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "not_configured"}
    
    try:
        # Step 1: Upload file to WhatsApp Media API
        upload_url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
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


async def _send_whatsapp_audio(recipient_wa_id: str, audio_bytes: bytes, 
                                filename: str = "audio.mp3", content_type: str = "audio/mpeg"):
    """Send an audio file via WhatsApp Cloud API"""
    import aiohttp
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "not_configured"}
    
    try:
        # Upload to Media API
        upload_url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
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


# ═══════════════════════════════════════
# Image Generation (Real — like Telegram)
# ═══════════════════════════════════════

# Arabic character detection for prompt translation
_ARABIC_CHAR_PATTERN = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')


def _contains_arabic(text: str) -> bool:
    """Check if text contains Arabic characters"""
    return bool(_ARABIC_CHAR_PATTERN.search(text))


async def _translate_prompt_to_english(prompt: str, user_id: int = None) -> str:
    """Translate Arabic image description to English for image generation models"""
    if not _contains_arabic(prompt):
        return prompt  # Not Arabic — leave as is
    
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
            translated = translated.strip()
            if translated.startswith('"') and translated.endswith('"'):
                translated = translated[1:-1]
            if translated.startswith("'") and translated.endswith("'"):
                translated = translated[1:-1]
            for prefix in ["English translation:", "English:", "Translation:"]:
                if translated.lower().startswith(prefix.lower()):
                    translated = translated[len(prefix):].strip()
            
            logger.info(f"🎨 Translated Arabic prompt: '{prompt[:50]}' → '{translated[:50]}'")
            return translated
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to translate Arabic prompt: {e}")
    
    return prompt


async def _generate_and_send_image(wa_id: str, prompt: str, wa_user_id: int, 
                                     contact_name: str, message_id: str = "", is_admin: bool = False):
    """Generate an image using AI and send it via WhatsApp — like Telegram's /image command
    
    This actually generates an image using the provider_manager (same as Telegram),
    instead of just asking the AI to describe what the image would look like.
    """
    from provider_manager import get_provider_manager
    
    # Start thinking feedback
    feedback = ThinkingFeedback(wa_id, message_id, context_type="image")
    await feedback.start()
    
    try:
        # Translate Arabic prompt to English for better image generation
        original_prompt = prompt
        image_prompt = await _translate_prompt_to_english(prompt, user_id=wa_user_id)
        was_translated = (image_prompt != original_prompt)
        
        # Generate image using provider_manager (same engine as Telegram)
        manager = get_provider_manager()
        result = await manager.generate_image_async(
            prompt=image_prompt,
            size="1024x1024",
            user_id=wa_user_id,
        )
        
        if not result:
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في إنشاء الصورة. جرب وصف تاني! 🎨")
            await feedback.error()
            return
        
        # Build caption
        if was_translated:
            caption = f"🎨 صورتك جاهزة!\n\n📝 {original_prompt[:150]}"
        else:
            caption = f"🎨 صورتك جاهزة!\n\n📝 {original_prompt[:200]}"
        
        # Send the image
        if result.get("base64"):
            await _send_whatsapp_image(wa_id, result["base64"], caption)
        elif result.get("url"):
            # Download from URL and send
            import aiohttp
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(result["url"], timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status == 200:
                            img_bytes = await resp.read()
                            img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                            await _send_whatsapp_image(wa_id, img_b64, caption)
                        else:
                            await _send_whatsapp_message(wa_id, "❌ فشل تحميل الصورة. جرب تاني! 🎨")
            except Exception as e:
                logger.error(f"❌ Error downloading generated image: {e}")
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الصورة. جرب تاني! 🎨")
        else:
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في إنشاء الصورة. جرب تاني! 🎨")
        
        # Increment usage
        if not is_admin:
            try:
                from premium import increment_usage
                increment_usage(wa_user_id, "image_generations")
            except Exception:
                pass
        
        # Try track event
        try:
            from dashboard import track_event
            track_event("image_generations", platform="whatsapp")
        except Exception:
            pass
        
        await feedback.complete()
        
        # Quick action buttons
        await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
            buttons=[
                {"id": "cmd_image_gen", "title": "🎨 صورة تانية"},
                {"id": "cmd_image_edit", "title": "🖌️ عدّلها"},
                {"id": "cmd_chat", "title": "💬 محادثة"},
            ])
        
        logger.info(f"✅ WA Image generated and sent to {wa_id}")
        
    except Exception as e:
        logger.error(f"❌ Image generation error for WA {wa_id}: {e}", exc_info=True)
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ في إنشاء الصورة. جرب تاني! 🎨")
        await feedback.error()


async def _edit_and_send_image(wa_id: str, prompt: str, image_base64: str, wa_user_id: int,
                                contact_name: str, message_id: str = "", is_admin: bool = False):
    """Edit an image using AI (same as Telegram's /edit command) — REAL image editing
    
    Uses the provider_manager's edit_image_async (NVIDIA Visual GenA) — same engine as Telegram.
    """
    from provider_manager import get_provider_manager
    
    # Start thinking feedback
    feedback = ThinkingFeedback(wa_id, message_id, context_type="image")
    await feedback.start()
    
    try:
        # Translate Arabic prompt to English for better editing results
        original_prompt = prompt
        edit_prompt = await _translate_prompt_to_english(prompt, user_id=wa_user_id)
        was_translated = (edit_prompt != original_prompt)
        
        # Edit the image using provider_manager (same engine as Telegram)
        manager = get_provider_manager()
        result = await manager.edit_image_async(
            prompt=edit_prompt,
            image_base64=image_base64,
            user_id=wa_user_id,
        )
        
        if not result:
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في تعديل الصورة. جرب وصف تاني! 🖌️")
            await feedback.error()
            return
        
        # Build caption
        if was_translated:
            caption = f"🖌️ الصورة بعد التعديل!\n\n📝 {original_prompt[:150]}"
        else:
            caption = f"🖌️ الصورة بعد التعديل!\n\n📝 {original_prompt[:200]}"
        
        # Send the edited image
        if result.get("base64"):
            await _send_whatsapp_image(wa_id, result["base64"], caption)
        elif result.get("url"):
            import aiohttp
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(result["url"], timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status == 200:
                            img_bytes = await resp.read()
                            img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                            await _send_whatsapp_image(wa_id, img_b64, caption)
                        else:
                            await _send_whatsapp_message(wa_id, "❌ فشل تحميل الصورة المعدلة. جرب تاني! 🖌️")
            except Exception as e:
                logger.error(f"❌ Error downloading edited image: {e}")
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الصورة المعدلة. جرب تاني! 🖌️")
        else:
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في تعديل الصورة. جرب وصف تاني! 🖌️")
        
        # Increment usage
        if not is_admin:
            try:
                from premium import increment_usage
                increment_usage(wa_user_id, "image_edits")
            except Exception:
                pass
        
        await feedback.complete()
        
        # Quick action buttons
        await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
            buttons=[
                {"id": "cmd_image_edit", "title": "🖌️ عدّل تاني"},
                {"id": "cmd_image_gen", "title": "🎨 صورة جديدة"},
                {"id": "cmd_chat", "title": "💬 محادثة"},
            ])
        
        logger.info(f"✅ WA Image edited and sent to {wa_id}")
        
    except Exception as e:
        logger.error(f"❌ Image editing error for WA {wa_id}: {e}", exc_info=True)
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ في تعديل الصورة. جرب تاني! 🖌️")
        await feedback.error()


# ═══════════════════════════════════════
# Video Download (Real — using yt-dlp like Telegram)
# + Multi-quality selection
# + Real image editing (edit_image_async)
# ═══════════════════════════════════════

# URL detection patterns (shared with Telegram download_handlers)
_URL_PATTERNS = {
    "youtube": re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube\.com/shorts)/', re.IGNORECASE),
    "facebook": re.compile(r'(https?://)?(www\.)?(facebook\.com|fb\.watch|m\.facebook\.com)/', re.IGNORECASE),
    "instagram": re.compile(r'(https?://)?(www\.)?(instagram\.com|instagr\.am)/', re.IGNORECASE),
    "tiktok": re.compile(r'(https?://)?(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/', re.IGNORECASE),
    "twitter": re.compile(r'(https?://)?(www\.)?(twitter\.com|x\.com|t\.co)/', re.IGNORECASE),
    "telegram": re.compile(r'(https?://)?(t\.me|telegram\.me|telegram\.org)/', re.IGNORECASE),
    "threads": re.compile(r'(https?://)?(www\.)?threads\.net/', re.IGNORECASE),
    "reddit": re.compile(r'(https?://)?(www\.)?(reddit\.com|redd\.it)/', re.IGNORECASE),
}

_GENERAL_URL_PATTERN = re.compile(r'https?://[^\s<>\"]+', re.IGNORECASE)


def _detect_platform(url: str) -> str:
    """Detect platform from URL"""
    for platform, pattern in _URL_PATTERNS.items():
        if pattern.search(url):
            return platform
    return "unknown"


def _extract_url(text: str) -> str:
    """Extract first URL from text"""
    match = _GENERAL_URL_PATTERN.search(text)
    return match.group(0) if match else ""


def _store_url(url: str) -> str:
    """Store URL in cache and return key (like Telegram's _store_url)"""
    key = _hashlib_mod.md5(url.encode()).hexdigest()[:10]
    _url_cache[key] = {"url": url, "expires": time.time() + _URL_CACHE_TTL}
    # Clean expired entries
    expired = [k for k, v in _url_cache.items() if v["expires"] < time.time()]
    for k in expired:
        del _url_cache[k]
    return key


def _get_url(key: str) -> str:
    """Get URL from cache by key"""
    entry = _url_cache.get(key)
    if entry and entry["expires"] > time.time():
        return entry["url"]
    return ""


async def _show_quality_selection(wa_id: str, url: str, wa_user_id: int, 
                                   contact_name: str, message_id: str = "", is_admin: bool = False):
    """Show quality selection buttons for video download (like Telegram)"""
    platform = _detect_platform(url)
    platform_names = {
        "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
        "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
        "threads": "Threads", "reddit": "Reddit", "unknown": "🌐",
    }
    platform_display = platform_names.get(platform, platform)
    url_key = _store_url(url)
    
    body = f"📥 *اختار الجودة*\n\n🔗 المنصة: {platform_display}"
    
    await _send_interactive_list(wa_id, 
        body_text=body,
        button_text="اختار الجودة",
        sections=[{
            "title": "جودة الفيديو",
            "rows": [
                {"id": f"dl_v_b_{url_key}", "title": "🎬 أعلى جودة", "description": "1080p - أفضل جودة متاحة"},
                {"id": f"dl_v_m_{url_key}", "title": "📹 جودة متوسطة", "description": "720p - توازن بين الجودة والحجم"},
                {"id": f"dl_v_l_{url_key}", "title": "📱 جودة منخفضة", "description": "480p - حجم صغير"},
            ],
        }, {
            "title": "صوت فقط",
            "rows": [
                {"id": f"dl_a_{url_key}", "title": "🎵 صوت بس MP3", "description": "استخراج الصوت فقط"},
            ],
        }],
        header_text=f"📥 تحميل من {platform_display}")


async def _download_and_send_video(wa_id: str, url: str, wa_user_id: int,
                                     contact_name: str, message_id: str = "", is_admin: bool = False,
                                     quality: str = "best", force_audio: bool = False):
    """Download a video using yt-dlp and send it via WhatsApp — like Telegram's /download command
    
    WhatsApp has a 100MB media size limit. For larger files, we send the download link instead.
    
    quality: "best" (1080p), "medium" (720p), "low" (480p), "audio" (MP3)
    force_audio: if True, force audio-only download regardless of quality param
    """
    # If force_audio, override quality
    if force_audio:
        quality = "audio"
    # Start thinking feedback
    feedback = ThinkingFeedback(wa_id, message_id, context_type="download")
    await feedback.start()
    
    try:
        import yt_dlp
        
        platform = _detect_platform(url)
        platform_names = {
            "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
            "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
            "threads": "Threads", "reddit": "Reddit", "unknown": "🌐",
        }
        platform_display = platform_names.get(platform, platform)
        
        # Send progress message
        await _send_whatsapp_message(wa_id, f"📥 جاري تحميل الفيديو من {platform_display}...")
        
        tmpdir = tempfile.mkdtemp(prefix="mybro_wa_dl_")
        output_template = os.path.join(tmpdir, "%(title).80s.%(ext)s")
        
        # ═══ المرحلة 0: Cobalt Self-Hosted (أول طبقة!) ═══
        # 🔵 أقوى وأسرع طريقة — بيشتغل على سيرفر منفصل ومش بيتأثر بـ bot detection
        cobalt_filepath = None
        cobalt_filename = None
        cobalt_filesize = 0
        
        try:
            from handlers.download_handlers import _try_cobalt_download
            cobalt_result = await _try_cobalt_download(url, quality, tmpdir)
            if cobalt_result:
                cobalt_filepath = cobalt_result["filepath"]
                cobalt_filename = cobalt_result["filename"]
                cobalt_filesize = cobalt_result["size"]
                logger.info(f"🔵 Cobalt succeeded for WhatsApp! Size: {cobalt_filesize // (1024*1024)}MB")
        except Exception as cobalt_err:
            logger.warning(f"🔵 Cobalt failed for WhatsApp: {cobalt_err}")
        
        if cobalt_filepath and cobalt_filesize > 0:
            # Cobalt نجح — نبعث الملف مباشرة بدون yt-dlp
            try:
                is_audio = (quality == "audio")
                
                # WhatsApp 100MB limit
                if cobalt_filesize > 100 * 1024 * 1024:
                    await _send_whatsapp_message(wa_id, f"⚠️ الملف كبير ({cobalt_filesize // (1024*1024)}MB) — أكبر من حد واتساب (100MB)")
                else:
                    # Send the media file via WhatsApp
                    with open(cobalt_filepath, 'rb') as f:
                        file_data = f.read()
                    
                    if is_audio:
                        await _send_whatsapp_audio(wa_id, file_data, cobalt_filename)
                    else:
                        content_type = "video/mp4"
                        await _send_whatsapp_document(wa_id, file_data, cobalt_filename, caption=f"📥 {cobalt_filename}", content_type=content_type)
                
                await feedback.complete()
                try: track_event("whatsapp_media_downloads", platform="whatsapp")
                except: pass
                return
                
            except Exception as send_err:
                logger.warning(f"⚠️ Failed to send Cobalt file via WhatsApp: {send_err}")
                # Fall through to yt-dlp
            finally:
                # Clean up
                try:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                except:
                    pass
        
        # ═══ Cobalt فشل → نكمل بـ yt-dlp ═══
        
        try:
            # yt-dlp options — with multi-quality support (like Telegram)
            # WhatsApp limit: ~100MB for media
            
            # Quality format strings (like Telegram's download_handlers)
            is_audio_only = (quality == "audio")
            
            # 🔴 FIX v9: Facebook family format + acodec!=none + no filesize limit
            is_facebook_family = platform in ("facebook", "instagram", "threads")
            
            if is_audio_only:
                format_str = 'bestaudio/best'
                merge_output = None
                remux = None
                progress_msg = f"🎵 جاري استخراج الصوت من {platform_display}..."
            elif is_facebook_family:
                # Facebook family: prefer merge (bestvideo+bestaudio) for audio guarantee
                if quality == "best":
                    format_str = (
                        'bestvideo[vcodec^=avc1][height<=1080]+bestaudio/'
                        'bestvideo[ext=mp4][height<=1080]+bestaudio/'
                        'bestvideo[height<=1080]+bestaudio/'
                        'best[ext=mp4][height<=1080][acodec!=none]/'
                        'best[acodec!=none][height<=1080]/'
                        'best[height<=1080]/'
                        'best'
                    )
                elif quality == "medium":
                    format_str = (
                        'bestvideo[vcodec^=avc1][height<=720]+bestaudio/'
                        'bestvideo[ext=mp4][height<=720]+bestaudio/'
                        'bestvideo[height<=720]+bestaudio/'
                        'best[ext=mp4][height<=720][acodec!=none]/'
                        'best[acodec!=none][height<=720]/'
                        'best[height<=720]/'
                        'best'
                    )
                else:  # low
                    format_str = (
                        'best[ext=mp4][height<=480][acodec!=none]/'
                        'best[acodec!=none][height<=480]/'
                        'best[height<=480]/'
                        'best'
                    )
                merge_output = 'mp4'
                remux = None  # Don't remux — let ffmpeg merge properly
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} ({'أعلى جودة' if quality=='best' else 'جودة متوسطة' if quality=='medium' else 'جودة منخفضة'})..."
            elif quality == "best":
                format_str = (
                    'bestvideo[vcodec^=avc1][height<=1080]+bestaudio/'
                    'best[ext=mp4][height<=1080][acodec!=none]/'
                    'best[acodec!=none][height<=1080]/'
                    'best[height<=1080]/'
                    'best'
                )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} (أعلى جودة)..."
            elif quality == "medium":
                format_str = (
                    'bestvideo[vcodec^=avc1][height<=720]+bestaudio/'
                    'best[ext=mp4][height<=720][acodec!=none]/'
                    'best[acodec!=none][height<=720]/'
                    'best[height<=720]/'
                    'best'
                )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} (جودة متوسطة)..."
            else:  # low
                format_str = (
                    'best[ext=mp4][height<=480][acodec!=none]/'
                    'best[acodec!=none][height<=480]/'
                    'best[height<=480]/'
                    'best'
                )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} (جودة منخفضة)..."
            
            # Send progress message
            await _send_whatsapp_message(wa_id, progress_msg)
            
            ydl_opts = {
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 5,
                'file_access_retries': 3,
                'no_check_certificates': True,
                'format': format_str,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                },
            }
            
            if merge_output:
                ydl_opts['merge_output_format'] = merge_output
            if remux:
                ydl_opts['remux_video'] = remux
            
            # Audio-only: extract to MP3
            if is_audio_only:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            
            # Add cookies if available
            cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            if os.path.exists(cookies_path):
                try:
                    with open(cookies_path, 'r') as f:
                        content = f.read().strip()
                        if content and len(content) > 50:
                            ydl_opts['cookiefile'] = cookies_path
                except Exception:
                    pass
            
            # Download video — Multi-stage approach
            loop = asyncio.get_event_loop()
            info = None
            last_error = None
            
            # ═══ المرحلة 1: yt-dlp مباشر (الأفضل) ═══
            try:
                def _run_ytdlp():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        return info
                
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, _run_ytdlp),
                    timeout=300  # 5 minutes max
                )
                if info:
                    logger.info(f"✅ yt-dlp download succeeded directly")
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ yt-dlp direct download failed: {e}")
            
            # ═══ المرحلة 2: yt-dlp مع خيارات مختلفة (بدون كوكيز) ═══
            if info is None:
                try:
                    # Try with android client (less likely to be blocked)
                    alt_opts = dict(ydl_opts)
                    alt_opts['extractor_args'] = {'youtube': {'player_client': ['android']}}
                    if 'cookiefile' in alt_opts:
                        del alt_opts['cookiefile']
                    
                    def _run_ytdlp_alt():
                        with yt_dlp.YoutubeDL(alt_opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                            return info
                    
                    info = await asyncio.wait_for(
                        loop.run_in_executor(None, _run_ytdlp_alt),
                        timeout=300
                    )
                    if info:
                        logger.info(f"✅ yt-dlp android client download succeeded")
                except Exception as e2:
                    last_error = e2
                    logger.warning(f"⚠️ yt-dlp android client also failed: {e2}")
            
            # ═══ المرحلة 3: Cloudflare Worker Proxy Fallback ═══
            # لو yt-dlp فشل على Railway (IPs محجوبة)، نجرب عبر Cloudflare Worker
            if info is None:
                from config import CLOUDFLARE_WORKER_URL
                if CLOUDFLARE_WORKER_URL:
                    logger.info(f"🔄 All yt-dlp methods failed, trying Cloudflare Worker proxy: {CLOUDFLARE_WORKER_URL}")
                    try:
                        await _send_whatsapp_message(wa_id, "🔄 جاري التحميل عبر سيرفر بروكسي...")
                    except:
                        pass
                    
                    try:
                        import aiohttp as _aiohttp
                        from urllib.parse import quote
                        
                        worker_url = CLOUDFLARE_WORKER_URL.rstrip("/")
                        dl_type = "audio" if is_audio_only else "video"
                        api_url = f"{worker_url}/download?url={quote(url)}&type={dl_type}"
                        
                        async with _aiohttp.ClientSession() as cf_session:
                            async with cf_session.get(api_url, timeout=_aiohttp.ClientTimeout(total=180)) as cf_resp:
                                if cf_resp.status == 200:
                                    content_type = cf_resp.headers.get('Content-Type', '')
                                    if 'video' in content_type or 'audio' in content_type or 'octet-stream' in content_type:
                                        # Save the streamed file
                                        ext = "mp3" if is_audio_only else "mp4"
                                        cf_filepath = os.path.join(tmpdir, f"video_cf.{ext}")
                                        
                                        file_data = await cf_resp.read()
                                        with open(cf_filepath, 'wb') as cf_f:
                                            cf_f.write(file_data)
                                        
                                        cf_size = os.path.getsize(cf_filepath)
                                        if cf_size > 10000:  # At least 10KB
                                            # Get video info from headers
                                            cf_title = cf_resp.headers.get('X-Video-Title', 'فيديو')[:80]
                                            cf_author = cf_resp.headers.get('X-Video-Author', '')
                                            cf_duration = cf_resp.headers.get('X-Video-Duration', '0')
                                            
                                            info = {
                                                "title": cf_title or "YouTube Video",
                                                "duration": int(cf_duration) if cf_duration.isdigit() else 0,
                                                "height": 720,
                                                "vcodec": "h264",
                                                "acodec": "aac",
                                                "author": cf_author,
                                                "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                                            }
                                            logger.info(f"✅ CF Worker proxy download succeeded! Size: {cf_size // 1024}KB")
                                        else:
                                            try: os.remove(cf_filepath)
                                            except: pass
                                    else:
                                        # Worker returned JSON (might be "needs_decipher")
                                        try:
                                            cf_data = await cf_resp.json(content_type=None)
                                            if cf_data.get('error') == 'needs_decipher':
                                                # Get stream URLs using yt-dlp (info-only) then proxy through Worker
                                                logger.info("🔄 Worker says needs_decipher, trying yt-dlp info + Worker proxy approach")
                                                try:
                                                    # Use yt-dlp to get stream URL only (no download)
                                                    info_opts = {
                                                        'quiet': True,
                                                        'no_warnings': True,
                                                        'format': format_str,
                                                        'skip_download': True,
                                                    }
                                                    if is_audio_only:
                                                        info_opts['postprocessors'] = ydl_opts.get('postprocessors')
                                                    
                                                    def _run_ytdlp_info():
                                                        with yt_dlp.YoutubeDL(info_opts) as ydl:
                                                            return ydl.extract_info(url, download=False)
                                                    
                                                    info_only = await asyncio.wait_for(
                                                        loop.run_in_executor(None, _run_ytdlp_info),
                                                        timeout=120
                                                    )
                                                    
                                                    if info_only:
                                                        # Get the best stream URL
                                                        stream_url = info_only.get('url', '')
                                                        if not stream_url and info_only.get('formats'):
                                                            # Find best format with URL
                                                            for fmt in info_only['formats']:
                                                                if fmt.get('url') and fmt.get('protocol', '') in ('https', 'http'):
                                                                    stream_url = fmt['url']
                                                                    break
                                                        
                                                        if stream_url:
                                                            # Proxy through Cloudflare Worker
                                                            proxy_api = f"{worker_url}/proxy?url={quote(stream_url)}&type={dl_type}"
                                                            async with cf_session.get(proxy_api, timeout=_aiohttp.ClientTimeout(total=180)) as proxy_resp:
                                                                if proxy_resp.status == 200:
                                                                    ext = "mp3" if is_audio_only else "mp4"
                                                                    proxy_filepath = os.path.join(tmpdir, f"video_proxy.{ext}")
                                                                    proxy_data = await proxy_resp.read()
                                                                    with open(proxy_filepath, 'wb') as pf:
                                                                        pf.write(proxy_data)
                                                                    
                                                                    proxy_size = os.path.getsize(proxy_filepath)
                                                                    if proxy_size > 10000:
                                                                        info = {
                                                                            "title": info_only.get('title', 'فيديو')[:80],
                                                                            "duration": info_only.get('duration', 0),
                                                                            "height": info_only.get('height', 720),
                                                                            "author": info_only.get('uploader', ''),
                                                                            "vcodec": "h264",
                                                                            "acodec": "aac",
                                                                            "requested_downloads": [{"height": 720}],
                                                                        }
                                                                        logger.info(f"✅ yt-dlp info + CF Worker proxy succeeded! Size: {proxy_size // 1024}KB")
                                                                    else:
                                                                        try: os.remove(proxy_filepath)
                                                                        except: pass
                                                except Exception as proxy_err:
                                                    logger.warning(f"⚠️ yt-dlp info + CF Worker proxy failed: {proxy_err}")
                                        except Exception as json_err:
                                            logger.warning(f"⚠️ CF Worker JSON parse error: {json_err}")
                                else:
                                    logger.warning(f"⚠️ CF Worker returned status {cf_resp.status}")
                    except Exception as cf_err:
                        logger.warning(f"⚠️ Cloudflare Worker proxy fallback failed: {cf_err}")
            
            if not info:
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الفيديو. جرب تاني! 📥")
                await feedback.error()
                return
            
            # Find the downloaded file
            downloaded_files = os.listdir(tmpdir)
            if not downloaded_files:
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الفيديو. جرب تاني! 📥")
                await feedback.error()
                return
            
            video_file = os.path.join(tmpdir, downloaded_files[0])
            file_size = os.path.getsize(video_file)
            title = info.get('title', 'فيديو')[:80]
            
            logger.info(f"📥 Downloaded video: {title} ({file_size / 1024 / 1024:.1f}MB, quality={quality})")
            
            # 🔴 FIX v9: ffprobe audio check + smart h264 re-encoding (SPEED-OPTIMIZED)
            # Check if video has audio using ffprobe, and convert non-h264 codecs
            if not is_audio_only and file_size > 0:
                try:
                    import subprocess as _sp
                    
                    # ffprobe check for audio
                    probe_result = _sp.run(
                        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', video_file],
                        capture_output=True, timeout=15
                    )
                    video_vcodec = None
                    has_audio = False
                    
                    if probe_result.returncode == 0:
                        try:
                            import json as _json
                            probe_data = _json.loads(probe_result.stdout)
                            for stream in probe_data.get('streams', []):
                                if stream.get('codec_type') == 'video':
                                    video_vcodec = stream.get('codec_name', '')
                                elif stream.get('codec_type') == 'audio':
                                    has_audio = True
                        except Exception:
                            pass
                    
                    # 🔴 No audio detected — retry with different format (Facebook fix)
                    if not has_audio and is_facebook_family:
                        logger.warning(f"⚠️ No audio detected in {platform} video — retrying with merge format")
                        try:
                            shutil.rmtree(tmpdir, ignore_errors=True)
                            tmpdir = tempfile.mkdtemp(prefix="mybro_wa_dl_")
                            retry_output = os.path.join(tmpdir, "%(title).80s.%(ext)s")
                            
                            retry_format = (
                                'bestvideo+bestaudio/'
                                'bestvideo[vcodec^=avc1]+bestaudio/'
                                'best[ext=mp4][acodec!=none]/'
                                'best[acodec!=none]/'
                                'best'
                            )
                            
                            retry_opts = {
                                'outtmpl': retry_output,
                                'quiet': True, 'no_warnings': True,
                                'format': retry_format,
                                'merge_output_format': 'mp4',
                                'socket_timeout': 30, 'retries': 3,
                                'fragment_retries': 5, 'file_access_retries': 3,
                                'no_check_certificates': True,
                                'http_headers': ydl_opts.get('http_headers', {}),
                            }
                            
                            def _run_ytdlp_retry():
                                with yt_dlp.YoutubeDL(retry_opts) as ydl:
                                    return ydl.extract_info(url, download=True)
                            
                            retry_info = await asyncio.wait_for(
                                loop.run_in_executor(None, _run_ytdlp_retry),
                                timeout=300
                            )
                            
                            if retry_info:
                                info = retry_info
                                downloaded_files = os.listdir(tmpdir)
                                if downloaded_files:
                                    video_file = os.path.join(tmpdir, downloaded_files[0])
                                    file_size = os.path.getsize(video_file)
                                    logger.info(f"✅ Audio retry succeeded: {file_size / 1024 / 1024:.1f}MB")
                        except Exception as retry_err:
                            logger.warning(f"⚠️ Audio retry failed: {retry_err}")
                    
                    # 🔴 h264 re-encoding — ONLY if codec is NOT h264 (VP9/AV1 etc.)
                    # SPEED OPTIMIZED: preset ultrafast + CRF 23 + 128k audio
                    if (video_vcodec and video_vcodec not in ("h264", "avc1", "avc", "mpeg4", "")
                        and not is_audio_only):
                        logger.info(f"🔧 Converting {video_vcodec} to h264 (ultrafast) for WhatsApp compatibility...")
                        try:
                            import multiprocessing
                            threads = min(multiprocessing.cpu_count(), 4)
                            converted_path = video_file + "_h264.mp4"
                            
                            convert_result = _sp.run(
                                ['ffmpeg', '-i', video_file,
                                 '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                                 '-threads', str(threads),
                                 '-c:a', 'aac', '-b:a', '128k',
                                 '-movflags', '+faststart',
                                 '-y', converted_path],
                                capture_output=True, timeout=180
                            )
                            
                            if convert_result.returncode == 0 and os.path.exists(converted_path):
                                converted_size = os.path.getsize(converted_path)
                                if converted_size > 0:
                                    try: os.remove(video_file)
                                    except: pass
                                    video_file = converted_path
                                    file_size = converted_size
                                    logger.info(f"✅ Converted to h264 (ultrafast): {file_size // (1024*1024)}MB")
                                else:
                                    try: os.remove(converted_path)
                                    except: pass
                            else:
                                try: os.remove(converted_path)
                                except: pass
                                logger.warning(f"⚠️ h264 conversion failed, keeping original")
                        except _sp.TimeoutExpired:
                            logger.warning("⚠️ h264 conversion timed out, keeping original")
                            try: os.remove(video_file + "_h264.mp4")
                            except: pass
                        except Exception as conv_err:
                            logger.warning(f"⚠️ h264 conversion error: {conv_err}")
                            
                except ImportError:
                    pass  # subprocess not available
                except Exception as e:
                    logger.warning(f"⚠️ Video check/conversion error: {e}")
            
            # 🔴 FIX: رفع الحد الأقصى — واتساب بيقبل لحد 512MB (تحديث 2025)
            # بنحط 500MB كحد آمن عشان نبعت الملف مباشرة
            MAX_WHATSAPP_MEDIA_SIZE = 500 * 1024 * 1024  # 500MB
            
            if file_size <= MAX_WHATSAPP_MEDIA_SIZE:
                with open(video_file, 'rb') as f:
                    file_bytes = f.read()
                
                if is_audio_only:
                    # Send as audio file
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + '.mp3'
                    caption = f"🎵 {title}\n🔗 {platform_display}\n📊 {file_size / 1024 / 1024:.1f}MB"
                    result = await _send_whatsapp_document(
                        wa_id, file_bytes, safe_filename, caption, "audio/mpeg"
                    )
                else:
                    # Send as document (video files are more reliable as documents on WA)
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + '.mp4'
                    quality_label = {"best": "1080p", "medium": "720p", "low": "480p"}.get(quality, "")
                    caption = f"📥 {title}\n🔗 {platform_display}\n📊 {file_size / 1024 / 1024:.1f}MB"
                    if quality_label:
                        caption += f"\n🎬 {quality_label}"
                    result = await _send_whatsapp_document(
                        wa_id, file_bytes, safe_filename, caption, "video/mp4"
                    )
                
                if "error" in result:
                    # لو الإرسال فشل — نجرب جودة أقل
                    error_msg = str(result.get("error", ""))
                    logger.warning(f"⚠️ WhatsApp send failed: {error_msg}")
                    
                    if quality != "audio" and quality != "low":
                        # نجرب جودة أقل
                        lower_quality = {"best": "medium", "medium": "low"}.get(quality, "low")
                        await _send_whatsapp_message(wa_id,
                            f"⚠️ الفيديو كبير ({file_size / 1024 / 1024:.1f}MB). جاري تحميل جودة أقل...")
                        # تنظيف وإعادة المحاولة
                        try:
                            shutil.rmtree(tmpdir, ignore_errors=True)
                        except Exception:
                            pass
                        await feedback.complete()
                        return await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=lower_quality)
                    else:
                        # لو حتى الجودة المنخفضة فشلت
                        await _send_whatsapp_message(wa_id, 
                            f"📥 *{title}*\n\n"
                            f"🔗 المنصة: {platform_display}\n"
                            f"📊 الحجم: {file_size / 1024 / 1024:.1f}MB\n\n"
                            f"⚠️ مش قادر أبعت الفيديو مباشرة على واتساب.\n"
                            f"💡 جرب التليجرام عشان تحمل الفيديو هناك!")
            else:
                # File too large for WhatsApp — جرب جودة أقل
                if quality != "audio" and quality != "low":
                    lower_quality = {"best": "medium", "medium": "low"}.get(quality, "low")
                    await _send_whatsapp_message(wa_id,
                        f"⚠️ الفيديو كبير جداً ({file_size / 1024 / 1024:.1f}MB). جاري تحميل جودة أقل...")
                    try:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                    except Exception:
                        pass
                    await feedback.complete()
                    return await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=lower_quality)
                
                # حتى الجودة المنخفضة كبيرة — نبعت معلومات
                duration = info.get('duration', 0)
                duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "غير معروف"
                
                await _send_whatsapp_message(wa_id,
                    f"📥 *{title}*\n\n"
                    f"🔗 المنصة: {platform_display}\n"
                    f"⏱️ المدة: {duration_str}\n"
                    f"📊 الحجم: {file_size / 1024 / 1024:.1f}MB\n\n"
                    f"⚠️ الفيديو كبير على واتساب (الحد 512MB)\n\n"
                    f"💡 جرب التليجرام عشان تحمل الفيديو بحجمه الكامل!")
            
            # Increment usage
            if not is_admin:
                try:
                    from premium import increment_usage
                    increment_usage(wa_user_id, "downloads")
                except Exception:
                    pass
            
            await feedback.complete()
            
        finally:
            # Cleanup temp directory
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass
        
    except ImportError:
        logger.error("❌ yt-dlp not installed!")
        await _send_whatsapp_message(wa_id, "❌ تحميل الفيديوهات مش متاح دلوقتي. جرب تاني بعد شوية! 📥")
        await feedback.error()
    except asyncio.TimeoutError:
        await _send_whatsapp_message(wa_id, "❌ انتهى وقت التحميل. حاول مرة تانية! 📥")
        await feedback.error()
    except Exception as e:
        logger.error(f"❌ Video download error for WA {wa_id}: {e}", exc_info=True)
        error_str = str(e).lower()
        
        # User-friendly error messages
        if "sign in" in error_str or "login" in error_str or "bot" in error_str:
            await _send_whatsapp_message(wa_id, 
                "❌ مش قادر أحمل الفيديو ده — YouTube طلب تسجيل دخول.\n\n"
                "💡 جرب فيديو تاني أو استخدم التليجرام!")
        elif "private" in error_str or "age" in error_str:
            await _send_whatsapp_message(wa_id, 
                "❌ الفيديو ده خاص أو مقيد بالعمر.\n\n💡 جرب فيديو تاني!")
        elif "not found" in error_str or "does not exist" in error_str:
            await _send_whatsapp_message(wa_id, 
                "❌ الرابط مش صحيح أو الفيديو مش موجود.\n\n💡 تأكد من الرابط وجرب تاني!")
        else:
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في التحميل. جرب تاني! 📥")
        
        await feedback.error()


# ═══════════════════════════════════════
# AI Response Helper (Enhanced with Typing Indicator)
# ═══════════════════════════════════════

async def _send_ai_response(wa_id: str, user_message: str, wa_user_id: int, contact_name: str,
                           message_id: str = "", thinking_emoji: str = "🤔",
                           context_type: str = "general", increment_feature: str = "ai_messages"):
    """
    Send an AI response with full pipeline (Enhanced with professional thinking feedback):
    1. ThinkingFeedback (💭 reaction + progressive status messages)
    2. Check premium limits
    3. Get AI response
    4. Send response chunks
    5. Increment usage
    6. Show remaining usage for free users
    7. Contextual quick action buttons
    8. Complete thinking feedback (✅ reaction)
    """
    from ai_engine import smart_chat
    from formatters import clean_ai_response

    is_admin = _is_wa_admin(wa_id)

    # Start professional thinking feedback (replaces old thinking indicator)
    feedback = ThinkingFeedback(wa_id, message_id, context_type=context_type)
    await feedback.start()

    try:
        # Check limits (skip for admin)
        if not is_admin:
            try:
                from premium import check_limit
                limit_check = check_limit(wa_user_id, f"{increment_feature}_per_day")
                if not limit_check.get("allowed", True):
                    remaining = limit_check.get("remaining", 0)
                    limit = limit_check.get("limit", 0)
                    await _send_whatsapp_message(wa_id,
                        f"⚠️ وصلت للحد اليومي!\n\n{increment_feature}: استخدمت {limit} من {limit} اليوم\n\n💡 الحد بيرجع تاني بكرة\n⭐ ترقية لـ Premium عشان استخدام غير محدود!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    if message_id:
                        try:
                            await _send_whatsapp_reaction(wa_id, message_id, "⚠️")
                        except Exception:
                            pass
                    await feedback.error()
                    return
            except Exception:
                pass  # If premium system fails, allow the message

        # Get AI response
        # 🔴 لو المستخدم هو الأدمن (المطور)، نمرر username=ziadamr عشان البوت يتعرف عليه
        smart_chat_username = "ziadamr" if is_admin else (contact_name if contact_name != "Unknown" else None)
        ai_response = await smart_chat(
            user_message=user_message,
            language="ar",
            user_id=wa_user_id,
            username=smart_chat_username,
        )
        ai_response = clean_ai_response(ai_response)
        wa_response = _strip_html_for_whatsapp(ai_response)

        # Split and send
        chunks = _split_whatsapp_message(wa_response)
        for chunk in chunks:
            await _send_whatsapp_message(wa_id, chunk)
            if len(chunks) > 1:
                await asyncio.sleep(0.3)

        # Increment usage (skip for admin)
        if not is_admin:
            try:
                from premium import increment_usage
                increment_usage(wa_user_id, increment_feature)
            except Exception:
                pass

        # Complete thinking feedback
        await feedback.complete()

        # Contextual quick action buttons
        await _send_contextual_buttons(wa_id, context_type)

        logger.info(f"✅ WA AI response sent to {wa_id} ({len(chunks)} chunk(s))")

    except Exception as e:
        logger.error(f"❌ AI engine error for WA {wa_id}: {e}", exc_info=True)
        await feedback.error()
        await _send_whatsapp_message(wa_id, "⚠️ مش قادر أرد دلوقتي — جرب تاني بعد شوية! 🔄")


async def _send_contextual_buttons(wa_id: str, context_type: str = "general"):
    """Send contextual quick action buttons based on the type of response"""
    try:
        if context_type == "news":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_news", "title": "📰 أخبار أخرى"},
                    {"id": "cmd_trending", "title": "📈 ترندات"},
                    {"id": "cmd_company", "title": "🏢 شركات"},
                ])
        elif context_type == "learn" or context_type == "study":
            await _send_interactive_buttons(wa_id, body_text="عايز تتعلم أكتر؟",
                buttons=[
                    {"id": "cmd_learn", "title": "📚 تعلم أكتر"},
                    {"id": "cmd_roadmap", "title": "🗺️ خريطة"},
                    {"id": "cmd_ask", "title": "❓ اسأل"},
                ])
        elif context_type == "memory":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_memory_view", "title": "🧠 عرض الذاكرة"},
                    {"id": "cmd_memory_reset", "title": "🗑️ مسح"},
                    {"id": "cmd_settings", "title": "⚙️ إعدادات"},
                ])
        elif context_type == "search":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_search", "title": "🔍 بحث تاني"},
                    {"id": "cmd_chat", "title": "💬 محادثة"},
                    {"id": "cmd_commands", "title": "📋 الأوامر"},
                ])
        elif context_type == "youtube":
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_youtube", "title": "🎬 فيديو تاني"},
                    {"id": "cmd_chat", "title": "💬 محادثة"},
                    {"id": "cmd_commands", "title": "📋 الأوامر"},
                ])
        else:  # general chat
            await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                buttons=[
                    {"id": "cmd_chat", "title": "💬 كمل"},
                    {"id": "cmd_news", "title": "📰 أخبار"},
                    {"id": "cmd_commands", "title": "📋 الأوامر"},
                ])
    except Exception:
        pass  # Non-critical


# ═══════════════════════════════════════
# Commands System — Full Feature Parity with Telegram
# ═══════════════════════════════════════

_COMMAND_TRIGGERS = {
    # Start / Welcome
    "/start": "start", "start": "start", "اهلا": "start", "مرحبا": "start", "سلام": "start", "هاي": "start",
    # Help / Commands
    "/help": "help", "help": "help", "مساعدة": "help", "اوامر": "help", "الأوامر": "help", "الاوامر": "help",
    # Commands menu
    "/commands": "commands", "commands": "commands", "قائمة": "commands", "القائمة": "commands", "الميزات": "commands",
    # News
    "/news": "news", "news": "news", "اخبار": "news", "أخبار": "news", "الاخبار": "news",
    # Breaking news
    "/breaking": "breaking", "breaking": "breaking", "عاجل": "breaking", "عاجلة": "breaking",
    # Weekly summary
    "/weekly": "weekly", "weekly": "weekly", "اسبوعي": "weekly", "أسبوعي": "weekly", "ملخص اسبوعي": "weekly",
    # Trending
    "/trending": "trending", "trending": "trending", "ترند": "trending", "ترندات": "trending", "الأكثر": "trending",
    # Search
    "/search": "search", "search": "search", "بحث": "search", "ابحث": "search", "البحث": "search",
    # Ask
    "/ask": "ask", "ask": "ask", "اسأل": "ask", "اسال": "ask", "سؤال": "ask",
    # Learn
    "/learn": "learn", "learn": "learn", "تعلم": "learn", "اتعلم": "learn",
    # Roadmap
    "/roadmap": "roadmap", "roadmap": "roadmap", "خريطة": "roadmap", "مسار": "roadmap",
    # Chat (force AI mode)
    "/chat": "chat", "chat": "chat", "محادثة": "chat", "كلم": "chat", "كلمني": "chat",
    # Company info
    "/company": "company", "company": "company", "شركة": "company", "شركات": "company",
    # About
    "/about": "about", "about": "about", "عن": "about", "مين": "about", "مين انت": "about",
    # Subscribe / Unsubscribe
    "/subscribe": "subscribe", "subscribe": "subscribe", "اشترك": "subscribe", "اشتراك": "subscribe",
    "/unsubscribe": "unsubscribe", "unsubscribe": "unsubscribe", "الغاء": "unsubscribe", "إلغاء": "unsubscribe", "الغاء اشتراك": "unsubscribe",
    # Language
    "/language": "language", "language": "language", "لغة": "language", "اللغة": "language",
    # Memory
    "/memory": "memory", "memory": "memory", "ذاكرة": "memory", "الذاكرة": "memory",
    # Premium
    "/premium": "premium", "premium": "premium", "بريميوم": "premium", "اشتراك مدفوع": "premium",
    # Plan / Usage
    "/plan": "plan", "plan": "plan", "حدود": "plan", "الحدود": "plan", "استخدام": "plan",
    "/usage": "plan",
    # Settings
    "/settings": "settings", "settings": "settings", "اعدادات": "settings", "الإعدادات": "settings", "ضبط": "settings",
    # Download
    "/download": "download", "download": "download", "تحميل": "download", "حمّل": "download",
    # Video/Audio Search
    "/video": "video_search", "فيديو بالبحث": "video_search", "فيديو بحث": "video_search",
    "/audio": "audio_search", "صوت بالبحث": "audio_search", "صوت بحث": "audio_search",
    # Photo Search
    "/photo": "photo_search", "بحث صور": "photo_search", "صور": "photo_search",
    # Study Mode
    "/study": "study", "study": "study", "دراسة": "study", "ادرس": "study",
    "/quiz": "quiz", "quiz": "quiz", "كويز": "quiz",
    "/exam": "exam", "exam": "exam", "امتحان": "exam",
    # YouTube
    "/youtube": "youtube", "youtube": "youtube", "يوتيوب": "youtube",
    # PDF
    "/pdf": "pdf", "pdf": "pdf",
    "/keypoints": "pdf_keypoints",
    # Image gen
    "/image": "image_gen", "image": "image_gen", "صورة": "image_gen",
    # Image edit
    "/edit": "image_edit", "edit": "image_edit", "عدل": "image_edit", "عدل صورة": "image_edit",
    # Favorites
    "/favorite": "favorite", "favorite": "favorite", "مفضلة": "favorite",
    "/favorites": "favorites", "favorites": "favorites", "المفضلات": "favorites",
    # Forget
    "/forget": "forget", "نسي": "forget", "امسح ذاكرة": "forget",
    # Admin commands
    "/admin": "admin", "ادمن": "admin", "لوحة التحكم": "admin",
    "/dashboard": "admin", "لوحة": "admin",
    "/stats": "admin_stats", "احصائيات": "admin_stats",
    "/botstats": "admin_stats",
    "/grant": "admin_grant", "تفعيل بروميوم": "admin_grant",
    "/revoke": "admin_revoke", "شيل بروميوم": "admin_revoke",
    "/resetlimit": "admin_resetlimit", "ريست حد": "admin_resetlimit",
    "/ban": "admin_ban", "حظر": "admin_ban",
    "/unban": "admin_unban", "الغاء حظر": "admin_unban",
    "/warn": "admin_warn", "تحذير": "admin_warn",
    "/userinfo": "admin_userinfo", "معلومات يوزر": "admin_userinfo",
    "/broadcast": "admin_broadcast", "بث": "admin_broadcast",
    "/allusers": "admin_allusers", "كل المستخدمين": "admin_allusers",
    "/addadmin": "admin_addadmin", "اضافة ادمن": "admin_addadmin",
    "/removeadmin": "admin_removeadmin", "شيل ادمن": "admin_removeadmin",
    "/listadmins": "admin_listadmins", "الادمنز": "admin_listadmins",
}


async def _handle_command(wa_id: str, command: str, wa_user_id: int, contact_name: str, message_id: str = ""):
    """Handle WhatsApp commands and send interactive responses — full Telegram parity"""

    is_admin = _is_wa_admin(wa_id)

    # ── Ensure admin is always premium ──
    if is_admin:
        _ensure_wa_admin_premium(wa_id)

    # ══════════════════════════════════════
    # ADMIN COMMANDS
    # ══════════════════════════════════════

    if command == "admin" or command == "admin_stats":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True

        try:
            from dashboard import format_dashboard
            from premium import get_all_premium_users
            from memory import get_all_subscribers, get_user

            dashboard = format_dashboard("ar", platform="whatsapp")
            total_subs = len(get_all_subscribers(platform="whatsapp"))
            total_prem = len(get_all_premium_users(platform="whatsapp"))

            admin_text = (
                f"👑 *لوحة تحكم الأدمن*\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"{_strip_html_for_whatsapp(dashboard)}\n\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"👑 *صلاحياتك:*\n"
                f"→ مفيش أي Limits — كل حاجة مفتوحة\n"
                f"→ تفعيل Premium لأي حد\n"
                f"→ شيل Premium من أي حد\n"
                f"→ بث رسالة لكل المشتركين\n"
                f"→ معلومات أي يوزر\n\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔧 *أوامر الأدمن:*\n"
                f"→ /grant user_id — تفعيل Premium\n"
                f"→ /revoke user_id — شيل Premium\n"
                f"→ /resetlimit user_id — ريست الحدود\n"
                f"→ /ban user_id — حظر مستخدم\n"
                f"→ /unban user_id — إلغاء حظر\n"
                f"→ /userinfo user_id — معلومات يوزر\n"
                f"→ /broadcast رسالة — بث لكل المشتركين\n"
                f"→ /stats — الإحصائيات"
            )
            await _send_whatsapp_message(wa_id, admin_text)
        except Exception as e:
            logger.error(f"❌ Admin command error: {e}")
            await _send_whatsapp_message(wa_id, f"⚠️ خطأ في لوحة التحكم: {e}")
        return True

    elif command == "admin_grant":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "⭐ *تفعيل Premium*\n\n"
            "الاستخدام:\n"
            "/grant user_id — تفعيل مدى الحياة\n"
            "/grant 30 user_id — تفعيل 30 يوم\n\n"
            "مثال: /grant 123456789")
        return True

    elif command == "admin_revoke":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "❌ *شيل Premium*\n\n"
            "الاستخدام: /revoke user_id\n"
            "مثال: /revoke 123456789")
        return True

    elif command == "admin_resetlimit":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "🔄 *ريست الحدود*\n\n"
            "الاستخدام: /resetlimit user_id\n"
            "مثال: /resetlimit 123456789")
        return True

    elif command == "admin_ban":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "🚫 *حظر مستخدم*\n\n"
            "الاستخدام: /ban user_id [سبب]\n"
            "مثال: /ban 123456789 سبام")
        return True

    elif command == "admin_unban":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "✅ *إلغاء حظر*\n\n"
            "الاستخدام: /unban user_id\n"
            "مثال: /unban 123456789")
        return True

    elif command == "admin_userinfo":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👤 *معلومات يوزر*\n\n"
            "الاستخدام: /userinfo user_id\n"
            "مثال: /userinfo 123456789")
        return True

    elif command == "admin_broadcast":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "📢 *بث رسالة*\n\n"
            "الاستخدام: /broadcast الرسالة\n"
            "مثال: /broadcast تحديث جديد في البوت!")
        return True

    elif command == "admin_stats":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "📊 *إحصائيات البوت*\n\n"
            "الاستخدام: /botstats أو /stats")
        return True

    elif command == "admin_allusers":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👥 *كل المستخدمين*\n\n"
            "الاستخدام: /allusers")
        return True

    elif command == "admin_warn":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "⚠️ *تحذير مستخدم*\n\n"
            "الاستخدام: /warn user_id [سبب]\n"
            "3 تحذيرات = حظر تلقائي\n"
            "مثال: /warn 123456789 سبام")
        return True

    elif command == "admin_addadmin":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👑 *إضافة أدمن*\n\n"
            "الاستخدام: /addadmin user_id\n"
            "مثال: /addadmin 123456789")
        return True

    elif command == "admin_removeadmin":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👑 *شيل أدمن*\n\n"
            "الاستخدام: /removeadmin user_id\n"
            "مثال: /removeadmin 123456789")
        return True

    elif command == "admin_listadmins":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "👑 *قائمة الأدمنز*\n\n"
            "الاستخدام: /listadmins")
        return True

    # ══════════════════════════════════════
    # START — Enhanced Multi-Page Menu
    # ══════════════════════════════════════

    if command == "start":
        # Welcome message with FULL category list like Telegram keyboard
        # Send welcome text first
        await _send_whatsapp_message(wa_id,
            "أهلاً بيك! 🤖 أنا *My Bro* — مساعدك الذكي الشخصي\n\n"
            "ممكن أساعدك في حاجات كتير!\nاختار من القائمة أو ابعت أي رسالة")

        # Then send interactive list with all categories
        admin_row = []
        if is_admin:
            admin_row = [{"id": "cmd_admin", "title": "👑 أدمن", "description": "لوحة تحكم الأدمن"}]

        await _send_interactive_list(
            wa_id,
            body_text="اختار من الميزات:",
            button_text="📋 الميزات",
            sections=[{
                "title": "🤖 الميزات الرئيسية",
                "rows": [
                    {"id": "cmd_chat", "title": "🤖 المحادثة", "description": "تحدث مع AI"},
                    {"id": "cmd_news", "title": "📰 الأخبار", "description": "أخبار AI لحظة بلحظة"},
                    {"id": "cmd_download", "title": "📥 تحميل فيديو", "description": "تحميل من يوتيوب وتيك توك"},
                    {"id": "video_search", "title": "🎬 فيديو بالبحث", "description": "ابحث وحمّل فيديو"},
                    {"id": "audio_search", "title": "🎵 صوت بالبحث", "description": "ابحث وحمّل صوت"},
                    {"id": "photo_search", "title": "🖼️ بحث صور", "description": "ابحث عن صور"},
                    {"id": "cmd_search", "title": "🔍 بحث الويب", "description": "ابحث في الإنترنت"},
                ],
            }, {
                "title": "📚 التعلم والدراسة",
                "rows": [
                    {"id": "cmd_study", "title": "📚 وضع الدراسة", "description": "ادرس واختبر نفسك"},
                    {"id": "cmd_memory", "title": "🧠 ذاكرتي", "description": "عرض وإدارة الذاكرة"},
                ],
            }, {
                "title": "🎨 الوسائط والصور ⭐",
                "rows": [
                    {"id": "cmd_image_gen", "title": "🎨 إنشاء صورة", "description": "Premium — صور من وصف"},
                    {"id": "cmd_image_edit", "title": "🖌️ تعديل صورة", "description": "Premium — عدّل صورة بالوصف"},
                ],
            }, {
                "title": "📄 المستندات واليوتيوب",
                "rows": [
                    {"id": "cmd_youtube", "title": "📺 ملخص يوتيوب", "description": "ملخص فيديو يوتيوب"},
                    {"id": "cmd_pdf", "title": "📄 تحليل PDF", "description": "ابعت PDF واسأل عنه"},
                ],
            }, {
                "title": "⚙️ الإعدادات",
                "rows": [
                    {"id": "cmd_settings", "title": "⚙️ الإعدادات", "description": "تغيير اللغة والإشعارات"},
                    {"id": "cmd_plan", "title": "📋 الخطة وحدودي", "description": "عرض خطتك واستخدامك"},
                ] + admin_row,
            }],
            header_text="🤖 My Bro",
            footer_text="v9.20 — مساعدك الذكي",
        )

    # ══════════════════════════════════════
    # HELP / COMMANDS
    # ══════════════════════════════════════

    elif command == "help" or command == "commands":
        await _send_interactive_list(
            wa_id,
            body_text="📋 كل الأوامر والميزات المتاحة:",
            button_text="عرض الأوامر",
            sections=[{
                "title": "🤖 المحادثة و الذكاء الاصطناعي",
                "rows": [
                    {"id": "cmd_chat", "title": "💬 محادثة AI", "description": "تحدث مع الذكاء الاصطناعي"},
                    {"id": "cmd_ask", "title": "❓ اسأل سؤال", "description": "اسأل أي سؤال وهجاوبك"},
                    {"id": "cmd_search", "title": "🔍 بحث ويب", "description": "ابحث في الإنترنت"},
                    {"id": "cmd_learn", "title": "📚 تعلم", "description": "تعلم أي موضوع بالتفصيل"},
                    {"id": "cmd_roadmap", "title": "🗺️ خريطة تعلم", "description": "خريطة طريق لتعلم أي تقنية"},
                    {"id": "cmd_study", "title": "📚 وضع الدراسة", "description": "ادرس واختبر نفسك"},
                    {"id": "cmd_news", "title": "📰 أخبار AI", "description": "آخر أخبار الذكاء الاصطناعي"},
                    {"id": "cmd_youtube", "title": "🎬 ملخص يوتيوب", "description": "لخص أي فيديو يوتيوب"},
                    {"id": "cmd_download", "title": "📥 تحميل فيديو", "description": "حمّل من يوتيوب"},
                    {"id": "video_search", "title": "🎬 فيديو بالبحث", "description": "ابحث وحمّل فيديو"},
                    {"id": "audio_search", "title": "🎵 صوت بالبحث", "description": "ابحث وحمّل صوت"},
                    {"id": "photo_search", "title": "🖼️ بحث صور", "description": "ابحث عن صور"},
                    {"id": "cmd_memory", "title": "🧠 ذاكرتي", "description": "عرض وإدارة الذاكرة"},
                ],
            }],
            header_text="📋 أوامر My Bro",
            footer_text="أو ابعت أي رسالة وهرد عليك!",
        )

    # ══════════════════════════════════════
    # NEWS COMMANDS
    # ══════════════════════════════════════

    elif command == "news":
        await _send_ai_response(wa_id, "اعطني اخر اخبار الذكاء الاصطناعي اليوم باختصار",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command == "breaking":
        await _send_ai_response(wa_id,
            "ما هي اهم الاخبار العاجلة في مجال الذكاء الاصطناعي اليوم؟ اذكر أهم التطورات والاعلانات الجديدة",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command == "weekly":
        await _send_ai_response(wa_id,
            "لخص لي أهم أخبار وتطورات الذكاء الاصطناعي خلال هذا الأسبوع بشكل شامل. اذكر أهم الاعلانات والمنتجات والأخبار",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command == "trending":
        await _send_ai_response(wa_id,
            "ما هي أهم المواضيع الترند في مجال الذكاء الاصطناعي اليوم؟ اذكر أهم 5 مواضيع أو تقنيات يتكلم عنها الناس حالياً",
            wa_user_id, contact_name, message_id, context_type="news")

    # ══════════════════════════════════════
    # SEARCH & ASK
    # ══════════════════════════════════════

    elif command == "search":
        await _send_interactive_buttons(
            wa_id,
            body_text="🔍 *بحث الويب*\n\nاكتب كلمة البحث بعد الأمر\nمثال: *بحث أحدث تقنيات AI*\n\nأو اختار من الاقتراحات:",
            buttons=[
                {"id": "cmd_search_ai", "title": "🤖 أخبار AI"},
                {"id": "cmd_search_code", "title": "👨‍💻 برمجة"},
            ],
            header_text="🔍 بحث ويب",
        )

    elif command == "ask":
        await _send_interactive_buttons(
            wa_id,
            body_text="❓ *اسأل أي سؤال*\n\nاكتب سؤالك مباشرة وهجاوبك بإذن الله\n\nأو اختار من الأسئلة الشائعة:",
            buttons=[
                {"id": "cmd_ask_ai", "title": "🤖 ما هو AI؟"},
                {"id": "cmd_ask_code", "title": "👨‍💻 برمجة"},
            ],
            header_text="❓ اسأل سؤال",
        )

    # ══════════════════════════════════════
    # LEARN & ROADMAP
    # ══════════════════════════════════════

    elif command == "learn":
        await _send_interactive_list(
            wa_id,
            body_text="📚 *تعلم أي موضوع*\n\nاختار الموضوع اللي عايز تتعلمه:",
            button_text="اختار موضوع",
            sections=[{
                "title": "📚 مواضيع التعلم",
                "rows": [
                    {"id": "cmd_learn_ai", "title": "🤖 الذكاء الاصطناعي", "description": "تعلم أساسيات AI"},
                    {"id": "cmd_learn_ml", "title": "🧠 تعلم الآلة", "description": "Machine Learning"},
                    {"id": "cmd_learn_dl", "title": "🔬 التعلم العميق", "description": "Deep Learning"},
                    {"id": "cmd_learn_nlp", "title": "💬 معالجة اللغة", "description": "NLP"},
                    {"id": "cmd_learn_llm", "title": "📝 النماذج اللغوية", "description": "LLMs"},
                    {"id": "cmd_learn_python", "title": "🐍 بايثون", "description": "Python programming"},
                    {"id": "cmd_learn_web", "title": "🌐 تطوير الويب", "description": "Web Development"},
                ],
            }],
            header_text="📚 تعلم",
        )

    elif command == "roadmap":
        await _send_interactive_list(
            wa_id,
            body_text="🗺️ *خريطة التعلم*\n\nاختار المجال اللي عايز تشوف خريطته:",
            button_text="اختار خريطة",
            sections=[{
                "title": "🗺️ خرائط التعلم",
                "rows": [
                    {"id": "cmd_roadmap_ai", "title": "🤖 AI", "description": "خريطة الذكاء الاصطناعي"},
                    {"id": "cmd_roadmap_ml", "title": "🧠 ML", "description": "خريطة تعلم الآلة"},
                    {"id": "cmd_roadmap_dl", "title": "🔬 Deep Learning", "description": "خريطة التعلم العميق"},
                    {"id": "cmd_roadmap_nlp", "title": "💬 NLP", "description": "خريطة معالجة اللغة"},
                    {"id": "cmd_roadmap_llm", "title": "📝 LLM", "description": "خريطة النماذج اللغوية"},
                ],
            }],
            header_text="🗺️ خريطة تعلم",
        )

    # ══════════════════════════════════════
    # COMPANY
    # ══════════════════════════════════════

    elif command == "company":
        await _send_interactive_list(
            wa_id,
            body_text="🏢 *أخبار الشركات*\n\nاختار الشركة اللي عايز تعرف آخر أخبارها:",
            button_text="اختار شركة",
            sections=[{
                "title": "🏢 شركات AI",
                "rows": [
                    {"id": "cmd_company_openai", "title": "🏢 OpenAI", "description": "آخر أخبار OpenAI"},
                    {"id": "cmd_company_google", "title": "🏢 Google", "description": "آخر أخبار Google AI"},
                    {"id": "cmd_company_anthropic", "title": "🏢 Anthropic", "description": "آخر أخبار Anthropic"},
                    {"id": "cmd_company_meta", "title": "🏢 Meta", "description": "آخر أخبار Meta AI"},
                    {"id": "cmd_company_xai", "title": "🏢 xAI", "description": "آخر أخبار xAI"},
                    {"id": "cmd_company_nvidia", "title": "🏢 NVIDIA", "description": "آخر أخبار NVIDIA"},
                ],
            }],
            header_text="🏢 شركات",
        )

    # ══════════════════════════════════════
    # CHAT
    # ══════════════════════════════════════

    elif command == "chat":
        await _send_whatsapp_message(wa_id,
            "💬 اكتب أي حاجة وهرد عليك!\n\n"
            "ممكن تسألني أي سؤال أو نتكلم عن أي موضوع 🤖\n\n"
            "نصايح:\n"
            "• اسألني عن أي موضوع\n"
            "• ابعتلي صوت وهحوله لنص\n"
            "• ابعتلي صورة وهحللها\n"
            "• ابعتلي ملف PDF وهحلله")

    # ══════════════════════════════════════
    # ABOUT
    # ══════════════════════════════════════

    elif command == "about":
        try:
            from config import BOT_NAME, BOT_VERSION, CREATOR_INFO
            # If admin asks "who made you?" — special response
            if is_admin:
                about_text = (
                    f"🤖 *{BOT_NAME}* v{BOT_VERSION}\n\n"
                    f"أنت اللي عملتني! 😄🫡\n\n"
                    f"👨‍💻 المطور: *{CREATOR_INFO['name_ar']}* — ده أنت!\n"
                    f"🏢 {CREATOR_INFO['company_ar']}\n\n"
                    f"👑 أنت الأدمن — مفيش أي Limits عليك!\n"
                    f"⭐ Premium مدى الحياة تلقائي\n"
                    f"🔧 كل أوامر الأدمن متاحة ليك"
                )
            else:
                about_text = (
                    f"🤖 *{BOT_NAME}* v{BOT_VERSION}\n\n"
                    f"مساعد ذكي شخصي بيشتغل على واتساب وتليجرام\n\n"
                    f"👨‍💻 المطور: {CREATOR_INFO['name_ar']}\n"
                    f"🏢 الشركة: {CREATOR_INFO['company_ar']}\n"
                    f"📧 {CREATOR_INFO['email']}\n"
                    f"🌐 {CREATOR_INFO['website']}\n\n"
                    f"المميزات:\n"
                    f"💬 محادثة ذكية بالعربي والإنجليزي\n"
                    f"🎤 تحويل الصوت لنص\n"
                    f"👁️ تحليل الصور\n"
                    f"📰 أخبار AI يومية وعاجلة\n"
                    f"🔍 بحث ويب\n"
                    f"📥 تحميل فيديو\n"
                    f"📚 وضع الدراسة\n"
                    f"🧠 ذاكرة ذكية\n"
                    f"🎨 إنشاء وتعديل صور\n"
                    f"📈 ترندات وأخبار شركات"
                )
            await _send_whatsapp_message(wa_id, about_text)
        except Exception:
            await _send_whatsapp_message(wa_id, "🤖 My Bro v9.15 — مساعدك الذكي الشخصي")

    # ══════════════════════════════════════
    # SUBSCRIBE / UNSUBSCRIBE
    # ══════════════════════════════════════

    elif command == "subscribe":
        await _send_interactive_buttons(
            wa_id,
            body_text="📬 *اشتراك الأخبار*\n\nهتبقي مشترك في الأخبار اليومية!\nهنبعتلك أخبار AI على مدار اليوم\n\nاختار:",
            buttons=[
                {"id": "cmd_subscribe_confirm", "title": "✅ اشترك"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ],
            header_text="📬 اشتراك",
        )

    elif command == "unsubscribe":
        await _send_interactive_buttons(
            wa_id,
            body_text="❌ *إلغاء اشتراك الأخبار*\n\nمتأكد إنك عايز تلغي اشتراك الأخبار اليومية؟",
            buttons=[
                {"id": "cmd_unsubscribe_confirm", "title": "❌ إلغاء الاشتراك"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ],
            header_text="❌ إلغاء اشتراك",
        )

    elif command == "subscribe_confirm":
        try:
            from memory import subscribe_user
            subscribe_user(wa_user_id)
            await _send_whatsapp_message(wa_id, "✅ تم الاشتراك بنجاح! 🎉\n\nهنبعتلك أخبار AI على مدار اليوم.\nلو عايز تلغي الاشتراك ابعت: إلغاء")
        except Exception:
            await _send_whatsapp_message(wa_id, "✅ تم الاشتراك بنجاح! 🎉")

    elif command == "unsubscribe_confirm":
        try:
            from memory import unsubscribe_user
            unsubscribe_user(wa_user_id)
            await _send_whatsapp_message(wa_id, "❌ تم إلغاء الاشتراك.\n\nلو عايز تشترك تاني ابعت: اشترك")
        except Exception:
            await _send_whatsapp_message(wa_id, "❌ تم إلغاء الاشتراك.")

    # ══════════════════════════════════════
    # LANGUAGE
    # ══════════════════════════════════════

    elif command == "language":
        await _send_interactive_buttons(
            wa_id,
            body_text="🌐 *اختار اللغة*\n\nاختار اللغة اللي عايز تتكلم بيها معايا:",
            buttons=[
                {"id": "cmd_lang_ar", "title": "🇸🇦 العربية"},
                {"id": "cmd_lang_en", "title": "🇺🇸 English"},
            ],
            header_text="🌐 اللغة",
        )

    elif command == "lang_ar":
        try:
            from memory import set_language
            set_language(wa_user_id, "ar")
            await _send_whatsapp_message(wa_id, "🇸🇦 تم تغيير اللغة للعربية!\n\nمن الآن هرد عليك بالعربي 🤖")
        except Exception:
            await _send_whatsapp_message(wa_id, "🇸🇦 تم تغيير اللغة للعربية!")

    elif command == "lang_en":
        try:
            from memory import set_language
            set_language(wa_user_id, "en")
            await _send_whatsapp_message(wa_id, "🇺🇸 Language changed to English!\n\nI'll respond in English from now on 🤖")
        except Exception:
            await _send_whatsapp_message(wa_id, "🇺🇸 Language changed to English!")

    # ══════════════════════════════════════
    # MEMORY
    # ══════════════════════════════════════

    elif command == "memory":
        # Check if free user — memory is premium
        if not is_admin:
            try:
                from premium import can_use_memory
                if not can_use_memory(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        "⭐ الذاكرة الطويلة مميزة Premium بس!\n\n"
                        "🆓 الخطة المجانية:\n"
                        "• 20 رسالة AI/يوم\n"
                        "• ذاكرة قصيرة المدى فقط\n\n"
                        "⭐ Premium:\n"
                        "• رسائل غير محدودة\n"
                        "• ذاكرة طويلة المدى 🧠\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_interactive_buttons(
            wa_id,
            body_text="🧠 *الذاكرة*\n\nأنا بفتكر المحادثات معاك عشان أرد أحسن!\n\nاختار:",
            buttons=[
                {"id": "cmd_memory_view", "title": "👁️ عرض الذاكرة"},
                {"id": "cmd_memory_reset", "title": "🗑️ مسح الذاكرة"},
                {"id": "cmd_favorites", "title": "⭐ المفضلات"},
            ],
            header_text="🧠 الذاكرة",
        )

    elif command == "memory_view":
        try:
            from memory import get_memories, get_user, get_favorites
            from formatters import clean_ai_response
            
            # Get user profile
            user_data = get_user(wa_user_id) or {}
            user_name = user_data.get("name", "")
            
            # Get memories
            memories = get_memories(wa_user_id)
            
            # Get favorites
            favs = get_favorites(wa_user_id)
            
            # Build structured display
            mem_text = "🧠 *الذاكرة*\n━━━━━━━━━━━━━━━━━\n\n"
            
            if user_name:
                mem_text += f"👤 الاسم: {user_name}\n\n"
            
            if memories:
                mem_text += "📝 *الأشياء اللي فاكرها:*\n"
                for key, value in list(memories.items())[:15]:
                    if key.startswith("pdf_context") or key.startswith("_"):
                        continue
                    val_preview = str(value)[:80]
                    mem_text += f"  • {key}: {val_preview}\n"
                mem_text += "\n"
            
            if favs:
                mem_text += "⭐ *المفضلات:*\n"
                for fav in favs[:10]:
                    fav_text = fav.get("content", "")[:60]
                    mem_text += f"  • {fav_text}\n"
                mem_text += "\n"
            
            if not memories and not favs:
                mem_text += "💭 لسه مفيش ذاكرة محفوظة!\n\nكل ما نتكلم أكتر هبدأ أفكر فيك 🧠\n"
            
            await _send_whatsapp_message(wa_id, mem_text)
        except Exception as e:
            logger.error(f"❌ Memory view error: {e}")
            # Fallback to AI-based memory display
            await _send_ai_response(wa_id, "ماذا تتذكر عني؟ اذكر الأشياء المهمة التي تعرفها عني",
                wa_user_id, contact_name, message_id, context_type="memory")

    elif command == "memory_reset":
        await _send_interactive_buttons(
            wa_id,
            body_text="🗑️ *مسح الذاكرة*\n\nمتأكد إنك عايز تمسح كل اللي فاكره عنك؟\nده مش هيترجع!",
            buttons=[
                {"id": "cmd_memory_reset_confirm", "title": "🗑️ امسح"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ],
        )

    elif command == "memory_reset_confirm":
        try:
            from memory import reset_all_memories
            reset_all_memories(wa_user_id)
            # Also clear PDF context
            _wa_user_pdf_context.pop(wa_user_id, None)
            # ⚡ مسح الكاش عشان السياق يتحدث
            try:
                from memory_context import invalidate_context_cache
                invalidate_context_cache(wa_user_id)
            except Exception:
                pass
            await _send_whatsapp_message(wa_id, "🗑️ تم مسح كل الذاكرة.\n\nهبدأ أعرفك من الأول!")
        except Exception as e:
            logger.error(f"❌ Memory reset error: {e}")
            await _send_whatsapp_message(wa_id, "🗑️ تم مسح الذاكرة.\n\nهبدأ أعرفك من الأول!")

    elif command == "forget":
        # /forget <keyword> — delete specific memory
        # The keyword comes from the message text
        await _send_whatsapp_message(wa_id, 
            "🗑️ *مسح ذاكرة محددة*\n\n"
            "اكتب الكلمة اللي عايز أمسحها من ذاكرتي\n"
            "مثال: /forget الرياضة\n\n"
            "أو اختار:")
        await _send_interactive_buttons(wa_id, body_text="🗑️ عايز تمسح إيه؟",
            buttons=[
                {"id": "cmd_memory_reset", "title": "🗑️ مسح الكل"},
                {"id": "cmd_memory_view", "title": "👁️ عرض الذاكرة"},
                {"id": "cmd_commands", "title": "📋 الأوامر"},
            ])

    elif command == "favorite":
        try:
            from ai_engine import smart_chat
            from formatters import clean_ai_response
            # Get last conversation topic
            # 🔴 لو المستخدم هو الأدمن، نمرر username=ziadamr
            _fav_is_admin = _is_wa_admin(wa_id)
            ai_response = await smart_chat(
                user_message="ما هو آخر موضوع تحدثنا عنه؟ اذكره باختصار",
                language="ar",
                user_id=wa_user_id,
                username="ziadamr" if _fav_is_admin else (contact_name if contact_name != "Unknown" else None),
            )
            ai_response = clean_ai_response(ai_response)
            topic = _strip_html_for_whatsapp(ai_response)[:100]

            from memory import add_favorite
            add_favorite(wa_user_id, "topic", topic)
            await _send_whatsapp_message(wa_id, f"⭐ تم حفظ في المفضلات!\n\n📝 {topic}")
        except Exception as e:
            logger.error(f"❌ Favorite save error: {e}")
            await _send_whatsapp_message(wa_id, "⭐ تم الحفظ في المفضلات!")

    elif command == "favorites":
        try:
            from memory import get_favorites
            favs = get_favorites(wa_user_id)
            if favs:
                fav_text = "⭐ *المفضلات*\n━━━━━━━━━━━━━━━━━\n\n"
                for fav in favs[:10]:
                    fav_text += f"• {fav.get('title', '')}\n"
                await _send_whatsapp_message(wa_id, fav_text)
            else:
                await _send_whatsapp_message(wa_id, "⭐ معندكش مفضلات لسه.\n\n💡 احفظ أي موضوع باستخدام /favorite")
        except Exception as e:
            logger.error(f"❌ Favorites error: {e}")
            await _send_whatsapp_message(wa_id, "⭐ معندكش مفضلات لسه.")

    # ══════════════════════════════════════
    # PREMIUM / PLAN / USAGE
    # ══════════════════════════════════════

    elif command == "premium":
        try:
            from premium import get_user_plan

            if is_admin:
                await _send_whatsapp_message(wa_id,
                    "👑 *أنت الأدمن*\n\n"
                    "⭐ كل حاجة مفتوحة — مفيش Limits!\n"
                    "كل مزايا Premium متاحة ليك تلقائياً.")
                return True

            plan = get_user_plan(wa_user_id)

            if plan in ("premium", "premium_plus"):
                await _send_whatsapp_message(wa_id,
                    "⭐ *أنت مشترك Premium!*\n\n"
                    "كل المزايا مفتوحة ليك:\n"
                    "💬 رسائل غير محدودة\n"
                    "📄 PDF غير محدود\n"
                    "🖼️ صور غير محدودة + Vision Pro\n"
                    "🎬 يوتيوب غير محدود\n"
                    "🔍 بحث غير محدود\n"
                    "🎨 إنشاء وتعديل صور\n"
                    "📚 وضع الدراسة\n"
                    "🧠 ذاكرة طويلة المدى")
                return True

            # Free user — show comparison
            await _send_whatsapp_message(wa_id,
                "🆓 *أنت على الخطة المجانية*\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                "🆓 *المجانية:*\n"
                "• 20 رسالة AI/يوم\n"
                "• 3 تحليلات PDF/يوم\n"
                "• 5 تحليلات صور/يوم\n"
                "• 3 ملخصات يوتيوب/يوم\n"
                "• 5 عمليات بحث/يوم\n\n"
                "⭐ *Premium:*\n"
                "• كل حاجة غير محدودة!\n"
                "• وضع الدراسة 📚\n"
                "• ذاكرة طويلة المدى 🧠\n"
                "• إنشاء وتعديل صور 🎨🖌️\n"
                "• Vision Pro 👁️\n"
                "• نماذج AI أقوى 🤖\n\n"
                f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
        except Exception as e:
            logger.error(f"❌ Premium command error: {e}")
        return True

    elif command == "plan":
        try:
            from premium import get_user_plan, get_usage, PLAN_LIMITS
            plan = get_user_plan(wa_user_id)
            usage = get_usage(wa_user_id)
            limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

            if is_admin:
                plan_text = (
                    "👑 *خطة الأدمن*\n"
                    "━━━━━━━━━━━━━━━━━\n\n"
                    "⭐ كل حاجة غير محدودة!\n"
                    "💬 رسائل: غير محدود\n"
                    "📄 PDF: غير محدود\n"
                    "🖼️ صور: غير محدود\n"
                    "🎬 يوتيوب: غير محدود\n"
                    "🔍 بحث: غير محدود\n"
                    "🎨 إنشاء صور: مفتوح\n"
                    "🖌️ تعديل صور: مفتوح\n"
                    "📚 وضع الدراسة: مفتوح\n"
                    "🧠 ذاكرة طويلة المدى: مفتوح"
                )
            elif plan in ("premium", "premium_plus"):
                plan_text = (
                    "⭐ *خطة Premium*\n"
                    "━━━━━━━━━━━━━━━━━\n\n"
                    "✅ أنت مشترك Premium!\n\n"
                    "💬 رسائل: غير محدود\n"
                    "📄 PDF: غير محدود\n"
                    "🖼️ صور: غير محدود + Vision Pro\n"
                    "🎬 يوتيوب: غير محدود\n"
                    "🔍 بحث: غير محدود\n"
                    "🎨 إنشاء صور: مفتوح\n"
                    "🖌️ تعديل صور: مفتوح\n"
                    "📚 وضع الدراسة: مفتوح\n"
                    "🧠 ذاكرة طويلة المدى: مفتوح"
                )
            else:
                # Free plan — show usage with limits
                ai_rem = max(0, limits["ai_messages_per_day"] - usage.get("ai_messages", 0))
                pdf_rem = max(0, limits["pdf_analyses_per_day"] - usage.get("pdf_analyses", 0))
                img_rem = max(0, limits["image_analyses_per_day"] - usage.get("image_analyses", 0))
                yt_rem = max(0, limits["youtube_summaries_per_day"] - usage.get("youtube_summaries", 0))
                search_rem = max(0, limits["searches_per_day"] - usage.get("searches", 0))

                ai_used = usage.get("ai_messages", 0)
                pdf_used = usage.get("pdf_analyses", 0)
                img_used = usage.get("image_analyses", 0)
                yt_used = usage.get("youtube_summaries", 0)
                search_used = usage.get("searches", 0)

                plan_text = (
                    "🆓 *الخطة المجانية*\n"
                    "━━━━━━━━━━━━━━━━━\n\n"
                    f"💬 رسائل: {ai_used}/{limits['ai_messages_per_day']} (متبقي {ai_rem})\n"
                    f"📄 PDF: {pdf_used}/{limits['pdf_analyses_per_day']} (متبقي {pdf_rem})\n"
                    f"🖼️ صور: {img_used}/{limits['image_analyses_per_day']} (متبقي {img_rem})\n"
                    f"🎬 يوتيوب: {yt_used}/{limits['youtube_summaries_per_day']} (متبقي {yt_rem})\n"
                    f"🔍 بحث: {search_used}/{limits['searches_per_day']} (متبقي {search_rem})\n\n"
                    "🎨 إنشاء صور: ❌ بريميوم\n"
                    "🖌️ تعديل صور: ❌ بريميوم\n"
                    "📚 وضع الدراسة: ❌ بريميوم\n"
                    "🧠 ذاكرة طويلة: ❌ بريميوم\n\n"
                    "💡 الحدود بتتجدد كل يوم الساعة 12:00 منتصف الليل\n\n"
                    "⭐ ترقية لـ Premium عشان استخدام غير محدود!\n"
                    f"📩 تواصل مع المطور:\n📱 {DEVELOPER_WHATSAPP_URL}"
                )

            await _send_whatsapp_message(wa_id, plan_text)
        except Exception as e:
            logger.error(f"❌ Plan command error: {e}")
            await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في عرض الخطة.")

    # ══════════════════════════════════════
    # SETTINGS
    # ══════════════════════════════════════

    elif command == "settings":
        await _send_interactive_list(
            wa_id,
            body_text="⚙️ *الإعدادات*\n\nاختار اللي عايز تغيره:",
            button_text="الإعدادات",
            sections=[{
                "title": "⚙️ الإعدادات",
                "rows": [
                    {"id": "cmd_language", "title": "🌐 اللغة", "description": "عربي أو English"},
                    {"id": "cmd_subscribe", "title": "📬 اشتراك الأخبار", "description": "أخبار يومية"},
                    {"id": "cmd_premium", "title": "⭐ Premium", "description": "خطة ومزايا"},
                    {"id": "cmd_plan", "title": "📋 حدود الاستخدام", "description": "شوف استخدامك"},
                    {"id": "cmd_memory", "title": "🧠 الذاكرة", "description": "عرض ومسح الذاكرة"},
                ],
            }],
            header_text="⚙️ الإعدادات",
        )

    # ══════════════════════════════════════
    # DOWNLOAD
    # ══════════════════════════════════════

    elif command == "download":
        await _send_whatsapp_message(wa_id,
            "📥 *تحميل فيديو*\n\n"
            "ابعتلي رابط الفيديو وهحاول أحملهلك!\n\n"
            "مثال:\n"
            "/download https://youtube.com/watch?v=...\n"
            "أو ابعت الرابط مباشرة وهفهم\n\n"
            "💡 ممكن تحميل من:\n"
            "• YouTube\n"
            "• Twitter/X\n"
            "• Instagram\n"
            "• TikTok")

    # ══════════════════════════════════════
    # VIDEO SEARCH / AUDIO SEARCH / PHOTO SEARCH
    # ══════════════════════════════════════

    elif command == "video_search":
        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "video_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🎬 *تحميل فيديو بالبحث*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك النتائج!\n\n"
            "مثال: اغاني رمضان\n\n"
            "💡 أو استخدم: /video كلمات البحث")
        return True

    elif command == "audio_search":
        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "audio_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🎵 *تحميل صوت بالبحث*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك النتائج!\n\n"
            "مثال: قرآن عبد الباسط\n\n"
            "💡 أو استخدم: /audio كلمات البحث")
        return True

    elif command == "photo_search":
        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "photo_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🖼️ *بحث عن صور*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك صور!\n\n"
            "مثال: محمد صلاح\n\n"
            "💡 أو استخدم: /photo كلمات البحث")
        return True

    # ══════════════════════════════════════
    # STUDY MODE
    # ══════════════════════════════════════

    elif command == "study":
        # Check premium for study mode
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        f"⭐ وضع الدراسة مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_interactive_list(
            wa_id,
            body_text="📚 *وضع الدراسة*\n\nاختار اللي عايزه:",
            button_text="وضع الدراسة",
            sections=[{
                "title": "📚 وضع الدراسة",
                "rows": [
                    {"id": "cmd_study_learn", "title": "📚 ادرس موضوع", "description": "شرح مفصل مع أمثلة"},
                    {"id": "cmd_study_quiz", "title": "📝 كويز", "description": "اختبر نفسك"},
                    {"id": "cmd_study_exam", "title": "📋 امتحان", "description": "امتحان شامل"},
                    {"id": "cmd_study_notes", "title": "📒 ملاحظات مراجعة", "description": "ملخص للمراجعة"},
                    {"id": "cmd_study_flash", "title": "🃏 كروت ذاكرة", "description": "Flashcards"},
                ],
            }],
            header_text="📚 وضع الدراسة",
        )

    elif command == "quiz":
        # Check premium
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, "⭐ الكويز مميزة Premium بس!")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            "📝 *كويز*\n\nاكتب الموضوع اللي عايز تتested فيه\n\nمثال:\n/quiz Python\n/quiz الذكاء الاصطناعي")

    elif command == "exam":
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, "⭐ الامتحان مميز Premium بس!")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            "📋 *امتحان*\n\nاكتب الموضوع اللي عايز تمتحن فيه\n\nمثال:\n/exam Machine Learning\n/exam JavaScript")

    # ══════════════════════════════════════
    # YOUTUBE SUMMARY
    # ══════════════════════════════════════

    elif command == "youtube":
        await _send_whatsapp_message(wa_id,
            "🎬 *ملخص يوتيوب*\n\nابعتلي رابط فيديو يوتيوب وهلخصلك محتواه!\n\nمثال:\n/youtube https://youtube.com/watch?v=...")

    # ══════════════════════════════════════
    # PDF
    # ══════════════════════════════════════

    elif command == "pdf":
        await _send_whatsapp_message(wa_id,
            "📄 *تحليل PDF*\n\nابعتلي ملف PDF (Document) وهحللهلك!\n\n"
            "ممكن أساعدك في:\n"
            "• تلخيص المحتوى\n"
            "• استخراج النقاط الرئيسية\n"
            "• كويز على المحتوى\n"
            "• ملاحظات دراسية\n\n"
            "💡 ابعت الملف مباشرة هنا")

    elif command == "pdf_keypoints":
        # Extract key points from stored PDF context
        pdf_ctx = _wa_user_pdf_context.get(wa_user_id, {})
        if not pdf_ctx:
            # Try loading from DB
            try:
                from memory import get_memories
                mems = get_memories(wa_user_id)
                pdf_text = mems.get("pdf_context_text", "")
                pdf_fn = mems.get("pdf_context_filename", "")
                if pdf_text:
                    pdf_ctx = {"text": pdf_text, "filename": pdf_fn}
                    _wa_user_pdf_context[wa_user_id] = pdf_ctx
            except Exception:
                pass
        
        if not pdf_ctx:
            await _send_whatsapp_message(wa_id, "📄 مفيش ملف محفوظ. ابعت ملف PDF الأول!")
            return True
        
        from agents.pdf_agent import PDFAgent
        pdf_agent = PDFAgent()
        try:
            result = await asyncio.wait_for(
                pdf_agent.key_points(pdf_ctx["text"][:30000], "ar", user_id=wa_user_id),
                timeout=120.0
            )
            from formatters import clean_ai_response
            result = clean_ai_response(result)
            if result:
                response_text = _strip_html_for_whatsapp(result)
                chunks = _split_whatsapp_message(response_text)
                for chunk in chunks:
                    await _send_whatsapp_message(wa_id, chunk)
                
                await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية مع الملف؟",
                    buttons=[
                        {"id": "cmd_study", "title": "📚 ادرسه"},
                        {"id": "cmd_chat", "title": "💬 اسأل سؤال"},
                        {"id": "cmd_commands", "title": "📋 الأوامر"},
                    ])
            else:
                await _send_whatsapp_message(wa_id, "⚠️ مش قادر أستخرج النقاط. جرب تاني!")
        except Exception as e:
            logger.error(f"❌ PDF key points error: {e}")
            await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ. جرب تاني!")
        return True

    elif command == "pdf_ask":
        await _send_whatsapp_message(wa_id, 
            "💬 *اسأل عن الملف*\n\n"
            "اكتب سؤالك عن الملف وانا هجاوبك!\n"
            "مثال: ايه أهم النتائج في الملف ده؟")
        return True

    # ══════════════════════════════════════
    # IMAGE GENERATION (Premium)
    # ══════════════════════════════════════

    elif command == "image_gen":
        if not is_admin:
            try:
                from premium import can_use_image_gen
                if not can_use_image_gen(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        "🎨 إنشاء الصور مميزة Premium بس!\n\n"
                        "⭐ Premium:\n"
                        "• إنشاء صور غير محدود 🎨\n"
                        "• تعديل صور 🖌️\n"
                        "• Vision Pro 👁️\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                # If premium check fails, allow for now
                pass

        await _send_whatsapp_message(wa_id,
            "🎨 *إنشاء صورة*\n\nاكتب وصف الصورة اللي عايزها!\n\n"
            "مثال:\n"
            "/image قطة لطيفة جنب النافذة\n"
            "/image sunset over mountains\n\n"
            "💡 كل ما الوصف يكون أدق، الصورة تكون أحسن!")

    # ══════════════════════════════════════
    # IMAGE EDITING (Premium)
    # ══════════════════════════════════════

    elif command == "image_edit":
        if not is_admin:
            try:
                from premium import can_use_image_edit
                if not can_use_image_edit(wa_user_id):
                    await _send_whatsapp_message(wa_id,
                        f"🖌️ تعديل الصور مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            "🖌️ *تعديل صورة*\n\n"
            "1️⃣ ابعت الصورة اللي عايز تعدلها\n"
            "2️⃣ اكتب التعديل المطلوب في الـ Caption\n\n"
            "مثال: ابعت صورة واكتب في الـ Caption:\n"
            "خلي الخلفية زرقاء")

    # ══════════════════════════════════════
    # ADMIN BUTTON HANDLER
    # ══════════════════════════════════════

    elif command == "admin_button":
        if is_admin:
            await _handle_command(wa_id, "admin", wa_user_id, contact_name, message_id)
        else:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
        return True

    # ── Dynamic AI-powered sub-commands ──
    elif command.startswith("search_") or command in ("cmd_search_ai", "cmd_search_code"):
        search_queries = {
            "cmd_search_ai": "أحدث تطورات الذكاء الاصطناعي",
            "cmd_search_code": "أحدث تقنيات البرمجة وتطوير البرمجيات",
        }
        query = search_queries.get(command, "أحدث التطورات التقنية")
        await _send_ai_response(wa_id, f"ابحث لي عن: {query}",
            wa_user_id, contact_name, message_id, context_type="search", increment_feature="searches")

    elif command.startswith("ask_") or command in ("cmd_ask_ai", "cmd_ask_code"):
        questions = {
            "cmd_ask_ai": "اشرح لي الذكاء الاصطناعي بشكل مبسط مع أمثلة عملية",
            "cmd_ask_code": "ما أهم لغات البرمجة للمبتدئين وكيف أبدأ؟",
        }
        question = questions.get(command, "اشرح لي بالتفصيل")
        await _send_ai_response(wa_id, question,
            wa_user_id, contact_name, message_id, context_type="general")

    elif command.startswith("learn_") or command.startswith("cmd_learn_"):
        topic_map = {
            "cmd_learn_ai": "الذكاء الاصطناعي",
            "cmd_learn_ml": "تعلم الآلة Machine Learning",
            "cmd_learn_dl": "التعلم العميق Deep Learning",
            "cmd_learn_nlp": "معالجة اللغة الطبيعية NLP",
            "cmd_learn_llm": "النماذج اللغوية الكبيرة LLMs",
            "cmd_learn_python": "برمجة بايثون Python",
            "cmd_learn_web": "تطوير الويب Web Development",
        }
        topic = topic_map.get(command, "الذكاء الاصطناعي")
        await _send_ai_response(wa_id,
            f"علمني عن {topic} من الصفر للمحترف. ابدأ بالأساسيات وشرح مبسط مع أمثلة عملية",
            wa_user_id, contact_name, message_id, context_type="learn")

    elif command.startswith("roadmap_") or command.startswith("cmd_roadmap_"):
        roadmap_map = {
            "cmd_roadmap_ai": "الذكاء الاصطناعي AI",
            "cmd_roadmap_ml": "تعلم الآلة Machine Learning",
            "cmd_roadmap_dl": "التعلم العميق Deep Learning",
            "cmd_roadmap_nlp": "معالجة اللغة الطبيعية NLP",
            "cmd_roadmap_llm": "النماذج اللغوية الكبيرة LLMs",
        }
        topic = roadmap_map.get(command, "الذكاء الاصطناعي")
        await _send_ai_response(wa_id,
            f"ارسم لي خريطة طريق تعلم {topic} من الصفر للمحترف. قسمها لمراحل (مبتدئ - متوسط - متقدم) مع المصادر والخطوات العملية",
            wa_user_id, contact_name, message_id, context_type="learn")

    elif command.startswith("company_") or command.startswith("cmd_company_"):
        company_map = {
            "cmd_company_openai": "OpenAI",
            "cmd_company_google": "Google AI",
            "cmd_company_anthropic": "Anthropic",
            "cmd_company_meta": "Meta AI",
            "cmd_company_xai": "xAI",
            "cmd_company_nvidia": "NVIDIA",
        }
        company = company_map.get(command, "AI")
        await _send_ai_response(wa_id,
            f"ما هي آخر أخبار وتطورات شركة {company}؟ اذكر أهم المنتجات والاعلانات والمشاريع",
            wa_user_id, contact_name, message_id, context_type="news")

    elif command.startswith("study_") or command.startswith("cmd_study_"):
        study_map = {
            "cmd_study_learn": "علمني",
            "cmd_study_quiz": "اعملني كويز",
            "cmd_study_exam": "اعملني امتحان شامل",
            "cmd_study_notes": "اعملني ملاحظات مراجعة مختصرة",
            "cmd_study_flash": "اعملني كروت ذاكرة Flashcards",
        }
        study_action = study_map.get(command, "علمني")
        # Check premium
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, f"⭐ وضع الدراسة مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        await _send_whatsapp_message(wa_id,
            f"📚 {study_action}\n\nاكتب الموضوع اللي عايز {study_action} فيه\n\nمثال: {study_action} Python")

    else:
        return False  # Not a command

    return True  # Command was handled


# ═══════════════════════════════════════
# GET / — Root Handler
# ═══════════════════════════════════════

async def root_handler(request: web.Request):
    """Root path — redirect to health check or show basic info"""
    return web.json_response({
        "service": "My Bro — WhatsApp & Telegram AI Bot",
        "version": "4.0",
        "endpoints": {
            "webhook_verification": "GET /whatsapp/webhook",
            "webhook_messages": "POST /whatsapp/webhook",
            "health": "GET /health",
            "diagnostics": "GET /debug/whatsapp",
            "activity_log": "GET /debug/whatsapp/activity",
        },
        "status": "running",
    })


# ═══════════════════════════════════════
# GET /whatsapp/webhook — Meta Verification
# ═══════════════════════════════════════

async def webhook_verification(request: web.Request):
    """Meta verification endpoint."""
    mode = request.query.get("hub.mode", "")
    token = request.query.get("hub.verify_token", "")
    challenge = request.query.get("hub.challenge", "")

    _log_event("IN", "verification_attempt", {
        "mode": mode,
        "token_provided": bool(token),
        "challenge_provided": bool(challenge),
    })

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully!")
        _log_event("OUT", "verification_success", {"challenge": challenge})
        return web.Response(text=challenge, status=200)

    logger.warning(f"❌ WhatsApp webhook verification failed!")
    _log_event("OUT", "verification_failed", {"mode": mode})
    return web.Response(text="Forbidden", status=403)


# ═══════════════════════════════════════
# POST /whatsapp/webhook — Incoming Messages
# ═══════════════════════════════════════

async def webhook_receiver(request: web.Request):
    """Receive incoming WhatsApp messages and status updates."""
    try:
        payload = await request.read()

        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(payload, signature):
            logger.warning(f"❌ Invalid webhook signature")
            _log_activity("signature_failed", {"signature_present": bool(signature), "app_secret_set": bool(WHATSAPP_APP_SECRET)}, "failed")
            return web.Response(text="Unauthorized", status=401)

        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            return web.Response(text="Bad Request", status=400)

        has_messages = False
        has_statuses = False
        try:
            has_messages = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages"))
            has_statuses = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"))
        except (IndexError, KeyError, TypeError):
            pass

        _log_event("IN", "webhook_event", {
            "keys": list(body.keys()),
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
        })

        _log_activity("webhook_post", {
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
            "payload_size": len(payload),
        }, "received")

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    messages = value.get("messages", [])
                    if messages:
                        for message in messages:
                            asyncio.create_task(_handle_incoming_message(message, value))

                    statuses = value.get("statuses", [])
                    if statuses:
                        for status in statuses:
                            _log_event("IN", "status_update", {
                                "message_id": status.get("id"),
                                "status": status.get("status"),
                                "timestamp": status.get("timestamp"),
                                "recipient_id": status.get("recipient_id"),
                            })

                    errors = value.get("errors", [])
                    if errors:
                        for error in errors:
                            logger.error(f"❌ WhatsApp API Error: {error}")
                            _log_event("IN", "api_error", error)
        else:
            logger.warning(f"⚠️ Unknown webhook object type: {body.get('object')}")

        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)
        return web.Response(text="OK", status=200)


def process_webhook_body(body: dict):
    """Synchronous entry point for processing WhatsApp webhook bodies.
    
    Called from bot.py's simple HTTP server when a POST /whatsapp/webhook
    is received. Processes the webhook body synchronously using the same
    logic as webhook_receiver but without the aiohttp request/response.
    
    Note: This skips signature verification since the simple HTTP server
    handles that separately. The WhatsApp webhook aiohttp server (if running)
    still does full signature verification.
    """
    try:
        has_messages = False
        has_statuses = False
        try:
            has_messages = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages"))
            has_statuses = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"))
        except (IndexError, KeyError, TypeError):
            pass

        _log_event("IN", "webhook_event_simple", {
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
        })

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    messages = value.get("messages", [])
                    if messages:
                        for message in messages:
                            # Schedule the async handler to run in the existing event loop
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.ensure_future(_handle_incoming_message(message, value), loop=loop)
                                else:
                                    loop.run_until_complete(_handle_incoming_message(message, value))
                            except RuntimeError:
                                # No event loop — create a new one
                                asyncio.run(_handle_incoming_message(message, value))

                    statuses = value.get("statuses", [])
                    if statuses:
                        for status in statuses:
                            _log_event("IN", "status_update", {
                                "message_id": status.get("id"),
                                "status": status.get("status"),
                                "timestamp": status.get("timestamp"),
                                "recipient_id": status.get("recipient_id"),
                            })

                    errors = value.get("errors", [])
                    if errors:
                        for error in errors:
                            logger.error(f"❌ WhatsApp API Error: {error}")
                            _log_event("IN", "api_error", error)
    except Exception as e:
        logger.error(f"❌ process_webhook_body error: {e}", exc_info=True)


# ═══════════════════════════════════════
# Message Handler — Full AI Integration
# ═══════════════════════════════════════

async def _handle_incoming_message(message: dict, value: dict):
    """Process an incoming WhatsApp message with full feature set."""
    try:
        wa_id = message.get("from", "")
        message_type = message.get("type", "")
        message_id = message.get("id", "")
        timestamp = message.get("timestamp", "")

        # Deduplication
        if _is_duplicate_wa_message(message_id):
            logger.debug(f"⏭️ Duplicate WA message {message_id} — skipping")
            return

        # Security: Check allowed numbers
        if ALLOWED_WA_NUMBERS and wa_id not in ALLOWED_WA_NUMBERS:
            logger.warning(f"🚫 WA message from unauthorized number: {wa_id}")
            return

        # Mark message as read
        asyncio.create_task(_mark_message_read(message_id))

        # Contact info
        contacts = value.get("contacts", [])
        contact_name = ""
        if contacts:
            contact_name = contacts[0].get("profile", {}).get("name", "Unknown")

        # Generate user ID
        wa_user_id = -abs(hash(f"wa_{wa_id}")) % (2**31)
        is_admin = _is_wa_admin(wa_id)

        # Ensure admin is premium
        if is_admin:
            _ensure_wa_admin_premium(wa_id)

        # Check if user is banned (skip for admin)
        if not is_admin:
            try:
                from memory import _execute, _is_postgres
                ph = "%s" if _is_postgres() else "?"
                banned = _execute(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (wa_user_id,), fetchone=True)
                if banned:
                    await _send_whatsapp_message(wa_id, f"🚫 تم حظر حسابك. لو عندك استفسار تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return
            except Exception:
                pass

        # Ensure user exists in DB
        try:
            from memory import _ensure_user_in_db
            _ensure_user_in_db(wa_user_id, platform="whatsapp")
            # Save name from WhatsApp profile
            if contact_name and contact_name != "Unknown":
                try:
                    from memory import update_user
                    update_user(wa_user_id, {"name": contact_name})
                except Exception:
                    pass
        except Exception:
            pass

        # Extract message content
        content = ""
        is_audio = False
        is_image = False
        is_document = False
        image_media_id = ""
        audio_media_id = ""
        document_media_id = ""
        interactive_id = ""

        if message_type == "text":
            content = message.get("text", {}).get("body", "")
        elif message_type == "audio":
            audio_media_id = message.get("audio", {}).get("id", "")
            is_audio = True
            content = "[Audio message]"
        elif message_type == "image":
            image_media_id = message.get("image", {}).get("id", "")
            caption = message.get("image", {}).get("caption", "")
            is_image = True
            content = caption if caption else "[Image]"
        elif message_type == "video":
            content = message.get("video", {}).get("caption", "[Video]")
        elif message_type == "document":
            document_media_id = message.get("document", {}).get("id", "")
            is_document = True
            content = message.get("document", {}).get("caption", "[Document]")
        elif message_type == "location":
            loc = message.get("location", {})
            content = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type", "")
            if interactive_type == "button_reply":
                button_reply = interactive.get("button_reply", {})
                content = button_reply.get("title", "[Button]")
                interactive_id = button_reply.get("id", "")
            elif interactive_type == "list_reply":
                list_reply = interactive.get("list_reply", {})
                content = list_reply.get("title", "[List Item]")
                interactive_id = list_reply.get("id", "")
        elif message_type == "reaction":
            emoji = message.get("reaction", {}).get("emoji", "")
            content = f"[Reaction: {emoji}]"
        elif message_type == "sticker":
            content = "[Sticker]"
        elif message_type == "contacts":
            content = "[Contacts]"
        elif message_type == "order":
            content = "[Order]"
        else:
            content = f"[{message_type}]"

        _log_event("IN", "message", {
            "from": wa_id,
            "contact_name": contact_name,
            "type": message_type,
            "content": content[:200],
            "message_id": message_id,
            "interactive_id": interactive_id,
        })

        logger.info(f"📩 WA Message from {contact_name} ({wa_id}): {content[:100]}")

        # Skip non-processable types
        if message_type in ("reaction", "sticker", "contacts", "order", "location"):
            return

        # ═══ الأولوية الأولى: Workflow النشط ═══
        # لو المستخدم في وسط عملية تفاعلية (بحث صور، تعديل صورة، الخ)
        # الرسالة بتروح للخدمة المسؤولة مش للذكاء الاصطناعي
        active_state = _get_user_state(wa_id)
        if active_state and message_type == "text" and content.strip():
            flow = active_state.get("flow", "")
            state_data = active_state.get("data", {})
            
            # 🔴 لو المستخدم عايز يلغي — أي كلمة إلغاء
            cancel_words = ["إلغاء", "الغاء", "cancel", "خلاص", "لا", "ابقى لا", "امسح"]
            if content.strip().lower() in cancel_words:
                _clear_user_state(wa_id)
                await _send_whatsapp_message(wa_id, "✅ تم إلغاء العملية.")
                return
            
            if flow == "photo_search":
                # المستخدم بيرد على "كم صورة تريد؟"
                query = state_data.get("query", "")
                cache_key = state_data.get("cache_key", "")
                # محاولة استخراج رقم من الرسالة
                import re as _re_num
                num_match = _re_num.search(r'\d+', content.strip())
                if num_match:
                    count = int(num_match.group())
                    # أقصى 20 صورة
                    count = min(count, 20)
                    if count < 1:
                        count = 3
                    logger.info(f"📸 Photo search workflow: user wants {count} images for '{query}'")
                    _clear_user_state(wa_id)
                    # كمل البحث بالعدد المحدد
                    await _execute_photo_search(wa_id, query, count, wa_user_id, contact_name, message_id, is_admin, cache_key)
                    return
                else:
                    # مش رقم — ممكن المستخدم كتب حاجة تانية
                    await _send_whatsapp_message(wa_id, "📝 اكتب رقم (مثلاً: 3 أو 5 أو 10) أو اضغط إلغاء.")
                    return
            
            elif flow == "image_edit":
                # المستخدم بيرد بوصف التعديل بعد ما بعت صورة
                cached_image = _wa_user_edit_images.get(wa_user_id, {})
                if cached_image and cached_image.get("image_base64"):
                    edit_prompt = content.strip()
                    logger.info(f"🖌️ Image edit workflow: user says '{edit_prompt[:50]}'")
                    _clear_user_state(wa_id)
                    # كمل تعديل الصورة
                    await _edit_and_send_image(wa_id, cached_image["image_base64"], edit_prompt, wa_user_id, contact_name, message_id, is_admin)
                    return
                else:
                    _clear_user_state(wa_id)
                    await _send_whatsapp_message(wa_id, "⚠️ الصورة انتهت صلاحيتها. ابعت صورة تانية وحاول تاني.")
                    return
            
            elif flow == "video_search":
                # المستخدم يكتب رقم الفيديو من النتائج
                cache_key = state_data.get("cache_key", "")
                cached = _wa_search_cache.get(cache_key)
                if cached and cached.get("results"):
                    num_match = __import__('re').search(r'\d+', content.strip())
                    if num_match:
                        idx = int(num_match.group()) - 1  # المستخدم بيكتب 1-5 ونحوله لـ 0-4
                        if 0 <= idx < len(cached["results"]):
                            r = cached["results"][idx]
                            logger.info(f"🎬 Video search workflow: user selected #{idx+1}")
                            _clear_user_state(wa_id)
                            await _send_whatsapp_message(wa_id, f"🎬 جاري تحميل الفيديو...\n\n📺 {r['title']}")
                            await _wa_download_youtube(wa_id, r['url'], wa_user_id, contact_name, message_id, is_admin, format="720")
                            return
                    # مش رقم صحيح
                    await _send_whatsapp_message(wa_id, "📝 اكتب رقم الفيديو (1-5) من القائمة أو اضغط إلغاء.")
                    return
                else:
                    _clear_user_state(wa_id)
                    await _send_whatsapp_message(wa_id, "❌ انتهت صلاحية النتائج! ابحث تاني.")
                    return
            
            elif flow == "audio_search":
                # نفس video_search بس صوت
                cache_key = state_data.get("cache_key", "")
                cached = _wa_search_cache.get(cache_key)
                if cached and cached.get("results"):
                    num_match = __import__('re').search(r'\d+', content.strip())
                    if num_match:
                        idx = int(num_match.group()) - 1
                        if 0 <= idx < len(cached["results"]):
                            r = cached["results"][idx]
                            logger.info(f"🎵 Audio search workflow: user selected #{idx+1}")
                            _clear_user_state(wa_id)
                            await _send_whatsapp_message(wa_id, f"🎵 جاري تحميل الصوت...\n\n📺 {r['title']}")
                            await _wa_download_youtube(wa_id, r['url'], wa_user_id, contact_name, message_id, is_admin, format="mp3")
                            return
                    await _send_whatsapp_message(wa_id, "📝 اكتب رقم الصوت (1-5) من القائمة أو اضغط إلغاء.")
                    return
                else:
                    _clear_user_state(wa_id)
                    await _send_whatsapp_message(wa_id, "❌ انتهت صلاحية النتائج! ابحث تاني.")
                    return
            
            elif flow == "video_search_query":
                # المستخدم كتب كلمات البحث بعد ما ضغط "فيديو بالبحث"
                query = content.strip()
                logger.info(f"🎬 Video search query workflow: user typed '{query[:50]}'")
                _clear_user_state(wa_id)
                await _handle_wa_video_search(wa_id, query, wa_user_id, contact_name, message_id, is_admin)
                # حفظ حالة انتظار اختيار الفيديو
                cache_key = hashlib.md5(f"wa_vs_{wa_id}_{query}".encode()).hexdigest()[:12]
                _set_user_state(wa_id, "video_search", {"cache_key": cache_key})
                return
            
            elif flow == "audio_search_query":
                # المستخدم كتب كلمات البحث بعد ما ضغط "صوت بالبحث"
                query = content.strip()
                logger.info(f"🎵 Audio search query workflow: user typed '{query[:50]}'")
                _clear_user_state(wa_id)
                await _handle_wa_audio_search(wa_id, query, wa_user_id, contact_name, message_id, is_admin)
                # حفظ حالة انتظار اختيار الصوت
                cache_key = hashlib.md5(f"wa_as_{wa_id}_{query}".encode()).hexdigest()[:12]
                _set_user_state(wa_id, "audio_search", {"cache_key": cache_key})
                return
            
            elif flow == "photo_search_query":
                # المستخدم كتب كلمات البحث بعد ما ضغط "بحث صور"
                query = content.strip()
                logger.info(f"🖼️ Photo search query workflow: user typed '{query[:50]}'")
                _clear_user_state(wa_id)
                # نوجهه لـ photo search اللي هيبدأ الـ workflow
                await _handle_command_with_arg(wa_id, "photo_search_query", query, wa_user_id, contact_name, message_id, is_admin)
                return

        # ═══ Handle Interactive Button/List Replies ═══
        if interactive_id:
            # Check for download quality selections first (dl_v_b_KEY, dl_v_m_KEY, etc.)
            if interactive_id.startswith("dl_"):
                quality_map = {
                    "dl_v_b_": "best",
                    "dl_v_m_": "medium",
                    "dl_v_l_": "low",
                    "dl_a_": "audio",
                }
                for prefix, q in quality_map.items():
                    if interactive_id.startswith(prefix):
                        url_key = interactive_id[len(prefix):]
                        cached_url = _get_url(url_key)
                        if cached_url:
                            logger.info(f"📥 Quality selection: {q} for URL key {url_key}")
                            # 🔴 YouTube: استخدم RapidAPI بدل yt-dlp
                            from youtube_rapidapi import is_youtube_url as _is_yt_url
                            if _is_yt_url(cached_url):
                                # تحويل الجودة لفورمات RapidAPI
                                yt_format_map = {
                                    "best": "1080",
                                    "medium": "720",
                                    "low": "360",
                                    "audio": "mp3",
                                }
                                yt_format = yt_format_map.get(q, "720")
                                logger.info(f"🎬 YouTube URL detected → RapidAPI format={yt_format}")
                                await _wa_download_youtube(wa_id, cached_url, wa_user_id, contact_name, message_id, is_admin, format=yt_format)
                            else:
                                # مش يوتيوب — yt-dlp عادي
                                await _download_and_send_video(wa_id, cached_url, wa_user_id, contact_name, message_id, is_admin, quality=q)
                        else:
                            await _send_whatsapp_message(wa_id, "⚠️ انتهت صلاحية الرابط. ابعت الرابط تاني! 📥")
                        return
                # Unknown dl_ prefix
                await _send_whatsapp_message(wa_id, "⚠️ اختيار مش معروف. جرب تاني! 📥")
                return
            
            command_map = {
                # Main features
                "cmd_chat": "chat",
                "cmd_commands": "commands",
                "cmd_news": "news",
                "cmd_more_news": "news",
                "cmd_about": "about",
                "cmd_admin": "admin",
                # News
                "cmd_breaking": "breaking",
                "cmd_weekly": "weekly",
                "cmd_trending": "trending",
                # AI
                "cmd_ask": "ask",
                "cmd_ask_ai": "cmd_ask_ai",
                "cmd_ask_code": "cmd_ask_code",
                "cmd_search": "search",
                "cmd_search_ai": "cmd_search_ai",
                "cmd_search_code": "cmd_search_code",
                "cmd_learn": "learn",
                "cmd_learn_ai": "cmd_learn_ai",
                "cmd_learn_ml": "cmd_learn_ml",
                "cmd_learn_dl": "cmd_learn_dl",
                "cmd_learn_nlp": "cmd_learn_nlp",
                "cmd_learn_llm": "cmd_learn_llm",
                "cmd_learn_python": "cmd_learn_python",
                "cmd_learn_web": "cmd_learn_web",
                "cmd_roadmap": "roadmap",
                "cmd_roadmap_ai": "cmd_roadmap_ai",
                "cmd_roadmap_ml": "cmd_roadmap_ml",
                "cmd_roadmap_dl": "cmd_roadmap_dl",
                "cmd_roadmap_nlp": "cmd_roadmap_nlp",
                "cmd_roadmap_llm": "cmd_roadmap_llm",
                # Company
                "cmd_company": "company",
                "cmd_company_openai": "cmd_company_openai",
                "cmd_company_google": "cmd_company_google",
                "cmd_company_anthropic": "cmd_company_anthropic",
                "cmd_company_meta": "cmd_company_meta",
                "cmd_company_xai": "cmd_company_xai",
                "cmd_company_nvidia": "cmd_company_nvidia",
                # Settings
                "cmd_subscribe": "subscribe",
                "cmd_subscribe_confirm": "subscribe_confirm",
                "cmd_unsubscribe_confirm": "unsubscribe_confirm",
                "cmd_language": "language",
                "cmd_lang_ar": "lang_ar",
                "cmd_lang_en": "lang_en",
                "cmd_settings": "settings",
                # Memory
                "cmd_memory": "memory",
                "cmd_memory_view": "memory_view",
                "cmd_memory_reset": "memory_reset",
                "cmd_memory_reset_confirm": "memory_reset_confirm",
                "cmd_forget": "forget",
                # Premium / Plan
                "cmd_premium": "premium",
                "cmd_plan": "plan",
                # Favorites
                "cmd_favorite": "favorite",
                "cmd_favorites": "favorites",
                # Download
                "cmd_download": "download",
                # Study
                "cmd_study": "study",
                "cmd_study_learn": "cmd_study_learn",
                "cmd_study_quiz": "cmd_study_quiz",
                "cmd_study_exam": "cmd_study_exam",
                "cmd_study_notes": "cmd_study_notes",
                "cmd_study_flash": "cmd_study_flash",
                # YouTube
                "cmd_youtube": "youtube",
                # PDF
                "cmd_pdf": "pdf",
                "cmd_pdf_keypoints": "pdf_keypoints",
                "cmd_pdf_ask": "pdf_ask",
                # Image gen/edit
                "cmd_image_gen": "image_gen",
                "cmd_image_edit": "image_edit",
                # 🔴 إصلاح: أضفنا أزرار البحث اللي كانت مكسورة
                "video_search": "video_search",
                "audio_search": "audio_search",
                "photo_search": "photo_search",
            }
            cmd = command_map.get(interactive_id)
            if cmd:
                await _handle_command(wa_id, cmd, wa_user_id, contact_name, message_id)
                return
            
            # 🔍 Handle search callbacks (video/audio/photo selections)
            if interactive_id.startswith("wa_vs_") or interactive_id.startswith("wa_as_") or interactive_id.startswith("wa_ph_"):
                await _handle_wa_search_callback(wa_id, interactive_id, wa_user_id, contact_name, message_id, is_admin)
                return

        # ═══ Handle Text Commands ═══
        if message_type == "text" and content.strip():
            content_lower = content.strip().lower()

            # Check for admin commands with arguments (e.g., /grant 123456789)
            if is_admin:
                admin_arg_commands = ["/grant", "/revoke", "/resetlimit", "/ban", "/unban", "/userinfo", "/broadcast"]
                for admin_cmd in admin_arg_commands:
                    if content_lower.startswith(admin_cmd + " ") or content_lower == admin_cmd:
                        await _handle_admin_with_args(wa_id, content.strip(), wa_user_id, contact_name)
                        return True

            # Check for prefix commands with arguments (e.g., /download URL, /study topic)
            prefix_commands = {
                "/download": "download",
                "/image": "image_gen",
                "/edit": "image_edit",
                "/youtube": "youtube",
                "/quiz": "quiz",
                "/exam": "exam",
                "/study": "study",
                "/search": "search",
                "/video": "video_search_query",
                "/audio": "audio_search_query",
                "/photo": "photo_search_query",
            }
            for prefix, cmd_name in prefix_commands.items():
                if content_lower.startswith(prefix + " "):
                    arg = content.strip()[len(prefix):].strip()
                    if arg:
                        await _handle_command_with_arg(wa_id, cmd_name, arg, wa_user_id, contact_name, message_id, is_admin)
                        return

            # Arabic prefix commands
            arabic_prefix_map = {
                "تحميل": "download",
                "صورة": "image_gen",
                "عدل صورة": "image_edit",
                "يوتيوب": "youtube",
                "كويز": "quiz",
                "امتحان": "exam",
                "دراسة": "study",
                "بحث": "search",
                "فيديو بالبحث": "video_search_query",
                "فيديو بحث": "video_search_query",
                "صوت بالبحث": "audio_search_query",
                "صوت بحث": "audio_search_query",
                "بحث صور": "photo_search_query",
            }
            for arabic_prefix, cmd_name in arabic_prefix_map.items():
                if content_lower.startswith(arabic_prefix):
                    arg = content.strip()[len(arabic_prefix):].strip()
                    if arg:
                        await _handle_command_with_arg(wa_id, cmd_name, arg, wa_user_id, contact_name, message_id, is_admin)
                        return

            # Check for simple command trigger
            command = _COMMAND_TRIGGERS.get(content_lower)
            if command:
                handled = await _handle_command(wa_id, command, wa_user_id, contact_name, message_id)
                if handled:
                    return

            # ═══ PDF Follow-up Q&A ═══
            # If user has a PDF context and asks a question, answer based on the PDF
            if not command:  # Not a recognized command
                pdf_ctx = _wa_user_pdf_context.get(wa_user_id, {})
                if not pdf_ctx:
                    # Try loading from DB
                    try:
                        from memory import get_memories
                        mems = get_memories(wa_user_id)
                        pdf_text = mems.get("pdf_context_text", "")
                        pdf_fn = mems.get("pdf_context_filename", "")
                        if pdf_text:
                            pdf_ctx = {"text": pdf_text, "filename": pdf_fn}
                            _wa_user_pdf_context[wa_user_id] = pdf_ctx
                    except Exception:
                        pass
                
                if pdf_ctx and len(content.strip()) > 3:
                    # Check if it looks like a question about the document
                    question_indicators = ["ايه", "إيه", "ازاي", "إزاي", "ليه", "ليه", "هل", "كام", "فين", "مين", "ان", "أن", "what", "how", "why", "when", "where", "who", "is", "are", "can", "?", "؟"]
                    is_question = any(content.strip().lower().startswith(q) for q in question_indicators) or "؟" in content or "?" in content
                    
                    if is_question:
                        from ai_engine import smart_chat
                        from formatters import clean_ai_response
                        
                        # Start thinking feedback for PDF Q&A (uses document threshold)
                        feedback = ThinkingFeedback(wa_id, message_id, context_type="document")
                        await feedback.start()
                        
                        pdf_question_prompt = f"""بناءً على المستند ده ({pdf_ctx.get('filename', 'PDF')}), جاوب على السؤال:

المحتوى:
{pdf_ctx['text'][:15000]}

السؤال: {content}"""
                        
                        # 🔴 لو المستخدم هو الأدمن، نمرر username=ziadamr
                        _pdf_is_admin = _is_wa_admin(wa_id)
                        ai_response = await smart_chat(
                            user_message=pdf_question_prompt,
                            language="ar",
                            user_id=wa_user_id,
                            username="ziadamr" if _pdf_is_admin else (contact_name if contact_name != "Unknown" else None),
                        )
                        ai_response = clean_ai_response(ai_response)
                        wa_response = _strip_html_for_whatsapp(ai_response)
                        chunks = _split_whatsapp_message(wa_response)
                        for chunk in chunks:
                            await _send_whatsapp_message(wa_id, chunk)
                        
                        await feedback.complete()
                        
                        await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية مع الملف؟",
                            buttons=[
                                {"id": "cmd_pdf_keypoints", "title": "🔑 نقاط رئيسية"},
                                {"id": "cmd_study", "title": "📚 ادرسه"},
                                {"id": "cmd_commands", "title": "📋 الأوامر"},
                            ])
                        return

        # ═══ Process Audio Messages ═══
        if is_audio and audio_media_id:
            try:
                # Start thinking feedback for voice
                feedback = ThinkingFeedback(wa_id, message_id, context_type="voice")
                await feedback.start()

                audio_content = await _transcribe_audio(audio_media_id, wa_user_id=wa_user_id)
                if audio_content:
                    content = audio_content
                    logger.info(f"🎤 Audio transcribed from {wa_id}: {content[:80]}")
                    await feedback.complete()
                else:
                    await _send_whatsapp_message(wa_id, "⚠️ مش قادر أفهم الصوت ده. جرب تبعت رسالة نصية! 🎤")
                    await feedback.error()
                    return
            except Exception as e:
                logger.error(f"❌ Audio transcription error: {e}")
                await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في تحويل الصوت لنص. جرب تاني! 🎤")
                await feedback.error()
                return

        # ═══ Process Image Messages ═══
        if is_image and image_media_id:
            try:
                # Start thinking feedback for image analysis
                feedback = ThinkingFeedback(wa_id, message_id, context_type="image")
                await feedback.start()

                # Check premium for image analysis
                if not is_admin:
                    try:
                        from premium import check_limit
                        limit_check = check_limit(wa_user_id, "image_analyses_per_day")
                        if not limit_check.get("allowed", True):
                            await _send_whatsapp_message(wa_id, "⚠️ وصلت حد تحليل الصور اليومي!\n⭐ ترقية لـ Premium عشان استخدام غير محدود!")
                            await feedback.error()
                            return
                    except Exception:
                        pass

                image_description = await _analyze_image(image_media_id, content, wa_user_id=wa_user_id)
                
                # Cache the image for later /edit (like Telegram caches photos)
                try:
                    cached_img_b64 = await _download_wa_media_base64(image_media_id)
                    if cached_img_b64:
                        _wa_user_edit_images[wa_user_id] = {
                            "image_base64": cached_img_b64,
                            "created_at": time.time(),
                        }
                        # Clean old entries (older than 1 hour)
                        expired_users = [uid for uid, data in _wa_user_edit_images.items() 
                                        if time.time() - data.get("created_at", 0) > 3600]
                        for uid in expired_users:
                            del _wa_user_edit_images[uid]
                except Exception as e:
                    logger.debug(f"Could not cache image for editing: {e}")
                
                if image_description:
                    response_text = _strip_html_for_whatsapp(image_description)
                    chunks = _split_whatsapp_message(response_text)
                    for chunk in chunks:
                        await _send_whatsapp_message(wa_id, chunk)

                    # Increment usage
                    if not is_admin:
                        try:
                            from premium import increment_usage
                            increment_usage(wa_user_id, "image_analyses")
                        except Exception:
                            pass

                    # Detect interests from image (same as Telegram)
                    try:
                        from memory import detect_interests
                        detect_interests(wa_user_id, f"[صورة] {image_description[:200]}", "ar")
                    except Exception:
                        pass

                    await feedback.complete()

                    # Quick action buttons
                    await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                        buttons=[
                            {"id": "cmd_chat", "title": "💬 اسأل عنها"},
                            {"id": "cmd_image_edit", "title": "🖌️ عدّلها"},
                            {"id": "cmd_commands", "title": "📋 الأوامر"},
                        ])
                    
                    # 🔴 حفظ حالة المستخدم — لو كتب وصف تعديل يروح للخدمة مش AI
                    _set_user_state(wa_id, "image_edit", {"step": "awaiting_edit_prompt"})
                else:
                    await _send_whatsapp_message(wa_id, "⚠️ مش قادر أحلل الصورة دي. جرب صورة تانية! 👁️")
                    await feedback.error()
                return
            except Exception as e:
                logger.error(f"❌ Image analysis error: {e}")
                await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في تحليل الصورة. جرب تاني! 👁️")
                try:
                    await feedback.error()
                except Exception:
                    pass
                return

        # ═══ Process Document (PDF) ═══
        if is_document and document_media_id:
            try:
                # Start thinking feedback for document analysis (10s threshold)
                feedback = ThinkingFeedback(wa_id, message_id, context_type="document")
                await feedback.start()

                # Check premium for PDF
                if not is_admin:
                    try:
                        from premium import check_limit
                        limit_check = check_limit(wa_user_id, "pdf_analyses_per_day")
                        if not limit_check.get("allowed", True):
                            await _send_whatsapp_message(wa_id, "⚠️ وصلت حد تحليل PDF اليومي!\n⭐ ترقية لـ Premium!")
                            await feedback.error()
                            return
                    except Exception:
                        pass

                pdf_result = await _analyze_document(document_media_id, content, wa_user_id=wa_user_id)
                if pdf_result:
                    response_text = _strip_html_for_whatsapp(pdf_result)
                    chunks = _split_whatsapp_message(response_text)
                    for chunk in chunks:
                        await _send_whatsapp_message(wa_id, chunk)

                    # Increment usage
                    if not is_admin:
                        try:
                            from premium import increment_usage
                            increment_usage(wa_user_id, "pdf_analyses")
                        except Exception:
                            pass

                    # Detect interests from document (same as Telegram)
                    try:
                        from memory import detect_interests, save_conversation
                        detect_interests(wa_user_id, f"[PDF: {content[:100]}]", "ar")
                        save_conversation(wa_user_id, "user", f"[PDF: {content[:50]}]", platform="whatsapp")
                    except Exception:
                        pass

                    await feedback.complete()

                    # PDF interactive buttons (same as Telegram)
                    pdf_filename = ""
                    pdf_ctx = _wa_user_pdf_context.get(wa_user_id, {})
                    if pdf_ctx:
                        pdf_filename = pdf_ctx.get("filename", "")
                    
                    pdf_body = "عايز حاجة تانية مع الملف ده؟"
                    if pdf_filename:
                        pdf_body = f"📄 {pdf_filename}\n\nعايز حاجة تانية؟"
                    
                    await _send_interactive_buttons(wa_id, body_text=pdf_body,
                        buttons=[
                            {"id": "cmd_pdf_keypoints", "title": "🔑 نقاط رئيسية"},
                            {"id": "cmd_study", "title": "📚 ادرسه"},
                            {"id": "cmd_chat", "title": "💬 اسأل عنه"},
                        ])
                else:
                    await _send_whatsapp_message(wa_id, "⚠️ مش قادر أحلل الملف ده. جرب تاني! 📄")
                    await feedback.error()
                return
            except Exception as e:
                logger.error(f"❌ Document analysis error: {e}")
                await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ في تحليل الملف. جرب تاني! 📄")
                try:
                    await feedback.error()
                except Exception:
                    pass
                return

        # ═══ Skip empty content ═══
        if not content.strip() or content.startswith("["):
            if not content.strip() or content in ("[Video]", "[Document]"):
                await _handle_command(wa_id, "start", wa_user_id, contact_name)
            return

        # ═══ Auto-detect URLs for download (like Telegram auto-download) ═══
        if message_type == "text":
            url = _extract_url(content.strip())
            if url:
                platform = _detect_platform(url)
                if platform != "unknown":
                    # User sent a video/social media URL — show quality selection!
                    logger.info(f"🔗 Auto-detected {platform} URL from {wa_id}: {url[:80]}")
                    await _show_quality_selection(wa_id, url, wa_user_id, contact_name, message_id, is_admin)
                    return

        # ═══ Route to AI Engine with Thinking Feedback ═══
        logger.info(f"🤖 Routing WA message to AI: {content[:80]}")

        await _send_ai_response(wa_id, content, wa_user_id, contact_name, message_id, context_type="general")

    except Exception as e:
        logger.error(f"❌ Error handling WA message: {e}", exc_info=True)
        _log_activity("message_handler_error", {"error": str(e)[:200]}, "error")


# ═══════════════════════════════════════
# Admin Commands with Arguments
# ═══════════════════════════════════════

async def _handle_admin_with_args(wa_id: str, content: str, wa_user_id: int, contact_name: str):
    """Handle admin commands that have arguments (e.g., /grant 123456789)"""
    if not _is_wa_admin(wa_id):
        await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
        return

    parts = content.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    try:
        if cmd in ("/grant",):
            if not args:
                await _send_whatsapp_message(wa_id, "⭐ الاستخدام: /grant [أيام] رقم_الواتساب\nمثال: /grant 201203551789\nمثال: /grant 30 201203551789")
                return

            from premium import grant_premium
            from memory import _ensure_user_in_db

            if len(args) == 1:
                phone = args[0]
                target_id = _wa_phone_to_user_id(phone)
                days = 0
            elif len(args) == 2:
                days = int(args[0])
                phone = args[1]
                target_id = _wa_phone_to_user_id(phone)
            else:
                await _send_whatsapp_message(wa_id, "❌ كترت الأرقام. /grant [أيام] رقم_الواتساب")
                return

            _ensure_user_in_db(target_id, platform="whatsapp")

            expires = None
            expires_display = "مدى الحياة 🔓"
            if days > 0:
                from datetime import timedelta
                from admin import CAIRO_TZ
                expires_date = datetime.now(CAIRO_TZ) + timedelta(days=days)
                expires = expires_date.isoformat()
                expires_display = f"{days} يوم 🔒"

            grant_premium(target_id, granted_by=f"admin_{wa_user_id}", expires=expires)
            await _send_whatsapp_message(wa_id, f"✅ تم تفعيل Premium!\n\n📱 المستخدم: {_wa_phone_to_display(phone)}\n⭐ الخطة: Premium\n⏰ المدة: {expires_display}")

        elif cmd in ("/revoke",):
            if not args:
                await _send_whatsapp_message(wa_id, "❌ الاستخدام: /revoke رقم_الواتساب\nمثال: /revoke 201203551789")
                return
            phone = args[0]
            target_id = _wa_phone_to_user_id(phone)
            from premium import revoke_premium
            revoke_premium(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم شيل Premium من {_wa_phone_to_display(phone)}")

        elif cmd in ("/resetlimit",):
            if not args:
                await _send_whatsapp_message(wa_id, "🔄 الاستخدام: /resetlimit رقم_الواتساب\nمثال: /resetlimit 201203551789")
                return
            phone = args[0]
            target_id = _wa_phone_to_user_id(phone)
            from premium import reset_user_usage
            success = reset_user_usage(target_id)
            if success:
                await _send_whatsapp_message(wa_id, f"✅ تم إعادة تعيين حدود {_wa_phone_to_display(phone)}")
            else:
                await _send_whatsapp_message(wa_id, f"❌ فشل في إعادة التعيين")

        elif cmd in ("/ban",):
            if not args:
                await _send_whatsapp_message(wa_id, "🚫 الاستخدام: /ban رقم_الواتساب [سبب]\nمثال: /ban 201203551789 سبام")
                return
            phone = args[0]
            target_id = _wa_phone_to_user_id(phone)
            reason = " ".join(args[1:]) if len(args) > 1 else "حظر من الأدمن"
            from memory import ban_user
            ban_user(target_id, reason=reason, banned_by=f"admin_{wa_user_id}")
            await _send_whatsapp_message(wa_id, f"🚫 تم حظر {_wa_phone_to_display(phone)}\n📝 السبب: {reason}")

        elif cmd in ("/unban",):
            if not args:
                await _send_whatsapp_message(wa_id, "✅ الاستخدام: /unban رقم_الواتساب\nمثال: /unban 201203551789")
                return
            phone = args[0]
            target_id = _wa_phone_to_user_id(phone)
            from memory import unban_user
            unban_user(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم إلغاء حظر {_wa_phone_to_display(phone)}")

        elif cmd in ("/userinfo",):
            if not args:
                await _send_whatsapp_message(wa_id, "👤 الاستخدام: /userinfo رقم_الواتساب\nمثال: /userinfo 201203551789")
                return
            phone = args[0]
            target_id = _wa_phone_to_user_id(phone)
            from memory import get_user, get_interests, get_favorite_companies
            from premium import get_user_plan, get_usage
            user_data = get_user(target_id)
            plan = get_user_plan(target_id)
            usage = get_usage(target_id)
            interests = get_interests(target_id)

            info = (
                f"👤 *معلومات المستخدم*\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"📱 الرقم: {_wa_phone_to_display(phone)}\n"
                f"📝 الاسم: {user_data.get('name', 'مش محدد')}\n"
                f"🌐 اللغة: {'العربية' if user_data.get('language') == 'ar' else 'English'}\n"
                f"⭐ الخطة: {plan.upper()}\n"
                f"📬 مشترك: {'نعم' if user_data.get('subscribed') else 'لا'}\n\n"
                f"📊 *استخدام اليوم:*\n"
                f"→ رسائل AI: {usage.get('ai_messages', 0)}\n"
                f"→ PDF: {usage.get('pdf_analyses', 0)}\n"
                f"→ صور: {usage.get('image_analyses', 0)}\n"
                f"→ YouTube: {usage.get('youtube_summaries', 0)}\n"
                f"→ بحث: {usage.get('searches', 0)}\n\n"
                f"🎯 اهتمامات: {', '.join(interests[:5]) if interests else 'لا يوجد'}"
            )
            await _send_whatsapp_message(wa_id, info)

        elif cmd in ("/broadcast",):
            if not args:
                await _send_whatsapp_message(wa_id, "📢 الاستخدام: /broadcast الرسالة")
                return
            broadcast_msg = " ".join(args)
            from memory import get_all_subscribers
            subscribers = get_all_subscribers(platform="whatsapp")

            await _send_whatsapp_message(wa_id, f"📢 جاري البث لـ {len(subscribers)} مشترك...")

            success = 0
            fail = 0
            for sub in subscribers:
                try:
                    # Note: For WA broadcast, we'd need each subscriber's WA ID
                    # This is limited by the WA API — we can only send to WA numbers we know
                    # For now, log the broadcast
                    success += 1
                except Exception:
                    fail += 1

            await _send_whatsapp_message(wa_id,
                f"📢 *تم البث!*\n\n👥 المجموع: {len(subscribers)}\n✅ نجح: {success}\n❌ فشل: {fail}\n\n⚠️ ملاحظة: البث على WA محدود — يتبعت بس على تليجرام")

        # ═══ أوامر أدمن إضافية — زي التليجرام ═══

        elif cmd in ("/botstats", "/stats"):
            from dashboard import get_today_stats, get_total_users, get_total_subscribers, get_total_premium
            stats = get_today_stats(platform="whatsapp")
            total_users = get_total_users(platform="whatsapp")
            total_subs = get_total_subscribers(platform="whatsapp")
            total_prem = get_total_premium(platform="whatsapp")
            sub_rate = f"{(total_subs/total_users*100):.1f}%" if total_users > 0 else "0%"
            prem_rate = f"{(total_prem/total_users*100):.1f}%" if total_users > 0 else "0%"
            await _send_whatsapp_message(wa_id,
                f"📊 *إحصائيات بوت الواتساب*\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"👥 *المستخدمين*\n"
                f"→ الإجمالي: {total_users}\n"
                f"→ مشتركين أخبار: {total_subs} ({sub_rate})\n"
                f"→ Premium: {total_prem} ({prem_rate})\n\n"
                f"📈 *إحصائيات اليوم*\n"
                f"→ الرسائل: {stats['total_messages']}\n"
                f"→ الأوامر: {stats['total_commands']}\n"
                f"→ طلبات AI: {stats['ai_requests']}\n"
                f"→ عمليات البحث: {stats['search_requests']}\n"
                f"→ تحليلات PDF: {stats['pdf_analyses']}\n"
                f"→ تحليلات صور: {stats['image_analyses']}\n"
                f"→ أخطاء: {stats['total_errors']}\n"
                f"→ مستخدمين جدد: {stats['new_users']}"
            )

        elif cmd in ("/allusers",):
            from memory import _execute, _is_postgres
            ph = "%s" if _is_postgres() else "?"
            rows = _execute(
                f"SELECT user_id, name, platform FROM user_profiles WHERE platform = {ph} ORDER BY created_at DESC LIMIT 30",
                ("whatsapp",), fetch=True
            )
            if rows:
                text = "👥 *كل مستخدمين الواتساب*\n━━━━━━━━━━━━━━━━━\n\n"
                for r in rows:
                    name = r[1] or "مش محدد"
                    uid = r[0]
                    # لو الـ user_id سالب (واتساب hashed)، نعرضه كـ ID داخلي
                    if uid < 0:
                        text += f"📱 {name}\n"
                    else:
                        text += f"👤 {uid} — {name}\n"
                if len(rows) >= 30:
                    text += f"\n... وأكتر"
                await _send_whatsapp_message(wa_id, text)
            else:
                await _send_whatsapp_message(wa_id, "👥 مفيش مستخدمين واتساب حالياً")

        elif cmd in ("/warn",):
            if not args:
                await _send_whatsapp_message(wa_id, "⚠️ الاستخدام: /warn رقم_الواتساب [السبب]\nمثال: /warn 201203551789 سبام")
                return
            try:
                phone = args[0]
                target_id = _wa_phone_to_user_id(phone)
                reason = " ".join(args[1:]) if len(args) > 1 else "تحذير من الأدمن"
                from memory import _execute, _is_postgres, _ensure_user_in_db
                _ensure_user_in_db(target_id, platform="whatsapp")
                ph1, ph2, ph3, ph4 = ("%s", "%s", "%s", "%s") if _is_postgres() else ("?", "?", "?", "?")
                # Check current warning count
                row = _execute(f"SELECT warning_count FROM banned_users WHERE user_id = {ph1}", (target_id,), fetchone=True)
                if row:
                    new_count = (row[0] or 0) + 1
                    _execute(f"UPDATE banned_users SET warning_count = {ph1}, reason = {ph2} WHERE user_id = {ph3}", (new_count, reason, target_id))
                else:
                    new_count = 1
                    _execute(f"INSERT INTO banned_users (user_id, reason, banned_by, warning_count) VALUES ({ph1}, {ph2}, 'admin', {ph3})", (target_id, reason, new_count))
                
                if new_count >= 3:
                    # Auto-ban after 3 warnings
                    _execute(f"UPDATE banned_users SET reason = {ph1}, banned_by = 'auto_ban' WHERE user_id = {ph2}", (f"حظر تلقائي بعد {new_count} تحذيرات", target_id))
                    await _send_whatsapp_message(wa_id, f"🚫 *حظر تلقائي!* المستخدم {_wa_phone_to_display(phone)} حصل على 3 تحذيرات واتحظر تلقائياً.")
                else:
                    await _send_whatsapp_message(wa_id, f"⚠️ *تحذير ({new_count}/3)*\n📱 المستخدم: {_wa_phone_to_display(phone)}\n📝 السبب: {reason}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/addadmin",):
            if not args:
                await _send_whatsapp_message(wa_id, "👑 الاستخدام: /addadmin رقم_الواتساب\nمثال: /addadmin 201203551789")
                return
            try:
                phone = args[0]
                target_id = _wa_phone_to_user_id(phone)
                from admin import _save_admin_to_db, ADMIN_USER_IDS
                _save_admin_to_db(target_id, role="admin", added_by=f"admin_{wa_user_id}")
                await _send_whatsapp_message(wa_id, f"👑 *تم إضافة أدمن جديد!*\n📱 {_wa_phone_to_display(phone)}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/removeadmin",):
            if not args:
                await _send_whatsapp_message(wa_id, "👑 الاستخدام: /removeadmin رقم_الواتساب\nمثال: /removeadmin 201203551789")
                return
            try:
                phone = args[0]
                target_id = _wa_phone_to_user_id(phone)
                from admin import _remove_admin_from_db, is_admin as check_admin
                if check_admin(target_id) and target_id in [8674141938, 8313119944]:
                    await _send_whatsapp_message(wa_id, "👑 مينفعش تشيل الـ Owner!")
                    return
                _remove_admin_from_db(target_id)
                await _send_whatsapp_message(wa_id, f"👑 *تم شيل أدمن*\n📱 {_wa_phone_to_display(phone)}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/listadmins",):
            from admin import ADMIN_USER_IDS
            from memory import _execute, _is_postgres
            rows = _execute("SELECT user_id, username, role FROM admin_users", fetch=True)
            if rows:
                text = "👑 *قائمة الأدمنز*\n━━━━━━━━━━━━━━━━━\n\n"
                for r in rows:
                    uid = r[0]
                    # لو الـ user_id سالب (واتساب)، نعرض إنه واتساب
                    if uid < 0:
                        text += f"📱 واتساب — {r[1] or 'مش محدد'} ({r[2]})\n"
                    else:
                        text += f"👤 تليجرام {uid} — {r[1] or 'مش محدد'} ({r[2]})\n"
                await _send_whatsapp_message(wa_id, text)
            else:
                await _send_whatsapp_message(wa_id, "👑 مفيش أدمنز مسجلين")

    except ValueError:
        await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح. اكتب الرقم زي: 201203551789")
    except Exception as e:
        logger.error(f"❌ Admin command error: {e}")
        await _send_whatsapp_message(wa_id, f"❌ حصل خطأ: {e}")


# ═══════════════════════════════════════
# Commands with Arguments
# ═══════════════════════════════════════

async def _handle_command_with_arg(wa_id: str, cmd_name: str, arg: str, wa_user_id: int,
                                   contact_name: str, message_id: str, is_admin: bool):
    """Handle commands that have arguments (e.g., /download URL, /study topic)"""

    if cmd_name == "download":
        # Download video — REAL download using yt-dlp (like Telegram)
        # Check if the argument is a URL
        url = arg.strip()
        if not _extract_url(url):
            # Not a URL — ask AI for help
            await _send_ai_response(wa_id,
                f"المستخدم عايز يحمل حاجة: {arg}\n\nلو ده رابط فيديو، قدم المساعدة. لو مش رابط، اشرح له ازاي يستخدم أمر التحميل مع رابط صحيح.",
                wa_user_id, contact_name, message_id, context_type="download")
        else:
            # It's a URL — actually download it!
            await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "image_gen":
        # Image generation (Premium) — REAL image generation (like Telegram)
        if not is_admin:
            try:
                from premium import can_use_image_gen
                if not can_use_image_gen(wa_user_id):
                    await _send_whatsapp_message(wa_id, f"🎨 إنشاء الصور مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return
            except Exception:
                pass

        # Actually generate and send the image
        await _generate_and_send_image(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "image_edit":
        if not is_admin:
            try:
                from premium import can_use_image_edit
                if not can_use_image_edit(wa_user_id):
                    await _send_whatsapp_message(wa_id, "🖌️ تعديل الصور مميزة Premium بس!")
                    return
            except Exception:
                pass

        # Check if user has a cached image
        cached_img = _wa_user_edit_images.get(wa_user_id)
        if cached_img and cached_img.get("image_base64"):
            # User has a cached image — edit it with the prompt
            await _edit_and_send_image(wa_id, arg, cached_img["image_base64"], wa_user_id, contact_name, message_id, is_admin)
        else:
            await _send_whatsapp_message(wa_id,
                "🖌️ عايز تعدّل صورة؟\n\n1️⃣ ابعت الصورة اللي عايز تعدلها\n2️⃣ بعد ما تبعتها، اكتب التعديل\n\n"
                "📝 أمثلة:\n→ /edit غيّر الخلفية لبحر\n→ /edit خلي الصورة زي رسمة")

    elif cmd_name == "youtube":
        # YouTube summary — REAL YouTubeAgent (same as Telegram)
        from agents.youtube_agent import YouTubeAgent
        yt_agent = YouTubeAgent()
        
        # Start thinking feedback
        feedback = ThinkingFeedback(wa_id, message_id, context_type="youtube")
        await feedback.start()
        
        try:
            summary = await yt_agent.summarize_video(arg, language="ar", user_id=wa_user_id)
            if summary:
                summary_text = _strip_html_for_whatsapp(summary)
                chunks = _split_whatsapp_message(summary_text)
                for chunk in chunks:
                    await _send_whatsapp_message(wa_id, chunk)
                
                # Increment usage
                if not is_admin:
                    try:
                        from premium import increment_usage
                        increment_usage(wa_user_id, "youtube_summaries")
                    except Exception:
                        pass
                
                await feedback.complete()
                
                # Quick action buttons
                await _send_interactive_buttons(wa_id, body_text="عايز حاجة تانية؟",
                    buttons=[
                        {"id": "cmd_youtube", "title": "🎬 فيديو تاني"},
                        {"id": "cmd_download", "title": "📥 حمّله"},
                        {"id": "cmd_chat", "title": "💬 محادثة"},
                    ])
            else:
                await _send_whatsapp_message(wa_id, "❌ مش قادر ألخص الفيديو ده. جرب رابط تاني! 🎬")
                await feedback.error()
        except Exception as e:
            logger.error(f"❌ YouTube summary error: {e}", exc_info=True)
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في تلخيص الفيديو. جرب تاني! 🎬")
            await feedback.error()

    elif cmd_name in ("quiz", "exam", "study"):
        # Study mode
        if not is_admin:
            try:
                from premium import can_use_study_mode
                if not can_use_study_mode(wa_user_id):
                    await _send_whatsapp_message(wa_id, f"⭐ وضع الدراسة مميزة Premium بس!\n\n📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return
            except Exception:
                pass

        if cmd_name == "quiz":
            prompt = f"اعمل كويز في موضوع: {arg}. اسأل 5 أسئلة اختيار متعدد مع الخيارات وانتظر الإجابة قبل ما تدي الحل."
        elif cmd_name == "exam":
            prompt = f"اعمل امتحان شامل في: {arg}. اسأل 10 أسئلة متنوعة (اختيار متعدد، صح وغلط، أكمل) وانتظر الإجابة قبل التصحيح."
        else:
            prompt = f"علمني عن {arg} من الصفر للمحترف. ابدأ بالأساسيات وشرح مبسط مع أمثلة عملية."

        await _send_ai_response(wa_id, prompt,
            wa_user_id, contact_name, message_id, context_type="study")

    elif cmd_name == "search":
        await _send_ai_response(wa_id, f"ابحث لي عن: {arg}",
            wa_user_id, contact_name, message_id, context_type="search",
            increment_feature="searches")

    # ══════════════════════════════════════
    # VIDEO SEARCH / AUDIO SEARCH / PHOTO SEARCH (with args)
    # ══════════════════════════════════════

    elif cmd_name == "video_search_query":
        # /video <query> — بحث يوتيوب + عرض نتائج + تحميل فيديو
        await _handle_wa_video_search(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "audio_search_query":
        # /audio <query> — بحث يوتيوب + عرض نتائج + تحميل صوت
        await _handle_wa_audio_search(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "photo_search_query":
        # /photo <query> — بحث صور
        await _handle_wa_photo_search(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)


# ═══════════════════════════════════════
# WhatsApp Video/Audio/Photo Search Handlers
# ═══════════════════════════════════════

# Cache لنتائج بحث الواتساب
_wa_search_cache = {}  # {wa_id: {"results": [...], "query": str, "type": str, "created_at": float}}
_WA_SEARCH_CACHE_TTL = 300


async def _wa_download_youtube(wa_id: str, url: str, wa_user_id: int,
                                 contact_name: str, message_id: str, is_admin: bool,
                                 format: str = "720"):
    """تحميل فيديو/صوت YouTube عبر RapidAPI للواتساب
    
    format: "720" لفيديو 720p, "mp3" لصوت, الخ
    لو مش يوتيوب، بيستخدم yt-dlp عادي
    """
    from youtube_rapidapi import is_youtube_url, download_youtube_file_async, get_error_message
    
    # لو مش يوتيوب، نستخدم الطريقة العادية (yt-dlp)
    if not is_youtube_url(url):
        force_audio = (format == "mp3")
        await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, force_audio=force_audio)
        return
    
    # ═══ YouTube: استخدم RapidAPI مع fallback لـ yt-dlp ═══
    is_audio = (format == "mp3")
    rapidapi_failed = False
    
    try:
        await _send_whatsapp_message(wa_id, 
            f"{'🎵' if is_audio else '🎬'} جاري التحميل عبر الخدمة الخارجية..."
        )
        
        # 🔴 timeout 90 ثانية — لو الخدمة بطيئة نروح yt-dlp
        try:
            result = await asyncio.wait_for(
                download_youtube_file_async(url, format=format, output_dir="/tmp"),
                timeout=90
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ YouTube RapidAPI timed out after 90s, falling back to yt-dlp")
            rapidapi_failed = True
            result = None
        
        # 🟢 تحقق من النتيجة — ممكن success=True بس مفيش file_path (لو تحميل الملف فشل)
        if result and result.get("success"):
            real_title = result.get("title", "فيديو YouTube")
            download_url = result.get("download_url", "")
            file_download_error = result.get("file_download_error", "")
            
            # 🟢 الحالة 1: الملف اتحمل بنجاح
            if result.get("file_path"):
                file_path = result["file_path"]
                file_size = result.get("file_size", 0)
                
                # لو الملف كبير، نجرب جودة أقل للفيديو
                if not is_audio and file_size > 64 * 1024 * 1024:
                    _cleanup_wa_file(file_path)
                    await _send_whatsapp_message(wa_id, "🎬 الملف كبير، بجرب جودة أقل...")
                    try:
                        result = await asyncio.wait_for(
                            download_youtube_file_async(url, format="360", output_dir="/tmp"),
                            timeout=60
                        )
                    except asyncio.TimeoutError:
                        result = None
                        
                    if result and result.get("success") and result.get("file_path"):
                        file_path = result["file_path"]
                        file_size = result.get("file_size", 0)
                        real_title = result.get("title", "فيديو YouTube")
                    else:
                        # حتى الجودة الأقل فشلت
                        logger.warning("⚠️ RapidAPI failed for lower quality too")
                        rapidapi_failed = True
                
                if not rapidapi_failed:
                    # إرسال الملف عبر WhatsApp
                    try:
                        with open(file_path, 'rb') as f:
                            file_data = f.read()
                        
                        if is_audio:
                            await _send_whatsapp_audio(wa_id, file_data, title=real_title[:64])
                        else:
                            ext = "mp4"
                            filename = f"{real_title[:50]}.{ext}"
                            await _send_whatsapp_document(wa_id, file_data, filename, caption=f"🎬 {real_title}", content_type="video/mp4")
                        
                        await _send_whatsapp_message(wa_id, 
                            f"✅ تم إرسال ال{'صوت' if is_audio else 'فيديو'}!"
                        )
                        
                        try:
                            increment_usage(wa_user_id, "youtube_summaries")
                        except Exception:
                            pass
                        
                    except Exception as e:
                        logger.error(f"WA send YouTube media error: {e}")
                        
                        # لو فشل الإرسال، نبعت الرابط كبديل
                        if download_url:
                            await _send_whatsapp_message(wa_id, 
                                f"⚠️ حجم الملف كبير عشان نبعتو على واتساب.\n\n"
                                f"🔗 رابط التحميل المباشر:\n{download_url}\n\n"
                                f"🎬 {real_title}"
                            )
                        else:
                            rapidapi_failed = True
                    finally:
                        _cleanup_wa_file(file_path)
                    
                    if not rapidapi_failed:
                        return
            
            # 🟢 الحالة 2: RapidAPI رجعت رابط تحميل بس فشل تحميل الملف على السيرفر
            elif download_url and file_download_error:
                logger.warning(f"⚠️ RapidAPI got download URL but file download failed: {file_download_error}")
                await _send_whatsapp_message(wa_id, 
                    f"✅ تم تجهيز رابط التحميل!\n\n"
                    f"🎬 {real_title}\n\n"
                    f"🔗 رابط التحميل المباشر:\n{download_url}\n\n"
                    f"⏰ الرابط صالح لفترة محدودة — حمّلو بسرعة!"
                )
                try:
                    increment_usage(wa_user_id, "youtube_summaries")
                except Exception:
                    pass
                return  # ✅ خلصنا — المستخدم اخد الرابط
            
            # 🟢 الحالة 3: success=True بس مفيش file_path ولا download_url
            elif not download_url:
                logger.warning(f"⚠️ RapidAPI returned success but no download URL or file path")
                rapidapi_failed = True
        
        # ═══ RapidAPI فشلت أو علّقت → fallback لـ yt-dlp ═══
        if not rapidapi_failed:
            error_code = result.get("error", "unknown") if result else "unknown"
            logger.warning(f"⚠️ YouTube RapidAPI failed ({error_code}), falling back to yt-dlp")
        
        await _send_whatsapp_message(wa_id, 
            "⚠️ الخدمة الخارجية فشلت، بجرب طريقة بديلة..."
        )
        force_audio = is_audio
        quality_map = {"1080": "best", "720": "medium", "360": "low", "mp3": "audio"}
        yt_quality = quality_map.get(format, "medium")
        await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=yt_quality, force_audio=force_audio)
        return
    
    except Exception as e:
        logger.error(f"WA YouTube RapidAPI error: {e}")
        # fallback لـ yt-dlp
        await _send_whatsapp_message(wa_id, "⚠️ حصل خطأ، بجرب طريقة بديلة...")
        force_audio = is_audio
        quality_map = {"1080": "best", "720": "medium", "360": "low", "mp3": "audio"}
        yt_quality = quality_map.get(format, "medium")
        await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=yt_quality, force_audio=force_audio)


def _cleanup_wa_file(file_path: str):
    """حذف ملف مؤقت"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass


async def _handle_wa_video_search(wa_id: str, query: str, wa_user_id: int, 
                                   contact_name: str, message_id: str, is_admin: bool):
    """بحث يوتيوب + عرض نتائج + تحميل فيديو عبر WhatsApp"""
    await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في YouTube عن: {query}...")
    
    try:
        from youtube_search import search_youtube, format_search_results
        
        results = await search_youtube(query, max_results=5)
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش نتائج. جرب كلمات بحث تانية!")
            return
        
        # حفظ النتائج في cache
        cache_key = hashlib.md5(f"wa_{wa_id}_{query}".encode()).hexdigest()[:12]
        _wa_search_cache[cache_key] = {
            "results": results,
            "query": query,
            "type": "video",
            "created_at": time.time(),
        }
        
        # عرض النتائج كـ interactive list
        text = format_search_results(results, lang="ar")
        
        sections = [{
            "title": "🎬 نتائج YouTube",
            "rows": []
        }]
        
        for i, r in enumerate(results):
            title = r['title'][:24]
            desc = f"⏱ {r['duration']} | 📺 {r['channel'][:15]}"
            sections[0]["rows"].append({
                "id": f"wa_vs_{cache_key}_{i}",
                "title": f"{i+1}. {title}",
                "description": desc,
            })
        
        await _send_interactive_list(wa_id, text, "🎬 اختر فيديو", sections)
        
    except Exception as e:
        logger.error(f"WA video search error: {e}")
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ في البحث. جرب تاني!")


async def _handle_wa_audio_search(wa_id: str, query: str, wa_user_id: int,
                                   contact_name: str, message_id: str, is_admin: bool):
    """بحث يوتيوب + عرض نتائج + تحميل صوت عبر WhatsApp"""
    await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في YouTube عن: {query}...")
    
    try:
        from youtube_search import search_youtube, format_search_results
        
        results = await search_youtube(query, max_results=5)
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش نتائج. جرب كلمات بحث تانية!")
            return
        
        cache_key = hashlib.md5(f"wa_{wa_id}_{query}".encode()).hexdigest()[:12]
        _wa_search_cache[cache_key] = {
            "results": results,
            "query": query,
            "type": "audio",
            "created_at": time.time(),
        }
        
        text = format_search_results(results, lang="ar")
        
        sections = [{
            "title": "🎵 نتائج YouTube - صوت",
            "rows": []
        }]
        
        for i, r in enumerate(results):
            title = r['title'][:24]
            desc = f"⏱ {r['duration']} | 📺 {r['channel'][:15]}"
            sections[0]["rows"].append({
                "id": f"wa_as_{cache_key}_{i}",
                "title": f"{i+1}. {title}",
                "description": desc,
            })
        
        await _send_interactive_list(wa_id, text, "🎵 اختر صوت", sections)
        
    except Exception as e:
        logger.error(f"WA audio search error: {e}")
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ في البحث. جرب تاني!")


async def _handle_wa_photo_search(wa_id: str, query: str, wa_user_id: int,
                                   contact_name: str, message_id: str, is_admin: bool):
    """بحث صور + اختيار عدد + إرسال عبر WhatsApp"""
    # حفظ الاستعلام في cache
    cache_key = hashlib.md5(f"wa_ph_{wa_id}_{query}".encode()).hexdigest()[:12]
    _wa_search_cache[cache_key] = {
        "query": query,
        "type": "photo",
        "results": [],
        "created_at": time.time(),
    }
    
    # 🔴 حفظ حالة المستخدم — في انتظار عدد الصور
    _set_user_state(wa_id, "photo_search", {"query": query, "cache_key": cache_key})
    
    text = f"🖼️ *بحث عن صور: {query}*\n━━━━━━━━━━━━━━━━━\n\nكم صورة تريد؟\n\n💡 ممكن تكتب رقم أو تختار من الأزرار:"
    
    await _send_interactive_buttons(wa_id, text, [
        {"id": f"wa_ph_{cache_key}_3", "title": "3 صور"},
        {"id": f"wa_ph_{cache_key}_5", "title": "5 صور"},
        {"id": f"wa_ph_{cache_key}_10", "title": "10 صور"},
    ])


async def _execute_photo_search(wa_id: str, query: str, count: int, wa_user_id: int,
                                 contact_name: str, message_id: str, is_admin: bool,
                                 cache_key: str = ""):
    """تنفيذ بحث الصور بعد ما المستخدم حدد العدد"""
    await _send_whatsapp_message(wa_id, f"🖼️ جاري البحث عن {count} صور لـ: {query}...")
    
    try:
        from image_search import search_images, download_images
        
        results = await search_images(query, count=count)
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش صور! جرب كلمات بحث تانية.")
            return
        
        image_urls = [r["url"] for r in results[:count]]
        images = await download_images(image_urls)
        
        if not images:
            await _send_whatsapp_message(wa_id, "❌ فشل تحميل الصور. جرب تاني!")
            return
        
        # إرسال الصور واحدة واحدة
        sent = 0
        for i, img_bytes in enumerate(images):
            try:
                img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                caption = ""
                if i == 0:
                    caption = f"🖼️ صور لـ: {query}\n📸 {i+1}/{len(images)}"
                
                await _send_whatsapp_image(wa_id, img_b64, caption)
                sent += 1
                if i < len(images) - 1:
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Failed to send image {i}: {e}")
        
        await _send_whatsapp_message(wa_id, f"✅ تم إرسال {sent}/{len(images)} صورة!")
        
    except Exception as e:
        logger.error(f"WA photo search error: {e}")
        await _send_whatsapp_message(wa_id, "❌ حصل خطأ. جرب تاني!")


async def _handle_wa_search_callback(wa_id: str, callback_id: str, wa_user_id: int,
                                      contact_name: str, message_id: str, is_admin: bool):
    """معالجة اختيارات البحث من الواتساب (list/button callbacks)"""
    
    # فيديو بالبحث: wa_vs_{cache_key}_{index}
    if callback_id.startswith("wa_vs_"):
        parts = callback_id.split("_", 3)
        if len(parts) < 4:
            return
        cache_key = parts[2]
        try:
            idx = int(parts[3])
        except ValueError:
            return
        
        cached = _wa_search_cache.get(cache_key)
        if not cached or idx >= len(cached["results"]):
            await _send_whatsapp_message(wa_id, "❌ النتائج انتهت! ابحث تاني.")
            return
        
        r = cached["results"][idx]
        await _send_whatsapp_message(wa_id, f"🎬 جاري تحميل الفيديو...\n\n📺 {r['title']}")
        await _wa_download_youtube(wa_id, r['url'], wa_user_id, contact_name, message_id, is_admin, format="720")
    
    # صوت بالبحث: wa_as_{cache_key}_{index}
    elif callback_id.startswith("wa_as_"):
        parts = callback_id.split("_", 3)
        if len(parts) < 4:
            return
        cache_key = parts[2]
        try:
            idx = int(parts[3])
        except ValueError:
            return
        
        cached = _wa_search_cache.get(cache_key)
        if not cached or idx >= len(cached["results"]):
            await _send_whatsapp_message(wa_id, "❌ النتائج انتهت! ابحث تاني.")
            return
        
        r = cached["results"][idx]
        await _send_whatsapp_message(wa_id, f"🎵 جاري تحميل الصوت...\n\n📺 {r['title']}")
        await _wa_download_youtube(wa_id, r['url'], wa_user_id, contact_name, message_id, is_admin, format="mp3")
    
    # صور: wa_ph_{cache_key}_{count}
    elif callback_id.startswith("wa_ph_"):
        parts = callback_id.split("_", 3)
        if len(parts) < 4:
            return
        cache_key = parts[2]
        try:
            count = int(parts[3])
        except ValueError:
            return
        
        # 🔴 مسح حالة المستخدم لأنه اختار من الأزرار
        _clear_user_state(wa_id)
        
        cached = _wa_search_cache.get(cache_key)
        if not cached or not cached.get("query"):
            await _send_whatsapp_message(wa_id, "❌ انتهت الجلسة! ابحث تاني.")
            return
        
        query = cached["query"]
        await _send_whatsapp_message(wa_id, f"🖼️ جاري البحث عن {count} صور لـ: {query}...")
        
        try:
            from image_search import search_images, download_images
            
            results = await search_images(query, count=count)
            
            if not results:
                await _send_whatsapp_message(wa_id, "❌ مفيش صور! جرب كلمات بحث تانية.")
                return
            
            image_urls = [r["url"] for r in results[:count]]
            images = await download_images(image_urls)
            
            if not images:
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الصور. جرب تاني!")
                return
            
            # إرسال الصور واحدة واحدة
            sent = 0
            for i, img_bytes in enumerate(images):
                try:
                    img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                    caption = ""
                    if i == 0:
                        caption = f"🖼️ صور لـ: {query}\n📸 {i+1}/{len(images)}"
                    
                    await _send_whatsapp_image(wa_id, img_b64, caption)
                    sent += 1
                    if i < len(images) - 1:
                        await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Failed to send image {i}: {e}")
            
            await _send_whatsapp_message(wa_id, f"✅ تم إرسال {sent}/{len(images)} صورة!")
            
        except Exception as e:
            logger.error(f"WA photo search error: {e}")
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ. جرب تاني!")


# ═══════════════════════════════════════
# Audio Transcription (VoiceAgent — Google Speech + 3 fallbacks)
# ═══════════════════════════════════════

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


# ═══════════════════════════════════════
# Image Analysis (Vision Models)
# ═══════════════════════════════════════

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


# ═══════════════════════════════════════
# Document Analysis (PDF)
# ═══════════════════════════════════════

async def _analyze_document(media_id: str, caption: str = "", wa_user_id: int = None) -> str:
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

        # Determine filename from caption or default
        filename = "document.pdf"
        if caption and caption != "[Document]":
            # If caption looks like a filename, use it
            if "." in caption.split()[0]:
                filename = caption.split()[0]

        # Use PDFAgent for extraction (same as Telegram)
        from agents.pdf_agent import PDFAgent
        pdf_agent = PDFAgent()

        text = await asyncio.wait_for(
            pdf_agent.extract_text(doc_bytes, filename=filename),
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


# ═══════════════════════════════════════
# Health Check
# ═══════════════════════════════════════

async def health_check(request: web.Request):
    """Health check endpoint for Railway — includes DB diagnostics"""
    whatsapp_ok = bool(WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID)
    ai_ok = True
    try:
        from ai_engine import smart_chat
    except Exception:
        ai_ok = False

    # ═══ Database Diagnostics ═══
    db_info = {
        "connected": False,
        "type": "none",
        "persistent": False,
        "tables": {},
        "user_count": 0,
        "error": None,
    }
    try:
        from memory import _is_postgres, _db_type, _pg_pool, _execute
        db_info["type"] = _db_type or "none"
        db_info["connected"] = _db_type is not None
        db_info["persistent"] = _db_type == "postgresql"

        if _db_type == "postgresql":
            db_info["pool_size"] = f"1-3 (maxconn)" if _pg_pool else "N/A"
            # Quick connectivity test
            try:
                result = _execute("SELECT 1 as test", fetchone=True)
                db_info["query_test"] = "ok" if result else "no_result"
            except Exception as e:
                db_info["query_test"] = f"error: {str(e)[:100]}"

        # Count users and table sizes
        if _db_type:
            try:
                user_count = _execute("SELECT COUNT(*) FROM user_profiles", fetchone=True)
                db_info["user_count"] = user_count[0] if user_count else 0
            except Exception:
                pass

            # Table row counts
            for table_name in ['user_profiles', 'conversations', 'user_memories',
                               'learning_progress', 'favorites', 'banned_users']:
                try:
                    count = _execute(f"SELECT COUNT(*) FROM {table_name}", fetchone=True)
                    db_info["tables"][table_name] = count[0] if count else 0
                except Exception:
                    db_info["tables"][table_name] = "error"

            # Premium tables
            try:
                from premium import _is_postgres as _prem_is_pg
                for table_name in ['premium_users', 'usage_tracking', 'workspace_items', 'smart_alerts']:
                    try:
                        count = _execute(f"SELECT COUNT(*) FROM {table_name}", fetchone=True)
                        db_info["tables"][table_name] = count[0] if count else 0
                    except Exception:
                        db_info["tables"][table_name] = "error"
            except Exception:
                pass

        # Check DATABASE_URL availability (masked)
        import os
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            if "neon.tech" in db_url:
                db_info["url_type"] = "neon_postgresql"
            elif db_url.startswith("file:"):
                db_info["url_type"] = "sqlite_local"
            elif "postgresql" in db_url or "postgres://" in db_url:
                db_info["url_type"] = "postgresql_other"
            else:
                db_info["url_type"] = "unknown"
            db_info["url_masked"] = db_url[:25] + "***" + db_url[-15:] if len(db_url) > 40 else "***"
        else:
            db_info["url_type"] = "not_set"
            db_info["error"] = "DATABASE_URL environment variable is not set!"

    except Exception as e:
        db_info["error"] = f"Diagnostic error: {str(e)[:200]}"

    overall_status = "ok" if (whatsapp_ok and ai_ok and db_info["connected"]) else "degraded"
    if not db_info["connected"]:
        overall_status = "critical"

    return web.json_response({
        "status": overall_status,
        "whatsapp": whatsapp_ok,
        "ai": ai_ok,
        "database": db_info,
        "service": "my-bro-whatsapp-webhook",
        "version": "4.0",
        "features": [
            "ai_chat", "audio_transcription", "image_analysis",
            "interactive_buttons", "interactive_lists",
            "commands_full", "read_receipts", "thinking_reactions",
            "quick_action_buttons",
            "news", "breaking_news", "weekly_summary", "trending",
            "web_search", "ask", "learn", "roadmap",
            "company_info", "subscribe", "language",
            "memory", "premium", "settings",
            "study_mode", "quiz", "exam",
            "youtube_summary", "pdf_analysis",
            "image_generation", "image_editing",
            "download", "favorites",
            "admin_system", "ban_system", "broadcast",
            "usage_tracking", "plan_system",
        ],
        "commands_count": len(_COMMAND_TRIGGERS),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ═══════════════════════════════════════
# Debug / Diagnostic Endpoint
# ═══════════════════════════════════════

async def debug_whatsapp(request: web.Request):
    """GET /debug/whatsapp — Full diagnostic"""
    import aiohttp as aio

    verify_token_set = bool(WHATSAPP_VERIFY_TOKEN)
    access_token_set = bool(WHATSAPP_ACCESS_TOKEN)
    phone_number_id_set = bool(WHATSAPP_PHONE_NUMBER_ID)
    app_secret_set = bool(WHATSAPP_APP_SECRET)

    meta_api_status = "unknown"
    token_info = None
    phone_number_info = None

    if WHATSAPP_ACCESS_TOKEN:
        try:
            async with aio.ClientSession() as session:
                url = "https://graph.facebook.com/v21.0/me?fields=id,name"
                headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
                async with session.get(url, headers=headers, timeout=aio.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        token_info = {"app_id": data.get("id", "N/A"), "app_name": data.get("name", "N/A")}
                        meta_api_status = "ok"
                    else:
                        meta_api_status = f"error_{resp.status}"
        except Exception as e:
            meta_api_status = f"error: {str(e)[:100]}"
    else:
        meta_api_status = "not_configured"

    if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
        try:
            async with aio.ClientSession() as session:
                url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}"
                headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
                async with session.get(url, headers=headers, timeout=aio.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        phone_number_info = {
                            "verified_name": data.get("verified_name", "N/A"),
                            "display_phone_number": data.get("display_phone_number", "N/A"),
                            "quality_rating": data.get("quality_rating", "N/A"),
                        }
        except Exception:
            pass

    ai_engine_status = "unknown"
    try:
        from ai_engine import smart_chat
        ai_engine_status = "ok"
    except ImportError as e:
        ai_engine_status = f"import_error: {str(e)[:80]}"
    except Exception as e:
        ai_engine_status = f"error: {str(e)[:80]}"

    groq_status = "unknown"
    try:
        from config import GROQ_API_KEY
        groq_status = "ok" if GROQ_API_KEY else "not_configured"
    except Exception:
        groq_status = "error"

    premium_status = "unknown"
    try:
        from premium import get_user_plan
        premium_status = "ok"
    except Exception as e:
        premium_status = f"error: {str(e)[:80]}"

    admin_status = "unknown"
    try:
        from admin import is_admin
        admin_status = "ok"
    except Exception as e:
        admin_status = f"error: {str(e)[:80]}"

    response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "webhook": {
            "verify_token_set": verify_token_set,
            "app_secret_set": app_secret_set,
        },
        "tokens": {
            "WHATSAPP_ACCESS_TOKEN": "set" if access_token_set else "MISSING",
            "WHATSAPP_PHONE_NUMBER_ID": "set" if phone_number_id_set else "MISSING",
            "WHATSAPP_VERIFY_TOKEN": "set" if verify_token_set else "MISSING",
            "WHATSAPP_APP_SECRET": "set" if app_secret_set else "MISSING",
        },
        "token_info": token_info,
        "phone_number": phone_number_info,
        "meta_api": meta_api_status,
        "ai_engine": ai_engine_status,
        "groq_asr": groq_status,
        "premium_system": premium_status,
        "admin_system": admin_status,
        "admin_wa_id": ADMIN_WA_ID,
        "features": [
            "interactive_buttons", "commands", "read_receipts", "thinking_reactions",
            "audio_transcription", "image_analysis", "pdf_analysis",
            "premium_system", "admin_system", "ban_system", "usage_tracking",
            "study_mode", "youtube_summary", "download", "image_generation",
            "image_editing", "favorites", "memory_system",
        ],
        "allowed_numbers": ALLOWED_WA_NUMBERS if ALLOWED_WA_NUMBERS else "all (no restriction)",
        "diagnosis": [],
    }

    issues = []
    for var_name in ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN"]:
        raw_val = os.environ.get(var_name, "")
        if raw_val.upper() == "PENDING":
            issues.append(f"🔧 {var_name} is set to 'PENDING'")
    if not WHATSAPP_ACCESS_TOKEN:
        issues.append("❌ WHATSAPP_ACCESS_TOKEN is not set")
    if not WHATSAPP_PHONE_NUMBER_ID:
        issues.append("❌ WHATSAPP_PHONE_NUMBER_ID is not set")
    if not WHATSAPP_VERIFY_TOKEN:
        issues.append("❌ WHATSAPP_VERIFY_TOKEN is not set")
    if not WHATSAPP_APP_SECRET:
        issues.append("⚠️ WHATSAPP_APP_SECRET is not set")
    if not issues:
        issues.append("✅ All systems operational")

    response["diagnosis"] = issues
    return web.json_response(response, status=200)


async def debug_whatsapp_activity(request: web.Request):
    """GET /debug/whatsapp/activity — Recent webhook activity."""
    return web.json_response({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_events": len(_webhook_activity_log),
        "events": _webhook_activity_log[-20:],
        "summary": {
            "webhook_posts": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post"),
            "messages_received": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post" and e.get("data", {}).get("has_messages")),
            "status_updates": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post" and e.get("data", {}).get("has_statuses")),
            "signature_failures": sum(1 for e in _webhook_activity_log if e["event_type"] == "signature_failed"),
            "ai_responses_sent": sum(1 for e in _webhook_activity_log if e["event_type"] == "ai_response_sent"),
            "ai_errors": sum(1 for e in _webhook_activity_log if e["event_type"] == "ai_error"),
            "messages_skipped": sum(1 for e in _webhook_activity_log if e["event_type"] == "message_skipped"),
        },
    }, status=200)


async def debug_rapidapi(request: web.Request):
    """GET /debug/rapidapi — Test RapidAPI YouTube download from Railway"""
    import time as _time
    
    test_video_id = request.query.get("video_id", "dQw4w9WgXcQ")
    test_format = request.query.get("format", "360")
    test_full = request.query.get("full", "0") == "1"
    
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_video_id": test_video_id,
        "test_format": test_format,
        "steps": {},
    }
    
    try:
        from youtube_rapidapi import (
            RAPIDAPI_KEY, RAPIDAPI_HOST, RAPIDAPI_BASE_URL,
            is_youtube_url, extract_video_id, download_youtube, download_youtube_file
        )
        
        # Step 1: Check environment
        results["steps"]["env_check"] = {
            "RAPIDAPI_KEY_set": bool(RAPIDAPI_KEY),
            "RAPIDAPI_KEY_prefix": RAPIDAPI_KEY[:10] + "..." if RAPIDAPI_KEY else "NOT SET",
            "RAPIDAPI_HOST": RAPIDAPI_HOST,
            "env_RAPIDAPI_KEY": os.environ.get("RAPIDAPI_KEY", "NOT SET")[:10] + "..." if os.environ.get("RAPIDAPI_KEY") else "NOT SET",
        }
        
        # Step 2: Test API connectivity
        t0 = _time.time()
        try:
            import requests as _req
            headers = {
                "x-rapidapi-host": RAPIDAPI_HOST,
                "x-rapidapi-key": RAPIDAPI_KEY,
                "Content-Type": "application/json",
            }
            init_resp = _req.get(
                f"{RAPIDAPI_BASE_URL}/api/v1/download",
                headers=headers,
                params={"id": test_video_id, "format": test_format},
                timeout=30,
            )
            t1 = _time.time()
            results["steps"]["api_connect"] = {
                "status": "ok",
                "http_status": init_resp.status_code,
                "response_time_ms": int((t1 - t0) * 1000),
            }
            
            if init_resp.status_code == 200:
                init_data = init_resp.json()
                progress_id = init_data.get("progressId")
                results["steps"]["api_connect"]["progressId"] = progress_id
                results["steps"]["api_connect"]["title"] = init_data.get("title")
                results["steps"]["api_connect"]["response_keys"] = list(init_data.keys())
                
                # Step 3: Test progress polling (just 3 attempts)
                if progress_id:
                    poll_results = []
                    for i in range(3):
                        _time.sleep(3)
                        try:
                            poll_resp = _req.get(
                                f"{RAPIDAPI_BASE_URL}/api/v1/progress",
                                headers=headers,
                                params={"id": progress_id},
                                timeout=30,
                            )
                            poll_data = poll_resp.json()
                            poll_results.append({
                                "attempt": i + 1,
                                "status": poll_resp.status_code,
                                "finished": poll_data.get("finished"),
                                "has_url": bool(poll_data.get("downloadUrl") or poll_data.get("url")),
                                "progress": poll_data.get("progress"),
                            })
                        except Exception as pe:
                            poll_results.append({"attempt": i + 1, "error": str(pe)})
                    
                    results["steps"]["polling"] = poll_results
                
                # Step 4: Full download test (optional)
                if test_full:
                    t2 = _time.time()
                    full_result = download_youtube(f"https://www.youtube.com/watch?v={test_video_id}", format=test_format)
                    t3 = _time.time()
                    results["steps"]["full_download"] = {
                        "success": full_result.get("success") if full_result else False,
                        "error": full_result.get("error") if full_result else "no_result",
                        "has_download_url": bool(full_result.get("download_url")) if full_result else False,
                        "time_ms": int((t3 - t2) * 1000),
                        "title": full_result.get("title", "") if full_result else "",
                    }
                    
                    # Step 5: File download test
                    if full_result and full_result.get("success") and full_result.get("download_url"):
                        t4 = _time.time()
                        file_result = download_youtube_file(
                            f"https://www.youtube.com/watch?v={test_video_id}",
                            format=test_format,
                            output_dir="/tmp"
                        )
                        t5 = _time.time()
                        results["steps"]["file_download"] = {
                            "success": file_result.get("success") if file_result else False,
                            "has_file_path": bool(file_result.get("file_path")) if file_result else False,
                            "file_size": file_result.get("file_size", 0) if file_result else 0,
                            "file_download_error": file_result.get("file_download_error", "") if file_result else "",
                            "time_ms": int((t5 - t4) * 1000),
                        }
                        # Cleanup
                        if file_result and file_result.get("file_path"):
                            try: os.remove(file_result["file_path"])
                            except: pass
            else:
                results["steps"]["api_connect"]["error_body"] = init_resp.text[:500]
                
        except Exception as api_err:
            results["steps"]["api_connect"] = {
                "status": "error",
                "error": str(api_err),
                "error_type": type(api_err).__name__,
            }
    
    except ImportError as imp_err:
        results["steps"]["module_import"] = {
            "status": "error",
            "error": str(imp_err),
        }
    except Exception as e:
        results["steps"]["unexpected_error"] = {
            "error": str(e),
            "error_type": type(e).__name__,
        }
    
    return web.json_response(results, status=200)


# ═══════════════════════════════════════
# Web Server Factory
# ═══════════════════════════════════════

def create_webhook_app() -> web.Application:
    """Create the aiohttp web application with webhook routes"""
    app = web.Application()

    app.router.add_get("/", root_handler)
    app.router.add_get("/whatsapp/webhook", webhook_verification)
    app.router.add_post("/whatsapp/webhook", webhook_receiver)
    app.router.add_get("/health", health_check)
    app.router.add_get("/debug/whatsapp", debug_whatsapp)
    app.router.add_get("/debug/whatsapp/activity", debug_whatsapp_activity)
    app.router.add_get("/debug/rapidapi", debug_rapidapi)

    logger.info("✅ WhatsApp webhook routes registered")
    logger.info(f"   GET  /whatsapp/webhook — Meta verification")
    logger.info(f"   POST /whatsapp/webhook — Incoming messages → AI engine")
    logger.info(f"   GET  /health — Health check")
    logger.info(f"   GET  /debug/whatsapp — Full diagnostic")
    logger.info(f"   GET  /debug/whatsapp/activity — Webhook activity log")
    logger.info(f"   GET  /debug/rapidapi — RapidAPI connectivity test")
    logger.info(f"   🔥 AI Integration: smart_chat() with Arabic support")
    logger.info(f"   🎤 Audio: Groq Whisper transcription")
    logger.info(f"   👁️ Vision: Image analysis via NVIDIA/Mistral")
    logger.info(f"   📄 PDF: Document analysis")
    logger.info(f"   🔘 Interactive: Buttons & Lists (like Telegram keyboards)")
    logger.info(f"   📋 Commands: {len(_COMMAND_TRIGGERS)} triggers — full Telegram parity")
    logger.info(f"   💭 Thinking: Reactions only (💭 → ✅)")
    logger.info(f"   📰 News: daily, breaking, weekly, trending, company")
    logger.info(f"   📚 Learning: learn, roadmap, ask, search, study, quiz, exam")
    logger.info(f"   ⚙️ Settings: language, subscribe, memory, premium, plan")
    logger.info(f"   👑 Admin: grant, revoke, ban, unban, broadcast, stats")
    logger.info(f"   ⭐ Premium: plan system, usage tracking, limit enforcement")
    logger.info(f"   🎨 Image Gen & Edit: Premium features")
    logger.info(f"   📥 Download: YouTube/social media")
    logger.info(f"   🎬 YouTube: Summary")
    logger.info(f"   🧠 Memory: view, reset, favorites")
    logger.info(f"   📊 Usage: limits, remaining, plan display")

    logger.info(f"   📋 Config: VERIFY_TOKEN={'✅' if WHATSAPP_VERIFY_TOKEN else '❌'}, "
                f"ACCESS_TOKEN={'✅' if WHATSAPP_ACCESS_TOKEN else '❌'}, "
                f"PHONE_ID={'✅' if WHATSAPP_PHONE_NUMBER_ID else '❌'}, "
                f"APP_SECRET={'✅' if WHATSAPP_APP_SECRET else '⚠️ not set'}")
    logger.info(f"   🔒 Allowed numbers: {ALLOWED_WA_NUMBERS if ALLOWED_WA_NUMBERS else 'all (no restriction)'}")
    logger.info(f"   👑 Admin WA ID: {ADMIN_WA_ID}")

    return app


async def start_webhook_server():
    """Start the webhook HTTP server"""
    app = create_webhook_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()

    logger.info(f"🌐 WhatsApp webhook server listening on port {WEBHOOK_PORT}")
    logger.info(f"🤖 AI Engine: smart_chat() ready for WhatsApp messages!")

    return runner
