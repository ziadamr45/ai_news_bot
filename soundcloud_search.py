"""
SoundCloud Search Module 🔍🎵
بحث صوت/مزيكا في SoundCloud وتحميل صوت بالبحث

🔴 ليه SoundCloud بدل YouTube للصوت؟
1. SoundCloud مخصص للصوت والمزيكا — نتائج أدق
2. مش محتاج API key دائم — بنستخرج client_id تلقائياً
3. مفيش bot detection زي YouTube
4. جودة صوت عالية ومتنوعة

🔴 كيف بيشتغل:
1. بيستخرج SoundCloud client_id تلقائياً من الـ JS bundles
2. بيستخدم SoundCloud API v2 للبحث
3. بيرجع قائمة نتائج فيها: عنوان، رابط، مدة، فنان، صورة ألبوم
4. بيشتغل مع download_handlers عشان يحمّل النتيجة المختارة
"""

import logging
import re
import os
import asyncio
import time
from typing import Dict, Optional, List
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات
# ═══════════════════════════════════════

REQUEST_TIMEOUT = 15

# SoundCloud client_id cache
_sc_client_id = None
_sc_client_id_expires = 0
_SC_CLIENT_ID_TTL = 7200  # 2 ساعات


def _format_duration(milliseconds: int) -> str:
    """تحويل المدة من ميلي ثانية لتنسيق مقروء
    
    مثال: 180000 → 3:00
    """
    if not milliseconds or milliseconds <= 0:
        return "0:00"
    
    total_seconds = milliseconds // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def _format_play_count(count: int) -> str:
    """تنسيق عدد التشغيلات"""
    try:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        else:
            return str(count)
    except:
        return "0"


async def _get_soundcloud_client_id() -> Optional[str]:
    """استخراج SoundCloud client_id من الـ JS bundles
    
    🔴 SoundCloud مش بيوفر client_id ثابت — بنستخرجه من الـ JS
    الكاش بيفيد لمدة ساعتين قبل ما يتجدد
    """
    global _sc_client_id, _sc_client_id_expires
    
    # لو عندنا client_id صالح — نرجعه
    if _sc_client_id and time.time() < _sc_client_id_expires:
        return _sc_client_id
    
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            # 1. نجلب صفحة SoundCloud الرئيسية
            async with session.get(
                "https://soundcloud.com",
                timeout=aiohttp.ClientTimeout(total=15),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"SoundCloud homepage returned HTTP {resp.status}")
                    return _sc_client_id  # نرجع القديم لو موجود
                
                html = await resp.text()
            
            # 2. نلاقي روابط الـ JS bundles
            js_pattern = r'<script[^>]*src="([^"]*\.js[^"]*)"'
            js_urls = re.findall(js_pattern, html)
            
            if not js_urls:
                logger.warning("No JS bundles found on SoundCloud homepage")
                return _sc_client_id
            
            # 3. نبحث في كل JS bundle عن client_id
            for js_url in js_urls[:5]:  # بنجرب أول 5 بس
                try:
                    async with session.get(
                        js_url,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as js_resp:
                        if js_resp.status != 200:
                            continue
                        
                        js_content = await js_resp.text()
                        
                        # بنبحث عن client_id pattern
                        # Pattern 1: client_id:"XXXX" أو client_id:"XXXX"
                        match = re.search(r'client_id["\s:=]+"([a-zA-Z0-9]{20,40})"', js_content)
                        if match:
                            _sc_client_id = match.group(1)
                            _sc_client_id_expires = time.time() + _SC_CLIENT_ID_TTL
                            logger.info(f"🎵 SoundCloud client_id extracted: {_sc_client_id[:10]}...")
                            return _sc_client_id
                        
                        # Pattern 2: client_id=XXXX
                        match = re.search(r'client_id=([a-zA-Z0-9]{20,40})', js_content)
                        if match:
                            _sc_client_id = match.group(1)
                            _sc_client_id_expires = time.time() + _SC_CLIENT_ID_TTL
                            logger.info(f"🎵 SoundCloud client_id extracted (pattern 2): {_sc_client_id[:10]}...")
                            return _sc_client_id
                except Exception as e:
                    logger.debug(f"Failed to check JS bundle: {e}")
                    continue
            
            logger.warning("Could not extract SoundCloud client_id from JS bundles")
            return _sc_client_id  # نرجع القديم لو موجود
    
    except Exception as e:
        logger.warning(f"SoundCloud client_id extraction error: {e}")
        return _sc_client_id


async def search_soundcloud(query: str, max_results: int = 5) -> Optional[List[Dict]]:
    """بحث صوت/مزيكا في SoundCloud
    
    🔴 بيستخدم SoundCloud API v2 مع client_id مستخرج تلقائياً
    
    Args:
        query: كلمة البحث
        max_results: أقصى عدد نتائج (5 افتراضياً)
    
    Returns:
        قائمة نتائج أو None لو فشل البحث
    """
    try:
        import aiohttp
        
        # نجيب الـ client_id
        client_id = await _get_soundcloud_client_id()
        
        if not client_id:
            logger.warning("No SoundCloud client_id available, cannot search")
            return None
        
        # SoundCloud API v2 Search
        url = "https://api-v2.soundcloud.com/search/tracks"
        params = {
            "q": query,
            "client_id": client_id,
            "limit": max_results,
            "offset": 0,
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
                    logger.warning(f"SoundCloud API search failed: HTTP {resp.status}")
                    # لو الـ client_id منتهي — نمسحه ونجرب تاني
                    if resp.status == 401 or resp.status == 403:
                        global _sc_client_id, _sc_client_id_expires
                        _sc_client_id = None
                        _sc_client_id_expires = 0
                        logger.info("🎵 SoundCloud client_id expired, will refresh on next search")
                    return None
                
                data = await resp.json()
                items = data.get("collection", [])
                
                if not items:
                    return []
                
                results = []
                for item in items:
                    # نتأكد إنه track (مش playlist أو user)
                    if item.get("kind") != "track":
                        continue
                    
                    track_id = item.get("id", "")
                    if not track_id:
                        continue
                    
                    # صورة الألبوم
                    artwork = item.get("artwork_url", "") or ""
                    if artwork:
                        # SoundCloud بيرجع صورة كبيرة - بنصغرها
                        artwork = artwork.replace("-large", "-t300x300")
                    
                    # المدة بالميلي ثانية
                    duration_ms = item.get("full_duration", 0) or item.get("duration", 0)
                    duration_str = _format_duration(duration_ms)
                    
                    # عدد التشغيلات
                    play_count = item.get("playback_count", 0) or 0
                    
                    # الفنان
                    user = item.get("user", {})
                    artist = user.get("username", "") if isinstance(user, dict) else ""
                    
                    # رابط التراك
                    permalink_url = item.get("permalink_url", "")
                    
                    results.append({
                        "title": item.get("title", ""),
                        "url": permalink_url,
                        "video_id": str(track_id),
                        "duration": duration_str,
                        "channel": artist,
                        "views": _format_play_count(play_count),
                        "thumbnail": artwork,
                        "platform": "soundcloud",
                        "description": item.get("title", "")[:200],
                    })
                
                logger.info(f"🔍 SoundCloud search: {len(results)} results for '{query}'")
                return results
        
    except asyncio.TimeoutError:
        logger.warning("SoundCloud API search timed out")
        return None
    except Exception as e:
        logger.warning(f"SoundCloud API search error: {e}")
        return None


def format_search_results(results: List[Dict], lang: str = "ar") -> str:
    """تنسيق نتائج البحث للعرض
    
    🔴 بيشتغل مع التليجرام والواتساب
    """
    if not results:
        return "❌ مفيش نتائج" if lang == "ar" else "❌ No results"
    
    if lang == "ar":
        text = f"🔍 *نتائج بحث SoundCloud* ({len(results)} نتيجة)\n"
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
                text += f" | 🎤 {channel}"
            if views and views != "0":
                text += f" | ▶️ {views}"
            text += "\n\n"
    else:
        text = f"🔍 *SoundCloud Search Results* ({len(results)} found)\n"
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
                text += f" | 🎤 {channel}"
            if views and views != "0":
                text += f" | ▶️ {views}"
            text += "\n\n"
    
    return text
