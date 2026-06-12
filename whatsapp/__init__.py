"""
WhatsApp Bot Package
تم تقسيم whatsapp_webhook.py الضخم (8361 سطر) لـ modules منفصلة عشان سهولة الصيانة

التركيب:
- whatsapp/state.py     → الثوابت والحالة المشتركة والأدوات المساعدة
- whatsapp/api.py       → دوال إرسال الرسائل والتواصل مع WhatsApp API
- whatsapp/media.py     → تحميل ومعالجة الميديا (فيديو، صوت، صور)
- whatsapp/commands.py  → معالجة الأوامر (/grant, /ban, /download, etc.)
- whatsapp/callbacks.py → معالجة الردود التفاعلية و webhook handlers

كل الدوال متاحة من هنا عشان backward compatibility:
    from whatsapp import _send_whatsapp_message, start_webhook_server
"""

# ═══════════════════════════════════════
# State & Utilities
# ═══════════════════════════════════════
from whatsapp.state import (
    # Config
    WHATSAPP_VERIFY_TOKEN,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_APP_SECRET,
    WHATSAPP_API_URL,
    WEBHOOK_PORT,
    ALLOWED_WA_NUMBERS,
    WA_MAX_MSG,
    ADMIN_WA_ID,
    DEVELOPER_WHATSAPP,
    DEVELOPER_WHATSAPP_URL,
    # Utility functions
    _get_env,
    _wa_phone_to_user_id,
    _wa_phone_to_display,
    _is_wa_admin,
    _ensure_wa_admin_premium,
    # State management
    _processed_message_ids,
    _MAX_DEDUP_CACHE,
    _wa_user_pdf_context,
    _wa_user_yt_url,
    _wa_user_state,
    _WA_STATE_TTL,
    _set_user_state,
    _get_user_state,
    _clear_user_state,
    _url_cache,
    _URL_CACHE_TTL,
    _wa_user_edit_images,
    _webhook_activity_log,
    _MAX_ACTIVITY_LOG,
    _log_activity,
    _is_duplicate_wa_message,
    _log_event,
    # Signature & formatting
    _verify_signature,
    _strip_html_for_whatsapp,
    _split_whatsapp_message,
    # URL utilities
    _detect_platform,
    _is_youtube_url,
    _extract_url,
    _is_threads_url,
    _store_url,
    _get_url,
    # Command triggers
    _COMMAND_TRIGGERS,
    # Search cache
    _wa_search_cache,
    _WA_SEARCH_CACHE_TTL,
    # Arabic detection
    _contains_arabic,
    logger,
)

# ═══════════════════════════════════════
# API Communication
# ═══════════════════════════════════════
from whatsapp.api import (
    _wa_api_post,
    _send_whatsapp_message,
    _send_whatsapp_reaction,
    _mark_message_read,
    _send_interactive_buttons,
    _send_interactive_list,
    _send_typing_indicator,
    ThinkingFeedback,
    _send_whatsapp_image,
    _send_whatsapp_document,
    _send_whatsapp_document_from_file,
    _send_whatsapp_audio,
    _send_whatsapp_video,
)

# ═══════════════════════════════════════
# Media Processing
# ═══════════════════════════════════════
from whatsapp.media import (
    _translate_prompt_to_english,
    _generate_and_send_image,
    _edit_and_send_image,
    _download_threads_media_wa,
    _show_quality_selection,
    _show_quality_selection_for_search,
    _download_and_send_video,
    _transcribe_audio,
    _download_wa_media_base64,
    _analyze_image,
    _analyze_document,
    _execute_photo_search,
)

# ═══════════════════════════════════════
# Command Handlers
# ═══════════════════════════════════════
from whatsapp.commands import (
    _handle_command,
    _handle_command_with_arg,
    _wa_download_youtube,
    _cleanup_wa_file,
)

# ═══════════════════════════════════════
# Callbacks & Webhook Handlers
# ═══════════════════════════════════════
from whatsapp.callbacks import (
    _send_ai_response,
    _send_contextual_buttons,
    _handle_wa_video_search,
    _handle_wa_audio_search,
    _handle_wa_photo_search,
    _handle_wa_search_callback,
    root_handler,
    webhook_verification,
    webhook_receiver,
    process_webhook_body,
    _handle_incoming_message,
    _handle_admin_with_args,
    health_check,
    debug_whatsapp,
    debug_whatsapp_activity,
    create_webhook_app,
    start_webhook_server,
)
