"""
البوت الرئيسي - AI News Telegram Bot
يتم تشغيله يومياً عبر GitHub Actions الساعة 9 صباحاً بتوقيت القاهرة
يدعم البث لكل المشتركين (مش بس CHAT_ID واحد)
+ نظام تحرير صحفي محترف
"""

import logging
import sys
import time
from datetime import datetime, timezone, timedelta

from config import (
    MAX_NEWS_COUNT, MIN_NEWS_COUNT, BOT_TOKEN,
    BROADCAST_DELAY_SECONDS
)
from news_fetcher import fetch_news_sync
from filters import filter_news
from scorer import rank_articles
from summarizer import summarize_articles
from telegram_sender import send_telegram_message, NO_NEWS_MESSAGE
from memory import get_all_subscribers, unsubscribe_user
from formatters import (
    daily_news_header, daily_news_footer, format_news_item
)

import requests

# إعداد الـ Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message_to_chat(chat_id: int, message: str) -> bool:
    """إرسال رسالة لشات معين"""
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                return True
        logger.warning(f"Failed to send to {chat_id}: {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Error sending to {chat_id}: {e}")
        return False


def main():
    """
    الوظيفة الرئيسية للبوت - بث الأخبار لكل المشتركين
    مع نظام التحرير الصحفي المحترف
    """
    logger.info("=" * 50)
    logger.info("AI News Bot - Starting daily news broadcast")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 50)

    # تهيئة قاعدة البيانات (مهم جداً عشان نقدر نوصل للمشتركين)
    try:
        from memory import init_database
        init_database()
        logger.info("✅ Database initialized for news broadcast")
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")

    # تهيئة جدول sent_articles
    try:
        from news_editor import init_sent_articles_table
        init_sent_articles_table()
        logger.info("✅ sent_articles table initialized")
    except Exception as e:
        logger.warning(f"⚠️ sent_articles init error: {e}")

    try:
        # الخطوة 1: جلب الأخبار من مصادر RSS
        logger.info("Step 1: Fetching news from RSS feeds...")
        articles = fetch_news_sync()

        if not articles:
            logger.warning("No articles fetched.")
            return

        logger.info(f"Fetched {len(articles)} articles")

        # الخطوة 2: فلترة الأخبار (AI-related only)
        logger.info("Step 2: Filtering AI-related news...")
        filtered_articles = filter_news(articles)

        if not filtered_articles:
            logger.warning("No AI-related articles found.")
            return

        logger.info(f"After filtering: {len(filtered_articles)} AI articles")

        # الخطوة 3: تقييم وترتيب الأخبار + الخط التحريري
        logger.info("Step 3: Scoring, ranking, and editorial review...")
        top_articles = rank_articles(
            filtered_articles,
            max_count=MAX_NEWS_COUNT,
            min_count=MIN_NEWS_COUNT
        )

        if not top_articles:
            logger.warning("No significant articles found after editorial review.")
            return

        logger.info(f"Selected {len(top_articles)} articles after editorial review")

        # الخطوة 4: تلخيص الأخبار بالعربية
        logger.info("Step 4: Summarizing articles in Arabic...")
        summarized_articles = summarize_articles(top_articles)

        # الخطوة 5: تجهيز الرسائل
        logger.info("Step 5: Preparing messages...")

        now = datetime.now(timezone(timedelta(hours=2)))
        days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        months_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                     "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

        messages = {}
        for lang_code in ["ar", "en"]:
            if lang_code == "ar":
                date_str = f"{days_ar[now.weekday()]}, {now.day} {months_ar[now.month]} {now.year}"
            else:
                date_str = now.strftime("%A, %B %d, %Y")

            header = daily_news_header(lang_code, date_str)

            items = []
            for i, article in enumerate(summarized_articles):
                item = format_news_item(
                    i + 1,
                    article.get("title", ""),
                    article.get("arabic_summary", article.get("description", "")[:200]),
                    article.get("link", ""),
                    article.get("is_top", False),
                    article.get("category", ""),
                    language=lang_code,  # 🔴 FIX: اللغة
                )
                items.append(item)

            footer = daily_news_footer("", lang_code)
            full_msg = header + "\n\n".join(items) + footer
            messages[lang_code] = full_msg

        # الخطوة 6: بث الأخبار لكل المشتركين
        logger.info("Step 6: Broadcasting to all subscribers...")
        subscribers = get_all_subscribers()

        if not subscribers:
            logger.warning("No subscribers found. Skipping broadcast.")
            # fallback: إرسال لـ CHAT_ID لو موجود
            from config import CHAT_ID
            if CHAT_ID:
                logger.info(f"Falling back to CHAT_ID: {CHAT_ID}")
                send_message_to_chat(int(CHAT_ID), messages.get("ar", ""))
            return

        logger.info(f"Broadcasting to {len(subscribers)} subscribers")

        success_count = 0
        fail_count = 0

        for subscriber in subscribers:
            chat_id = subscriber["user_id"]
            lang = subscriber.get("language", "ar")
            message = messages.get(lang, messages["ar"])

            try:
                # تقسيم الرسالة لو طويلة
                if len(message) > 4000:
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for chunk in chunks:
                        send_message_to_chat(chat_id, chunk)
                else:
                    send_message_to_chat(chat_id, message)

                success_count += 1
                logger.info(f"✅ News sent to {chat_id}")

                # تأخير بسيط عشان منحصلش spam
                time.sleep(BROADCAST_DELAY_SECONDS)

            except Exception as e:
                fail_count += 1
                logger.error(f"❌ Failed to send to {chat_id}: {e}")

                # لو المستخدم حظر البوت، ألغي اشتراكه تلقائياً
                if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                    unsubscribe_user(chat_id)
                    logger.info(f"🗑️ Auto-unsubscribed blocked user {chat_id}")

        logger.info(f"📬 Broadcast complete: {success_count} sent, {fail_count} failed out of {len(subscribers)} subscribers")

        # ملخص تحريري
        try:
            from news_editor import format_editorial_summary
            summary = format_editorial_summary(summarized_articles, "ar")
            logger.info(f"📰 Editorial Summary: {summary}")
        except Exception:
            pass

    except Exception as e:
        logger.error(f"❌ Critical error in main process: {e}", exc_info=True)
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("AI News Bot - Daily broadcast complete")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
