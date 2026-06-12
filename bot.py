"""
My Bro v9.4 - مساعد الذكاء الاصطناعي الشخصي المتكامل
بوت تيليجرام كامل مع:
+ أوامر + محادثة ذكية + بحث ويب + أزرار تفاعلية
+ تجربة متميزة مع مؤشرات الكتابة + نظام تقدم مباشر + جدولة الأخبار
+ نظام Premium + وكلاء AI (PDF, YouTube, Study, Voice)
+ لوحة تحكم Dashboard + تتبع الاستخدام
+ نظام ذاكرة متكامل (سياق 20 رسالة + ذاكرة طويلة المدى + استرجاع دلالي)
"""

import logging
import sys
import asyncio
import signal
from datetime import datetime

# 🐦 Sentry — must be one of the very first imports
from sentry_config import init_sentry
init_sentry()

from telegram import Update
from telegram.ext import Application, ContextTypes

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import (
    BOT_TOKEN, BOT_NAME, BOT_VERSION,
    DAILY_NEWS_TIMEZONE, BROADCAST_DELAY_SECONDS, CHAT_ID,
)
from premium import init_premium_tables
from dashboard import init_dashboard_tables, track_event
from handlers import register_handlers
from handlers.error_monitor import get_error_stats

# ═══ News broadcast imports ═══
from memory import (
    get_subscribers_for_time, set_last_news_delivery,
    unsubscribe_user,
)
from news_fetcher import fetch_news
from filters import filter_news
from scorer import rank_articles
from summarizer import summarize_articles
from formatters import (
    format_news_item, daily_news_header, daily_news_footer,
)

# إعداد الـ Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# ⚡ كاش أخبار AI المسبق — يتجهز في الخلفية كل ساعة
_precomputed_news_cache = {
    "ar": {"summary": "", "updated_at": 0},
    "en": {"summary": "", "updated_at": 0},
}
_NEWS_CACHE_TTL = 3600  # 1 ساعة


async def _precompute_news_background():
    """حساب أخبار AI في الخلفية — يتجهز كل ساعة عشان الرد يكون فوري"""
    global _precomputed_news_cache

    while True:
        try:
            for lang in ["ar", "en"]:
                logger.info(f"📰 Pre-computing AI news summary ({lang})...")

                if lang == "ar":
                    query = "أحدث أخبار الذكاء الاصطناعي اليوم"
                else:
                    query = "latest artificial intelligence news today"

                # استخدم البحث العادي (مش عميق) عشان يكون أسرع
                from web_search import search_and_summarize_async
                summary = await search_and_summarize_async(query, language=lang)

                if summary:
                    import time as _time
                    _precomputed_news_cache[lang] = {
                        "summary": summary,
                        "updated_at": _time.time(),
                    }
                    logger.info(f"📰 Pre-computed AI news ({lang}): {len(summary)} chars")
                else:
                    logger.warning(f"📰 Failed to pre-compute AI news ({lang})")

        except Exception as e:
            logger.error(f"📰 News pre-computation error: {e}")

        # انتظر ساعة قبل التحديث
        await asyncio.sleep(3600)


def get_precomputed_news(language: str = "ar") -> str:
    """الحصول على أخبار AI المسبقة — فوري من الكاش"""
    import time as _time
    cache = _precomputed_news_cache.get(language, {})
    if cache.get("summary") and _time.time() - cache.get("updated_at", 0) < _NEWS_CACHE_TTL:
        return cache["summary"]
    return None  # الكاش منتهي أو فاضي — هيضطر يبحث


# ═══════════════════════════════════════
# بث الأخبار اليومية - Daily News Broadcast
# ═══════════════════════════════════════

async def broadcast_daily_news(context: ContextTypes.DEFAULT_TYPE):
    """بث الأخبار اليومية لكل مشترك حسب وقته المخصص
    
    🔴 FIX v3:
    - بث على التلجرام والواتساب
    - فلترة حسب الـ platform
    - 🔴 CRITICAL FIX: الواتساب بيتستخدم wa_phone (رقم التليفون) مش user_id الداخلي
    - منطق الفترة: بنجيب الأخبار اللي حصلت من آخر مرة بعتنا فيها للمستخدم
    - جلب الأخبار بفترة زمنية مبنية على last_news_delivery
    """
    logger.info("=" * 50)
    logger.info("Checking for scheduled news deliveries")
    logger.info("=" * 50)

    try:
        tz = pytz.timezone(DAILY_NEWS_TIMEZONE)
        now = datetime.now(tz)
        current_hour = now.hour
        current_minute = now.minute

        # ═══ بث التلجرام ═══
        tg_subscribers = get_subscribers_for_time(current_hour, current_minute, platform="telegram")
        
        # 🔴 FIX: لو مفيش مشتركين بالدقيقة دي، نجرب بنفس الساعة مع دقيقة 0
        if not tg_subscribers and current_minute != 0:
            tg_subscribers = get_subscribers_for_time(current_hour, 0, platform="telegram")

        # ═══ بث الواتساب ═══
        wa_subscribers = get_subscribers_for_time(current_hour, current_minute, platform="whatsapp")
        
        if not wa_subscribers and current_minute != 0:
            wa_subscribers = get_subscribers_for_time(current_hour, 0, platform="whatsapp")

        total_subscribers = len(tg_subscribers) + len(wa_subscribers)

        if not total_subscribers:
            logger.info(f"No subscribers for time {current_hour:02d}:{current_minute:02d}. Skipping.")
            return

        logger.info(f"Found {len(tg_subscribers)} Telegram + {len(wa_subscribers)} WhatsApp subscribers for time {current_hour:02d}:{current_minute:02d}")

        # ═══ حساب الفترة الزمنية للأخبار ═══
        # 🔴 FIX v3: بنحدد الفترة بناءً على آخر مرة بعتنا فيها أخبار
        # لو ده أول مرة نبعت، بنستخدم آخر 24 ساعة كـ fallback
        from config import NEWS_FETCH_HOURS
        fetch_hours = NEWS_FETCH_HOURS  # default: 24 hours
        
        # نجيب أكتر فترة قديمة بين كل المشتركين
        all_subscribers = tg_subscribers + wa_subscribers
        earliest_last_delivery = None
        for sub in all_subscribers:
            last_del = sub.get("last_news_delivery")
            if last_del:
                try:
                    last_dt = datetime.fromisoformat(last_del)
                    if last_dt.tzinfo is None:
                        last_dt = tz.localize(last_dt)
                    if earliest_last_delivery is None or last_dt < earliest_last_delivery:
                        earliest_last_delivery = last_dt
                except Exception:
                    pass
        
        if earliest_last_delivery:
            time_since_last = (now - earliest_last_delivery).total_seconds() / 3600
            # بنزود ساعتين احتياط عشان مفيش أخبار تتفوت
            fetch_hours = min(max(time_since_last + 2, 6), 72)
            logger.info(f"📅 Last delivery was {time_since_last:.1f}h ago — fetching {fetch_hours:.1f}h of news")
        else:
            logger.info(f"📅 No previous delivery found — fetching default {fetch_hours}h of news")

        # ═══ جلب الأخبار ═══
        # 🔴 FIX v3: بنمرر الفترة الزمنية المحسوبة
        import config as _config
        original_hours = _config.NEWS_FETCH_HOURS
        _config.NEWS_FETCH_HOURS = fetch_hours
        try:
            articles = await fetch_news()
        finally:
            _config.NEWS_FETCH_HOURS = original_hours
        
        if not articles:
            logger.warning("No articles fetched. Skipping broadcast.")
            return

        filtered = filter_news(articles)
        if not filtered:
            logger.warning("No AI-related articles found. Skipping broadcast.")
            return

        ranked = rank_articles(filtered)
        summarized = await summarize_articles(ranked)
        
        if not summarized:
            logger.warning("No articles after summarization. Skipping broadcast.")
            return

        from i18n import format_date_ar, format_date_en

        messages = {}
        for lang_code in ["ar", "en"]:
            if lang_code == "ar":
                date_str = format_date_ar(now)
            else:
                date_str = format_date_en(now)

            header = daily_news_header(lang_code, date_str)
            items = []
            for i, article in enumerate(summarized):
                # 🔴 FIX v3: العربي يشوف تلخيص عربي، الإنجليزي يشوف تلخيص إنجليزي
                if lang_code == "ar":
                    # للمستخدم العربي: نستخدم العنوان العربي والتلخيص العربي
                    item_title = article.get("arabic_title") or article.get("title", "")
                    item_summary = article.get("arabic_summary", article.get("description", "")[:200])
                else:
                    # للمستخدم الإنجليزي: نستخدم العنوان الإنجليزي الأصلي والوصف الأصلي
                    item_title = article.get("title", "")
                    item_summary = article.get("description", "")[:300]
                
                item = format_news_item(
                    i + 1,
                    item_title,
                    item_summary,
                    article.get("link", ""),
                    article.get("is_top", False),
                    article.get("category", ""),
                    language=lang_code,
                )
                items.append(item)

            footer = daily_news_footer("", lang_code)
            full_msg = header + "\n\n".join(items) + footer
            messages[lang_code] = full_msg

        # ═══ بث التلجرام ═══
        tg_success = 0
        tg_fail = 0

        for subscriber in tg_subscribers:
            chat_id = subscriber["user_id"]
            lang = subscriber.get("language", "ar")
            message = messages.get(lang, messages["ar"])

            try:
                if len(message) > 4000:
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for chunk in chunks:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )

                set_last_news_delivery(chat_id, now.isoformat())
                tg_success += 1
                logger.info(f"✅ Telegram news sent to {chat_id}")

                await asyncio.sleep(BROADCAST_DELAY_SECONDS)

            except Exception as e:
                tg_fail += 1
                error_str = str(e).lower()
                logger.error(f"❌ Failed to send to TG {chat_id}: {e}")

                # Handle Telegram rate limiting (429 Too Many Requests)
                if "429" in str(e) or "flood" in error_str or "too many requests" in error_str:
                    retry_after = 5
                    try:
                        if hasattr(e, 'retry_after'):
                            retry_after = e.retry_after
                        elif hasattr(e, 'parameters') and hasattr(e.parameters, 'retry_after'):
                            retry_after = e.parameters.retry_after
                    except Exception:
                        pass
                    logger.warning(f"⏱️ Rate limited by Telegram, waiting {retry_after}s before continuing broadcast...")
                    await asyncio.sleep(retry_after)
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=message[:4000],
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        set_last_news_delivery(chat_id, now.isoformat())
                        tg_success += 1
                        tg_fail -= 1
                        logger.info(f"✅ TG News sent to {chat_id} after rate limit retry")
                    except Exception as retry_e:
                        logger.error(f"❌ Retry also failed for TG {chat_id}: {retry_e}")

                if "blocked" in error_str or "deactivated" in error_str:
                    unsubscribe_user(chat_id)
                    logger.info(f"🗑️ Auto-unsubscribed blocked user {chat_id}")

        # ═══ بث الواتساب ═══
        wa_success = 0
        wa_fail = 0

        for subscriber in wa_subscribers:
            # 🔴 CRITICAL FIX v3: بنستخدم wa_phone (رقم التليفون الحقيقي) مش user_id الداخلي
            # user_id هو رقم مشفر زي -1234567890 لكن واتساب عايز الرقم الحقيقي زي 201234567890
            wa_phone = subscriber.get("wa_phone", "")
            wa_user_id = subscriber["user_id"]  # ده الرقم الداخلي للداتابيز
            
            # لو مفيش wa_phone، محاولة استخراجه من user_id (للبيانات القديمة)
            if not wa_phone:
                logger.warning(f"⚠️ No wa_phone for WA subscriber {wa_user_id} — skipping (can't send to internal ID)")
                wa_fail += 1
                continue
            
            lang = subscriber.get("language", "ar")
            message = messages.get(lang, messages["ar"])
            
            # WhatsApp مش بيدعم HTML — لازم نشيل الـ tags
            import re as _re
            wa_message = _re.sub(r'<[^>]+>', '', message)
            # نحول الـ &amp; وغيره
            wa_message = wa_message.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')

            try:
                from whatsapp_webhook import _send_whatsapp_message
                await _send_whatsapp_message(wa_phone, wa_message[:4000])
                
                # 🔴 FIX: بنحدث last_news_delivery بـ user_id الداخلي مش wa_phone
                set_last_news_delivery(wa_user_id, now.isoformat())
                wa_success += 1
                logger.info(f"✅ WhatsApp news sent to {wa_phone} (user_id: {wa_user_id})")
                
                await asyncio.sleep(BROADCAST_DELAY_SECONDS)
                
            except Exception as e:
                wa_fail += 1
                logger.error(f"❌ Failed to send WA news to {wa_phone} (user_id: {wa_user_id}): {e}")

        logger.info(f"📬 Broadcast complete: TG({tg_success} sent, {tg_fail} failed) WA({wa_success} sent, {wa_fail} failed)")

    except Exception as e:
        logger.error(f"❌ Critical error in broadcast: {e}", exc_info=True)


# ═══════════════════════════════════════
# تشغيل البوت - Main
# ═══════════════════════════════════════

_scheduler = None


def main():
    """تشغيل البوت مع الجدولة"""
    global _scheduler

    logger.info("=" * 60)
    logger.info(f"🤖 {BOT_NAME} v{BOT_VERSION} Starting...")
    logger.info("=" * 60)

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set! Set it as environment variable.")
        sys.exit(1)

    # Initialize premium and dashboard tables
    try:
        init_premium_tables()
        logger.info("✅ Premium tables initialized")
    except Exception as e:
        logger.warning(f"Premium tables init error: {e}")

    try:
        init_dashboard_tables()
        logger.info("✅ Dashboard tables initialized")
    except Exception as e:
        logger.warning(f"Dashboard tables init error: {e}")

    # Initialize memory database (PostgreSQL or SQLite)
    try:
        from memory import init_database
        init_database()
        logger.info("✅ Memory database initialized")
    except Exception as e:
        logger.warning(f"Memory database init error: {e}")

    # 🔴 FIX: ابدأ الـ WhatsApp Webhook Server الأول عشان الـ healthcheck يشتغل
    # حتى لو البوت واجه مشكلة 409 Conflict، السيرفر لازم يكون شغال
    _webhook_runner = None
    try:
        import asyncio as _aio
        from whatsapp_webhook import start_webhook_server
        
        # بنبدأ الـ webhook server في event loop منفصل عشان ميعطلش البوت
        _webhook_loop = _aio.new_event_loop()
        
        def _start_webhook_in_thread():
            _aio.set_event_loop(_webhook_loop)
            _webhook_loop.run_until_complete(start_webhook_server())
            _webhook_loop.run_forever()
        
        import threading
        _whatsapp_thread = threading.Thread(target=_start_webhook_in_thread, name="WhatsAppWebhook", daemon=True)
        _whatsapp_thread.start()
        logger.info("✅ WhatsApp webhook server starting in background thread...")
    except Exception as e:
        logger.warning(f"⚠️ WhatsApp webhook server failed to start in thread: {e}")
    
    # بناء التطبيق مع إعدادات الاستقرار
    app = Application.builder().token(BOT_TOKEN).build()

    # 🔴 FIX: إضافة error handler عشان الأخطاء مش بتوقف البوت بس مش بتتسجل صح
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        """معالج الأخطاء العام — يسجل الأخطاء ومنعش البوت يقع"""
        error = context.error
        error_type = type(error).__name__ if error else "UnknownError"
        error_msg = str(error)[:300] if error else "No error details"
        
        logger.error(f"❌ Unhandled error [{error_type}]: {error_msg}", exc_info=error)
        try:
            track_event("total_errors")
        except Exception:
            pass
        # لو في update موجود، نبعت رسالة خطأ أوضح للمستخدم
        if update and hasattr(update, 'effective_chat'):
            try:
                # 🔴 FIX: نبعت رسالة أوضح عشان المستخدم (والأدمن) يعرفوا إيه الخطأ
                # الأدمن يشوف التفاصيل، المستخدم العادي يشوف رسالة بسيطة
                chat_id = update.effective_chat.id
                is_admin_chat = str(chat_id) == str(CHAT_ID)
                
                if is_admin_chat:
                    # الأدمن يشوف التفاصيل الكاملة
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ <b>خطأ غير متوقع</b>\n\n🔴 <b>النوع:</b> <code>{error_type}</code>\n📝 <b>التفاصيل:</b> <code>{error_msg}</code>\n\n💡 جرب تاني أو بص في الـ logs.",
                        parse_mode="HTML"
                    )
                else:
                    # المستخدم العادي يشوف رسالة بسيطة
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ حصل خطأ غير متوقع. جرب تاني!\n💡 لو المشكلة مستمرة، تواصل مع الدعم @ziadamr"
                    )
            except Exception:
                pass

    app.add_error_handler(error_handler)

    # ═══ تسجيل الأوامر ═══
    register_handlers(app)

    # ═══ إعداد الجدولة (APScheduler) ═══
    _scheduler = AsyncIOScheduler(timezone=pytz.timezone(DAILY_NEWS_TIMEZONE))

    async def scheduled_broadcast():
        """بث مجدول - يشيك كل 30 دقيقة"""
        class FakeContext:
            def __init__(self, bot):
                self.bot = bot
        try:
            await broadcast_daily_news(FakeContext(app.bot))
        except Exception as e:
            logger.error(f"CRITICAL: Scheduled broadcast failed: {e}", exc_info=True)
            try:
                if CHAT_ID:
                    error_msg = (
                        f"\u26a0\ufe0f <b>Broadcast Failed</b>\n"
                        f"\ud83d\udd34 Error: <code>{str(e)[:200]}</code>\n"
                        f"\ud83d\udd52 Time: {datetime.now().isoformat()}\n"
                        f"\ud83d\udcca Check logs for details."
                    )
                    await app.bot.send_message(
                        chat_id=int(CHAT_ID),
                        text=error_msg,
                        parse_mode="HTML"
                    )
            except Exception as notify_err:
                logger.error(f"Failed to notify admin about broadcast failure: {notify_err}")

    _scheduler.add_job(
        scheduled_broadcast,
        trigger="cron",
        hour="*",  # 🔴 FIX v3: كل ساعة — عشان نوصل لأي وقت المستخدم يختاره
        minute="0",
        id="daily_news_broadcast",
        name="Daily AI News Broadcast (per-user time)",
        jitter=60,
    )

    # ═══ Supabase Storage Cleanup — حذف الملفات المنتهية (أكتر من 24 ساعة) ═══
    async def supabase_cleanup():
        """تنظيف ملفات Supabase المنتهية — كل ساعة"""
        try:
            from supabase_storage import cleanup_expired_files
            deleted = await cleanup_expired_files(max_age_hours=24)
            if deleted > 0:
                logger.info(f"☁️ Supabase cleanup: {deleted} expired file(s) deleted")
        except Exception as e:
            logger.warning(f"⚠️ Supabase cleanup failed: {e}")

    _scheduler.add_job(
        supabase_cleanup,
        trigger="cron",
        hour="*",
        minute="0",
        id="supabase_cleanup",
        name="Supabase Storage Cleanup (delete files older than 24h)",
        jitter=120,
    )

    # تعيين أوامر البوت + تشغيل الجدولة بعد بدء event loop
    async def post_init(application):
        """بعد تشغيل البوت - inside event loop"""

        # ═══ WhatsApp Webhook Server — شغال بالفعل من الـ main thread ═══
        # 🔴 FIX: الـ webhook server بدأ قبل كده في thread منفصل عشان الـ healthcheck يشتغل
        # حتى لو البوت واجه مشكلة 409 Conflict
        logger.info("✅ WhatsApp webhook server already running from background thread")

        # ═══ Playwright Chromium Check — لو مش موجود نثبته ═══
        # 🔴 Playwright مهم لتحميل فيديوهات Threads (الطريقة الوحيدة اللي بتشتغل)
        try:
            from playwright.async_api import async_playwright
            # لو الاستيراد اشتغل → نتأكد إن Chromium موجود
            import subprocess as _sp
            check = _sp.run(['playwright', 'install', 'chromium', '--dry-run'],
                           capture_output=True, timeout=10)
            # لو --dry-run مش مدعوم، نجرب نبعت browser
            try:
                pw = async_playwright().start()
                browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
                await browser.close()
                pw.stop()
                logger.info("✅ Playwright + Chromium ready for Threads downloads")
            except Exception as pw_err:
                logger.warning(f"⚠️ Playwright Chromium not installed, installing now...")
                install = _sp.run(['playwright', 'install', 'chromium', '--with-deps'],
                                 capture_output=True, timeout=120)
                if install.returncode == 0:
                    logger.info("✅ Playwright Chromium installed successfully")
                else:
                    logger.warning(f"⚠️ Playwright Chromium install failed: {install.stderr.decode()[:200]}")
        except ImportError:
            logger.warning("⚠️ Playwright not installed — Threads video downloads may fail")
        except Exception as e:
            logger.warning(f"⚠️ Playwright check error: {e}")

        # ═══ تشغيل Cookie Auto-Rotation ═══
        # 🍪 تدوير كوكيز YouTube — بس كوكيز مرفوعة من المستخدمين (لا كوكيز تلقائية)
        try:
            from cookie_rotator import start_cookie_rotation, get_cookie_rotation_status
            start_cookie_rotation()
            status = get_cookie_rotation_status()
            logger.info(f"✅ Cookie monitoring started (user uploads only, no auto) — {status['total_cookies']} cookies loaded")
        except Exception as e:
            logger.warning(f"⚠️ Cookie auto-rotation failed to start: {e}")

        try:
            from telegram import BotCommand
            await application.bot.set_my_commands([
                BotCommand("start", "بدء البوت / Start the bot"),
                BotCommand("help", "المساعدة / Help"),
                BotCommand("news", "أخبار AI / AI News"),
                BotCommand("breaking", "خبر عاجل / Breaking news"),
                BotCommand("weekly", "ملخص أسبوعي / Weekly summary"),
                BotCommand("trending", "الترندات / Trending"),
                BotCommand("search", "بحث / Search"),
                BotCommand("ask", "سؤال / Ask question"),
                BotCommand("learn", "تعلم / Learn topic"),
                BotCommand("roadmap", "خارطة طريق / Roadmap"),
                # company command removed — الشركات تم إزالتها
                BotCommand("study", "وضع الدراسة / Study mode (Premium)"),
                BotCommand("quiz", "كويز / Quiz (Premium)"),
                BotCommand("exam", "امتحان / Exam (Premium)"),
                BotCommand("youtube", "ملخص YouTube / YouTube summary"),
                BotCommand("pdf", "تحليل PDF / PDF analysis"),
                BotCommand("image", "إنشاء صورة / Generate image (Premium)"),
                BotCommand("edit", "تعديل صورة / Edit image (Premium)"),
                BotCommand("download", "تحميل فيديو/صورة/صوت / Download media (Premium)"),
                BotCommand("video", "فيديو Dailymotion / Dailymotion video search (Premium)"),
                BotCommand("audio", "صوت SoundCloud / SoundCloud audio search (Premium)"),
                BotCommand("photo", "بحث صور / Image search (Premium)"),
                BotCommand("cookies", "رفع كوكيز YouTube / Upload YouTube cookies"),
                BotCommand("premium", "الاشتراك / Premium status"),
                BotCommand("subscribe", "اشترك / Subscribe"),
                BotCommand("unsubscribe", "إلغاء اشتراك / Unsubscribe"),
                BotCommand("memory", "ذاكرتي / My memory"),
                BotCommand("progress", "تقدم التعلم / Learning progress"),
                BotCommand("favorite", "مفضلة / Favorite"),
                BotCommand("favorites", "المفضلات / Favorites"),
                BotCommand("forget", "امسح ذكرى / Forget memory"),
                BotCommand("resetmemory", "مسح الكل / Reset memory"),
                BotCommand("language", "اللغة / Language"),
                BotCommand("about", "عن البوت / About"),
                BotCommand("admin", "لوحة الأدمن / Admin panel"),
                BotCommand("dashboard", "لوحة التحكم / Dashboard (Admin)"),
                BotCommand("addadmin", "إضافة أدمن / Add admin (Owner)"),
                BotCommand("removeadmin", "شيل أدمن / Remove admin (Owner)"),
                BotCommand("listadmins", "قائمة الأدمنز / List admins"),
                BotCommand("resetlimit", "إعادة تعيين الحدود / Reset free limits (Admin)"),
            ])
            logger.info("✅ Bot commands registered with Telegram")
        except Exception as e:
            logger.warning(f"Failed to register commands: {e}")

        # تشغيل الجدولة
        _scheduler.start()
        logger.info("✅ APScheduler started - news broadcasts scheduled")

        # ⚡ بدء حساب الأخبار في الخلفية
        asyncio.create_task(_precompute_news_background())
        logger.info("📰 News pre-computation background task started")

    # Graceful shutdown handler for SIGTERM
    _shutdown_requested = False

    def _signal_handler(signum, frame):
        """Handle SIGTERM gracefully — cleanup database connections and stop scheduler"""
        nonlocal _shutdown_requested
        if _shutdown_requested:
            return
        _shutdown_requested = True
        logger.info(f"\u26a0\ufe0f Received signal {signum} — initiating graceful shutdown...")

        # Stop the scheduler first
        try:
            if _scheduler and _scheduler.running:
                _scheduler.shutdown(wait=False)
                logger.info("\u2705 APScheduler stopped")
        except Exception as e:
            logger.warning(f"Scheduler shutdown error: {e}")

        # Close PostgreSQL connection pool
        try:
            from memory import _pg_pool
            if _pg_pool is not None:
                _pg_pool.closeall()
                logger.info("\u2705 PostgreSQL connection pool closed")
        except Exception as e:
            logger.warning(f"Pool close error: {e}")

        logger.info("\u2705 Graceful shutdown complete — exiting")
        sys.exit(0)

    # Register signal handlers for SIGTERM and SIGINT
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    logger.info("\u2705 Graceful shutdown handlers registered (SIGTERM/SIGINT)")

    # تشغيل البوت
    app.post_init = post_init

    logger.info(f"🚀 {BOT_NAME} v{BOT_VERSION} is running!")
    
    # 🔴 FIX: حذف أي webhook نشط قبل البدء — ده بيمنع خطأ 409 Conflict
    # اللي بيحصل لما بوتين (القديم والجديد) بيحاولوا يشتغلوا في نفس الوقت
    # بنستخدم HTTP request مباشرة عشان منعملش مشكلة للـ event loop بتاع python-telegram-bot
    try:
        import urllib.request
        import json as _json
        webhook_api = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"
        req = urllib.request.Request(webhook_api)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read().decode())
            if result.get('ok'):
                logger.info("✅ Deleted any active webhook before polling (via HTTP)")
            else:
                logger.warning(f"⚠️ deleteWebhook response: {result}")
    except Exception as e:
        logger.warning(f"⚠️ Could not delete webhook before polling: {e}")
    
    # 🔴 FIX: انتظر ثانية بعد حذف الـ webhook عشان Telegram يفرغ الـ pending updates
    import time as _time
    _time.sleep(2)
    
    # 🔴 FIX: drop_pending_updates=True عشان منع معالجة رسائل قديمة
    # ممكن تكون سبب الـ crash لو في رسائل كتير متراكمة
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt")
    except SystemExit:
        # 🔴 FIX: لا تحاول إعادة التشغيل لو كان إغلاق مقصود (SIGTERM/signal)
        logger.info("Bot stopped by system exit (graceful shutdown)")
    except Exception as e:
        logger.critical(f"💥 FATAL: Bot crashed with unhandled exception: {e}", exc_info=True)
        # 🐦 Sentry — capture the fatal crash
        from sentry_config import capture_exception
        capture_exception(e)
        # 🔴 FIX: تنظيف الموارد قبل محاولة إعادة التشغيل
        # عشان مفيش تسريب للـ connections والموارد
        try:
            if _scheduler and _scheduler.running:
                _scheduler.shutdown(wait=False)
                logger.info("✅ Scheduler stopped before restart")
        except Exception:
            pass
        try:
            from memory import _pg_pool
            if _pg_pool is not None:
                _pg_pool.closeall()
                logger.info("✅ PostgreSQL pool closed before restart")
        except Exception:
            pass
        
        # 🔴 FIX: بدل ما نعمل main() تاني (بيسبب تسريب موارد)
        # Railway هيشغل البوت تاني لو process exit code مش 0
        # وده أحسن عشان يبدأ من الصفر من غير موارد متراكمة
        logger.info("🔄 Exiting to let Railway restart the bot cleanly...")
        sys.exit(1)
