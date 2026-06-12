"""
جلب الأخبار - News Fetcher Module
يقوم بجلب الأخبار من مصادر RSS المتعددة
+ دعم المكالمات غير المتزامنة
"""

import re
import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests

import config as _config_module
from config import RSS_FEEDS, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)


def _is_recent(published: datetime = None, max_hours: float = None) -> bool:
    """فحص هل الخبر حديث
    
    🔴 FIX v2: لو مفيش تاريخ بنسيب الخبر يعدي عشان:
    - كتير من الـ RSS feeds مش بتبعت تاريخ
    - الأخبار دي ممكن تكون مهمة
    - الفلترة الدقيقة بتتعمل بعدين في filters.py
    
    🔴 FIX v3: بنقرأ NEWS_FETCH_HOURS ديناميكي من الـ config module
    عشان لو البوت غيّر القيمة قبل ما ينادي fetch_news()، التغيير ينعكس هنا
    """
    if published is None:
        return True  # 🔴 FIX v2: أخبار بدون تاريخ = نسيبها تعدي (قبل كده كانت False وده بيضيع أخبار كتير!)
    now = datetime.now(timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    time_diff = now - published
    hours = max_hours if max_hours is not None else _config_module.NEWS_FETCH_HOURS
    return time_diff.total_seconds() <= hours * 3600


def _parse_published(entry) -> Optional[datetime]:
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


def parse_entry(entry, feed_url: str, published: datetime = None) -> Optional[Dict]:
    article = {
        "title": getattr(entry, "title", "").strip(),
        "link": getattr(entry, "link", "").strip(),
        "description": "",
        "published": published,
        "source": "",
        "source_url": feed_url,
    }

    if hasattr(entry, "summary"):
        article["description"] = re.sub(r'<[^>]+>', '', entry.summary).strip()
    elif hasattr(entry, "description"):
        article["description"] = re.sub(r'<[^>]+>', '', entry.description).strip()

    if hasattr(entry, "source") and hasattr(entry.source, "title"):
        article["source"] = entry.source.title
    else:
        try:
            domain = urlparse(feed_url).netloc
            article["source"] = domain.replace("www.", "")
        except Exception:
            article["source"] = "Unknown"

    return article


def _fetch_rss_feed_sync(feed_url: str) -> List[Dict]:
    """جلب الأخبار من مصدر RSS واحد (متزامن)"""
    articles = []

    try:
        logger.info(f"Fetching RSS feed: {feed_url}")
        response = requests.get(
            feed_url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "AI-News-Bot/1.0 (Telegram Bot)"}
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        if feed.bozo and not feed.entries:
            logger.warning(f"Failed to parse feed {feed_url}: {feed.bozo_exception}")
            return articles

        total_entries = len(feed.entries)
        skipped_old = 0

        for entry in feed.entries:
            try:
                published = _parse_published(entry)
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


async def fetch_rss_feed(feed_url: str) -> List[Dict]:
    """جلب الأخبار من مصدر RSS واحد (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _fetch_rss_feed_sync(feed_url))


async def fetch_all_feeds() -> List[Dict]:
    """جلب الأخبار من جميع مصادر RSS (بالتوازي)"""
    # جلب كل المصادر بالتوازي عشان أسرع
    tasks = [fetch_rss_feed(feed_url) for feed_url in RSS_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)
        else:
            logger.error(f"Error fetching feed: {result}")

    logger.info(f"Total recent articles fetched from all feeds: {len(all_articles)}")

    # إزالة المكررات
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


async def fetch_news() -> List[Dict]:
    """الوظيفة الرئيسية لجلب الأخبار (غير متزامن)"""
    logger.info("Starting news fetch process...")
    articles = await fetch_all_feeds()
    logger.info(f"News fetch complete. Total: {len(articles)} recent articles")
    return articles


# Keep sync version for backward compatibility (main.py uses it)
def fetch_news_sync() -> List[Dict]:
    """الوظيفة الرئيسية لجلب الأخبار (متزامن - للتوافق)"""
    logger.info("Starting news fetch process (sync)...")
    all_articles = []

    for feed_url in RSS_FEEDS:
        articles = _fetch_rss_feed_sync(feed_url)
        all_articles.extend(articles)

    logger.info(f"Total recent articles fetched from all feeds: {len(all_articles)}")

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
