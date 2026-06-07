"""
جلب الأخبار - News Fetcher Module
يقوم بجلب الأخبار من مصادر RSS المتعددة
يتم فلترة الأخبار حسب التاريخ أثناء الجلب لتوفير الوقت وال带宽
"""

import re
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests

from config import RSS_FEEDS, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_DELAY, NEWS_FETCH_HOURS

logger = logging.getLogger(__name__)


def _is_recent(published: datetime = None) -> bool:
    """
    التحقق من أن الخبر ضمن الإطار الزمني المحدد
    """
    if published is None:
        return True  # لو مفيش تاريخ، نسيبه يعدي (هيتفلتر بعدين)

    now = datetime.now(timezone.utc)

    # Handle timezone-naive datetimes
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    time_diff = now - published
    return time_diff.total_seconds() <= NEWS_FETCH_HOURS * 3600


def _parse_published(entry) -> Optional[datetime]:
    """
    استخراج تاريخ النشر من المدخل
    """
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def fetch_rss_feed(feed_url: str) -> List[Dict]:
    """
    جلب الأخبار من مصدر RSS واحد
    يتم فلترة الأخبار حسب التاريخ أثناء الجلب لتوفير الوقت
    """
    articles = []

    try:
        logger.info(f"Fetching RSS feed: {feed_url}")

        response = requests.get(
            feed_url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "AI-News-Bot/1.0 (Telegram Bot)"
            }
        )
        response.raise_for_status()

        # تحليل الـ RSS
        feed = feedparser.parse(response.content)

        if feed.bozo and not feed.entries:
            logger.warning(f"Failed to parse feed {feed_url}: {feed.bozo_exception}")
            return articles

        total_entries = len(feed.entries)
        skipped_old = 0

        for entry in feed.entries:
            try:
                # استخراج تاريخ النشر الأول
                published = _parse_published(entry)

                # فلترة حسب التاريخ أثناء الجلب - تخطي الأخبار القديمة
                if published and not _is_recent(published):
                    skipped_old += 1
                    continue

                article = parse_entry(entry, feed_url, published)
                if article and article.get("title"):
                    articles.append(article)
            except Exception as e:
                logger.warning(f"Error parsing entry from {feed_url}: {e}")
                continue

        logger.info(f"Fetched {len(articles)} recent articles from {feed_url} "
                    f"(skipped {skipped_old} old out of {total_entries} total)")

    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching {feed_url}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching {feed_url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching {feed_url}: {e}")

    return articles


def parse_entry(entry, feed_url: str, published: datetime = None) -> Optional[Dict]:
    """
    تحليل مدخل RSS واستخراج البيانات
    """
    article = {
        "title": getattr(entry, "title", "").strip(),
        "link": getattr(entry, "link", "").strip(),
        "description": "",
        "published": published,
        "source": "",
        "source_url": feed_url,
    }

    # استخراج الوصف
    if hasattr(entry, "summary"):
        article["description"] = re.sub(r'<[^>]+>', '', entry.summary).strip()
    elif hasattr(entry, "description"):
        article["description"] = re.sub(r'<[^>]+>', '', entry.description).strip()

    # استخراج اسم المصدر
    if hasattr(entry, "source") and hasattr(entry.source, "title"):
        article["source"] = entry.source.title
    else:
        try:
            domain = urlparse(feed_url).netloc
            article["source"] = domain.replace("www.", "")
        except Exception:
            article["source"] = "Unknown"

    return article


def fetch_all_feeds() -> List[Dict]:
    """
    جلب الأخبار من جميع مصادر RSS
    """
    all_articles = []

    for feed_url in RSS_FEEDS:
        articles = fetch_rss_feed(feed_url)
        all_articles.extend(articles)

    logger.info(f"Total recent articles fetched from all feeds: {len(all_articles)}")

    # إزالة المكررات بناءً على الرابط
    seen_links = set()
    unique_articles = []
    for article in all_articles:
        link = article.get("link", "")
        if link and link not in seen_links:
            seen_links.add(link)
            unique_articles.append(article)
        elif not link:
            unique_articles.append(article)

    logger.info(f"After deduplication: {len(unique_articles)} unique articles")
    return unique_articles


def fetch_news() -> List[Dict]:
    """
    الوظيفة الرئيسية لجلب الأخبار
    """
    logger.info("Starting news fetch process...")
    articles = fetch_all_feeds()
    logger.info(f"News fetch complete. Total: {len(articles)} recent articles")
    return articles
