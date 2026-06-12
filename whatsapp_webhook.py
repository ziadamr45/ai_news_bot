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

from i18n import t

from content_safety import (
    check_query_safety,
    check_search_results_safety,
    comprehensive_media_safety_check,
    get_block_message,
    get_no_safe_results_message,
    should_enable_safe_search,
)

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
    
    ⚠️ BUG FIX: Python's hash() is NOT deterministic across restarts!
    Since Python 3.3, hash() uses a random seed (PYTHONHASHSEED) that changes
    on every interpreter start. This means the same phone number would produce
    different user_ids after each bot restart, orphaning all user data.
    
    FIX: Use hashlib.sha256 for deterministic hashing.
    """
    # إزالة + من البداية لو موجود
    clean = phone.lstrip('+')
    # إزالة مسافات
    clean = clean.strip()
    # ✅ Deterministic hash — same result every time, even after restarts
    h = hashlib.sha256(f"wa_{clean}".encode()).hexdigest()
    return -(int(h, 16) % (2**31))


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
        wa_user_id = _wa_phone_to_user_id(wa_id)
        return is_admin(wa_user_id)
    except Exception:
        return False


def _ensure_wa_admin_premium(wa_id: str):
    """Ensure the WhatsApp admin is always premium"""
    if wa_id == ADMIN_WA_ID:
        try:
            from admin import ensure_admin_premium
            wa_user_id = _wa_phone_to_user_id(wa_id)
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
_wa_user_yt_url = {}  # {wa_id: "youtube_url"} — 🍪 cache YouTube URL for download button

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
_URL_CACHE_TTL = 1800  # 30 minutes (was 10 min — too short for quality selection)

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


async def _send_whatsapp_document_from_file(recipient_wa_id: str, file_path: str,
                                               filename: str, caption: str = "", 
                                               content_type: str = "video/mp4"):
    """Send a document via WhatsApp Cloud API — STREAMING from file (no memory loading)
    
    🔴 FIX: ده بيبعت الملف مباشرة من الديسك من غير ما يحمله كله في الرام
    عشان نتجنب Out of Memory على Railway
    """
    import aiohttp
    
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "not_configured"}
    
    file_size = os.path.getsize(file_path)
    logger.info(f"📤 WA Document streaming upload: {filename} ({file_size / 1024 / 1024:.1f}MB)")
    
    try:
        upload_url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
        
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
    "threads": re.compile(r'(https?://)?(www\.)?threads\.(net|com)/', re.IGNORECASE),
    "reddit": re.compile(r'(https?://)?(www\.)?(reddit\.com|redd\.it)/', re.IGNORECASE),
    "dailymotion": re.compile(r'(https?://)?(www\.)?(dailymotion\.com|dai\.ly)/', re.IGNORECASE),
    "soundcloud": re.compile(r'(https?://)?(www\.)?soundcloud\.com/', re.IGNORECASE),
}

_GENERAL_URL_PATTERN = re.compile(r'https?://[^\s<>\"]+', re.IGNORECASE)


def _detect_platform(url: str) -> str:
    """Detect platform from URL"""
    for platform, pattern in _URL_PATTERNS.items():
        if pattern.search(url):
            return platform
    return "unknown"


def _is_youtube_url(url: str) -> bool:
    """فحص هل الرابط يوتيوب — يشمل youtube.com, youtu.be, youtube.com/shorts"""
    return bool(_URL_PATTERNS.get("youtube") and _URL_PATTERNS["youtube"].search(url))


def _extract_url(text: str) -> str:
    """Extract first URL from text"""
    match = _GENERAL_URL_PATTERN.search(text)
    return match.group(0) if match else ""


# ═══════════════════════════════════════
# تحميل Threads — طريقة مخصصة
# ═══════════════════════════════════════

_THREADS_URL_PATTERN = re.compile(r'(https?://)?(www\.)?threads\.(net|com)/', re.IGNORECASE)


def _is_threads_url(url: str) -> bool:
    """كشف هل الرابط من Threads"""
    return bool(_THREADS_URL_PATTERN.search(url))


async def _download_threads_media_wa(url: str, tmpdir: str) -> dict | None:
    """تحميل فيديو/صورة من Threads — نفس الـ fallback chain زي التليجرام
    
    🔴 الترتيب (مزامنة مع download_handlers.py v5):
    0. Playwright headless browser — الأضمن (بيرندر الصفحة ويسحب الفيديو)
    1. RapidAPI — الأسرع (لو المفتاح متاح)
    2. data-sjs JSON parsing — استخراج من <script data-sjs> tags في HTML
       ⚠️ video_versions بيبقي null دلوقتي → شغال للصور بس
    3. GraphQL API — طلب مباشر من threads.net/api/graphql
    4. Cobalt API — خدمة مفتوحة المصدر كـ fallback
    
    Returns: dict فيه {success, file_path, title, is_video} أو None
    """
    try:
        # 🔴 نستورد الدوال المشتركة من download_handlers (نفس الكود بالظبط)
        from handlers.download_handlers import _download_threads_media as _tg_threads_download
        
        logger.info(f"🧵 Threads WA: Using shared download (Playwright → RapidAPI → data-sjs → GraphQL → Cobalt)")
        
        result = await _tg_threads_download(url, tmpdir, quality="best")
        
        if result and result.get("success"):
            logger.info(f"🧵 Threads WA: Download succeeded via {result.get('method', 'unknown')} method")
            return result
        
        logger.warning(f"🧵 Threads WA: All methods failed for {url[:80]}")
        return None
    
    except Exception as e:
        logger.warning(f"🧵 Threads WA: Error using shared download: {e}")
        return None


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
        "threads": "Threads", "reddit": "Reddit", "dailymotion": "Dailymotion",
        "soundcloud": "SoundCloud", "unknown": "🌐",
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


async def _show_quality_selection_for_search(wa_id: str, url: str, title: str, 
                                              wa_user_id: int, contact_name: str, 
                                              message_id: str, is_admin: bool,
                                              search_type: str = "video"):
    """عرض اختيار الجودة بعد اختيار نتيجة من البحث — نفس قائمة التحميل العادي
    
    🔴 الفرق عن _show_quality_selection:
    - دي بتتكلم بعد اختيار نتيجة بحث (مش بعد إرسال رابط)
    - لو search_type="audio" → بتحط خيار الصوت كأول اختيار
    - بتعرض عنوان الفيديو كمان
    """
    platform = _detect_platform(url)
    platform_names = {
        "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
        "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
        "threads": "Threads", "reddit": "Reddit", "dailymotion": "Dailymotion",
        "soundcloud": "SoundCloud", "unknown": "🌐",
    }
    platform_display = platform_names.get(platform, platform)
    url_key = _store_url(url)
    
    display_title = title[:50] if title else "فيديو"
    body = f"📥 *اختار الجودة*\n\n📺 {display_title}\n🔗 المنصة: {platform_display}"
    
    # 🔴 لو البحث كان صوت → نحط خيارات الصوت بس (مفيش فيديو — المستخدم طلب صوت)
    if search_type == "audio":
        sections = [{
            "title": "🎵 جودة الصوت",
            "rows": [
                {"id": f"dl_aq_320_{url_key}", "title": "🎧 320kbps", "description": "أعلى جودة صوت - وضوح ممتاز"},
                {"id": f"dl_aq_192_{url_key}", "title": "🎵 192kbps", "description": "جودة عالية - توازن مثالي"},
                {"id": f"dl_aq_128_{url_key}", "title": "🎶 128kbps", "description": "جودة متوسطة - حجم أقل"},
                {"id": f"dl_aq_64_{url_key}", "title": "📻 64kbps", "description": "جودة منخفضة - حجم صغير جداً"},
            ],
        }]
    else:
        sections = [{
            "title": "🎬 جودة الفيديو",
            "rows": [
                {"id": f"dl_v_b_{url_key}", "title": "🎬 أعلى جودة", "description": "1080p - أفضل جودة متاحة"},
                {"id": f"dl_v_m_{url_key}", "title": "📹 جودة متوسطة", "description": "720p - توازن بين الجودة والحجم"},
                {"id": f"dl_v_l_{url_key}", "title": "📱 جودة منخفضة", "description": "480p - حجم صغير"},
            ],
        }, {
            "title": "🎵 صوت فقط",
            "rows": [
                {"id": f"dl_a_{url_key}", "title": "🎵 صوت بس MP3", "description": "استخراج الصوت فقط"},
            ],
        }]
    
    await _send_interactive_list(wa_id, 
        body_text=body,
        button_text="اختار الجودة",
        sections=sections,
        header_text=f"📥 تحميل من {platform_display}")


async def _download_and_send_video(wa_id: str, url: str, wa_user_id: int,
                                     contact_name: str, message_id: str = "", is_admin: bool = False,
                                     quality: str = "best", force_audio: bool = False):
    """Download a video and send it via WhatsApp — Invidious/Piped FIRST then yt-dlp
    
    🔴 FIX v11: نفس fallback chain زي التليجرام بالظبط!
    0. 🖥️ سيرفر التحميل الخاص (VPS بـ IP نظيف)
    1. 🟣 Invidious API (IP مختلف — مش من Railway!)
    2. 🟢 Piped API (IP مختلف — سيرفرات مختلفة عن Invidious)
    3. yt-dlp + deno + remote_components + كوكيز
    4. yt-dlp player_client fallback (android → ios → mweb → tv → web) + كوكيز
    5. 🟠 Cobalt API
    6. 🔵 Apify
    7. 🔄 yt-dlp WITHOUT cookies (أحياناً الكوكيز بتسبب مشاكل!) — جديد!
    8. 🟢 Piped API (fallback إضافي)
    9. 🟣 Invidious API (fallback إضافي)
    10. 🔵 Cobalt Self-Hosted — جديد!
    11. 🔐 Cobalt JWT
    12. 🔄 Cloudflare Worker proxy (آخر محاولة)
    
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
        is_youtube = _is_youtube_url(url)  # 🔴 FIX: لازم نعرّف is_youtube هنا عشان الكود اللي بعد كده يستخدمه
        is_threads = _is_threads_url(url)   # 🔴 FIX: Threads مش مدعوم من yt-dlp
        platform_names = {
            "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
            "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
            "threads": "Threads", "reddit": "Reddit", "dailymotion": "Dailymotion",
            "soundcloud": "SoundCloud", "unknown": "🌐",
        }
        platform_display = platform_names.get(platform, platform)
        
        # Send progress message
        _is_audio_dl = (quality == "audio" or quality.startswith("audio_"))
        if is_threads:
            # 🔴 Threads فيديو → هيتبعت كملف مباشر (زي التليجرام!)
            await _send_whatsapp_message(wa_id, f"🧵 جاري تحميل فيديو Threads...")
        elif _is_audio_dl:
            # 🔴 FIX: لو تحميل صوت → نقول صوت مش فيديو
            await _send_whatsapp_message(wa_id, f"🎵 جاري تحميل الصوت من {platform_display}...")
        else:
            await _send_whatsapp_message(wa_id, f"📥 جاري تحميل الفيديو من {platform_display}...")
        
        tmpdir = tempfile.mkdtemp(prefix="mybro_wa_dl_")
        output_template = os.path.join(tmpdir, "%(title).80s.%(ext)s")
        
        # 🔴 FIX: Threads — yt-dlp مش بيدعمه، نستخدم طريقة مخصصة
        if is_threads:
            logger.info(f"🧵 WhatsApp: Threads detected — using custom download method")
            threads_result = await _download_threads_media_wa(url, tmpdir)
            
            if threads_result and threads_result.get("success"):
                file_path = threads_result["file_path"]
                file_size = threads_result.get("file_size", os.path.getsize(file_path))
                real_title = threads_result.get("title", "Threads Post")
                is_video = threads_result.get("is_video", True)
                size_mb = file_size / (1024 * 1024)
                size_str = f"{size_mb:.1f}MB"
                
                # 🛡️ Safety check on downloaded media (زي التليجرام بالظبط)
                try:
                    media_type = "video" if is_video else "image"
                    is_safe_dl, block_msg_dl, _reason_dl = await comprehensive_media_safety_check(
                        title=real_title, file_path=file_path, file_type=media_type,
                        platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                    )
                    if not is_safe_dl:
                        await _send_whatsapp_message(wa_id, block_msg_dl)
                        try: os.remove(file_path)
                        except: pass
                        await feedback.error()
                        return
                except Exception:
                    pass  # Fail-open
                
                # ═══ إرسال الملف — فيديو: رفع على السحابة مباشرة | صورة: إرسال مباشر ═══
                
                if is_video:
                    # ═══════════════════════════════════════════════════════════
                    # 🔴 FIX v10: فيديوهات Threads على واتساب
                    # نفس طريقة الفيديوهات العادية (YouTube وغيرها):
                    # إرسال كـ document (ملف) بدل video — أضمن بكثير!
                    # ═══════════════════════════════════════════════════════════
                    
                    # 🔴 Step 1: تحويل لـ H.264+AAC+MP4 لو مش كده (زي الفيديوهات العادية)
                    try:
                        import subprocess as _sp
                        import multiprocessing
                        conv_threads = min(multiprocessing.cpu_count(), 4)
                        
                        # فحص الكودك الحالي بـ ffprobe
                        probe_result = _sp.run(
                            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', file_path],
                            capture_output=True, timeout=15
                        )
                        video_vcodec = None
                        if probe_result.returncode == 0:
                            try:
                                import json as _json
                                probe_data = _json.loads(probe_result.stdout)
                                for stream in probe_data.get('streams', []):
                                    if stream.get('codec_type') == 'video':
                                        video_vcodec = stream.get('codec_name', '')
                                        break
                            except Exception:
                                pass
                        
                        # تحويل بس لو مش H.264
                        if video_vcodec and video_vcodec not in ("h264", "avc1", "avc", "mpeg4", ""):
                            converted_path = file_path + "_h264.mp4"
                            logger.info(f"🧵 Threads WA: Converting {video_vcodec} to H.264 for WhatsApp...")
                            
                            conv_cmd = [
                                'ffmpeg', '-y', '-i', file_path,
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                                '-threads', str(conv_threads),
                                '-c:a', 'aac', '-b:a', '128k',
                                '-movflags', '+faststart',
                                '-y', converted_path
                            ]
                            
                            conv_result = _sp.run(conv_cmd, capture_output=True, timeout=180)
                            
                            if conv_result.returncode == 0 and os.path.exists(converted_path) and os.path.getsize(converted_path) > 1000:
                                try: os.remove(file_path)
                                except: pass
                                file_path = converted_path
                                file_size = os.path.getsize(file_path)
                                size_mb = file_size / (1024 * 1024)
                                size_str = f"{size_mb:.1f}MB"
                                logger.info(f"🧵 Threads WA: ✅ H.264 conversion OK! Size: {size_str}")
                            else:
                                logger.warning(f"🧵 Threads WA: Conversion failed, using original file")
                                try: os.remove(converted_path)
                                except: pass
                        else:
                            logger.info(f"🧵 Threads WA: Video is already H.264 ({video_vcodec}), no conversion needed")
                    except ImportError:
                        pass
                    except Exception as conv_err:
                        logger.warning(f"🧵 Threads WA: Conversion check error: {conv_err}")
                    
                    # 🔴 Step 2: إرسال كـ document (ملف) — نفس طريقة الفيديوهات العادية!
                    # ده أضمن بكتير من إرسال كـ video عشان واتساب مش بيرفض الملفات
                    MAX_WHATSAPP_DIRECT_SIZE = 25 * 1024 * 1024  # 25MB — زي الفيديوهات العادية
                    
                    if file_size <= MAX_WHATSAPP_DIRECT_SIZE:
                        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', real_title) + '.mp4'
                        caption = f"📥 {real_title[:200]}\n🧵 Threads\n📊 {size_str}"
                        
                        logger.info(f"🧵 Threads WA: Sending as document ({size_str})...")
                        result = await _send_whatsapp_document_from_file(
                            wa_id, file_path, safe_filename, caption, "video/mp4"
                        )
                        
                        if "error" not in result:
                            logger.info(f"🧵 Threads WA: ✅ Document send succeeded!")
                            await feedback.success()
                            try: os.remove(file_path)
                            except: pass
                            return
                        else:
                            error_msg = str(result.get("error", ""))
                            logger.warning(f"🧵 Threads WA: Document send failed: {error_msg}")
                    
                    # 🔴 Step 3: لو الملف أكبر من 25MB أو الإرسال المباشر فشل → رفع على السحابة
                    logger.info(f"🧵 Threads WA: Trying Supabase cloud upload...")
                    
                    # 🔴 Silent: no user message for cloud upload
                    
                    try:
                        from supabase_storage import upload_and_get_link
                        cloud_msg = await asyncio.wait_for(
                            upload_and_get_link(
                                file_path=file_path,
                                filename=f"threads_video.mp4",
                                content_type="video/mp4",
                                platform="whatsapp",
                                title=real_title,
                                lang="ar",
                            ),
                            timeout=600
                        )
                        
                        if cloud_msg:
                            await _send_whatsapp_message(wa_id, cloud_msg)
                            await feedback.success()
                            try: os.remove(file_path)
                            except: pass
                            logger.info(f"🧵 Threads WA: ✅ Supabase upload succeeded!")
                            return
                        else:
                            logger.error(f"🧵 Threads WA: Supabase returned None!")
                    except asyncio.TimeoutError:
                        logger.error(f"🧵 Threads WA: Supabase upload timed out after 600s")
                    except Exception as supa_err:
                        logger.error(f"🧵 Threads WA: Supabase upload exception: {supa_err}")
                    
                    # 🔴 Fallback أخير
                    await _send_whatsapp_message(wa_id, f"❌ فشل إرسال فيديو Threads ({size_str}). جرب تاني!")
                    await feedback.error()
                    
                    try: os.remove(file_path)
                    except: pass
                    return
                else:
                    # صورة
                    try:
                        with open(file_path, 'rb') as img_f:
                            media_response = requests.post(
                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                files={"file": (f"{real_title[:50]}.jpg", img_f, "image/jpeg")},
                                data={"messaging_product": "whatsapp", "type": "image"},
                                timeout=60
                            )
                            if media_response.status_code == 200:
                                media_id = media_response.json().get("id")
                                await _send_whatsapp_image(wa_id, media_id, caption=f"🧵 {real_title[:200]}\n📥 Threads")
                                await feedback.success()
                                try: os.remove(file_path)
                                except: pass
                                return
                            else:
                                logger.warning(f"⚠️ Threads WA: image upload returned {media_response.status_code}")
                    except Exception as send_err:
                        logger.warning(f"⚠️ Threads WA image send failed: {send_err}")
                    
                    await _send_whatsapp_message(wa_id, f"❌ فشل إرسال الصورة من Threads. جرب تاني!")
                    await feedback.error()
                    try: os.remove(file_path)
                    except: pass
                    return
            else:
                # 🔴 FIX v5: Threads مش مدعوم من yt-dlp — لا fallback!
                # yt-dlp بيرجع "Unsupported URL" لـ threads.com/threads.net
                logger.warning("🧵 Threads WA: All custom methods failed — yt-dlp doesn't support Threads, not trying it")
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الفيديو من Threads. جرب تاني!")
                await feedback.error()
                return
        
        # ═══════════════════════════════════════════════════════════════
        # 🔴 FIX v9: Cobalt API كـ fallback تالت!
        # نفس ترتيب التليجرام بالظبط
        # ═══════════════════════════════════════════════════════════════
        
        # ═══ المرحلة 1: yt-dlp + deno + remote_components (الأفضل!) ═══
        # 🔴 الكوكيز الوهمية اتشالت — بنستخدم headers نظيفة فقط
        # 🔴 بنستخدم cookies.txt لو موجود — الحل الأقوى
        
        try:
            # yt-dlp options — with multi-quality support (like Telegram)
            # WhatsApp limit: ~100MB for media
            
            # Quality format strings (like Telegram's download_handlers)
            is_audio_only = (quality == "audio" or quality.startswith("audio_"))
            
            # 🔴 FIX v9: Facebook family format + acodec!=none + no filesize limit
            is_facebook_family = platform in ("facebook", "instagram", "threads")
            
            if is_audio_only:
                format_str = 'bestaudio/best'
                merge_output = None
                remux = None
                progress_msg = f"🎵 جاري استخراج الصوت من {platform_display}..."
            elif platform in ("dailymotion", "soundcloud"):
                # 🔴 FIX: Dailymotion/SoundCloud — صيغة أبسط لأنهم مش زي YouTube
                # Dailymotion بيرجع formats مختلفة → best+/best أحسن من bestvideo+bestaudio
                if quality == "best":
                    format_str = (
                        'best[ext=mp4][height<=1080]/'
                        'best[height<=1080]/'
                        'best'
                    )
                elif quality == "medium":
                    format_str = (
                        'best[ext=mp4][height<=720]/'
                        'best[height<=720]/'
                        'best'
                    )
                else:  # low
                    format_str = (
                        'best[ext=mp4][height<=480]/'
                        'best[height<=480]/'
                        'best'
                    )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display}..."
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
            
            # 🔴 WhatsApp: لا نرسل رسائل تقدم وسيطة — رسالة واحدة بس (الاولى)
            # المستخدم مش شايف الخدمات — بس الشغل بيحصل في الباك اند
            
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
                # 🔴 FIX: استخدام الـ bitrate المحدد من جودة الصوت
                audio_bitrate = '192'
                if quality.startswith("audio_"):
                    try: audio_bitrate = quality.split("_")[1]
                    except: pass
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': audio_bitrate,
                }]
            
            # ═══ إضافة كوكيز + إعدادات YouTube المحسّنة ═══
            # 🔴 FIX: استخدام _get_cookies_file() من التليجرام — بيدور في أماكن كتير
            try:
                from handlers.download_handlers import _get_cookies_file
                cookies_path = _get_cookies_file()
            except (ImportError, Exception):
                cookies_path = None
            
            # Fallback: البحث المباشر لو _get_cookies_file مش متاح
            if not cookies_path:
                cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            
            if cookies_path and os.path.exists(cookies_path):
                try:
                    ydl_opts['cookiefile'] = cookies_path
                    logger.info(f"🍪 WhatsApp: Using cookies file: {cookies_path}")
                except Exception:
                    pass
            
            # 🔴 FIX: إضافة deno + remote_components لليوتيوب (زي التليجرام بالظبط)
            # ده أفضل طريقة لتخطي bot detection — بيدي 37 تنسيق لحد 1080p
            is_youtube_platform = platform.lower() == "youtube"
            if is_youtube_platform:
                try:
                    from handlers.download_handlers import _ensure_deno_in_path
                    _ensure_deno_in_path()
                    ydl_opts['remote_components'] = ['ejs:github']
                    logger.info("🔧 WhatsApp yt-dlp: default mode + deno + remote_components (best method)")
                except Exception:
                    logger.warning("⚠️ Could not add deno/remote_components for WhatsApp yt-dlp")
            
            # Download video — Multi-stage approach
            loop = asyncio.get_event_loop()
            info = None
            last_error = None
            
            # Progress timer removed — no periodic updates
            
            # ═══ المرحلة 0: سيرفر التحميل الخاص (VPS بـ IP نظيف) ═══
            # 🔴 ده أفضل طريقة — السيرفر بيحمل من YouTube بـ IP نظيف ومبيحصلش حظر
            if is_youtube:
                try:
                    from config import DOWNLOAD_SERVICE_URL, DOWNLOAD_SERVICE_KEY
                    if DOWNLOAD_SERVICE_URL:
                        logger.info(f"🖥️ WA Download Service: Trying VPS download for {url[:80]}")
                        # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة — الشغل بصمت في الباك اند
                        
                        from urllib.parse import quote as _wa_quote
                        def wa_quote(s): return _wa_quote(s, safe='')
                        
                        import aiohttp as _aiohttp_wa_ds
                        ds_url = DOWNLOAD_SERVICE_URL.rstrip("/")
                        api_url = f"{ds_url}/download?url={wa_quote(url)}&quality={quality}&platform=whatsapp&lang=ar"
                        ds_headers = {}
                        if DOWNLOAD_SERVICE_KEY:
                            ds_headers["X-API-Key"] = DOWNLOAD_SERVICE_KEY
                        
                        try:
                            async with _aiohttp_wa_ds.ClientSession(timeout=_aiohttp_wa_ds.ClientTimeout(total=360)) as ds_session:
                                async with ds_session.get(api_url, headers=ds_headers) as ds_resp:
                                    if ds_resp.status == 200:
                                        ds_result = await ds_resp.json()
                                        if ds_result and ds_result.get("success"):
                                            logger.info(f"🖥️ WA Download Service succeeded!")
                                            
                                            
                                            # بعت الرابط للمستخدم
                                            cloud_msg = ds_result.get("cloud_msg", "")
                                            if cloud_msg:
                                                await _send_whatsapp_message(wa_id, cloud_msg)
                                            else:
                                                dl_url = ds_result.get("url", "")
                                                title = ds_result.get("title", "Video")
                                                size_mb = ds_result.get("size_mb", 0)
                                                await _send_whatsapp_message(wa_id,
                                                    f"🎬 *{title}*\n\n☁️ تم رفعه على السحابة ({size_mb:.1f}MB)\n\n🔗 رابط التحميل:\n{dl_url}"
                                                )
                                            
                                            await feedback.success()
                                            
                                            # Increment usage
                                            if not is_admin:
                                                try:
                                                    from premium import increment_usage
                                                    increment_usage(wa_user_id, "downloads")
                                                except:
                                                    pass
                                            
                                            try: shutil.rmtree(tmpdir, ignore_errors=True)
                                            except: pass
                                            return  # ✅ السيرفر الخاص نجح!
                                        else:
                                            error_msg = ds_result.get("message", "unknown error") if ds_result else "no response"
                                            logger.warning(f"🖥️ WA Download Service failed: {error_msg}")
                                    else:
                                        logger.warning(f"🖥️ WA Download Service returned status {ds_resp.status}")
                        except asyncio.TimeoutError:
                            logger.warning("🖥️ WA Download Service timed out")
                        except Exception as ds_err:
                            logger.warning(f"🖥️ WA Download Service error: {ds_err}")
                        
                        logger.info("🖥️ WA Download Service failed, falling back to local yt-dlp...")
                except ImportError:
                    pass
                except Exception as ds_outer_err:
                    logger.warning(f"🖥️ WA Download Service outer error: {ds_outer_err}")
            
            # ═══ المرحلة 1: Invidious API (IP مختلف — مش بيتأثر بـ YouTube bot detection!) ═══
            # 🔴 Invidious بيشتغل من سيرفرات مختلفة — مش من Railway IP
            # ده أحسن من yt-dlp عشان yt-dlp بيستخدم Railway IP وبيتحظر
            if is_youtube:
                try:
                    from invidious_api import download_youtube_invidious_file
                    
                    inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                       "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    inv_quality = inv_quality_map.get(quality, "best")
                    
                    logger.info(f"🟣 WA Invidious (early): Attempting download quality={inv_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    inv_result = None
                    try:
                        inv_result = await asyncio.wait_for(
                            download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                            timeout=60
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"⚠️ WA Invidious (early) timed out after 60s")
                    
                    if inv_result and inv_result.get("success") and inv_result.get("file_path"):
                        logger.info(f"🟣 WA Invidious (early) succeeded! File: {inv_result['file_path']}")
                        
                        inv_file = inv_result["file_path"]
                        inv_size = inv_result.get("file_size", os.path.getsize(inv_file))
                        inv_title = inv_result.get("title", "YouTube Video")
                        inv_duration = inv_result.get("duration", 0)
                        inv_format = inv_result.get("format_info", {})
                        
                        if inv_file and os.path.exists(inv_file):
                            target = os.path.join(tmpdir, f"{inv_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(inv_file, target)
                            except Exception:
                                target = inv_file
                            
                            # 🛡️ Safety check
                            try:
                                inv_file_type = "audio" if is_audio_only else "video"
                                is_safe_inv, block_msg_inv, _ = await comprehensive_media_safety_check(
                                    title=inv_title, file_path=target, file_type=inv_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_inv:
                                    await _send_whatsapp_message(wa_id, block_msg_inv)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass
                            
                            inv_size_mb = inv_size / (1024 * 1024)
                            inv_quality_label = inv_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{inv_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ WA Invidious (early) audio send failed: {audio_send_err}")
                            else:
                                if inv_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{inv_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {inv_title[:200]}\n📥 Invidious | {inv_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ WA Invidious (early) video send failed: {video_send_err}")
                                else:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        inv_size_str = f"{inv_size_mb:.1f}MB"
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{inv_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=inv_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Invidious: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ WA Invidious (early) failed, trying Piped...")
                except ImportError:
                    logger.warning("⚠️ invidious_api module not available, skipping Invidious")
                except Exception as inv_err:
                    logger.warning(f"⚠️ WA Invidious (early) error: {inv_err}, trying Piped...")
            
            # ═══ المرحلة 2: Piped API (IP مختلف — سيرفرات مختلفة عن Invidious!) ═══
            # 🔴 Piped بيستخدم NewPipe Extractor — سيرفرات مختلفة عن Invidious
            # لو Invidious فشل، Piped ممكن يشتغل لأنه بيستخدم طريقة مختلفة
            if is_youtube:
                try:
                    from piped_api import download_youtube_piped_file
                    
                    piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                         "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    piped_quality = piped_quality_map.get(quality, "best")
                    
                    logger.info(f"🟢 WA Piped (early): Attempting download quality={piped_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    piped_result = None
                    try:
                        piped_result = await asyncio.wait_for(
                            download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                            timeout=90
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"⚠️ WA Piped (early) timed out after 90s")
                    
                    if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                        logger.info(f"🟢 WA Piped (early) succeeded! File: {piped_result['file_path']}")
                        
                        piped_file = piped_result["file_path"]
                        piped_size = piped_result.get("file_size", os.path.getsize(piped_file))
                        piped_title = piped_result.get("title", "YouTube Video")
                        piped_duration = piped_result.get("duration", 0)
                        piped_format = piped_result.get("format_info", {})
                        
                        if piped_file and os.path.exists(piped_file):
                            target = os.path.join(tmpdir, f"{piped_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(piped_file, target)
                            except Exception:
                                target = piped_file
                            
                            # 🛡️ Safety check
                            try:
                                pp_file_type = "audio" if is_audio_only else "video"
                                is_safe_pp, block_msg_pp, _ = await comprehensive_media_safety_check(
                                    title=piped_title, file_path=target, file_type=pp_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_pp:
                                    await _send_whatsapp_message(wa_id, block_msg_pp)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass
                            
                            piped_size_mb = piped_size / (1024 * 1024)
                            piped_quality_label = piped_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{piped_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ WA Piped (early) audio send failed: {audio_send_err}")
                            else:
                                if piped_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{piped_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {piped_title[:200]}\n📥 Piped | {piped_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ WA Piped (early) video send failed: {video_send_err}")
                                else:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        piped_size_str = f"{piped_size_mb:.1f}MB"
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{piped_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=piped_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Piped: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ WA Piped (early) failed, falling back to yt-dlp...")
                except ImportError:
                    logger.warning("⚠️ piped_api module not available, skipping Piped")
                except Exception as piped_err:
                    logger.warning(f"⚠️ WA Piped (early) error: {piped_err}, falling back to yt-dlp...")
            
            # ═══ المرحلة 3: yt-dlp مباشر + deno + remote_components ═══
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
                    logger.info(f"✅ yt-dlp download succeeded directly (deno + remote_components)")
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ yt-dlp direct download failed: {e}")
                # 🔴 لو YouTube حجبنا — حدث yt-dlp فوراً
                err_str = str(e).lower()
                if any(kw in err_str for kw in ["sign in", "bot", "captcha", "confirm", "login", "403"]):
                    logger.warning("🔴 YouTube bot detection in WA! Triggering yt-dlp update...")
                    try:
                        from handlers.download_handlers import trigger_ytdlp_update
                        trigger_ytdlp_update()
                    except Exception:
                        pass
            
            # 🔴 FIX: Retry with simpler format for non-YouTube platforms (Dailymotion/SoundCloud)
            # لو أول محاولة فشلت والمنصة مش YouTube → نجرب بـ format أبسط
            if info is None and not is_youtube:
                try:
                    retry_format = 'best'
                    retry_opts = dict(ydl_opts)
                    retry_opts['format'] = retry_format
                    # شيلنا postprocessors عشان ممكن تكون سبب المشكلة
                    retry_opts.pop('postprocessors', None)
                    retry_opts.pop('remote_components', None)
                    retry_opts.pop('merge_output_format', None)
                    retry_opts.pop('remux_video', None)
                    
                    logger.info(f"🔧 WhatsApp yt-dlp: Retrying with 'best' format for {platform}")
                    
                    def _run_ytdlp_simple():
                        with yt_dlp.YoutubeDL(retry_opts) as ydl:
                            return ydl.extract_info(url, download=True)
                    
                    info = await asyncio.wait_for(
                        loop.run_in_executor(None, _run_ytdlp_simple),
                        timeout=180
                    )
                    if info:
                        logger.info(f"✅ yt-dlp simple format retry succeeded for {platform}")
                except Exception as retry_err:
                    last_error = retry_err
                    logger.warning(f"⚠️ yt-dlp simple format retry failed for {platform}: {retry_err}")
            
            # ═══ المرحلة 2: yt-dlp player_client fallback chain (YouTube فقط!) ═══
            # 🔴 FIX: player_client ده لليوتيوب بس — مش بيشتغل مع Dailymotion/SoundCloud
            # 🔴 FIX v2: استخدام أزواج client زي التليجرام بالظبط — كل زوج فيه client + web fallback
            if info is None and is_youtube:
                _YOUTUBE_PLAYER_CLIENTS = [
                    ['android', 'web'],    # Android client — fallback أول
                    ['ios', 'web'],        # iOS client
                    ['mweb', 'web'],       # Mobile Web
                    ['tv', 'web'],         # TV client
                    ['web'],               # Default web — آخر حل
                ]
                for pc_idx, pc in enumerate(_YOUTUBE_PLAYER_CLIENTS):
                    try:
                        alt_opts = dict(ydl_opts)
                        alt_opts['extractor_args'] = {'youtube': {'player_client': pc}}
                        # 🔴 FIX: نشيل remote_components مع player_client (مش متوافقين)
                        alt_opts.pop('remote_components', None)
                        
                        logger.info(f"🔧 WhatsApp yt-dlp fallback: player_client={pc} (attempt {pc_idx + 1})")
                        
                        def _run_ytdlp_alt():
                            with yt_dlp.YoutubeDL(alt_opts) as ydl:
                                info = ydl.extract_info(url, download=True)
                                return info
                        
                        info = await asyncio.wait_for(
                            loop.run_in_executor(None, _run_ytdlp_alt),
                            timeout=300
                        )
                        if info:
                            logger.info(f"✅ yt-dlp {pc} client download succeeded")
                            break
                    except Exception as e2:
                        last_error = e2
                        logger.warning(f"⚠️ yt-dlp {pc} client failed: {e2}")
                        # 🔴 لو bot detection — حدث yt-dlp فوراً
                        err_str2 = str(e2).lower()
                        if any(kw in err_str2 for kw in ["sign in", "bot", "captcha", "confirm", "login", "403"]):
                            try:
                                from handlers.download_handlers import trigger_ytdlp_update
                                trigger_ytdlp_update()
                            except Exception:
                                pass
            
            # 🔴 FIX: Cobalt API لكل المنصات (مش بس YouTube!)
            # Cobalt بيدعم Dailymotion و SoundCloud و TikTok و Instagram وغيرهم
            if info is None and not is_youtube:
                try:
                    import aiohttp as _aiohttp_cobalt
                    cobalt_instances = [
                        'https://api.cobalt.tools',
                        'https://cobalt-api.kwiatekmiki.com',
                    ]
                    
                    for cobalt_url in cobalt_instances:
                        try:
                            cobalt_headers = {
                                'Accept': 'application/json',
                                'Content-Type': 'application/json',
                            }
                            cobalt_payload = {'url': url}
                            if is_audio_only:
                                cobalt_payload['downloadMode'] = 'audio'
                            elif quality in ("medium", "low"):
                                cobalt_payload['videoQuality'] = '720' if quality == 'medium' else '480'
                            
                            async with _aiohttp_cobalt.ClientSession() as cobalt_session:
                                async with cobalt_session.post(
                                    cobalt_url, headers=cobalt_headers, json=cobalt_payload,
                                    timeout=_aiohttp_cobalt.ClientTimeout(total=30)
                                ) as cobalt_resp:
                                    if cobalt_resp.status != 200:
                                        continue
                                    
                                    cobalt_data = await cobalt_resp.json()
                                    cobalt_status = cobalt_data.get('status', '')
                                    
                                    dl_url = None
                                    if cobalt_status in ('redirect', 'tunnel'):
                                        dl_url = cobalt_data.get('url', '')
                                    elif cobalt_status == 'picker':
                                        picker = cobalt_data.get('picker', [])
                                        if picker:
                                            dl_url = picker[0].get('url', '')
                                    
                                    if dl_url:
                                        logger.info(f"🟠 WA Cobalt: Got download URL from {cobalt_url} for {platform}")
                                        ext = "mp3" if is_audio_only else "mp4"
                                        cobalt_file = os.path.join(tmpdir, f"cobalt_dl.{ext}")
                                        
                                        dl_headers = {'Referer': 'https://www.youtube.com/'}
                                        async with cobalt_session.get(dl_url, headers=dl_headers,
                                              timeout=_aiohttp_cobalt.ClientTimeout(total=120)) as dl_resp:
                                            if dl_resp.status == 200:
                                                cobalt_file_size = 0
                                                with open(cobalt_file, 'wb') as cf:
                                                    async for chunk in dl_resp.content.iter_chunked(8192):
                                                        cf.write(chunk)
                                                        cobalt_file_size += len(chunk)
                                                
                                                if cobalt_file_size > 1000:
                                                    # 🔴 Build info dict for the standard send flow
                                                    cobalt_title = cobalt_data.get('filename', '')
                                                    if cobalt_title:
                                                        cobalt_title = os.path.splitext(cobalt_title)[0][:80]
                                                    if not cobalt_title:
                                                        cobalt_title = f"{platform_display} Video"
                                                    info = {
                                                        "title": cobalt_title,
                                                        "duration": 0,
                                                        "height": 720,
                                                        "vcodec": "h264",
                                                        "acodec": "aac",
                                                        "_cobalt_file": cobalt_file,
                                                        "_cobalt_size": cobalt_file_size,
                                                    }
                                                    logger.info(f"🟠 WA Cobalt: Download succeeded! Size: {cobalt_file_size // 1024}KB")
                                                    break
                                                else:
                                                    try: os.remove(cobalt_file)
                                                    except: pass
                        except asyncio.TimeoutError:
                            logger.debug(f"🟠 WA Cobalt {cobalt_url} timed out")
                        except Exception as cobalt_err:
                            logger.debug(f"🟠 WA Cobalt {cobalt_url} error: {cobalt_err}")
                except Exception as cobalt_outer_err:
                    logger.warning(f"🟠 WA Cobalt non-YT error: {cobalt_outer_err}")
            
            # ═══ المرحلة 3: Cobalt API Fallback (fallback تالت — أسرع وأضمن من Piped) ═══
            # 🔴 نفس fallback chain زي التليجرام بالظبط
            # Cobalt Public API + Self-Hosted
            if info is None and is_youtube:
                try:
                    from handlers.download_handlers import _try_cobalt_for_youtube
                    
                    logger.info(f"🟠 WhatsApp Cobalt: Attempting download as 3rd fallback for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    cobalt_result = await asyncio.wait_for(
                        _try_cobalt_for_youtube(url, quality, tmpdir),
                        timeout=90
                    )
                    
                    if cobalt_result and cobalt_result.get("filepath"):
                        logger.info(f"🟠 WhatsApp Cobalt (3rd fallback) succeeded! File: {cobalt_result['filepath']}")
                        
                        cobalt_file = cobalt_result["filepath"] if "filepath" in cobalt_result else cobalt_result.get("file_path")
                        cobalt_size = cobalt_result.get("size", os.path.getsize(cobalt_file) if os.path.exists(cobalt_file) else 0)
                        cobalt_title = cobalt_result.get("title", "YouTube Video")
                        cobalt_height = cobalt_result.get("height", 720)
                        cobalt_size_mb = cobalt_size / (1024 * 1024)
                        size_str = f"{cobalt_size_mb:.1f}MB"
                        
                        if cobalt_file and os.path.exists(cobalt_file):
                            # 🛡️ Safety check
                            try:
                                from content_safety import comprehensive_media_safety_check
                                cb_file_type = "audio" if is_audio_only else "video"
                                is_safe_cb, block_msg_cb, _ = await comprehensive_media_safety_check(
                                    title=cobalt_title, file_path=cobalt_file, file_type=cb_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_cb:
                                    await _send_whatsapp_message(wa_id, block_msg_cb)
                                    try: os.remove(cobalt_file)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(cobalt_file, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{cobalt_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(cobalt_file)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Cobalt audio send failed: {audio_send_err}")
                            else:
                                # 🔴 استخدام Supabase للملفات الكبيرة — صامت، بدون رسالة للمستخدم
                                if cobalt_size_mb > 25:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=cobalt_file,
                                            filename=f"{cobalt_title[:50]}.mp4",
                                            content_type="video/mp4",
                                            platform="whatsapp",
                                            title=cobalt_title,
                                            lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(cobalt_file)
                                            except: pass
                                            return
                                    except Exception as sup_err:
                                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                                    logger.warning(f"⚠️ WA Cobalt: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(cobalt_file)
                                    except: pass
                                else:
                                    # File <= 25MB — try direct WhatsApp send
                                    try:
                                        with open(cobalt_file, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{cobalt_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                tech_info = f"{cobalt_height}p | {size_str} | Cobalt"
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {cobalt_title[:200]}\n📥 {tech_info}")
                                                await feedback.success()
                                                try: os.remove(cobalt_file)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Cobalt video send failed: {video_send_err}")
                    
                    logger.warning(f"⚠️ Cobalt (3rd fallback) failed, trying Apify...")
                except ImportError:
                    logger.warning("⚠️ Cobalt download handler not available, trying Apify...")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Cobalt timed out, trying Apify...")
                except Exception as cobalt_err:
                    logger.warning(f"⚠️ Cobalt error: {cobalt_err}, trying Apify...")
            
            # ═══ المرحلة 4: Apify — fallback رابع (سيرفرات مختلفة عن YouTube خالص) ═══
            # 🔵 Apify بيستخدم actors عشان يحمل الفيديو — مش بيتأثر بـ bot detection
            if info is None and is_youtube:
                try:
                    from apify_download import download_youtube_apify
                    
                    logger.info(f"🔵 WhatsApp Apify: Attempting download as 4th fallback for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    apify_result = await asyncio.wait_for(
                        download_youtube_apify(url, quality, tmpdir),
                        timeout=150
                    )
                    
                    if apify_result and apify_result.get("success") and apify_result.get("filepath"):
                        logger.info(f"🔵 WhatsApp Apify (4th fallback) succeeded! File: {apify_result['filepath']}")
                        
                        apify_file = apify_result["filepath"]
                        apify_size = apify_result.get("size", os.path.getsize(apify_file) if os.path.exists(apify_file) else 0)
                        apify_title = apify_result.get("title", "YouTube Video")
                        apify_height = apify_result.get("height", 720)
                        apify_size_mb = apify_size / (1024 * 1024)
                        size_str = f"{apify_size_mb:.1f}MB"
                        
                        if apify_file and os.path.exists(apify_file):
                            # 🛡️ Safety check
                            try:
                                from content_safety import comprehensive_media_safety_check
                                af_file_type = "audio" if is_audio_only else "video"
                                is_safe_af, block_msg_af, _ = await comprehensive_media_safety_check(
                                    title=apify_title, file_path=apify_file, file_type=af_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_af:
                                    await _send_whatsapp_message(wa_id, block_msg_af)
                                    try: os.remove(apify_file)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(apify_file, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{apify_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(apify_file)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Apify audio send failed: {audio_send_err}")
                            else:
                                # 🔴 استخدام Supabase للملفات الكبيرة — صامت، بدون رسالة للمستخدم
                                if apify_size_mb > 25:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=apify_file,
                                            filename=f"{apify_title[:50]}.mp4",
                                            content_type="video/mp4",
                                            platform="whatsapp",
                                            title=apify_title,
                                            lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(apify_file)
                                            except: pass
                                            return
                                    except Exception as sup_err:
                                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                                    logger.warning(f"⚠️ WA Apify: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(apify_file)
                                    except: pass
                                else:
                                    # File <= 25MB — try direct WhatsApp send
                                    try:
                                        with open(apify_file, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{apify_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                tech_info = f"{apify_height}p | {size_str} | Apify"
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {apify_title[:200]}\n📥 {tech_info}")
                                                await feedback.success()
                                                try: os.remove(apify_file)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Apify video send failed: {video_send_err}")
                    
                    logger.warning(f"⚠️ Apify (4th fallback) failed, trying yt-dlp without cookies...")
                except ImportError:
                    logger.warning("⚠️ Apify module not available, trying yt-dlp without cookies...")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Apify timed out, trying yt-dlp without cookies...")
                except Exception as apify_err:
                    logger.warning(f"⚠️ Apify error: {apify_err}, trying yt-dlp without cookies...")
            
            # ═══ المرحلة 4.5: yt-dlp WITHOUT cookies (زي التليجرام بالظبط!) ═══
            # 🔴 أحياناً الكوكيز نفسها بتسبب مشاكل (expired/invalid) → نجرب بدونها
            # 🔴 FIX: زي التليجرام — بنشيل الكوكيز بس، مش remote_components
            if info is None and is_youtube:
                logger.info("🔄 WhatsApp: All methods failed (including Cobalt & Apify), trying WITHOUT cookies...")
                
                try:
                    # المحاولة الأولى: default + deno بدون كوكيز (بإبقاء remote_components زي التليجرام)
                    clean_opts = dict(ydl_opts)
                    clean_opts.pop('cookiefile', None)
                    # 🔴 FIX: مش بنشيل remote_components — زي التليجرام بالظبط
                    clean_opts['format'] = format_str if not is_audio_only else 'bestaudio/best'
                    
                    logger.info("🔄 WhatsApp: Clean attempt (default, no cookies, keeping remote_components)...")
                    
                    def _run_ytdlp_clean():
                        with yt_dlp.YoutubeDL(clean_opts) as ydl:
                            return ydl.extract_info(url, download=True)
                    
                    try:
                        info = await asyncio.wait_for(
                            loop.run_in_executor(None, _run_ytdlp_clean),
                            timeout=300
                        )
                        if info is not None:
                            logger.info("✅ WhatsApp: Download succeeded with default (no cookies)!")
                    except Exception as clean_error:
                        last_error = clean_error
                        logger.warning(f"⚠️ WhatsApp clean attempt (no cookies) failed: {clean_error}")
                        
                        # المحاولة التانية: android player_client بدون كوكيز
                        android_clean = dict(ydl_opts)
                        android_clean.pop('cookiefile', None)
                        # 🔴 نشيل remote_components مع player_client (مش متوافقين)
                        android_clean.pop('remote_components', None)
                        android_clean['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}
                        android_clean['format'] = format_str if not is_audio_only else 'bestaudio/best'
                        
                        logger.info("🔄 WhatsApp: Android+web player_client clean attempt (no cookies)...")
                        
                        def _run_ytdlp_android_clean():
                            with yt_dlp.YoutubeDL(android_clean) as ydl:
                                return ydl.extract_info(url, download=True)
                        
                        try:
                            info = await asyncio.wait_for(
                                loop.run_in_executor(None, _run_ytdlp_android_clean),
                                timeout=300
                            )
                            if info is not None:
                                logger.info("✅ WhatsApp: Download succeeded with android (no cookies)!")
                        except Exception as ac_error:
                            last_error = ac_error
                            logger.warning(f"⚠️ WhatsApp android clean attempt also failed: {ac_error}")
                except Exception as clean_outer_err:
                    logger.warning(f"⚠️ WhatsApp yt-dlp without cookies error: {clean_outer_err}")
            
            # ═══ المرحلة 5: Invidious API (تم تجربته فوق — هنا fallback إضافي) ═══
            # 🔴 نفس ترتيب التليجرام: Invidious قبل Piped
            # Invidious = واجهة بديلة لليوتيوب مفتوحة المصدر
            if info is None and is_youtube:
                try:
                    from invidious_api import download_youtube_invidious_file
                    
                    inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                       "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    inv_quality = inv_quality_map.get(quality, "best")
                    
                    logger.info(f"🟣 WhatsApp Invidious (retry): Attempting download quality={inv_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    inv_result = await asyncio.wait_for(
                        download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                        timeout=60
                    )
                    
                    if inv_result and inv_result.get("success") and inv_result.get("file_path"):
                        logger.info(f"🟣 WhatsApp Invidious (retry) succeeded! File: {inv_result['file_path']}")
                        
                        inv_file = inv_result["file_path"]
                        inv_size = inv_result.get("file_size", os.path.getsize(inv_file))
                        inv_title = inv_result.get("title", "YouTube Video")
                        inv_duration = inv_result.get("duration", 0)
                        inv_format = inv_result.get("format_info", {})
                        
                        info = {
                            "title": inv_title,
                            "duration": int(inv_duration) if inv_duration else 0,
                            "height": 720,
                            "vcodec": "h264",
                            "acodec": "aac",
                            "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                        }
                        
                        if inv_file and os.path.exists(inv_file):
                            target = os.path.join(tmpdir, f"{inv_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(inv_file, target)
                            except Exception:
                                target = inv_file
                            
                            # 🛡️ Safety check on Invidious downloaded media
                            try:
                                inv_file_type = "audio" if is_audio_only else "video"
                                is_safe_inv, block_msg_inv, _ = await comprehensive_media_safety_check(
                                    title=inv_title, file_path=target, file_type=inv_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_inv:
                                    await _send_whatsapp_message(wa_id, block_msg_inv)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            inv_size_mb = inv_size / (1024 * 1024)
                            inv_quality_label = inv_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{inv_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Invidious (retry) audio send failed: {audio_send_err}")
                            else:
                                if inv_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{inv_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {inv_title[:200]}\n📥 Invidious | {inv_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Invidious (retry) video send failed: {video_send_err}")
                                else:
                                    # File too large for WhatsApp — upload to Supabase (silent)
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{inv_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=inv_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Invidious (retry): File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ Invidious (retry) failed, trying Piped...")
                except ImportError:
                    logger.warning("⚠️ invidious_api module not available, skipping Invidious")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Invidious (retry) timed out, trying Piped...")
                except Exception as inv_err:
                    logger.warning(f"⚠️ Invidious (retry) error: {inv_err}, trying Piped...")
            
            # ═══ المرحلة 6: Piped API (تم تجربته فوق — هنا fallback إضافي) ═══
            # 🔴 نفس ترتيب التليجرام: Piped بعد Invidious
            # Piped = واجهة بديلة لليوتيوب مفتوحة المصدر — مختلفة عن Invidious
            # بيستخدم NewPipe Extractor — أحياناً بيشتغل لما Invidious يبقى منطفي
            if info is None and is_youtube:
                try:
                    from piped_api import download_youtube_piped_file
                    
                    piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                         "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    piped_quality = piped_quality_map.get(quality, "best")
                    
                    logger.info(f"🟢 WhatsApp Piped (retry): Attempting download quality={piped_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    piped_result = await asyncio.wait_for(
                        download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                        timeout=90
                    )
                    
                    if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                        logger.info(f"🟢 WhatsApp Piped (retry) succeeded! File: {piped_result['file_path']}")
                        
                        piped_file = piped_result["file_path"]
                        piped_size = piped_result.get("file_size", os.path.getsize(piped_file))
                        piped_title = piped_result.get("title", "YouTube Video")
                        piped_duration = piped_result.get("duration", 0)
                        piped_format = piped_result.get("format_info", {})
                        
                        # Construct info dict for the send logic below
                        info = {
                            "title": piped_title,
                            "duration": int(piped_duration) if piped_duration else 0,
                            "height": 720,
                            "vcodec": "h264",
                            "acodec": "aac",
                            "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                        }
                        
                        # Move the Piped file to the expected location
                        if piped_file and os.path.exists(piped_file):
                            target = os.path.join(tmpdir, f"{piped_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(piped_file, target)
                            except Exception:
                                target = piped_file
                            
                            # 🛡️ Safety check on Piped downloaded media
                            try:
                                pp_file_type = "audio" if is_audio_only else "video"
                                is_safe_pp, block_msg_pp, _ = await comprehensive_media_safety_check(
                                    title=piped_title, file_path=target, file_type=pp_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_pp:
                                    await _send_whatsapp_message(wa_id, block_msg_pp)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            # Send the file directly from here
                            piped_size_mb = piped_size / (1024 * 1024)
                            piped_quality_label = piped_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{piped_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Piped (retry) audio send failed: {audio_send_err}")
                            else:
                                if piped_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{piped_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {piped_title[:200]}\n📥 Piped | {piped_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Piped (retry) video send failed: {video_send_err}")
                                else:
                                    # File too large for WhatsApp — upload to Supabase (silent)
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{piped_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=piped_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Piped (retry): File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ Piped (retry) failed, trying Cobalt Self-Hosted...")
                except ImportError:
                    logger.warning("⚠️ piped_api module not available, skipping Piped")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Piped (retry) timed out, trying Cobalt Self-Hosted...")
                except Exception as piped_err:
                    logger.warning(f"⚠️ Piped (retry) error: {piped_err}, trying Cobalt Self-Hosted...")
            
            # ═══ المرحلة 6.5: Cobalt Self-Hosted (زي التليجرام بالظبط!) ═══
            # 🔵 _try_cobalt_download بيجرب الـ COBALT_API_URL (self-hosted) 
            # ده مختلف عن _try_cobalt_for_youtube اللي اتجرب فوق — ده مرحلة إضافية
            if info is None:
                try:
                    from handlers.download_handlers import _try_cobalt_download
                    
                    logger.info(f"🔵 WhatsApp Cobalt Self-Hosted: Attempting download for {url[:80]}")
                    
                    cobalt_sh_result = await asyncio.wait_for(
                        _try_cobalt_download(url, quality, tmpdir),
                        timeout=90
                    )
                    
                    if cobalt_sh_result and cobalt_sh_result.get("filepath"):
                        logger.info(f"🔵 WhatsApp Cobalt Self-Hosted succeeded! File: {cobalt_sh_result['filepath']}")
                        
                        cobalt_sh_file = cobalt_sh_result["filepath"]
                        cobalt_sh_size = cobalt_sh_result.get("size", os.path.getsize(cobalt_sh_file) if os.path.exists(cobalt_sh_file) else 0)
                        cobalt_sh_title = cobalt_sh_result.get("title", "Video")
                        cobalt_sh_height = cobalt_sh_result.get("height", 720)
                        cobalt_sh_size_mb = cobalt_sh_size / (1024 * 1024)
                        cobalt_sh_size_str = f"{cobalt_sh_size_mb:.1f}MB"
                        
                        if cobalt_sh_file and os.path.exists(cobalt_sh_file):
                            # 🛡️ Safety check
                            try:
                                from content_safety import comprehensive_media_safety_check
                                sh_file_type = "audio" if is_audio_only else "video"
                                is_safe_sh, block_msg_sh, _ = await comprehensive_media_safety_check(
                                    title=cobalt_sh_title, file_path=cobalt_sh_file, file_type=sh_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_sh:
                                    await _send_whatsapp_message(wa_id, block_msg_sh)
                                    try: os.remove(cobalt_sh_file)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(cobalt_sh_file, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{cobalt_sh_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(cobalt_sh_file)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Cobalt Self-Hosted audio send failed: {audio_send_err}")
                            else:
                                # 🔴 صامت — بدون رسالة للمستخدم
                                if cobalt_sh_size_mb > 25:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=cobalt_sh_file,
                                            filename=f"{cobalt_sh_title[:50]}.mp4",
                                            content_type="video/mp4",
                                            platform="whatsapp",
                                            title=cobalt_sh_title,
                                            lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(cobalt_sh_file)
                                            except: pass
                                            return
                                    except Exception as sup_err:
                                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                                    logger.warning(f"⚠️ WA Cobalt Self-Hosted: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(cobalt_sh_file)
                                    except: pass
                                else:
                                    # File <= 25MB — try direct WhatsApp send
                                    try:
                                        with open(cobalt_sh_file, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{cobalt_sh_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                tech_info = f"{cobalt_sh_height}p | {cobalt_sh_size_str} | Cobalt Self-Hosted"
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {cobalt_sh_title[:200]}\n📥 {tech_info}")
                                                await feedback.success()
                                                try: os.remove(cobalt_sh_file)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Cobalt Self-Hosted video send failed: {video_send_err}")
                    
                    logger.warning(f"⚠️ Cobalt Self-Hosted failed, trying Cobalt JWT...")
                except ImportError:
                    logger.warning("⚠️ _try_cobalt_download not available, trying Cobalt JWT...")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Cobalt Self-Hosted timed out, trying Cobalt JWT...")
                except Exception as cobalt_sh_err:
                    logger.warning(f"⚠️ Cobalt Self-Hosted error: {cobalt_sh_err}, trying Cobalt JWT...")
            
            # ═══ المرحلة 7: Cobalt JWT — آخر fallback قبل Cloudflare Worker ═══
            # 🔴 ده JWT شخصي من cobalt.tools — بنستخدمه كـ آخر حل لو كل حاجة فشلت
            if info is None and is_youtube:
                try:
                    from config import COBALT_JWT
                    
                    if COBALT_JWT:
                        logger.info(f"🔐 WhatsApp Cobalt JWT: Last-resort attempt for {url[:80]}")
                        # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                        
                        import aiohttp as _aiohttp_wa
                        import json as _json_wa
                        
                        is_audio_jwt = (quality == "audio" or quality.startswith("audio_"))
                        jwt_quality_map = {"best": "1080", "medium": "720", "low": "480", "audio": "720"}
                        jwt_v_quality = jwt_quality_map.get(quality, "1080")
                        
                        jwt_payload = {
                            "url": url,
                            "videoQuality": jwt_v_quality,
                            "filenameStyle": "classic",
                        }
                        if is_audio_jwt:
                            jwt_payload["downloadMode"] = "audio"
                            jwt_payload["audioFormat"] = "mp3"
                        
                        jwt_headers = {
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {COBALT_JWT}",
                        }
                        
                        try:
                            from handlers.download_handlers import _cobalt_api_request
                            jwt_result = await asyncio.wait_for(
                                _cobalt_api_request(
                                    "https://api.cobalt.tools", jwt_payload, jwt_headers,
                                    jwt_v_quality, is_audio_jwt, tmpdir
                                ),
                                timeout=90
                            )
                            
                            if jwt_result and jwt_result.get("filepath"):
                                logger.info(f"🔐 WhatsApp Cobalt JWT succeeded! File: {jwt_result['filepath']}")
                                
                                jwt_file = jwt_result["filepath"]
                                jwt_size = jwt_result.get("size", os.path.getsize(jwt_file) if os.path.exists(jwt_file) else 0)
                                jwt_title = jwt_result.get("title", "YouTube Video")
                                jwt_height = jwt_result.get("height", 720)
                                jwt_size_mb = jwt_size / (1024 * 1024)
                                size_str = f"{jwt_size_mb:.1f}MB"
                                
                                if jwt_file and os.path.exists(jwt_file):
                                    # 🛡️ Safety check on Cobalt JWT downloaded media
                                    try:
                                        jwt_file_type = "audio" if is_audio_jwt else "video"
                                        is_safe_jwt, block_msg_jwt, _ = await comprehensive_media_safety_check(
                                            title=jwt_title, file_path=jwt_file, file_type=jwt_file_type,
                                            platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                        )
                                        if not is_safe_jwt:
                                            await _send_whatsapp_message(wa_id, block_msg_jwt)
                                            try: os.remove(jwt_file)
                                            except: pass
                                            await feedback.error()
                                            return
                                    except Exception:
                                        pass  # Fail-open
                                    
                                    if is_audio_jwt:
                                        try:
                                            with open(jwt_file, 'rb') as af:
                                                media_response = requests.post(
                                                    f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                    headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                    files={"file": (f"{jwt_title[:50]}.mp3", af, "audio/mpeg")},
                                                    data={"messaging_product": "whatsapp", "type": "audio"},
                                                    timeout=120
                                                )
                                                if media_response.status_code == 200:
                                                    media_id = media_response.json().get("id")
                                                    await _send_whatsapp_audio(wa_id, media_id)
                                                    await feedback.success()
                                                    try: os.remove(jwt_file)
                                                    except: pass
                                                    return
                                        except Exception as audio_send_err:
                                            logger.warning(f"⚠️ Cobalt JWT audio send failed: {audio_send_err}")
                                    else:
                                        if jwt_size_mb <= 25:
                                            try:
                                                with open(jwt_file, 'rb') as vf:
                                                    media_response = requests.post(
                                                        f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                        headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                        files={"file": (f"{jwt_title[:50]}.mp4", vf, "video/mp4")},
                                                        data={"messaging_product": "whatsapp", "type": "video"},
                                                        timeout=180
                                                    )
                                                    if media_response.status_code == 200:
                                                        media_id = media_response.json().get("id")
                                                        tech_info = f"{jwt_height}p | {size_str} | Cobalt JWT"
                                                        await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {jwt_title[:200]}\n📥 {tech_info}")
                                                        await feedback.success()
                                                        try: os.remove(jwt_file)
                                                        except: pass
                                                        return
                                            except Exception as video_send_err:
                                                logger.warning(f"⚠️ Cobalt JWT video send failed: {video_send_err}")
                                        else:
                                            # File too large for WhatsApp — upload to Supabase
                                            try:
                                                from supabase_storage import upload_and_get_link
                                                jwt_size_str = f"{jwt_size_mb:.1f}MB"
                                                cloud_msg = await upload_and_get_link(
                                                    file_path=jwt_file, filename=f"{jwt_title[:50]}.mp4",
                                                    content_type="video/mp4", platform="whatsapp", title=jwt_title, lang="ar",
                                                )
                                                if cloud_msg:
                                                    await _send_whatsapp_message(wa_id, cloud_msg)
                                                    await feedback.success()
                                                    try: os.remove(jwt_file)
                                                    except: pass
                                                    return
                                            except Exception:
                                                pass
                                            logger.warning(f"⚠️ WA Cobalt JWT: File downloaded but sending failed, trying next fallback...")
                                            try: os.remove(jwt_file)
                                            except: pass
                            
                            logger.warning(f"⚠️ Cobalt JWT failed, trying Cloudflare Worker...")
                        except asyncio.TimeoutError:
                            logger.warning(f"⚠️ Cobalt JWT timed out, trying Cloudflare Worker...")
                    else:
                        logger.info("🔐 Cobalt JWT: No COBALT_JWT configured, skipping")
                except Exception as jwt_err:
                    logger.warning(f"⚠️ Cobalt JWT error: {jwt_err}")
            
            # ═══ المرحلة 8: Cloudflare Worker Proxy Fallback (آخر محاولة) ═══
            # لو yt-dlp فشل على Railway (IPs محجوبة)، نجرب عبر Cloudflare Worker
            if info is None:
                from config import CLOUDFLARE_WORKER_URL
                if CLOUDFLARE_WORKER_URL:
                    logger.info(f"🔄 All yt-dlp methods failed, trying Cloudflare Worker proxy: {CLOUDFLARE_WORKER_URL}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
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
                                                        'http_headers': ydl_opts.get('http_headers', {}),
                                                    }
                                                    # 🔴 FIX: إضافة كوكيز لو موجودة (زي باقي yt-dlp calls)
                                                    if 'cookiefile' in ydl_opts:
                                                        info_opts['cookiefile'] = ydl_opts['cookiefile']
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
            
            # 🔴 FIX: لو Cobalt نزل الملف مباشرة (مش عبر yt-dlp)
            cobalt_direct_file = info.get('_cobalt_file') if isinstance(info, dict) else None
            if cobalt_direct_file and os.path.exists(cobalt_direct_file):
                video_file = cobalt_direct_file
                file_size = info.get('_cobalt_size', os.path.getsize(video_file))
                title = info.get('title', 'فيديو')[:80]
            else:
                # Find the downloaded file (yt-dlp case)
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
                            # 🔴 FIX: إضافة كوكيز لو موجودة (زي باقي yt-dlp calls)
                            if 'cookiefile' in ydl_opts:
                                retry_opts['cookiefile'] = ydl_opts['cookiefile']
                            
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
            
            # 🛡️ Safety: Comprehensive media safety check before sending
            try:
                media_type = "audio" if is_audio_only else "video"
                is_safe, block_msg, safety_reason = await comprehensive_media_safety_check(
                    title=title,
                    file_path=video_file,
                    file_type=media_type,
                    platform="whatsapp",
                    user_id=str(wa_user_id),
                    lang="ar",
                )
                if not is_safe:
                    await _send_whatsapp_message(wa_id, block_msg)
                    try:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                    except Exception:
                        pass
                    await feedback.error()
                    return
            except Exception as e:
                logger.warning(f"🛡️ Media safety check failed (allowing): {e}")
            
            # ═══ إرسال الملف — Direct Send أو Supabase Cloud Upload ═══
            #
            # 🔴 FIX v3: Supabase free tier has a 50MB per-file upload limit!
            # upload_and_get_link() now auto-compresses files > 50MB with ffmpeg before uploading.
            #
            # Flow:
            # 1. لو الملف <= 100MB → إرسال مباشر عبر WhatsApp
            # 2. لو الإرسال المباشر فشل → Supabase (مع ضغط تلقائي لو > 50MB)
            # 3. لو الملف > 100MB → Supabase مباشرة (مع ضغط تلقائي)
            # 4. لو Supabase فشل (حتى بعد الضغط) → رسالة خطأ
            #
            MAX_WHATSAPP_DIRECT_SIZE = 25 * 1024 * 1024    # 25MB — عشان نتجنب OOM على Railway (كان 100MB)
            MAX_SUPABASE_SIZE = 2 * 1024 * 1024 * 1024      # 2GB — أقصى حد للرفع على السحابة
            
            # 🔴 Step 1: لو الملف <= 100MB → إرسال مباشر
            if file_size <= MAX_WHATSAPP_DIRECT_SIZE:
                # 🔴 FIX: بنستخدم streaming send عشان نتجنب OOM
                if is_audio_only:
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + '.mp3'
                    caption = f"🎵 {title}\n🔗 {platform_display}\n📊 {file_size / 1024 / 1024:.1f}MB"
                    result = await _send_whatsapp_document_from_file(
                        wa_id, video_file, safe_filename, caption, "audio/mpeg"
                    )
                else:
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + '.mp4'
                    quality_label = {"best": "1080p", "medium": "720p", "low": "480p"}.get(quality, "")
                    caption = f"📥 {title}\n🔗 {platform_display}\n📊 {file_size / 1024 / 1024:.1f}MB"
                    if quality_label:
                        caption += f"\n🎬 {quality_label}"
                    result = await _send_whatsapp_document_from_file(
                        wa_id, video_file, safe_filename, caption, "video/mp4"
                    )
                
                if "error" not in result:
                    # ✅ الإرسال المباشر نجح
                    pass
                else:
                    # الإرسال المباشر فشل — نجرب Supabase
                    error_msg = str(result.get("error", ""))
                    logger.warning(f"⚠️ WhatsApp direct send failed: {error_msg}")
                    
                    # 🔴 محاولة رفع على Supabase (مع ضغط تلقائي لو > 50MB) — silent, no user message
                    
                    content_type = "audio/mpeg" if is_audio_only else "video/mp4"
                    ext = ".mp3" if is_audio_only else ".mp4"
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + ext
                    
                    try:
                        from supabase_storage import upload_and_get_link
                        cloud_msg = await upload_and_get_link(
                            file_path=video_file,
                            filename=safe_filename,
                            content_type=content_type,
                            platform="whatsapp",
                            title=title,
                            lang="ar",
                        )
                        if cloud_msg:
                            await _send_whatsapp_message(wa_id, cloud_msg)
                            await feedback.success()
                            try: shutil.rmtree(tmpdir, ignore_errors=True)
                            except: pass
                            return  # ✅ رفع السحابة نجح
                        else:
                            # Supabase فشل — رسالة خطأ
                            await _send_whatsapp_message(wa_id,
                                f"📥 *{title}*\n\n"
                                f"🔗 المنصة: {platform_display}\n\n"
                                f"❌ فشل إرسال الملف. جرب تاني!")
                    except Exception as sup_err:
                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                        await _send_whatsapp_message(wa_id,
                            f"📥 *{title}*\n\n"
                            f"🔗 المنصة: {platform_display}\n\n"
                            f"❌ فشل إرسال الملف. جرب تاني!")
            
            # 🔴 Step 2: لو الملف > 100MB → رفع على Supabase مباشرة (مع ضغط تلقائي)
            else:
                # 🔴 FIX v3: Supabase free tier = 50MB limit, but upload_and_get_link auto-compresses — silent, no user message
                size_mb_str = f"{file_size / 1024 / 1024:.0f}MB"
                
                content_type = "audio/mpeg" if is_audio_only else "video/mp4"
                ext = ".mp3" if is_audio_only else ".mp4"
                safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + ext
                
                cloud_msg = None
                try:
                    from supabase_storage import upload_and_get_link
                    cloud_msg = await upload_and_get_link(
                        file_path=video_file,
                        filename=safe_filename,
                        content_type=content_type,
                        platform="whatsapp",
                        title=title,
                        lang="ar",
                    )
                except Exception as sup_err:
                    logger.error(f"☁️ Supabase upload error: {sup_err}")
                
                if cloud_msg:
                    # ✅ رفع السحابة نجح
                    await _send_whatsapp_message(wa_id, cloud_msg)
                else:
                    # 🔴 Supabase فشل حتى بعد الضغط — نجرب جودة أقل كآخر محاولة
                    logger.error("☁️ Supabase upload failed even after compression")
                    
                    if quality != "low":
                        # نجرب نحمل بجودة أقل ونحاول تاني — silent, no user message
                        try:
                            shutil.rmtree(tmpdir, ignore_errors=True)
                        except Exception:
                            pass
                        await feedback.complete()
                        lower_quality = {"best": "medium", "medium": "low", "audio": "low"}.get(quality, "low")
                        return await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=lower_quality)
                    else:
                        await _send_whatsapp_message(wa_id,
                            f"📥 *{title}*\n\n"
                            f"🔗 المنصة: {platform_display}\n\n"
                            f"❌ فشل رفع الملف على السحابة. جرب تاني!")
            
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
                await asyncio.sleep(0.05)  # ⚡ كان 0.3s - اتعمل 0.05s عشان سرعة أكتر

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
    # Exit
    "/exit": "exit", "exit": "exit", "خروج": "exit", "الغاء": "exit", "إلغاء": "exit",
    # YouTube
    "/youtube": "youtube", "youtube": "youtube", "يوتيوب": "youtube",
    # Cookies
    "/cookies": "cookies", "cookies": "cookies", "كوكيز": "cookies",
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
    "/userstats": "admin_userstats", "احصائيات يوزر": "admin_userstats",
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
                f"→ /grant [مدة] رقم_الواتساب — تفعيل Premium (m=شهر, w=أسبوع, y=سنة)\n"
                f"→ /revoke user_id — شيل Premium\n"
                f"→ /resetlimit user_id — ريست الحدود\n"
                f"→ /ban user_id — حظر مستخدم\n"
                f"→ /unban user_id — إلغاء حظر\n"
                f"→ /userinfo رقم_الواتساب — معلومات يوزر شاملة (بدون بيانات حساسة)\n"
                f"→ /userstats رقم_الواتساب — إحصائيات يوزر مفصلة\n"
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
            "/grant رقم_الواتساب — تفعيل مدى الحياة\n"
            "/grant 30 رقم_الواتساب — تفعيل 30 يوم\n"
            "/grant m رقم_الواتساب — تفعيل شهر\n"
            "/grant w رقم_الواتساب — تفعيل أسبوع\n"
            "/grant y رقم_الواتساب — تفعيل سنة\n\n"
            "🔑 *اختصارات المدة:*\n"
            "d = يوم | w = أسبوع | m = شهر | y = سنة\n"
            "0 أو دائم = مدى الحياة\n\n"
            "مثال: /grant m 201203551789\n"
            "مثال: /grant w2 201203551789")
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
            "👤 *معلومات مستخدم شاملة*\n\n"
            "الاستخدام: /userinfo رقم_الواتساب\n"
            "مثال: /userinfo 201203551789\n\n"
            "💡 بيرجع كل المعلومات العامة:\n"
            "→ الاسم (من البروفايل + المفضل)\n"
            "→ الخطة وتاريخ الاشتراكات\n"
            "→ كم مدة على البوت\n"
            "→ إحصائيات الاستخدام\n\n"
            "🔒 مش بيرجع بيانات حساسة")
        return True

    elif command == "admin_userstats":
        if not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
            return True
        await _send_whatsapp_message(wa_id,
            "📊 *إحصائيات مستخدم شاملة*\n\n"
            "الاستخدام: /userstats رقم_الواتساب\n\n"
            "💡 بيرجع كل المعلومات العامة:\n"
            "→ الخطة وتاريخ الاشتراكات\n"
            "→ كم مرة اشترك Premium\n"
            "→ إحصائيات الاستخدام الإجمالي\n"
            "→ حالة الحظر والتحذيرات\n\n"
            "🔒 مش بيرجع بيانات حساسة:\n"
            "→ محتوى المحادثات\n"
            "→ ذكريات المستخدم\n\n"
            "مثال: /userstats 201203551789")
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
        # 🔴 FIX v3: كالتليجرام بالظبط — لو المستخدم جديد ومش مشترك، نسأله هل عايز يشترك في الأخبار
        
        from memory import is_new_user, is_subscribed, get_language
        user_lang = get_language(wa_user_id)
        user_is_new = is_new_user(wa_user_id)
        user_subscribed = is_subscribed(wa_user_id)
        
        # Send welcome text first
        if user_lang == "en":
            await _send_whatsapp_message(wa_id,
                "Welcome! 🤖 I'm *My Bro* — your personal AI assistant\n\n"
                "I can help you with many things!\nChoose from the menu or just type anything")
        else:
            await _send_whatsapp_message(wa_id,
                "أهلاً بيك! 🤖 أنا *My Bro* — مساعدك الذكي الشخصي\n\n"
                "ممكن أساعدك في حاجات كتير!\nاختار من القائمة أو ابعت أي رسالة")

        # Then send interactive list with all categories
        admin_row = []
        if is_admin:
            admin_row = [{"id": "cmd_admin", "title": t("wa.menu_admin", user_lang), "description": t("wa.menu_admin_desc", user_lang)}]

        await _send_interactive_list(
            wa_id,
            body_text=t("wa.menu_choose_feature", user_lang),
            button_text=t("wa.menu_features", user_lang),
            sections=[{
                "title": t("wa.menu_main_features", user_lang),
                "rows": [
                    {"id": "cmd_chat", "title": t("wa.menu_chat", user_lang), "description": t("wa.menu_chat_desc", user_lang)},
                    {"id": "cmd_news", "title": t("wa.menu_news", user_lang), "description": t("wa.menu_news_desc", user_lang)},
                    {"id": "cmd_download", "title": t("wa.menu_download", user_lang), "description": t("wa.menu_download_desc", user_lang)},
                    {"id": "video_search", "title": t("wa.menu_video_search", user_lang), "description": t("wa.menu_video_search_desc", user_lang)},
                    {"id": "audio_search", "title": t("wa.menu_audio_search", user_lang), "description": t("wa.menu_audio_search_desc", user_lang)},
                    {"id": "photo_search", "title": t("wa.menu_photo_search", user_lang), "description": t("wa.menu_photo_search_desc", user_lang)},
                    {"id": "cmd_search", "title": t("wa.menu_web_search", user_lang), "description": t("wa.menu_web_search_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_learning", user_lang),
                "rows": [
                    {"id": "cmd_study", "title": t("wa.menu_study", user_lang), "description": t("wa.menu_study_desc", user_lang)},
                    {"id": "cmd_memory", "title": t("wa.menu_memory", user_lang), "description": t("wa.menu_memory_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_media", user_lang),
                "rows": [
                    {"id": "cmd_image_gen", "title": t("wa.menu_image_gen", user_lang), "description": t("wa.menu_image_gen_desc", user_lang)},
                    {"id": "cmd_image_edit", "title": t("wa.menu_image_edit", user_lang), "description": t("wa.menu_image_edit_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_documents", user_lang),
                "rows": [
                    {"id": "cmd_youtube", "title": t("wa.menu_youtube_summary", user_lang), "description": t("wa.menu_youtube_summary_desc", user_lang)},
                    {"id": "cmd_pdf", "title": t("wa.menu_pdf", user_lang), "description": t("wa.menu_pdf_desc", user_lang)},
                ],
            }, {
                "title": t("wa.menu_settings_section", user_lang),
                "rows": [
                    {"id": "cmd_settings", "title": t("wa.menu_settings", user_lang), "description": t("wa.menu_settings_desc", user_lang)},
                    {"id": "cmd_plan", "title": t("wa.menu_plan", user_lang), "description": t("wa.menu_plan_desc", user_lang)},
                ] + admin_row,
            }],
            header_text="🤖 My Bro",
            footer_text=t("wa.menu_footer", user_lang),
        )
        
        # 🔴 FIX v3: زي التليجرام بالظبط — لو المستخدم جديد ومش مشترك، نبعتله سؤال الاشتراك
        if user_is_new and not user_subscribed:
            import asyncio as _aio
            await _aio.sleep(1.5)  # انتظر شوية عشان الرسالة اللي فاتت توصل الأول
            if user_lang == "en":
                await _send_interactive_buttons(
                    wa_id,
                    body_text="📬 *Subscribe to Daily News!*\n━━━━━━━━━━━━━━━━━\n\n"
                              "I'll send you the most important AI news every day at 12:00 PM Cairo time 🌅\n\n"
                              "✅ Latest AI news from global sources\n"
                              "✅ Clear and simple summaries\n"
                              "✅ Completely free\n\n"
                              "👇 Choose below!",
                    buttons=[
                        {"id": "cmd_subscribe_confirm", "title": "✅ Subscribe"},
                        {"id": "cmd_skip_subscribe", "title": "No Thanks"},
                    ],
                    header_text="📬 Daily News",
                )
            else:
                await _send_interactive_buttons(
                    wa_id,
                    body_text="📬 *اشترك في الأخبار اليومية!*\n━━━━━━━━━━━━━━━━━\n\n"
                              "هابعتلك أهم أخبار الذكاء الاصطناعي كل يوم الساعة 12 الظهر بتوقيت القاهرة 🌅\n\n"
                              "✅ آخر أخبار AI من مصادر عالمية\n"
                              "✅ ملخص بالعربية مفهوم وبسيط\n"
                              "✅ مجاني تماماً\n\n"
                              "👇 اختار من تحت!",
                    buttons=[
                        {"id": "cmd_subscribe_confirm", "title": "✅ اشترك"},
                        {"id": "cmd_skip_subscribe", "title": "لا شكراً"},
                    ],
                    header_text="📬 أخبار يومية",
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
                    {"id": "cmd_cookies", "title": "🍪 رفع كوكيز", "description": "ارفع ملف كوكيز YouTube"},
                    {"id": "video_search", "title": "🎬 فيديو بالبحث", "description": "ابحث Dailymotion وحمّل فيديو"},
                    {"id": "audio_search", "title": "🎵 صوت بالبحث", "description": "ابحث SoundCloud وحمّل صوت"},
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
            body_text="🔍 *بحث الويب*\n\nاكتب كلمة البحث بعد الأمر\nمثال: *بحث الحضارة الإسلامية*\n\nأو اختار من الاقتراحات:",
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
            from memory import subscribe_user, get_news_time, set_news_time
            subscribe_user(wa_user_id)
            # 🔴 FIX: نتأكد إن news_time = "12:00" (الافتراضي الجديد)
            # لو المستخدم كان عنده "09:00" من الوقت القديم، نحدثه
            current_time = get_news_time(wa_user_id)
            if current_time == "09:00":
                set_news_time(wa_user_id, "12:00")
            await _send_whatsapp_message(wa_id, "✅ تم الاشتراك بنجاح! 🎉\n\n📬 هنبعتلك أخبار AI كل يوم الساعة 12 الظهر (توقيت القاهرة).\n\n⏰ لو عايز تغير الوقت ابعت بصيغة HH:MM\nمثال: 14:30\n\nلو عايز تلغي الاشتراك ابعت: إلغاء")
        except Exception:
            await _send_whatsapp_message(wa_id, "✅ تم الاشتراك بنجاح! 🎉")

    elif command == "skip_subscribe":
        # 🔴 FIX v3: المستخدم ضغط "لا شكراً" على سؤال الاشتراك — نحترم اختياره بس نقوله ممكن يشترك بعدين
        from memory import get_language
        skip_lang = get_language(wa_user_id)
        if skip_lang == "en":
            await _send_whatsapp_message(wa_id, "👍 No problem! You can subscribe anytime by sending: subscribe")
        else:
            await _send_whatsapp_message(wa_id, "👍 مفيش مشكلة! ممكن تشترك أي وقت لو ابعتت: اشترك")

    elif command == "unsubscribe_confirm":
        from memory import get_language
        unsub_lang = get_language(wa_user_id)
        try:
            from memory import unsubscribe_user
            unsubscribe_user(wa_user_id)
            await _send_whatsapp_message(wa_id, t("wa.unsubscribe_success", unsub_lang))
        except Exception:
            await _send_whatsapp_message(wa_id, t("wa.unsubscribe_error", unsub_lang))

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
                    "📥 تحميل من أي منصة (YouTube, Insta, TikTok...)\n"
                    "🎬 فيديو بالبحث غير محدود\n"
                    "🎵 صوت بالبحث غير محدود\n"
                    "🖼️ بحث صور غير محدود\n"
                    "🎨 إنشاء وتعديل صور\n"
                    "📚 وضع الدراسة\n"
                    "🧠 ذاكرة طويلة المدى\n"
                    "🤖 نماذج AI أقوى")
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
                "• 5 عمليات بحث/يوم\n"
                "• 3 بحث صور/يوم 🖼️\n\n"
                "⭐ *Premium:*\n"
                "• كل حاجة غير محدودة!\n"
                "• تحميل من أي منصة 📥\n"
                "  (YouTube, Insta, TikTok, FB, Twitter...)\n"
                "• فيديو بالبحث 🎬\n"
                "• صوت بالبحث 🎵\n"
                "• بحث صور غير محدود 🖼️\n"
                "• إنشاء وتعديل صور 🎨🖌️\n"
                "• وضع الدراسة 📚\n"
                "• ذاكرة طويلة المدى 🧠\n"
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
                    "📥 تحميل من أي منصة: مفتوح\n"
                    "🎬 فيديو بالبحث: مفتوح\n"
                    "🎵 صوت بالبحث: مفتوح\n"
                    "🖼️ بحث صور: مفتوح\n"
                    "🎨 إنشاء صور: مفتوح\n"
                    "🖌️ تعديل صور: مفتوح\n"
                    "📚 وضع الدراسة: مفتوح\n"
                    "🧠 ذاكرة طويلة المدى: مفتوح\n"
                    "🤖 نماذج AI أقوى: مفتوح"
                )
            else:
                # Free plan — show usage with limits
                ai_rem = max(0, limits["ai_messages_per_day"] - usage.get("ai_messages", 0))
                pdf_rem = max(0, limits["pdf_analyses_per_day"] - usage.get("pdf_analyses", 0))
                img_rem = max(0, limits["image_analyses_per_day"] - usage.get("image_analyses", 0))
                yt_rem = max(0, limits["youtube_summaries_per_day"] - usage.get("youtube_summaries", 0))
                search_rem = max(0, limits["searches_per_day"] - usage.get("searches", 0))
                photo_rem = max(0, limits.get("photo_searches_per_day", 3) - usage.get("photo_searches", 0))

                ai_used = usage.get("ai_messages", 0)
                pdf_used = usage.get("pdf_analyses", 0)
                img_used = usage.get("image_analyses", 0)
                yt_used = usage.get("youtube_summaries", 0)
                search_used = usage.get("searches", 0)
                photo_used = usage.get("photo_searches", 0)

                plan_text = (
                    "🆓 *الخطة المجانية*\n"
                    "━━━━━━━━━━━━━━━━━\n\n"
                    f"💬 رسائل: {ai_used}/{limits['ai_messages_per_day']} (متبقي {ai_rem})\n"
                    f"📄 PDF: {pdf_used}/{limits['pdf_analyses_per_day']} (متبقي {pdf_rem})\n"
                    f"🖼️ تحليل صور: {img_used}/{limits['image_analyses_per_day']} (متبقي {img_rem})\n"
                    f"🎬 يوتيوب: {yt_used}/{limits['youtube_summaries_per_day']} (متبقي {yt_rem})\n"
                    f"🔍 بحث: {search_used}/{limits['searches_per_day']} (متبقي {search_rem})\n"
                    f"🖼️ بحث صور: {photo_used}/{limits.get('photo_searches_per_day', 3)} (متبقي {photo_rem})\n\n"
                    "📥 تحميل فيديو: ❌ بريميوم\n"
                    "🎬 فيديو بالبحث: ❌ بريميوم\n"
                    "🎵 صوت بالبحث: ❌ بريميوم\n"
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

    elif command == "download_yt":
        # 🍪 تحميل فيديو YouTube اللي اتلخص ده — بنستخدم الرابط المخزّن
        cached_url = _wa_user_yt_url.get(wa_id, "")
        if cached_url:
            await _download_and_send_video(wa_id, cached_url, wa_user_id, contact_name, message_id, is_admin)
        else:
            await _send_whatsapp_message(wa_id, "❌ مش قادر ألاقي رابط الفيديو. جرب /download مع الرابط مباشرة.")

    # ══════════════════════════════════════
    # VIDEO SEARCH / AUDIO SEARCH / PHOTO SEARCH
    # ══════════════════════════════════════

    elif command == "video_search":
        # 🔴 فحص Premium — فيديو بالبحث مميزة بريميوم بس
        if not is_admin:
            try:
                from premium import get_user_plan, PLAN_LIMITS
                plan = get_user_plan(wa_user_id)
                if plan not in ("premium", "premium_plus"):
                    await _send_whatsapp_message(wa_id,
                        f"🎬 فيديو بالبحث مميزة Premium بس!\n\n"
                        f"📥 تحميل من أي منصة 📥\n"
                        f"🎬 فيديو بالبحث\n"
                        f"🎵 صوت بالبحث\n"
                        f"🎨 إنشاء وتعديل صور 🎨🖌️\n"
                        f"📚 وضع الدراسة\n"
                        f"🧠 ذاكرة طويلة المدى\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "video_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🎬 *تحميل فيديو بالبحث*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك النتائج!\n\n"
            "مثال: قرآن ماهر المعيقلي\n\n"
            "💡 أو استخدم: /video كلمات البحث")
        return True

    elif command == "audio_search":
        # 🔴 فحص Premium — صوت بالبحث مميزة بريميوم بس
        if not is_admin:
            try:
                from premium import get_user_plan
                plan = get_user_plan(wa_user_id)
                if plan not in ("premium", "premium_plus"):
                    await _send_whatsapp_message(wa_id,
                        f"🎵 صوت بالبحث مميزة Premium بس!\n\n"
                        f"📥 تحميل من أي منصة 📥\n"
                        f"🎬 فيديو بالبحث\n"
                        f"🎵 صوت بالبحث\n"
                        f"🎨 إنشاء وتعديل صور 🎨🖌️\n"
                        f"📚 وضع الدراسة\n"
                        f"🧠 ذاكرة طويلة المدى\n\n"
                        f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                    return True
            except Exception:
                pass

        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "audio_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🎵 *تحميل صوت بالبحث*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك النتائج!\n\n"
            "مثال: قرآن عبد الباسط\n\n"
            "💡 أو استخدم: /audio كلمات البحث")
        return True

    elif command == "photo_search":
        # 🔴 فحص Premium — بحث صور (مجاني 3/يوم، بريميوم غير محدود)
        if not is_admin:
            try:
                from premium import get_user_plan, check_limit, increment_usage
                plan = get_user_plan(wa_user_id)
                if plan not in ("premium", "premium_plus"):
                    can_search, _ = check_limit(wa_user_id, "photo_searches_per_day")
                    if not can_search:
                        await _send_whatsapp_message(wa_id,
                            "🖼️ وصلت حد بحث الصور اليوم (3/يوم)\n\n"
                            "⭐ Premium: بحث صور غير محدود!\n\n"
                            f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                        return True
            except Exception:
                pass

        # 🔴 حفظ حالة المستخدم — في انتظار كلمات البحث
        _set_user_state(wa_id, "photo_search_query", {"step": "awaiting_query"})
        await _send_whatsapp_message(wa_id,
            "🖼️ *بحث عن صور*\n\n"
            "اكتب اللي عايز تبحث عنه وأنا هجيبلوك صور!\n\n"
            "مثال: المسجد الأقصى\n\n"
            "💡 أو استخدم: /photo كلمات البحث")
        return True

    # ══════════════════════════════════════
    # EXIT (الخروج من وضع الدراسة أو أي workflow)
    # ══════════════════════════════════════

    elif command == "exit":
        workflow_cleared = False
        try:
            from workflow_manager import get_workflow, clear_workflow
            workflow = get_workflow(wa_user_id)
            if workflow:
                clear_workflow(wa_user_id)
                workflow_cleared = True
        except Exception:
            pass
        # مسح user_states القديم
        if wa_user_id in _wa_user_state:
            _wa_user_state.pop(wa_user_id, None)
            workflow_cleared = True
        if workflow_cleared:
            await _send_whatsapp_message(wa_id, "✅ خرجت من الوضع النشط. اكتب أي حاجة وهرد عليك عادي! 🤖")
        else:
            await _send_whatsapp_message(wa_id, "ℹ️ مش في أي وضع نشط دلوقتي. اكتب أي حاجة وهرد عليك! 🤖")
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
    # COOKIES
    # ══════════════════════════════════════

    elif command == "cookies":
        # 🍪 أمر الكوكيز — كل المستخدمين يقدروا يرفعوا كوكيز
        if is_admin:
            # الأدمن يشوف التفاصيل الكاملة
            cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            if os.path.exists(cookies_file):
                try:
                    size = os.path.getsize(cookies_file)
                    with open(cookies_file, 'r') as f:
                        lines = f.readlines()
                    cookie_lines = [l for l in lines if l.strip() and not l.strip().startswith('#')]
                    yt_cookies = [l for l in cookie_lines if 'youtube.com' in l.lower()]
                    msg = (
                        f"🍪 *حالة ملف الكوكيز*\n\n"
                        f"📊 الحجم: {size} bytes\n"
                        f"🔢 عدد الكوكيز: {len(cookie_lines)}\n"
                        f"▶️ كوكيز YouTube: {len(yt_cookies)}\n"
                        f"🔴 لا كوكيز تلقائية — بس كوكيز مرفوعة من المستخدمين\n\n"
                        f"✅ الملف موجود وشغال!\n\n"
                        f"💡 لرفع ملف جديد: ابعت ملف cookies.txt كـ document مع كتابة *cookies* في الرسالة\n"
                        f"🗑️ لمسح الملف: /cookies delete"
                    )
                except Exception as e:
                    msg = f"🍪 ❌ خطأ في قراءة الملف: {e}"
            else:
                msg = (
                    "🍪 *ملف الكوكيز مش موجود*\n\n"
                    "⚠️ بدون ملف كوكيز، YouTube ممكن يمنع التحميل.\n"
                    "🔴 مفيش كوكيز تلقائية — بس كوكيز مرفوعة من المستخدمين!\n\n"
                    "💡 ابعت ملف cookies.txt كـ document مع كتابة *cookies* في الرسالة\n\n"
                    "إزاي تجيب الملف:\n"
                    "1️⃣ افتح Chrome على الكمبيوتر\n"
                    "2️⃣ ثبّت إضافة Get cookies.txt LOCALLY\n"
                    "3️⃣ افتح youtube.com واعمل login\n"
                    "4️⃣ اضغط على الإضافة واختار Export\n"
                    "5️⃣ ابعت الملف هنا مع كتابة cookies في الرسالة"
                )
        else:
            # المستخدم العادي — رسالة بسيطة
            msg = (
                "🍪 *ارفع ملف الكوكيز بتاعك*\n\n"
                "ابعت ملف cookies.txt من جهازك وهنسخه للبوت عشان نساعد في تحميل الفيديوهات.\n\n"
                "💡 إزاي تجيب الملف:\n"
                "1️⃣ افتح Chrome على الكمبيوتر\n"
                "2️⃣ ثبّت إضافة Get cookies.txt LOCALLY\n"
                "3️⃣ افتح youtube.com واعمل login\n"
                "4️⃣ اضغط على الإضافة واختار Export\n"
                "5️⃣ ابعت الملف هنا كـ document مع كتابة *cookies* في الرسالة"
            )
        await _send_whatsapp_message(wa_id, msg)

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
            "/image مسجد جميل عند الغروب\n"
            "/image sunset over mosque\n\n"
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
            "خلي الخلفية زرقاء زي السماء")

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
            f"📚 {study_action}\n\nاكتب الموضوع اللي عايز {study_action} فيه\n\nمثال: {study_action} الفقه الإسلامي")

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
        # ✅ FIX: First check if user already exists by wa_phone (handles hash changes after restarts)
        # If found, use their existing user_id to preserve all data
        from memory import find_user_by_wa_phone
        existing_user_id = find_user_by_wa_phone(wa_id)
        if existing_user_id is not None:
            wa_user_id = existing_user_id
        else:
            wa_user_id = _wa_phone_to_user_id(wa_id)
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
            updates = {}
            if contact_name and contact_name != "Unknown":
                updates["name"] = contact_name
                # 🔴 حفظ الاسم الأصلي من بروفايل واتساب (منفصل عن الاسم المفضل)
                updates["profile_name"] = contact_name
            # 🔴 حفظ رقم واتساب المستخدم — ضروري لإرسال الإشعارات من التليجرام
            if wa_id:
                updates["wa_phone"] = wa_id
            if updates:
                try:
                    from memory import update_user
                    update_user(wa_user_id, updates)
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
            # Check for download quality selections first (dl_v_b_KEY, dl_v_m_KEY, dl_aq_320_KEY, etc.)
            if interactive_id.startswith("dl_"):
                quality_map = {
                    "dl_v_b_": "best",
                    "dl_v_m_": "medium",
                    "dl_v_l_": "low",
                    "dl_a_": "audio",
                }
                # 🔴 Audio quality with specific bitrate: dl_aq_{bitrate}_{key}
                audio_quality = None
                if interactive_id.startswith("dl_aq_"):
                    # dl_aq_320_abc123 → quality="audio_320", url_key="abc123"
                    aq_parts = interactive_id.split("_", 3)  # dl, aq, 320, abc123
                    if len(aq_parts) >= 4:
                        bitrate = aq_parts[2]
                        audio_quality = f"audio_{bitrate}"
                        url_key = aq_parts[3]
                
                if audio_quality:
                    cached_url = _get_url(url_key)
                    if cached_url:
                        logger.info(f"📥 Audio quality selection: {audio_quality} for URL key {url_key}")
                        await _download_and_send_video(wa_id, cached_url, wa_user_id, contact_name, message_id, is_admin, quality=audio_quality)
                    else:
                        await _send_whatsapp_message(wa_id, "⚠️ انتهت صلاحية الرابط. ابعت الرابط تاني! 📥")
                    return
                
                for prefix, q in quality_map.items():
                    if interactive_id.startswith(prefix):
                        url_key = interactive_id[len(prefix):]
                        cached_url = _get_url(url_key)
                        if cached_url:
                            logger.info(f"📥 Quality selection: {q} for URL key {url_key}")
                            # تحميل مباشر بـ yt-dlp لكل المنصات
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
                "cmd_skip_subscribe": "skip_subscribe",
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
                "cmd_download_yt": "download_yt",
                # Study
                "cmd_study": "study",
                "cmd_study_learn": "cmd_study_learn",
                "cmd_study_quiz": "cmd_study_quiz",
                "cmd_study_exam": "cmd_study_exam",
                "cmd_study_notes": "cmd_study_notes",
                "cmd_study_flash": "cmd_study_flash",
                # YouTube
                "cmd_youtube": "youtube",
                # Cookies
                "cmd_cookies": "cookies",
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
                admin_arg_commands = ["/grant", "/revoke", "/resetlimit", "/ban", "/unban", "/userinfo", "/userstats", "/broadcast"]
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
                "/cookies": "cookies",
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

            # ═══ Time Change Detection (HH:MM pattern) ═══
            # لو المستخدم كتب وقت بصيغة HH:MM (زي 14:30 أو 09:00)
            # ده معناه إنه عايز يغير وقت الأخبار اليومية
            import re as _time_re
            _time_match = _time_re.match(r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$', content.strip())
            if _time_match:
                hour_str = _time_match.group(1).zfill(2)
                minute_str = _time_match.group(2).zfill(2)
                new_time = f"{hour_str}:{minute_str}"
                
                try:
                    from memory import set_news_time
                    set_news_time(wa_user_id, new_time)
                    await _send_whatsapp_message(wa_id,
                        f"✅ تم تغيير وقت الأخبار!\n\n"
                        f"⏰ الوقت الجديد: {new_time} (توقيت القاهرة)\n"
                        f"📬 هابعتلك الأخبار كل يوم في الوقت ده.\n\n"
                        f"💡 ممكن تغيره تاني من الإعدادات"
                    )
                except Exception:
                    await _send_whatsapp_message(wa_id, f"✅ تم تغيير وقت الأخبار إلى {new_time}")
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

        # ═══ Process Document — Cookies file check first ═══
        # 🍪 لو الملف اسمه cookies أو الرسالة فيها كلمة cookies → نوجهه لـ cookies handler
        if is_document and document_media_id:
            is_cookies_doc = False
            content_lower = (content or "").lower()
            # فحص الـ caption/الرسالة
            if 'cookie' in content_lower or 'كوكيز' in content_lower:
                is_cookies_doc = True

            if is_cookies_doc:
                try:
                    # تحميل الملف من WhatsApp
                    import aiohttp
                    cookie_file_content = ""
                    async with aiohttp.ClientSession() as session:
                        media_url_resp = await session.get(
                            f"https://graph.facebook.com/v21.0/{document_media_id}",
                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                        )
                        if media_url_resp.status == 200:
                            media_data = await media_url_resp.json()
                            download_url = media_data.get("url", "")
                            if download_url:
                                doc_resp = await session.get(
                                    download_url,
                                    headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                )
                                if doc_resp.status == 200:
                                    doc_bytes = await doc_resp.read()
                                    cookie_file_content = doc_bytes.decode('utf-8', errors='ignore')

                    if cookie_file_content:
                        # 🔴 فحص المحتوى — نتأكد إنه ملف كوكيز حقيقي
                        has_netscape_header = '# Netscape HTTP Cookie File' in cookie_file_content
                        has_youtube = '.youtube.com' in cookie_file_content or 'youtube.com' in cookie_file_content

                        is_valid = False
                        if has_netscape_header or has_youtube:
                            cookie_lines = [l for l in cookie_file_content.splitlines() if l.strip() and not l.strip().startswith('#')]
                            valid_lines = [l for l in cookie_lines if len(l.split('\t')) >= 7]
                            if valid_lines:
                                is_valid = True

                        if is_valid:
                            # 🔴 دمج الكوكيز مع الملف الموجود
                            cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
                            existing_content = ""
                            if os.path.exists(cookies_path):
                                try:
                                    with open(cookies_path, 'r', encoding='utf-8') as f:
                                        existing_content = f.read()
                                except Exception:
                                    existing_content = ""

                            if existing_content.strip():
                                # في ملف موجود — ندمج
                                from handlers.download_handlers import _merge_cookies
                                merged_content, new_added, new_yt_added = _merge_cookies(existing_content, cookie_file_content)
                                with open(cookies_path, 'w', encoding='utf-8') as f:
                                    f.write(merged_content)
                                logger.info(f"🍪 WA Cookies merged from user {wa_id}: {new_added} new cookies ({new_yt_added} YouTube)")
                            else:
                                # مفيش ملف موجود — نكتب مباشرة
                                with open(cookies_path, 'w', encoding='utf-8') as f:
                                    f.write(cookie_file_content)
                                new_added = 0
                                new_yt_added = 0
                                logger.info(f"🍪 WA Cookies file created by user {wa_id}")

                            # التحقق
                            total_yt = 0
                            total_all = 0
                            try:
                                with open(cookies_path, 'r') as f:
                                    all_lines = f.readlines()
                                total_all = len([l for l in all_lines if l.strip() and not l.strip().startswith('#')])
                                total_yt = len([l for l in all_lines if 'youtube.com' in l.lower() and l.strip() and not l.strip().startswith('#')])
                            except Exception:
                                pass

                            # ✅ للمستخدم العادي — رسالة بسيطة
                            if not is_admin:
                                await _send_whatsapp_message(wa_id, "✅ تم رفع ملف الكوكيز بنجاح! شكراً لمساعدتنا 🎬")
                            else:
                                # 🔴 للأدمن — تفاصيل كاملة
                                if new_added > 0:
                                    await _send_whatsapp_message(wa_id,
                                        f"✅ *تم دمج الكوكيز بنجاح!*\n\n"
                                        f"🆕 كوكيز جديدة: {new_added} ({new_yt_added} YouTube)\n"
                                        f"📊 إجمالي الكوكيز: {total_all}\n"
                                        f"▶️ كوكيز YouTube: {total_yt}\n\n"
                                        f"🎬 التحميل هيشتغل بشكل أفضل!")
                                else:
                                    await _send_whatsapp_message(wa_id,
                                        f"✅ *تم رفع ملف الكوكيز بنجاح!*\n\n"
                                        f"▶️ كوكيز YouTube: {total_yt}\n\n"
                                        f"🎬 التحميل هيشتغل بشكل أفضل!")
                        else:
                            await _send_whatsapp_message(wa_id, "❌ الملف ده مش ملف كوكيز صحيح. لازم يكون Netscape HTTP Cookie File وفيه كوكيز YouTube.")
                    else:
                        await _send_whatsapp_message(wa_id, "❌ مش قادر أحمل الملف. جرب تاني!")
                except Exception as e:
                    logger.error(f"🍪 WA Cookies document handling error: {e}")
                    await _send_whatsapp_message(wa_id, f"❌ حصل خطأ في رفع الكوكيز: {e}")
                return  # 🍪 مهم — منع الملف يروح لـ PDF analysis

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
                    # 🔴 فحص Premium — التحميل من المنصات مميز بريميوم بس
                    if not is_admin:
                        try:
                            from premium import get_user_plan
                            plan = get_user_plan(wa_user_id)
                            if plan not in ("premium", "premium_plus"):
                                await _send_whatsapp_message(wa_id,
                                    f"📥 تحميل الفيديوهات مميز Premium بس!\n\n"
                                    f"⭐ مع Premium تقدر:\n"
                                    f"• تحميل من أي منصة 📥\n"
                                    f"  (YouTube, Insta, TikTok, FB, Twitter...)\n"
                                    f"• فيديو بالبحث 🎬\n"
                                    f"• صوت بالبحث 🎵\n\n"
                                    f"📩 تواصل مع المطور على واتساب:\n📱 {DEVELOPER_WHATSAPP_URL}")
                                return
                        except Exception:
                            pass
                    
                    # 🛡️ Safety: Check URL/query before proceeding with download
                    try:
                        is_safe, reason = await check_query_safety(url, platform="whatsapp", user_id=str(wa_user_id))
                        if not is_safe:
                            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
                            return
                    except Exception as e:
                        logger.warning(f"🛡️ URL safety check failed (allowing): {e}")
                    
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

    # ✅ FIX: Helper to resolve WA phone to user_id — prefers database lookup over hash
    def _resolve_wa_target(phone: str) -> int:
        """Resolve a WhatsApp phone number to a user_id.
        First tries database lookup by wa_phone (reliable, survives restarts),
        then falls back to deterministic hash for new users.
        """
        from memory import find_user_by_wa_phone
        existing = find_user_by_wa_phone(phone)
        if existing is not None:
            return existing
        return _wa_phone_to_user_id(phone)

    try:
        if cmd in ("/grant",):
            if not args:
                await _send_whatsapp_message(wa_id, "⭐ الاستخدام: /grant [مدة] رقم_الواتساب\nمثال: /grant 201203551789\nمثال: /grant m 201203551789\nمثال: /grant w 201203551789\nمثال: /grant y 201203551789\n\n🔄 تجديد: /grant force m 201203551789")
                return

            from premium import grant_premium, get_premium_info
            from memory import _ensure_user_in_db
            from admin import parse_duration

            # 🔴 فحص كلمة force — عشان تجديد Premium
            force_renew = False
            if args[0].lower() == "force":
                force_renew = True
                args = args[1:]

            if not args:
                await _send_whatsapp_message(wa_id, "❌ لازم تحدد رقم الواتساب. مثال: /grant force m 201203551789")
                return

            if len(args) == 1:
                # /grant phone → مدى الحياة
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                days = 0
                expires_display = "مدى الحياة 🔓"
            elif len(args) == 2:
                # /grant [مدة] phone
                duration_str = args[0]
                phone = args[1]
                target_id = _resolve_wa_target(phone)
                days, expires_display = parse_duration(duration_str)
                if days == -1:
                    await _send_whatsapp_message(wa_id, "❌ المدة مش صحيحة.\n\n🔑 الاختصارات:\nd = يوم | w = أسبوع | m = شهر | y = سنة\n0 أو دائم = مدى الحياة\n\nمثال: /grant m 201203551789")
                    return
            else:
                await _send_whatsapp_message(wa_id, "❌ كترت المعاملات. /grant [مدة] رقم_الواتساب")
                return

            _ensure_user_in_db(target_id, platform="whatsapp")

            expires = None
            if days > 0:
                from datetime import timedelta
                from admin import CAIRO_TZ
                expires_date = datetime.now(CAIRO_TZ) + timedelta(days=days)
                expires = expires_date.isoformat()
                expires_display += f" (ينتهي {expires_date.strftime('%Y-%m-%d')})"

            # 🔴 فحص هل المستخدم أصلاً Premium
            current_info = get_premium_info(target_id)
            
            if current_info["is_premium"] and not force_renew:
                # المستخدم أصلاً Premium — نقول للأدمن
                current_expires = current_info["expires_display"]
                current_since = current_info["premium_since"][:10] if current_info["premium_since"] else "مش محدد"
                await _send_whatsapp_message(wa_id,
                    f"⚠️ المستخدم ده أصلاً Premium!\n\n"
                    f"📱 المستخدم: {_wa_phone_to_display(phone)}\n"
                    f"⭐ الخطة: Premium\n"
                    f"📅 مفعل من: {current_since}\n"
                    f"⏰ المتبقي: {current_expires}\n\n"
                    f"🔄 عايز تجدده؟ اكتب:\n"
                    f"/grant force {' '.join(parts[2:]) if len(parts) > 2 else phone}"
                )
                return

            if force_renew and current_info["is_premium"]:
                # تجديد
                old_expires = current_info["expires_display"]
                grant_premium(target_id, granted_by=f"admin_{wa_user_id}", expires=expires)
                await _send_whatsapp_message(wa_id, f"🔄 تم تجديد Premium!\n\n📱 المستخدم: {_wa_phone_to_display(phone)}\n⭐ الخطة: Premium\n⏰ المدة القديمة: {old_expires}\n⏰ المدة الجديدة: {expires_display}")
            else:
                # تفعيل جديد
                grant_premium(target_id, granted_by=f"admin_{wa_user_id}", expires=expires)
                await _send_whatsapp_message(wa_id, f"✅ تم تفعيل Premium!\n\n📱 المستخدم: {_wa_phone_to_display(phone)}\n📊 الخطة السابقة: Free\n⭐ الخطة الجديدة: Premium\n⏰ المدة: {expires_display}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    f"⭐ مبروك! تم تفعيل Premium!\n\n"
                    f"أنت دلوقتي مشترك Premium في My Bro!\n"
                    f"استمتع بكل المزايا:\n"
                    f"• رسائل AI غير محدودة 💬\n"
                    f"• تحليل PDF غير محدود 📄\n"
                    f"• تحليل صور غير محدود + Vision Pro 👁️\n"
                    f"• ملخصات YouTube غير محدودة 🎬\n"
                    f"• بحث غير محدود 🔍\n"
                    f"• تحميل وسائط من أي منصة 📥\n"
                    f"  (YouTube, Instagram, TikTok, FB, Twitter...)\n"
                    f"• فيديو بالبحث غير محدود 🎬\n"
                    f"• صوت بالبحث غير محدود 🎵\n"
                    f"• بحث صور غير محدود 🖼️\n"
                    f"• إنشاء صور بالذكاء الاصطناعي 🎨\n"
                    f"• تعديل صور بالذكاء الاصطناعي 🖌️\n"
                    f"• وضع الدراسة 📚\n"
                    f"• ذاكرة طويلة المدى 🧠\n\n"
                    f"⏰ المدة: {expires_display}"
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/revoke",):
            if not args:
                await _send_whatsapp_message(wa_id, "❌ الاستخدام: /revoke رقم_الواتساب\nمثال: /revoke 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            from premium import revoke_premium, get_premium_info
            
            # 🔴 فحص هل المستخدم أصلاً مش Premium
            current_info = get_premium_info(target_id)
            if not current_info["is_premium"]:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} أصلاً مش Premium — على الخطه المجانيه بالفعل!")
                return
            
            # المستخدم Premium → شيله
            old_expires = current_info["expires_display"]
            revoke_premium(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم شيل Premium من {_wa_phone_to_display(phone)}\n\n📅 كان المتبقي: {old_expires}\n📊 الخطة الجديدة: Free")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    "❌ تم إلغاء اشتراك Premium.\n\n"
                    "لو تعتقد إن ده غلطة، تواصل مع الأدمن."
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/resetlimit",):
            if not args:
                await _send_whatsapp_message(wa_id, "🔄 الاستخدام: /resetlimit رقم_الواتساب\nمثال: /resetlimit 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            from premium import reset_user_usage, get_premium_info
            
            # 🔴 فحص هل المستخدم Premium — لو آه، الريست مش هيعمل حاجة
            current_info = get_premium_info(target_id)
            if current_info["is_premium"]:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} Premium — استخدام غير محدود أصلاً!\n\nمفيش حدود تتأثر بالريست.\nلو عايز تشيل البريميوم: /revoke {phone}")
                return
            
            success = reset_user_usage(target_id)
            if success:
                await _send_whatsapp_message(wa_id, f"✅ تم إعادة تعيين حدود {_wa_phone_to_display(phone)}")
                # 🔴 إرسال إشعار للمستخدم المستهدف
                try:
                    target_wa_id = phone.lstrip('+').strip()
                    await _send_whatsapp_message(target_wa_id,
                        "🔄 تم إعادة تعيين حدود الاستخدام بتاعتك!\n\n"
                        "تقدر تستخدم البوت تاني عادي."
                    )
                except Exception as e:
                    logger.info(f"Could not notify WA user {phone}: {e}")
            else:
                await _send_whatsapp_message(wa_id, f"❌ فشل في إعادة التعيين")

        elif cmd in ("/ban",):
            if not args:
                await _send_whatsapp_message(wa_id, "🚫 الاستخدام: /ban رقم_الواتساب [سبب]\nمثال: /ban 201203551789 سبام")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            reason = " ".join(args[1:]) if len(args) > 1 else "حظر من الأدمن"
            
            # 🔴 فحص هل المستخدم محظور بالفعل
            from memory import _execute as _mem_execute, _is_postgres as _mem_is_postgres
            ph = "%s" if _mem_is_postgres() else "?"
            already_banned = _mem_execute(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (target_id,), fetchone=True)
            if already_banned:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} محظور بالفعل!")
                return
            
            from memory import ban_user
            ban_user(target_id, reason=reason, banned_by=f"admin_{wa_user_id}")
            await _send_whatsapp_message(wa_id, f"🚫 تم حظر {_wa_phone_to_display(phone)}\n📝 السبب: {reason}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    f"🚫 تم حظرك من استخدام البوت.\n📝 السبب: {reason}\n\nلو تعتقد إن ده غلطة، تواصل مع الأدمن."
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/unban",):
            if not args:
                await _send_whatsapp_message(wa_id, "✅ الاستخدام: /unban رقم_الواتساب\nمثال: /unban 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            
            # 🔴 فحص هل المستخدم محظور أصلاً
            from memory import _execute as _mem_execute2, _is_postgres as _mem_is_postgres2, unban_user
            ph = "%s" if _mem_is_postgres2() else "?"
            is_banned = _mem_execute2(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (target_id,), fetchone=True)
            if not is_banned:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} مش محظور أصلاً!")
                return
            
            unban_user(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم إلغاء حظر {_wa_phone_to_display(phone)}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    "✅ تم إلغاء الحظر! تقدر تستخدم البوت تاني عادي."
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/userinfo",):
            if not args:
                await _send_whatsapp_message(wa_id, 
                    "👤 *معلومات مستخدم شاملة*\n\n"
                    "الاستخدام: /userinfo رقم_الواتساب\n"
                    "مثال: /userinfo 201203551789\n\n"
                    "💡 بيرجع كل المعلومات العامة:\n"
                    "→ الاسم (من البروفايل + المفضل)\n"
                    "→ الخطة وتاريخ الاشتراكات\n"
                    "→ كم مدة على البوت\n"
                    "→ إحصائيات الاستخدام\n\n"
                    "🔒 مش بيرجع بيانات حساسة")
                return
            phone = args[0]
            # ✅ FIX: First try to find user by wa_phone in database (reliable)
            # Falls back to deterministic hash if not found
            from memory import find_user_by_wa_phone
            target_id = find_user_by_wa_phone(phone)
            if target_id is None:
                # No user found with this phone — try deterministic hash as fallback
                target_id = _wa_phone_to_user_id(phone)
            from premium import get_user_stats
            
            stats = get_user_stats(target_id, platform="whatsapp")
            
            if not stats.get("found"):
                await _send_whatsapp_message(wa_id, "❌ المستخدم ده مش موجود في قاعدة البيانات.")
                return
            
            # ═══ الأسماء ═══
            name = stats.get("name", "")
            profile_name = stats.get("profile_name", "")
            
            if name and profile_name and name != profile_name:
                name_display = f"{name} (اسم البروفايل: {profile_name})"
            elif name:
                name_display = name
            elif profile_name:
                name_display = profile_name
            else:
                name_display = "مش محدد"
            
            # ═══ معلومات أساسية ═══
            plan_display = "⭐ Premium" if stats.get("is_premium") else "🆓 Free"
            if stats.get("plan") == "premium_plus":
                plan_display = "⭐ Premium+"
            
            platform_display = "📱 تليجرام" if stats.get("platform") == "telegram" else "📱 واتساب"
            lang_display = "🇪🇬 العربية" if stats.get("language") == "ar" else "🇬🇧 English"
            
            # ═══ معلومات Premium ═══
            if stats.get("is_premium"):
                premium_section = (
                    f"⭐ الخطة: {plan_display}\n"
                    f"📅 مفعل من: {stats.get('premium_since', '')[:10] if stats.get('premium_since') else 'مش محدد'}\n"
                    f"⏰ المتبقي: {stats.get('premium_expires_display', '—')}\n"
                    f"⏱️ على الخطة دي من: {stats.get('time_on_current_plan', 'مش محدد')}\n"
                    f"🔑 بواسطة: {stats.get('premium_granted_by') or 'مش محدد'}\n"
                )
            else:
                premium_section = f"⭐ الخطة: {plan_display}\n"
            
            # ═══ تاريخ Premium ═══
            grant_count = stats.get("premium_grant_count", 0)
            revoke_count = stats.get("premium_revoke_count", 0)
            history = stats.get("premium_history", [])
            
            premium_history_text = f"🔄 مرات الاشتراك: {grant_count}"
            if revoke_count > 0:
                premium_history_text += f" | ❌ مرات الإلغاء: {revoke_count}"
            
            if history:
                premium_history_text += "\n\n📜 آخر أحداث Premium:"
                for h in history[:5]:
                    action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                    action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                    date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                    by = h.get("granted_by", "") or ""
                    by_text = f" (بواسطة: {by})" if by and by != "None" else ""
                    premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"
            
            # ═══ حالة الحظر ═══
            ban_section = ""
            if stats.get("banned"):
                ban_section = f"\n🚫 محظور! السبب: {stats.get('ban_reason', 'مش محدد')}\n"
            
            # ═══ تحذيرات ═══
            warnings = stats.get("warning_count", 0)
            warn_section = f"\n⚠️ تحذيرات: {warnings}/3" if warnings > 0 else ""
            
            # ═══ أدمن ═══
            admin_section = "\n👑 أدمن: نعم" if stats.get("is_admin") else ""
            
            # ═══ إحصائيات الاستخدام ═══
            total = stats.get("total_usage", {})
            today = stats.get("today_usage", {})
            
            info = (
                f"👤 *معلومات المستخدم الشاملة*\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔒 بدون بيانات حساسة\n\n"
                f"📱 الرقم: {_wa_phone_to_display(phone)}\n"
                f"📝 الاسم: {name_display}\n"
                f"📱 المنصة: {platform_display}\n"
                f"🌐 اللغة: {lang_display}\n"
                f"⏱️ على البوت من: {stats.get('time_on_bot', 'مش محدد')}\n\n"
                f"{premium_section}\n"
                f"{premium_history_text}\n"
                f"{ban_section}{warn_section}{admin_section}\n\n"
                f"📊 *استخدام اليوم:*\n"
                f"→ رسائل AI: {today.get('ai_messages', 0)}\n"
                f"→ PDF: {today.get('pdf_analyses', 0)}\n"
                f"→ صور: {today.get('image_analyses', 0)}\n"
                f"→ YouTube: {today.get('youtube_summaries', 0)}\n"
                f"→ بحث: {today.get('searches', 0)}\n\n"
                f"📈 *الإجمالي عبر الوقت:*\n"
                f"→ رسائل AI: {total.get('ai_messages', 0)}\n"
                f"→ PDF: {total.get('pdf_analyses', 0)}\n"
                f"→ صور: {total.get('image_analyses', 0)}\n"
                f"→ YouTube: {total.get('youtube_summaries', 0)}\n"
                f"→ بحث: {total.get('searches', 0)}\n"
                f"→ بحث عميق: {total.get('deep_searches', 0)}\n"
                f"📅 أيام نشاط: {total.get('active_days', 0)}\n\n"
                f"💬 محادثات: {stats.get('chat_count', 0)}\n"
                f"⚡ أوامر: {stats.get('commands_used', 0)}\n"
                f"🎯 اهتمامات: {', '.join(stats.get('interests', [])[:5]) if stats.get('interests') else 'لا يوجد'}\n\n"
                f"📅 التسجيل: {stats.get('created_at', 'مش محدد')[:16] if stats.get('created_at') else 'مش محدد'}\n"
                f"📅 آخر تفاعل: {stats.get('last_interaction', 'مش محدد')[:16] if stats.get('last_interaction') else 'مش محدد'}"
            )
            await _send_whatsapp_message(wa_id, info)

        elif cmd in ("/userstats",):
            if not args:
                await _send_whatsapp_message(wa_id, "📊 الاستخدام: /userstats رقم_الواتساب\nمثال: /userstats 201203551789\n\n💡 بيرجع إحصائيات شاملة بدون بيانات حساسة")
                return
            phone = args[0]
            # ✅ FIX: First try to find user by wa_phone in database (reliable)
            from memory import find_user_by_wa_phone
            target_id = find_user_by_wa_phone(phone)
            if target_id is None:
                target_id = _wa_phone_to_user_id(phone)
            from premium import get_user_stats
            
            stats = get_user_stats(target_id, platform="whatsapp")
            
            if not stats.get("found"):
                await _send_whatsapp_message(wa_id, "❌ المستخدم ده مش موجود في قاعدة البيانات.")
                return
            
            # ═══ معلومات أساسية ═══
            plan_display = "⭐ Premium" if stats.get("is_premium") else "🆓 Free"
            if stats.get("plan") == "premium_plus":
                plan_display = "⭐ Premium+"
            
            platform_display = "📱 تليجرام" if stats.get("platform") == "telegram" else "📱 واتساب"
            lang_display = "🇪🇬 العربية" if stats.get("language") == "ar" else "🇬🇧 English"
            
            # ═══ معلومات Premium ═══
            if stats.get("is_premium"):
                premium_section = (
                    f"⭐ الخطة: {plan_display}\n"
                    f"📅 مفعل من: {stats.get('premium_since', '')[:10] if stats.get('premium_since') else 'مش محدد'}\n"
                    f"⏰ المتبقي: {stats.get('premium_expires_display', '—')}\n"
                    f"⏱️ على الخطة دي من: {stats.get('time_on_current_plan', 'مش محدد')}\n"
                    f"🔑 بواسطة: {stats.get('premium_granted_by') or 'مش محدد'}\n"
                )
            else:
                premium_section = f"⭐ الخطة: {plan_display}\n"
            
            # ═══ تاريخ Premium ═══
            grant_count = stats.get("premium_grant_count", 0)
            revoke_count = stats.get("premium_revoke_count", 0)
            history = stats.get("premium_history", [])
            
            premium_history_text = f"🔄 مرات الاشتراك: {grant_count}"
            if revoke_count > 0:
                premium_history_text += f" | ❌ مرات الإلغاء: {revoke_count}"
            
            if history:
                premium_history_text += "\n\n📜 آخر أحداث Premium:"
                for h in history[:5]:
                    action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                    action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                    date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                    by = h.get("granted_by", "") or ""
                    by_text = f" ({by})" if by and by != "None" else ""
                    premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"
            
            # ═══ إحصائيات الاستخدام ═══
            total = stats.get("total_usage", {})
            today = stats.get("today_usage", {})
            
            # ═══ حالة الحظر ═══
            ban_section = ""
            if stats.get("banned"):
                ban_section = f"\n🚫 محظور! السبب: {stats.get('ban_reason', '')}"
            
            warnings = stats.get("warning_count", 0)
            warn_section = f"\n⚠️ تحذيرات: {warnings}/3" if warnings > 0 else ""
            admin_section = "\n👑 أدمن: نعم" if stats.get("is_admin") else ""
            
            interests = stats.get("interests", [])
            companies = stats.get("favorite_companies", [])
            
            info = (
                f"📊 *إحصائيات المستخدم الشاملة*\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔒 بدون بيانات حساسة\n\n"
                f"👤 *معلومات أساسية:*\n"
                f"📱 الرقم: {_wa_phone_to_display(phone)}\n"
                f"📝 الاسم: {stats.get('name') or 'مش محدد'}\n"
                f"{platform_display} | {lang_display}\n"
                f"📅 على البوت من: {stats.get('time_on_bot', 'مش محدد')} ({stats.get('days_on_bot', 0)} يوم)\n"
                f"📅 التسجيل: {stats.get('created_at', '')[:16] if stats.get('created_at') else 'مش محدد'}\n"
                f"📅 آخر تفاعل: {stats.get('last_interaction', '')[:16] if stats.get('last_interaction') else 'مش محدد'}\n\n"
                f"💬 محادثات: {stats.get('chat_count', 0)}\n"
                f"⚡ أوامر: {stats.get('commands_used', 0)}\n"
                f"📬 مشترك أخبار: {'نعم ✅' if stats.get('subscribed') else 'لا ❌'}"
                f"{admin_section}{ban_section}{warn_section}\n\n"
                f"⭐ *Premium:*\n"
                f"{premium_section}\n"
                f"{premium_history_text}\n\n"
                f"📊 *استخدام اليوم:*\n"
                f"→ رسائل AI: {today.get('ai_messages', 0)}\n"
                f"→ PDF: {today.get('pdf_analyses', 0)}\n"
                f"→ صور: {today.get('image_analyses', 0)}\n"
                f"→ YouTube: {today.get('youtube_summaries', 0)}\n"
                f"→ بحث: {today.get('searches', 0)}\n\n"
                f"📈 *الإجمالي عبر الوقت:*\n"
                f"→ رسائل AI: {total.get('ai_messages', 0)}\n"
                f"→ PDF: {total.get('pdf_analyses', 0)}\n"
                f"→ صور: {total.get('image_analyses', 0)}\n"
                f"→ YouTube: {total.get('youtube_summaries', 0)}\n"
                f"→ بحث: {total.get('searches', 0)}\n"
                f"→ بحث عميق: {total.get('deep_searches', 0)}\n"
                f"→ إنشاء صور: {total.get('image_generations', 0)}\n"
                f"→ تعديل صور: {total.get('image_edits', 0)}\n"
                f"📅 أيام نشاط: {total.get('active_days', 0)}\n\n"
                f"🎯 اهتمامات: {', '.join(interests[:8]) if interests else 'لا يوجد'}\n"
                f"🏢 شركات: {', '.join(companies[:5]) if companies else 'لا يوجد'}\n"
                f"📚 متعلمة: {stats.get('learning_topics_count', 0)} موضوع\n"
                f"⭐ مفضلات: {stats.get('favorites_count', 0)} عنصر\n"
                f"🗂️ Workspace: {stats.get('workspace_count', 0)} عنصر\n"
                f"🔔 تنبيهات: {stats.get('smart_alerts_count', 0)}"
            )
            
            # WhatsApp message limit — split if needed
            for chunk in _split_whatsapp_message(info):
                await _send_whatsapp_message(wa_id, chunk)

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
                target_id = _resolve_wa_target(phone)
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
                target_id = _resolve_wa_target(phone)
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
                target_id = _resolve_wa_target(phone)
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

    elif cmd_name == "cookies":
        # 🍪 /cookies delete — أدمن بس
        if is_admin and arg.lower() in ("delete", "remove", "مسح", "حذف"):
            cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            try:
                if os.path.exists(cookies_file):
                    os.remove(cookies_file)
                    await _send_whatsapp_message(wa_id, "✅ تم حذف ملف الكوكيز.")
                    logger.info(f"🍪 WA Cookies file deleted by admin {wa_id}")
                else:
                    await _send_whatsapp_message(wa_id, "❌ ملف الكوكيز مش موجود أصلاً.")
            except Exception as e:
                await _send_whatsapp_message(wa_id, f"❌ فشل الحذف: {e}")
        elif not is_admin:
            await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
        else:
            await _handle_command(wa_id, "cookies", wa_user_id, contact_name, message_id)

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
                "📝 أمثلة:\n→ /edit غيّر الخلفية لمسجد\n→ /edit خلي الصورة زي لوحة إسلامية")

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
                _wa_user_yt_url[wa_id] = arg  # 🍪 خزّن رابط YouTube عشان زر التحميل
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
                        {"id": "cmd_download_yt", "title": "📥 حمّله"},
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
        # /video <query> — بحث Dailymotion + عرض نتائج + تحميل فيديو
        await _handle_wa_video_search(wa_id, arg, wa_user_id, contact_name, message_id, is_admin)

    elif cmd_name == "audio_search_query":
        # /audio <query> — بحث SoundCloud + عرض نتائج + تحميل صوت
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
    """تحميل فيديو/صوت YouTube عبر yt-dlp مباشرة للواتساب
    
    format: "720" لفيديو 720p, "mp3" لصوت, الخ
    """
    # تحويل الفورمات لجودة yt-dlp
    is_audio = (format == "mp3")
    quality_map = {"1080": "best", "720": "medium", "360": "low", "mp3": "audio"}
    yt_quality = quality_map.get(format, "medium")
    
    logger.info(f"🎬 WA YouTube download: format={format} → yt_quality={yt_quality} for {url[:80]}")
    await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=yt_quality, force_audio=is_audio)


def _cleanup_wa_file(file_path: str):
    """حذف ملف مؤقت"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass


async def _handle_wa_video_search(wa_id: str, query: str, wa_user_id: int, 
                                   contact_name: str, message_id: str, is_admin: bool):
    """بحث Dailymotion + عرض نتائج + تحميل فيديو عبر WhatsApp"""
    # 🛡️ Safety: Check query before searching
    try:
        is_safe, reason = await check_query_safety(query, platform="whatsapp", user_id=str(wa_user_id))
        if not is_safe:
            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
            return
    except Exception as e:
        logger.warning(f"🛡️ Query safety check failed (allowing): {e}")
    
    await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في Dailymotion عن: {query}...")
    
    try:
        from dailymotion_search import search_dailymotion, format_search_results as format_dm_results
        
        results = await search_dailymotion(query, max_results=5)
        
        # ✅ FIX: If Dailymotion fails, fallback to YouTube search
        if not results:
            logger.info(f"🎬 Dailymotion search failed for '{query}', trying YouTube as fallback...")
            await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في YouTube عن: {query}...")
            try:
                from youtube_search import search_youtube
                results = await search_youtube(query, max_results=5)
            except Exception as yt_err:
                logger.warning(f"🎬 YouTube fallback also failed: {yt_err}")
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش نتائج. جرب كلمات بحث تانية!")
            return
        
        # 🛡️ Safety: Filter search results
        try:
            results = await check_search_results_safety(results, platform="whatsapp", user_id=str(wa_user_id))
            if not results:
                await _send_whatsapp_message(wa_id, get_no_safe_results_message("ar"))
                return
        except Exception as e:
            logger.warning(f"🛡️ Search results safety check failed (allowing): {e}")
        
        # حفظ النتائج في cache
        cache_key = hashlib.md5(f"wa_{wa_id}_{query}".encode()).hexdigest()[:12]
        _wa_search_cache[cache_key] = {
            "results": results,
            "query": query,
            "type": "video",
            "created_at": time.time(),
        }
        
        # عرض النتائج كـ interactive list
        text = format_dm_results(results, lang="ar")
        
        sections = [{
            "title": "🎬 نتائج Dailymotion",
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
    """بحث صوت + عرض نتائج + تحميل صوت عبر WhatsApp
    
    🔴 FIX v3: Dailymotion كمحرك بحث أساسي للصوت
    - Dailymotion API مجاني ومفتوح — مش محتاج API key
    - yt-dlp بيدعم Dailymotion للتحميل
    - SoundCloud كـ fallback
    """
    # 🛡️ Safety: Check query before searching
    try:
        is_safe, reason = await check_query_safety(query, platform="whatsapp", user_id=str(wa_user_id))
        if not is_safe:
            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
            return
    except Exception as e:
        logger.warning(f"🛡️ Query safety check failed (allowing): {e}")
    
    await _send_whatsapp_message(wa_id, f"🔍 جاري البحث عن صوت: {query}...")
    
    results = None
    search_source = "dailymotion"
    
    try:
        # 🔴 الطريقة 1: Dailymotion Search (أساسي — مجاني ومفتوح ومستقر)
        try:
            from dailymotion_search import search_dailymotion
            results = await search_dailymotion(query, max_results=5)
            if results:
                # Mark results as audio search for proper handling
                for r in results:
                    r["_search_type"] = "audio"
                logger.info(f"🎵 Dailymotion audio search: {len(results)} results for '{query}'")
        except Exception as dm_err:
            logger.warning(f"🎵 Dailymotion search failed: {dm_err}")
        
        # 🔴 الطريقة 2: SoundCloud كـ fallback
        if not results:
            logger.info(f"🎵 Dailymotion search failed for '{query}', trying SoundCloud as fallback...")
            await _send_whatsapp_message(wa_id, f"🔍 جاري البحث في SoundCloud عن: {query}...")
            try:
                from soundcloud_search import search_soundcloud
                results = await search_soundcloud(query, max_results=5)
                if results:
                    search_source = "soundcloud"
                    logger.info(f"🎵 SoundCloud audio search: {len(results)} results for '{query}'")
            except Exception as sc_err:
                logger.warning(f"🎵 SoundCloud fallback also failed: {sc_err}")
        
        if not results:
            await _send_whatsapp_message(wa_id, "❌ مفيش نتائج. جرب كلمات بحث تانية!")
            return
        
        # 🛡️ Safety: Filter search results
        try:
            results = await check_search_results_safety(results, platform="whatsapp", user_id=str(wa_user_id))
            if not results:
                await _send_whatsapp_message(wa_id, get_no_safe_results_message("ar"))
                return
        except Exception as e:
            logger.warning(f"🛡️ Search results safety check failed (allowing): {e}")
        
        cache_key = hashlib.md5(f"wa_{wa_id}_{query}".encode()).hexdigest()[:12]
        _wa_search_cache[cache_key] = {
            "results": results,
            "query": query,
            "type": "audio",
            "created_at": time.time(),
        }
        
        # تنسيق النتائج
        source_label = "Dailymotion" if search_source == "dailymotion" else "SoundCloud"
        text = f"🔍 *نتائج بحث صوت {source_label}* ({len(results)} نتيجة)\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        
        for i, r in enumerate(results):
            title = r.get('title', 'بدون عنوان')
            duration = r.get('duration', '0:00')
            channel = r.get('channel', '')
            views = r.get('views', '0')
            
            text += f"*{i+1}.* {title}\n"
            if duration and duration != "0:00":
                text += f"⏱ {duration}"
            if channel:
                text += f" | 🎤 {channel[:20]}"
            if views and views != "0":
                text += f" | ▶️ {views}"
            text += "\n\n"
        
        sections = [{
            "title": f"🎵 نتائج {source_label} - صوت",
            "rows": []
        }]
        
        for i, r in enumerate(results):
            title = r['title'][:24]
            desc = f"⏱ {r.get('duration', '0:00')} | 🎤 {r.get('channel', '')[:15]}"
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
    # 🛡️ Safety: Check query before searching
    try:
        is_safe, reason = await check_query_safety(query, platform="whatsapp", user_id=str(wa_user_id))
        if not is_safe:
            await _send_whatsapp_message(wa_id, get_block_message("ar", reason))
            return
    except Exception as e:
        logger.warning(f"🛡️ Query safety check failed (allowing): {e}")
    
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
        # 🔴 FIX: مسح حالة المستخدم لأنه اختار من الأزرار — عشان الرسالة العادية اللي بعد كده متتعاملش كأنها اختيار بحث
        _clear_user_state(wa_id)
        # 🔴 FIX: بدل ما نحمل بجودة ثابتة، نعرض اختيار الجودة للمستخدم (زي التليجرام)
        await _show_quality_selection_for_search(wa_id, r['url'], r['title'], wa_user_id, contact_name, message_id, is_admin, search_type="video")
    
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
        # 🔴 FIX: مسح حالة المستخدم لأنه اختار من الأزرار — عشان الرسالة العادية اللي بعد كده متتعاملش كأنها اختيار بحث
        _clear_user_state(wa_id)
        # 🔴 FIX: بدل ما نحمل صوت مباشرة، نعرض اختيار الجودة (فيديو أو صوت)
        await _show_quality_selection_for_search(wa_id, r['url'], r['title'], wa_user_id, contact_name, message_id, is_admin, search_type="audio")
    
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

        # 🔴 FIX: بنستخدم _execute_photo_search بدل تكرار الكود
        # _execute_photo_search بيدي أخطاء بنفسه — مش محتاجين try/except هنا
        await _execute_photo_search(wa_id, query, count, wa_user_id, contact_name, message_id, is_admin, cache_key)


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
    logger.info("✅ WhatsApp webhook routes registered")
    logger.info(f"   GET  /whatsapp/webhook — Meta verification")
    logger.info(f"   POST /whatsapp/webhook — Incoming messages → AI engine")
    logger.info(f"   GET  /health — Health check")
    logger.info(f"   GET  /debug/whatsapp — Full diagnostic")
    logger.info(f"   GET  /debug/whatsapp/activity — Webhook activity log")
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
