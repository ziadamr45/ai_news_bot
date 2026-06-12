"""
WhatsApp Callback Handlers Package
====================================
Split from the original callbacks.py (2645 lines) into focused sub-modules:

- ai_response.py       → _send_ai_response, _send_contextual_buttons
- message_handler.py   → _handle_incoming_message
- admin_handler.py     → _handle_admin_with_args
- search_handlers.py   → _wa_download_youtube, _handle_wa_video/audio/photo_search, _handle_wa_search_callback
- webhook_server.py    → root_handler, webhook_verification, webhook_receiver, process_webhook_body,
                         health_check, debug_whatsapp, debug_whatsapp_activity, create_webhook_app,
                         start_webhook_server

All names are re-exported here for backward compatibility:
    from whatsapp.callbacks import _send_ai_response, root_handler, ...
"""

# ═══════════════════════════════════════
# AI Response Helper
# ═══════════════════════════════════════
from whatsapp.callbacks.ai_response import (
    _send_ai_response,
    _send_contextual_buttons,
)

# ═══════════════════════════════════════
# Message Handler
# ═══════════════════════════════════════
from whatsapp.callbacks.message_handler import (
    _handle_incoming_message,
)

# ═══════════════════════════════════════
# Admin Command Handler
# ═══════════════════════════════════════
from whatsapp.callbacks.admin_handler import (
    _handle_admin_with_args,
)

# ═══════════════════════════════════════
# Search Handlers
# ═══════════════════════════════════════
from whatsapp.callbacks.search_handlers import (
    _wa_download_youtube,
    _handle_wa_video_search,
    _handle_wa_audio_search,
    _handle_wa_photo_search,
    _handle_wa_search_callback,
)

# ═══════════════════════════════════════
# Webhook Server
# ═══════════════════════════════════════
from whatsapp.callbacks.webhook_server import (
    root_handler,
    webhook_verification,
    webhook_receiver,
    process_webhook_body,
    health_check,
    debug_whatsapp,
    debug_whatsapp_activity,
    create_webhook_app,
    start_webhook_server,
)

__all__ = [
    # AI Response
    "_send_ai_response",
    "_send_contextual_buttons",
    # Message Handler
    "_handle_incoming_message",
    # Admin Handler
    "_handle_admin_with_args",
    # Search Handlers
    "_wa_download_youtube",
    "_handle_wa_video_search",
    "_handle_wa_audio_search",
    "_handle_wa_photo_search",
    "_handle_wa_search_callback",
    # Webhook Server
    "root_handler",
    "webhook_verification",
    "webhook_receiver",
    "process_webhook_body",
    "health_check",
    "debug_whatsapp",
    "debug_whatsapp_activity",
    "create_webhook_app",
    "start_webhook_server",
]
