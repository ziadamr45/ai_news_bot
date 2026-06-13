"""
WhatsApp Cloud API Webhook Server
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ تم تقسيم الملف ده لـ package منفصل (whatsapp/)
الملف ده بيقوم بدور shim/bridge عشان backward compatibility

لو عايز تعدل أي حاجة، روح للملف المناسب:
- whatsapp/state.py     → الثوابت والحالة المشتركة والأدوات المساعدة
- whatsapp/api.py       → دوال إرسال الرسائل والتواصل مع WhatsApp API
- whatsapp/media.py     → تحميل ومعالجة الميديا (فيديو، صوت، صور)
- whatsapp/commands.py  → معالجة الأوامر (/grant, /ban, /download, etc.)
- whatsapp/callbacks.py → معالجة الردود التفاعلية و webhook handlers

الملفات الخارجية بتستورد من هنا عادي:
    from whatsapp_webhook import _send_whatsapp_message, start_webhook_server
"""

# Re-export everything from the whatsapp package for backward compatibility
from whatsapp import *  # noqa: F401,F403

# Explicit re-exports for commonly imported names
# (helps IDEs and linters know what's available)
from whatsapp import (  # noqa: F811
    # Config
    WHATSAPP_VERIFY_TOKEN,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_APP_SECRET,
    WEBHOOK_PORT,
    ALLOWED_WA_NUMBERS,
    WA_MAX_MSG,
    ADMIN_WA_ID,
    DEVELOPER_WHATSAPP,
    DEVELOPER_WHATSAPP_URL,
    # API
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
    # Media
    _download_and_send_video,
    _generate_and_send_image,
    _edit_and_send_image,
    _show_quality_selection,
    _transcribe_audio,
    _download_wa_media_base64,
    _analyze_image,
    _analyze_document,
    # Commands
    _handle_command,
    _handle_command_with_arg,
    _handle_admin_with_args,
    # Callbacks & Webhook
    _send_ai_response,
    _send_contextual_buttons,
    _handle_incoming_message,
    root_handler,
    webhook_verification,
    webhook_receiver,
    process_webhook_body,
    health_check,
    debug_whatsapp,
    debug_whatsapp_activity,
    create_webhook_app,
    start_webhook_server,
    # Search Handlers
    _handle_wa_video_search,
    _handle_wa_audio_search,
    _handle_wa_photo_search,
    # State & Utilities
    _strip_html_for_whatsapp,
    _split_whatsapp_message,
    _verify_signature,
    _wa_phone_to_user_id,
    _wa_phone_to_display,
    _is_wa_admin,
    _set_user_state,
    _get_user_state,
    _clear_user_state,
    _detect_platform,
    _is_youtube_url,
    _extract_url,
    _is_threads_url,
    _store_url,
    _get_url,
    _contains_arabic,
    logger,
)
