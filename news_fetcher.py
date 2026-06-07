"""
جلب الأخبار - News Fetcher Module
يقوم بجلب الأخبار من مصادر RSS المتعددة
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests

from config import RSS_FEEDS, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)


def fetch_rss_feed(feed_url: str) -> List[Dict]:
    """
    جلب الأخبار من مصدر RSS واحد
    """
    articles = []

    try:
        logger.info(f"Fetching RSS feed: {feed_url}")

        # استخدام requests مع timeout قبل feedparser
        # لأن feedparser مش بيدعم timeout كويس
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

        for entry in feed.entries:
            try:
                article = parse_entry(entry, feed_url)
                if article and article.get("title"):
                    articles.append(article)
            except Exception as e:
                logger.warning(f"Error parsing entry from {feed_url}: {e}")
                continue

        logger.info(f"Fetched {len(articles)} articles from {feed_url}")

    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching {feed_url}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching {feed_url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching {feed_url}: {e}")

    return articles


def parse_entry(entry, feed_url: str) -> Optional[Dict]:
    """
    تحليل مدخل RSS واستخراج البيانات
    """
    article = {
        "title": getattr(entry, "title", "").strip(),
        "link": getattr(entry, "link", "").strip(),
        "description": "",
        "published": None,
        "source": "",
        "source_url": feed_url,
    }

    # استخراج الوصف
    if hasattr(entry, "summary"):
        # إزالة HTML tags
        import re
        article["description"] = re.sub(r'<[^>]+>', '', entry.summary).strip()
    elif hasattr(entry, "description"):
        import re
        article["description"] = re.sub(r'<[^>]+>', '', entry.description).strip()

    # استخراج تاريخ النشر
    published = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    elif hasattr(entry, "updated_parsed') and entry.updated_parsed"):
        try:
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass

    article["published"] = published

    # استخراج اسم المصدر
    if hasattr(entry, "source") and hasattr(entry.source, "title"):
        article["source"] = entry.source.title
    else:
        # استخدام اسم النطاق
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

    logger.info(f"Total articles fetched from all feeds: {len(all_articles)}")

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
    logger.info(f"News fetch complete. Total: {len(articles)} articles")
    return articles
