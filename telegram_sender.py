"""
إرسال الرسائل عبر تيليجرام - Telegram Sender Module
"""

import logging
from typing import Optional
from datetime import datetime

import requests

from config import (
    BOT_TOKEN, CHAT_ID, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_DELAY,
    MESSAGE_TEMPLATE, NEWS_ITEM_TEMPLATE, TOP_NEWS_BADGE,
    REGULAR_NEWS_BADGE, NO_NEWS_MESSAGE
)

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def format_date_arabic() -> str:
    """
    تنسيق التاريخ بالعربية
    """
    now = datetime.now()
    days = {
        0: "الإثنين", 1: "الثلاثاء", 2: "الأربعاء",
        3: "الخميس", 4: "الجمعة", 5: "السبت", 6: "الأحد"
    }
    months = {
        1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل",
        5: "مايو", 6: "يونيو", 7: "يوليو", 8: "أغسطس",
        9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"
    }

    day_name = days[now.weekday()]
    month_name = months[now.month]

    return f"{day_name}، {now.day} {month_name} {now.year}"


def format_news_message(articles: list) -> str:
    """
    تنسيق رسالة الأخبار الكاملة
    """
    if not articles:
        return NO_NEWS_MESSAGE

    date_str = format_date_arabic()
    news_items = []

    for i, article in enumerate(articles):
        title = article.get("title", "")
        summary = article.get("arabic_summary", article.get("description", ""))
        url = article.get("link", "")
        is_top = article.get("is_top", False)

        # الاختيار بين شارة الخبر الأهم والعادي
        badge = TOP_NEWS_BADGE if is_top else REGULAR_NEWS_BADGE

        item = NEWS_ITEM_TEMPLATE.format(
            badge=badge,
            title=title,
            summary=summary,
            url=url
        )
        news_items.append(item)

    news_text = "\n\n".join(news_items)

    message = MESSAGE_TEMPLATE.format(
        date=date_str,
        news_items=news_text
    )

    return message


def send_telegram_message(message: str) -> bool:
    """
    إرسال رسالة عبر تيليجرام
    """
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("BOT_TOKEN or CHAT_ID not configured")
        return False

    url = f"{TELEGRAM_API_BASE}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.info("Message sent successfully to Telegram")
                    return True
                else:
                    logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
            else:
                logger.error(f"HTTP error {response.status_code}: {response.text[:200]}")

        except requests.exceptions.Timeout:
            logger.error(f"Timeout sending message (attempt {attempt + 1})")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending message (attempt {attempt + 1}): {e}")

        if attempt < MAX_RETRIES - 1:
            import time
            time.sleep(RETRY_DELAY)

    logger.error("All attempts to send Telegram message failed")
    return False


def send_news(articles: list) -> bool:
    """
    تنسيق وإرسال أخبار الذكاء الاصطناعي
    """
    logger.info(f"Preparing to send {len(articles) if articles else 0} articles...")

    message = format_news_message(articles)

    # التحقق من طول الرسالة (حد تيليجرام 4096 حرف)
    if len(message) > 4096:
        # تقسيم الرسالة
        logger.info(f"Message too long ({len(message)} chars), splitting...")
        return send_split_message(message)

    return send_telegram_message(message)


def send_split_message(message: str) -> bool:
    """
    تقسيم الرسالة الطويلة وإرسالها على أجزاء
    """
    # تقسيم عند فواصل الأخبار
    parts = message.split("━━━━━━━━━━━━━━━━━")

    if len(parts) <= 2:
        # لو مفيش تقسيم واضح، نقطع بالطول بذكاء
        chunks = []
        while len(message) > 4000:
            # البحث عن أفضل نقطة تقسيم (بالأولوية)
            split_point = -1
            for marker in ["\n\n", "\n", " • ", " "]:
                pos = message.rfind(marker, 0, 4000)
                if pos > 0:
                    split_point = pos + len(marker)
                    break
            # لو ملقيناش نقطة كويسة، نقطع عند آخر جملة
            if split_point <= 0:
                for end_char in [".", "؟", "،", "!", "؛"]:
                    pos = message.rfind(end_char, 0, 4000)
                    if pos > 0:
                        split_point = pos + 1
                        break
            # آخر حل: قطع على 4000
            if split_point <= 0:
                split_point = 4000
            chunks.append(message[:split_point])
            message = message[split_point:]
        chunks.append(message)

        success = True
        for chunk in chunks:
            if not send_telegram_message(chunk.strip()):
                success = False
        return success

    # إرسال الهيدر أولًا
    header = parts[0].strip()
    if header:
        send_telegram_message(header)

    # إرسال كل خبر على حدة لو لازم
    success = True
    current_part = ""
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue

        if len(current_part) + len(part) + 20 > 4000:
            if current_part:
                if not send_telegram_message(current_part.strip()):
                    success = False
            current_part = part
        else:
            current_part += "\n" + part

    if current_part:
        if not send_telegram_message(current_part.strip()):
            success = False

    return success
