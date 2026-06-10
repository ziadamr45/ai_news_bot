"""
YouTube Search Module 🔍🎬
بحث في YouTube وتحميل فيديو/صوت بالبحث

🔴 كيف بيشتغل:
1. بيستخدم YouTube Data API v3 (لو متاح) أو web scraping كبديل
2. بيرجع قائمة نتائج فيها: عنوان، رابط، مدة، قناة، صورة مصغرة
3. بيشتغل مع download_handlers عشان يحمّل النتيجة المختارة

🔴 الميزات:
- بحث فيديو YouTube مع نتائج مرتبة بالصلة
- معلومات كاملة لكل نتيجة (عنوان، مدة، قناة، مشاهدة)
- تنسيق النتائج للعرض في التليجرام والواتساب
- Fallback من API → scraping لو الـ API مش متاح
"""

import logging
import re
import os
import asyncio
import json
from typing import Dict, Optional, List
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات
# ═══════════════════════════════════════

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_API_MAX_RESULTS = int(os.environ.get("YOUTUBE_API_MAX_RESULTS", "5"))

# Timeout للطلبات
REQUEST_TIMEOUT = 15


def _format_duration(iso_duration: str) -> str:
    """تحويل مدة YouTube ISO 8601 لتنسيق مقروء
    
    مثال: PT1H23M45S → 1:23:45
    """
    if not iso_duration:
        return "0:00"
    
    hours = 0
    minutes = 0
    seconds = 0
    
    # استخراج الساعات
    h_match = re.search(r'(\d+)H', iso_duration)
    if h_match:
        hours = int(h_match.group(1))
    
    # استخراج الدقائق
    m_match = re.search(r'(\d+)M', iso_duration)
    if m_match:
        minutes = int(m_match.group(1))
    
    # استخراج الثواني
    s_match = re.search(r'(\d+)S', iso_duration)
    if s_match:
        seconds = int(s_match.group(1))
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"


def _format_view_count(count_str: str) -> str:
    """تنسيق عدد المشاهدات"""
    try:
        count = int(count_str)
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        else:
            return str(count)
    except:
        return count_str or "0"


async def search_youtube_youtubeapi(query: str, max_results: int = 5) -> Optional[List[Dict]]:
    """بحث YouTube باستخدام YouTube Data API v3
    
    🔴 ده الطريقة الرسمية والمستقرة — محتاجة API key
    """
    if not YOUTUBE_API_KEY:
        return None
    
    try:
        import aiohttp
        
        # 1. بحث عن الفيديوهات
        search_url = "https://www.googleapis.com/youtube/v3/search"
        search_params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
            "videoDefinition": "any",
            "videoEmbeddable": "true",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                search_url, params=search_params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"YouTube API search failed: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                items = data.get("items", [])
                
                if not items:
                    return []
                
                # 2. نجيب تفاصيل الفيديوهات (مدة، مشاهدات)
                video_ids = [item["id"]["videoId"] for item in items if "videoId" in item.get("id", {})]
                
                details = {}
                if video_ids:
                    details_url = "https://www.googleapis.com/youtube/v3/videos"
                    details_params = {
                        "part": "contentDetails,statistics",
                        "id": ",".join(video_ids),
                        "key": YOUTUBE_API_KEY,
                    }
                    
                    async with session.get(
                        details_url, params=details_params,
                        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
                    ) as details_resp:
                        if details_resp.status == 200:
                            details_data = await details_resp.json()
                            for item in details_data.get("items", []):
                                vid = item.get("id", "")
                                details[vid] = item
                
                # 3. بناء النتائج
                results = []
                for item in items:
                    video_id = item.get("id", {}).get("videoId", "")
                    if not video_id:
                        continue
                    
                    snippet = item.get("snippet", {})
                    detail = details.get(video_id, {})
                    
                    duration_iso = ""
                    view_count = "0"
                    
                    if detail:
                        content_details = detail.get("contentDetails", {})
                        duration_iso = content_details.get("duration", "")
                        statistics = detail.get("statistics", {})
                        view_count = statistics.get("viewCount", "0")
                    
                    # أفضل صورة مصغرة
                    thumbnails = snippet.get("thumbnails", {})
                    thumbnail = ""
                    for quality in ["high", "medium", "default"]:
                        if quality in thumbnails:
                            thumbnail = thumbnails[quality].get("url", "")
                            break
                    
                    results.append({
                        "title": snippet.get("title", ""),
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "video_id": video_id,
                        "duration": _format_duration(duration_iso),
                        "channel": snippet.get("channelTitle", ""),
                        "views": _format_view_count(view_count),
                        "thumbnail": thumbnail,
                        "published_at": snippet.get("publishedAt", ""),
                        "description": snippet.get("description", "")[:200],
                    })
                
                return results
        
    except Exception as e:
        logger.warning(f"YouTube API search error: {e}")
        return None


async def search_youtube_scraping(query: str, max_results: int = 5) -> Optional[List[Dict]]:
    """بحث YouTube باستخدام web scraping (Fallback)
    
    🔴 ده Fallback لو الـ API مش متاح
    بيستخدم yt-dlp كمحرك بحث
    """
    try:
        import yt_dlp
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'default_search': 'ytsearch',
            'max_results': max_results,
            'socket_timeout': REQUEST_TIMEOUT,
        }
        
        loop = asyncio.get_event_loop()
        
        def _search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
                return result
        
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _search),
            timeout=30
        )
        
        if not result or 'entries' not in result:
            return []
        
        results = []
        for entry in result['entries']:
            if not entry:
                continue
            
            video_id = entry.get('id', '') or entry.get('url', '').split('v=')[-1].split('&')[0] if 'v=' in entry.get('url', '') else entry.get('id', '')
            
            # محاولة استخراج video_id
            if not video_id or len(video_id) != 11:
                url = entry.get('url', '')
                vid_match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
                if vid_match:
                    video_id = vid_match.group(1)
                else:
                    continue
            
            duration = entry.get('duration', 0)
            if duration:
                if isinstance(duration, (int, float)):
                    mins = int(duration // 60)
                    secs = int(duration % 60)
                    duration_str = f"{mins}:{secs:02d}"
                else:
                    duration_str = str(duration)
            else:
                duration_str = "0:00"
            
            results.append({
                "title": entry.get('title', ''),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "video_id": video_id,
                "duration": duration_str,
                "channel": entry.get('uploader', entry.get('channel', '')),
                "views": _format_view_count(str(entry.get('view_count', 0) or 0)),
                "thumbnail": entry.get('thumbnail', entry.get('thumbnails', [{}])[0].get('url', '') if entry.get('thumbnails') else ''),
                "published_at": entry.get('upload_date', ''),
                "description": entry.get('description', '')[:200] if entry.get('description') else '',
            })
        
        return results
        
    except Exception as e:
        logger.warning(f"YouTube scraping search error: {e}")
        return None


async def search_youtube(query: str, max_results: int = 5) -> Optional[List[Dict]]:
    """بحث YouTube — API أولاً ثم scraping كبديل
    
    Args:
        query: كلمة البحث
        max_results: أقصى عدد نتائج (5 افتراضياً)
    
    Returns:
        قائمة نتائج أو None لو فشل البحث كله
    """
    # 1. نجرب YouTube Data API
    results = await search_youtube_youtubeapi(query, max_results)
    
    if results is not None:
        logger.info(f"🔍 YouTube API search: {len(results)} results for '{query}'")
        return results
    
    # 2. Fallback: yt-dlp scraping
    logger.info(f"🔍 YouTube API unavailable, falling back to yt-dlp scraping for '{query}'")
    results = await search_youtube_scraping(query, max_results)
    
    if results is not None:
        logger.info(f"🔍 YouTube scraping search: {len(results)} results for '{query}'")
        return results
    
    logger.warning(f"🔍 All YouTube search methods failed for '{query}'")
    return None


def format_search_results(results: List[Dict], lang: str = "ar") -> str:
    """تنسيق نتائج البحث للعرض
    
    🔴 بيشتغل مع التليجرام والواتساب
    """
    if not results:
        return "❌ مفيش نتائج" if lang == "ar" else "❌ No results"
    
    if lang == "ar":
        text = f"🔍 *نتائج البحث في YouTube* ({len(results)} نتيجة)\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        
        for i, r in enumerate(results):
            title = r.get('title', 'بدون عنوان')
            duration = r.get('duration', '0:00')
            channel = r.get('channel', '')
            views = r.get('views', '0')
            
            text += f"*{i+1}.* {title}\n"
            if duration and duration != "0:00":
                text += f"⏱ {duration}"
            if channel:
                text += f" | 📺 {channel}"
            if views and views != "0":
                text += f" | 👁 {views}"
            text += "\n\n"
    else:
        text = f"🔍 *YouTube Search Results* ({len(results)} found)\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        
        for i, r in enumerate(results):
            title = r.get('title', 'Untitled')
            duration = r.get('duration', '0:00')
            channel = r.get('channel', '')
            views = r.get('views', '0')
            
            text += f"*{i+1}.* {title}\n"
            if duration and duration != "0:00":
                text += f"⏱ {duration}"
            if channel:
                text += f" | 📺 {channel}"
            if views and views != "0":
                text += f" | 👁 {views}"
            text += "\n\n"
    
    return text
