"""
Handler package for My Bro Telegram bot.
Exports register_handlers() to wire all handlers with the Application.
"""

from telegram.ext import (
    CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

from handlers.basic_handlers import (
    start_command, help_command, about_command,
    status_command, premium_command, plan_command,
    dashboard_command,
)
from handlers.news_handlers import (
    news_command, breaking_command, weekly_command,
    trending_command, search_command,
)
from handlers.ai_handlers import (
    ask_command, learn_command, roadmap_command,
    deepsearch_command, company_command,
)
from handlers.memory_handlers import (
    memory_command, progress_command, favorite_command,
    favorites_command, forget_command, resetmemory_command,
    language_command, time_command, sources_command,
    subscribe_command, unsubscribe_command, subscribers_command,
)
from handlers.media_handlers import (
    pdf_command, youtube_command,
    handle_document, handle_photo, handle_voice,
    study_command, quiz_command, exam_command, studyplan_command,
    exit_command,
)
from handlers.image_handlers import (
    image_command, edit_command,
)
from handlers.download_handlers import (
    download_command, handle_download_callback,
    cookies_command, handle_cookies_file,
)
from handlers.search_download_handlers import (
    video_search_command, audio_search_command,
    photo_search_command, handle_search_callback,
)
from handlers.callbacks import button_callback
from handlers.message_handler import handle_message

from admin import (
    admin_command, grant_premium_command, revoke_premium_command,
    broadcast_command, userinfo_command,
    ban_command, unban_command, warn_command,
    allusers_command, botstats_command,
    addadmin_command, removeadmin_command, listadmins_command,
    resetlimit_command,
)


async def _handle_any_document(update, context):
    """توجيه الملفات: cookies.txt → cookies handler، غير كده → PDF/document handler"""
    # 🔴 لو الملف اسمه cookies.txt أو فيه كلمة cookie → نوجهه لـ cookies handler
    if update.message.document:
        filename = (update.message.document.file_name or "").lower()
        if 'cookie' in filename and filename.endswith('.txt'):
            await handle_cookies_file(update, context)
            return
    # باقي الملفات → handle_document العادي
    await handle_document(update, context)


def register_handlers(app):
    """Register all bot handlers with the telegram Application."""

    # أوامر أساسية
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("breaking", breaking_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("trending", trending_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("company", company_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("learn", learn_command))
    app.add_handler(CommandHandler("roadmap", roadmap_command))

    # إعدادات
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("time", time_command))
    app.add_handler(CommandHandler("sources", sources_command))

    # اشتراكات
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CommandHandler("subscribers", subscribers_command))

    # معلومات
    app.add_handler(CommandHandler("about", about_command))

    # ذاكرة
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("favorite", favorite_command))
    app.add_handler(CommandHandler("favorites", favorites_command))
    app.add_handler(CommandHandler("forget", forget_command))
    app.add_handler(CommandHandler("resetmemory", resetmemory_command))

    # أوامر متقدمة
    # بحث عميق تم إزالته من الواجهة - مش مسجل كـ command
    # app.add_handler(CommandHandler("deepsearch", deepsearch_command))
    app.add_handler(CommandHandler("status", status_command))

    # Premium أوامر
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("plan", plan_command))

    # Study Mode أوامر (Premium)
    app.add_handler(CommandHandler("study", study_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("exam", exam_command))
    app.add_handler(CommandHandler("studyplan", studyplan_command))
    app.add_handler(CommandHandler("exit", exit_command))  # الخروج من وضع الدراسة أو أي workflow

    # YouTube أمر
    app.add_handler(CommandHandler("youtube", youtube_command))

    # PDF أمر
    app.add_handler(CommandHandler("pdf", pdf_command))

    # Dashboard أمر (Admin)
    app.add_handler(CommandHandler("dashboard", dashboard_command))

    # Admin أوامر
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("grant", grant_premium_command))
    app.add_handler(CommandHandler("revoke", revoke_premium_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("userinfo", userinfo_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("allusers", allusers_command))
    app.add_handler(CommandHandler("botstats", botstats_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command))
    app.add_handler(CommandHandler("removeadmin", removeadmin_command))
    app.add_handler(CommandHandler("listadmins", listadmins_command))
    app.add_handler(CommandHandler("resetlimit", resetlimit_command))

    # 🎨 Image Generation (Premium Only)
    app.add_handler(CommandHandler("image", image_command))

    # 🖌️ Image Editing (Premium Only)
    app.add_handler(CommandHandler("edit", edit_command))

    # 📥 تحميل الوسائط (فيديو/صور/صوت)
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CallbackQueryHandler(handle_download_callback, pattern="^dl_"))
    
    # 🔍 تحميل بالبحث (فيديو/صوت/صور)
    app.add_handler(CommandHandler("video", video_search_command))
    app.add_handler(CommandHandler("audio", audio_search_command))
    app.add_handler(CommandHandler("photo", photo_search_command))
    app.add_handler(CallbackQueryHandler(handle_search_callback, pattern="^(sv|sa)_"))

    # 🍪 أمر الكوكيز (أدمن بس) — عشان يرفع ملف cookies.txt لـ YouTube
    app.add_handler(CommandHandler("cookies", cookies_command))

    # أزرار Inline
    app.add_handler(CallbackQueryHandler(button_callback))

    # Message Handlers (order matters!)
    # 🍪 ملف الكوكيز — لازم يكون قبل handle_document عشان الأدمن يقدر يرفعه
    app.add_handler(MessageHandler(filters.Document.ALL, _handle_any_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
