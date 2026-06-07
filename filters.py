"""
فلترة الأخبار - News Filtering Module
يقوم بفلترة الأخبار بناءً على الكلمات المفتاحية واستبعاد المواضيع غير المرتبطة بالذكاء الاصطناعي
"""

import re
import logging
from typing import List, Dict
from datetime import datetime, timezone, timedelta

from config import AI_KEYWORDS, EXCLUSION_KEYWORDS, NEWS_FETCH_HOURS

logger = logging.getLogger(__name__)


def is_ai_related(title: str, description: str = "") -> bool:
    """
    التحقق من أن الخبر مرتبط بالذكاء الاصطناعي
    يفحص العنوان والوصف مقابل قائمة الكلمات المفتاحية
    """
    text = f"{title} {description}".lower()

    # التحقق من وجود كلمات مفتاحية للذكاء الاصطناعي
    ai_match_count = 0
    for keyword in AI_KEYWORDS:
        # استخدام word boundary للكلمات القصيرة
        if len(keyword) <= 4:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                ai_match_count += 1
        else:
            if keyword.lower() in text:
                ai_match_count += 1

    # لازم يكون فيه كلمة مفتاحية واحدة على الأقل
    if ai_match_count == 0:
        return False

    # التحقق من عدم وجود كلمات استبعاد
    for keyword in EXCLUSION_KEYWORDS:
        if len(keyword) <= 4:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                logger.info(f"Excluded (exclusion keyword '{keyword}'): {title[:60]}")
                return False
        else:
            if keyword.lower() in text:
                logger.info(f"Excluded (exclusion keyword '{keyword}'): {title[:60]}")
                return False

    return True


def is_within_timeframe(published_date: datetime = None) -> bool:
    """
    التحقق من أن الخبر ضمن الإطار الزمني المحدد (آخر 24 ساعة)
    """
    if published_date is None:
        return True  # لو مفيش تاريخ، نسيبه يعدي

    now = datetime.now(timezone.utc)

    # Handle timezone-naive datetimes
    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)

    time_diff = now - published_date
    return time_diff.total_seconds() <= NEWS_FETCH_HOURS * 3600


def is_duplicate(title: str, seen_titles: List[str], threshold: float = 0.7) -> bool:
    """
    كشف الأخبار المكررة باستخدام نسبة التشابه البسيطة
    """
    title_lower = title.lower().strip()

    for seen in seen_titles:
        seen_lower = seen.lower().strip()

        # حساب نسبة التشابه البسيطة (common words ratio)
        title_words = set(title_lower.split())
        seen_words = set(seen_lower.split())

        if not title_words or not seen_words:
            continue

        common_words = title_words & seen_words
        similarity = len(common_words) / min(len(title_words), len(seen_words))

        if similarity >= threshold:
            logger.info(f"Duplicate detected (similarity: {similarity:.2f}): {title[:60]}")
            return True

    return False


def filter_news(articles: List[Dict]) -> List[Dict]:
    """
    فلترة شاملة للأخبار:
    1. الاحتفاظ فقط بالأخبار المرتبطة بالذكاء الاصطناعي
    2. استبعاد الأخبار خارج الإطار الزمني
    3. إزالة الأخبار المكررة
    """
    filtered = []
    seen_titles = []

    for article in articles:
        title = article.get("title", "")
        description = article.get("description", "")
        published = article.get("published", None)

        # التحقق من الارتباط بالذكاء الاصطناعي
        if not is_ai_related(title, description):
            logger.debug(f"Filtered out (not AI-related): {title[:60]}")
            continue

        # التحقق من الإطار الزمني
        if published and not is_within_timeframe(published):
            logger.debug(f"Filtered out (out of timeframe): {title[:60]}")
            continue

        # التحقق من التكرار
        if is_duplicate(title, seen_titles):
            continue

        seen_titles.append(title)
        filtered.append(article)
        logger.info(f"Accepted: {title[:80]}")

    logger.info(f"Filtering complete: {len(articles)} articles -> {len(filtered)} AI-related articles")
    return filtered
