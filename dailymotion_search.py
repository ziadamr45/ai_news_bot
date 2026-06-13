"""
Dailymotion Search Module 🔍🎬
بحث فيديو في Dailymotion وتحميل فيديو بالبحث

🔴 ليه Dailymotion بدل YouTube؟
1. YouTube API محتاجة API key + quotas محدودة
2. yt-dlp بتواجه bot detection على YouTube باستمرار
3. Dailymotion API مجاني ومفتوح — مش محتاج API key
4. مفيش quotas أو rate limits مزعجة
5. نتائج كويسة ومتنوعة

🔴 كيف بيشتغل:
1. بيستخدم Dailymotion REST API (api.dailymotion.com)
2. بيرجع قائمة نتائج فيها: عنوان، رابط، مدة، قناة، صورة مصغرة
3. بيشتغل مع download_handlers عشان يحمّل النتيجة المختارة
"""

import logging
import re
import os
import asyncio
from typing import Dict, Optional, List
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات
# ═══════════════════════════════════════

REQUEST_TIMEOUT = 15


def _format_duration(seconds: int) -> str:
    """تحويل المدة من ثواني لتنسيق مقروء
    
    مثال: 3661 → 1:01:01
    """
    if not seconds or seconds <= 0:
        return "0:00"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def _format_view_count(count: int) -> str:
    """تنسيق عدد المشاهدات"""
    try:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        else:
            return str(count)
    except:
        return "0"


async def search_dailymotion(query: str, max_results: int = 5) -> Optional[List[Dict]]:
    """بحث فيديو في Dailymotion باستخدام REST API
    
    🔴 Dailymotion API مجاني ومفتوح — مش محتاج API key!
    
    Args:
        query: كلمة البحث
        max_results: أقصى عدد نتائج (5 افتراضيًا)
    
    Returns:
        قائمة نتائج أو None لو فشل البحث
    """
    try:
        import aiohttp
        
        # Dailymotion Search API
        url = "https://api.dailymotion.com/videos"
        params = {
            "search": query,
            "fields": "id,title,thumbnail_720_url,thumbnail_240_url,duration,views_total,owner.screenname,channel,url,created_time",
            "sort": "relevance",
            "limit": max_results,
            "page": 1,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Dailymotion API search failed: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                items = data.get("list", [])
                
                if not items:
                    return []
                
                results = []
                for item in items:
                    video_id = item.get("id", "")
                    if not video_id:
                        continue
                    
                    # أفضل صورة مصغرة
                    thumbnail = (
                        item.get("thumbnail_720_url", "") or 
                        item.get("thumbnail_240_url", "") or
                        ""
                    )
                    
                    # المدة بالثواني
                    duration = item.get("duration", 0)
                    duration_str = _format_duration(duration) if duration else "0:00"
                    
                    # عدد المشاهدات
                    views = item.get("views_total", 0) or 0
                    
                    # القناة
                    channel = item.get("owner.screenname", "") or ""
                    
                    # رابط الفيديو
                    video_url = item.get("url", "") or f"https://www.dailymotion.com/video/{video_id}"
                    
                    results.append({
                        "title": item.get("title", ""),
                        "url": video_url,
                        "video_id": video_id,
                        "duration": duration_str,
                        "channel": channel,
                        "views": _format_view_count(views),
                        "thumbnail": thumbnail,
                        "platform": "dailymotion",
                        "description": item.get("title", "")[:200],
                    })
                
                logger.info(f"🔍 Dailymotion search: {len(results)} results for '{query}'")
                return results
        
    except asyncio.TimeoutError:
        logger.warning("Dailymotion API search timed out")
        return None
    except Exception as e:
        logger.warning(f"Dailymotion API search error: {e}")
        return None


def format_search_results(results: List[Dict], lang: str = "ar") -> str:
    """تنسيق نتائج البحث للعرض
    
    🔴 بيشتغل مع التليجرام والواتساب
    """
    if not results:
        return "❌ مفيش نتائج" if lang == "ar" else "❌ No results"
    
    if lang == "ar":
        text = f"🔍 *نتائج بحث Dailymotion* ({len(results)} نتيجة)\n"
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
        text = f"🔍 *Dailymotion Search Results* ({len(results)} found)\n"
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
