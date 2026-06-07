"""
البوت الرئيسي - AI News Telegram Bot
يتم تشغيله يومياً عبر GitHub Actions الساعة 9 صباحاً بتوقيت القاهرة
"""

import logging
import sys
from datetime import datetime

from config import MAX_NEWS_COUNT, MIN_NEWS_COUNT
from news_fetcher import fetch_news
from filters import filter_news
from scorer import rank_articles
from summarizer import summarize_articles
from telegram_sender import send_news, send_telegram_message, NO_NEWS_MESSAGE

# إعداد الـ Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def main():
    """
    الوظيفة الرئيسية للبوت
    """
    logger.info("=" * 50)
    logger.info("AI News Bot - Starting daily news cycle")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 50)

    try:
        # الخطوة 1: جلب الأخبار من مصادر RSS
        logger.info("Step 1: Fetching news from RSS feeds...")
        articles = fetch_news()

        if not articles:
            logger.warning("No articles fetched. Sending no-news message.")
            send_telegram_message(NO_NEWS_MESSAGE)
            return

        logger.info(f"Fetched {len(articles)} articles")

        # الخطوة 2: فلترة الأخبار (AI-related only)
        logger.info("Step 2: Filtering AI-related news...")
        filtered_articles = filter_news(articles)

        if not filtered_articles:
            logger.warning("No AI-related articles found. Sending no-news message.")
            send_telegram_message(NO_NEWS_MESSAGE)
            return

        logger.info(f"After filtering: {len(filtered_articles)} AI articles")

        # الخطوة 3: تقييم وترتيب الأخبار
        logger.info("Step 3: Scoring and ranking articles...")
        top_articles = rank_articles(
            filtered_articles,
            max_count=MAX_NEWS_COUNT,
            min_count=MIN_NEWS_COUNT
        )

        if not top_articles:
            logger.warning("No significant articles found. Sending no-news message.")
            send_telegram_message(NO_NEWS_MESSAGE)
            return

        logger.info(f"Selected {len(top_articles)} top articles")

        # الخطوة 4: تلخيص الأخبار بالعربية
        logger.info("Step 4: Summarizing articles in Arabic...")
        summarized_articles = summarize_articles(top_articles)

        # الخطوة 5: إرسال الأخبار عبر تيليجرام
        logger.info("Step 5: Sending news via Telegram...")
        success = send_news(summarized_articles)

        if success:
            logger.info("✅ News sent successfully!")
        else:
            logger.error("❌ Failed to send news via Telegram")
            sys.exit(1)

    except Exception as e:
        logger.error(f"❌ Critical error in main process: {e}", exc_info=True)
        # محاولة إرسال رسالة خطأ
        try:
            error_msg = f"⚠️ حدث خطأ في بوت أخبار AI:\n{str(e)[:200]}"
            send_telegram_message(error_msg)
        except Exception:
            pass
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("AI News Bot - Daily cycle complete")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
