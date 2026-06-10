"""
Image Search Module 🔍🖼️
بحث عن صور وتحميلها

🔴 كيف بيشتغل:
1. بيستخدم DuckDuckGo Images API كبحث أساسي (مجاني وموثوق)
2. Fallback لـ Unsplash / Pexels / Pixabay لو متاحين
3. بيرجع قائمة صور فيها: رابط، صورة مصغرة، حجم، مصدر
4. بيقدر يحمّل الصور ويبعتها

🔴 الميزات:
- بحث صور بالكلمات المفتاحية
- تحديد عدد الصور المطلوبة (1-15)
- تحميل الصور وإرسالها مباشرة
- Fallback بين محركات بحث متعددة
"""

import logging
import os
import asyncio
import re
import tempfile
import hashlib
import base64
from typing import Dict, Optional, List
from urllib.parse import quote_plus, urlparse

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات
# ═══════════════════════════════════════

REQUEST_TIMEOUT = 15
MAX_IMAGE_COUNT = 15
MIN_IMAGE_COUNT = 1

# User-Agent
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


# ═══════════════════════════════════════
# DuckDuckGo Image Search (الأساسي — مجاني وموثوق)
# ═══════════════════════════════════════

async def search_images_duckduckgo(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام DuckDuckGo Images — لا يحتاج API key
    
    🔴 ده البحث الأساسي لأنه:
    1. مجاني ومش محتاج API key
    2. ddgs موجود في requirements.txt
    3. بيرجع روابط صور مباشرة (مش صفحات ويب)
    """
    try:
        from ddgs import DDGS
        
        def _sync_search():
            results = []
            with DDGS() as ddgs:
                search_results = list(ddgs.images(query, max_results=min(count, 30)))
                for item in search_results[:count]:
                    results.append({
                        "url": item.get("image", ""),
                        "thumbnail": item.get("thumbnail", ""),
                        "full_url": item.get("image", ""),
                        "width": item.get("width", 0),
                        "height": item.get("height", 0),
                        "description": item.get("title", ""),
                        "author": "",
                        "source": "DuckDuckGo",
                        "download_url": item.get("image", ""),
                    })
            return results
        
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _sync_search)
        
        if results:
            logger.info(f"🖼️ DuckDuckGo image search: {len(results)} results for '{query}'")
            return results
        return None
        
    except ImportError:
        logger.warning("ddgs not installed — DuckDuckGo image search unavailable")
        return None
    except Exception as e:
        logger.warning(f"DuckDuckGo image search error: {e}")
        return None


# ═══════════════════════════════════════
# Unsplash API (Fallback — محتاج API key)
# ═══════════════════════════════════════

async def search_images_unsplash(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام Unsplash API
    
    🔴 محتاج UNSPLASH_ACCESS_KEY في الـ env vars
    """
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not unsplash_key:
        return None
    
    try:
        import aiohttp
        
        url = "https://api.unsplash.com/search/photos"
        params = {
            "query": query,
            "per_page": min(count, 30),
            "client_id": unsplash_key,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Unsplash API failed: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                results_raw = data.get("results", [])
                
                results = []
                for item in results_raw[:count]:
                    results.append({
                        "url": item.get("urls", {}).get("regular", ""),
                        "thumbnail": item.get("urls", {}).get("thumb", ""),
                        "full_url": item.get("urls", {}).get("full", ""),
                        "width": item.get("width", 0),
                        "height": item.get("height", 0),
                        "description": item.get("description", "") or item.get("alt_description", ""),
                        "author": item.get("user", {}).get("name", ""),
                        "source": "Unsplash",
                        "download_url": item.get("links", {}).get("download", ""),
                    })
                
                return results
        
    except Exception as e:
        logger.warning(f"Unsplash search error: {e}")
        return None


# ═══════════════════════════════════════
# Pexels API (Fallback — محتاج API key)
# ═══════════════════════════════════════

async def search_images_pexels(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام Pexels API
    
    🔴 محتاج PEXELS_API_KEY في الـ env vars
    """
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    if not pexels_key:
        return None
    
    try:
        import aiohttp
        
        url = "https://api.pexels.com/v1/search"
        params = {
            "query": query,
            "per_page": min(count, 30),
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"Authorization": pexels_key},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Pexels API failed: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                results_raw = data.get("photos", [])
                
                results = []
                for item in results_raw[:count]:
                    results.append({
                        "url": item.get("src", {}).get("large", ""),
                        "thumbnail": item.get("src", {}).get("medium", ""),
                        "full_url": item.get("src", {}).get("original", ""),
                        "width": item.get("width", 0),
                        "height": item.get("height", 0),
                        "description": item.get("alt", ""),
                        "author": item.get("photographer", ""),
                        "source": "Pexels",
                        "download_url": item.get("src", {}).get("original", ""),
                    })
                
                return results
        
    except Exception as e:
        logger.warning(f"Pexels search error: {e}")
        return None


# ═══════════════════════════════════════
# Pixabay API (Fallback — محتاج API key)
# ═══════════════════════════════════════

async def search_images_pixabay(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام Pixabay API
    
    🔴 محتاج PIXABAY_API_KEY في الـ env vars
    """
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
    if not pixabay_key:
        return None
    
    try:
        import aiohttp
        
        url = "https://pixabay.com/api/"
        params = {
            "key": pixabay_key,
            "q": query,
            "per_page": min(count, 30),
            "image_type": "photo",
            "safesearch": "true",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Pixabay API failed: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                results_raw = data.get("hits", [])
                
                results = []
                for item in results_raw[:count]:
                    results.append({
                        "url": item.get("webformatURL", ""),
                        "thumbnail": item.get("previewURL", ""),
                        "full_url": item.get("largeImageURL", ""),
                        "width": item.get("imageWidth", 0),
                        "height": item.get("imageHeight", 0),
                        "description": item.get("tags", ""),
                        "author": item.get("user", ""),
                        "source": "Pixabay",
                        "download_url": item.get("largeImageURL", ""),
                    })
                
                return results
        
    except Exception as e:
        logger.warning(f"Pixabay search error: {e}")
        return None


# ═══════════════════════════════════════
# بحث صور — Fallback chain
# ═══════════════════════════════════════

async def search_images(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور — Fallback chain بين محركات بحث متعددة
    
    🔴 الأولوية:
    1. DuckDuckGo Images (مجاني — لا يحتاج API key)
    2. Unsplash API (صور عالية الجودة)
    3. Pexels API (صور مجانية)
    4. Pixabay API (صور مجانية)
    
    Args:
        query: كلمة البحث
        count: عدد الصور المطلوبة (1-15)
    
    Returns:
        قائمة نتائج أو None لو فشل البحث كله
    """
    count = max(MIN_IMAGE_COUNT, min(count, MAX_IMAGE_COUNT))
    
    # Fallback chain — DuckDuckGo الأول لأنه مجاني وموثوق
    search_methods = [
        ("DuckDuckGo", search_images_duckduckgo),
        ("Unsplash", search_images_unsplash),
        ("Pexels", search_images_pexels),
        ("Pixabay", search_images_pixabay),
    ]
    
    for name, method in search_methods:
        try:
            results = await method(query, count)
            if results and len(results) > 0:
                logger.info(f"🖼️ Image search ({name}): {len(results)} results for '{query}'")
                return results
        except Exception as e:
            logger.warning(f"🖼️ Image search ({name}) error: {e}")
        logger.debug(f"🖼️ Image search ({name}): no results, trying next...")
    
    logger.warning(f"🖼️ All image search methods failed for '{query}'")
    return None


# ═══════════════════════════════════════
# تحميل الصور
# ═══════════════════════════════════════

async def download_image(url: str, output_dir: str = "/tmp") -> Optional[str]:
    """تحميل صورة من رابط وحفظها محلياً
    
    Returns: مسار الملف المحلي أو None لو فشل التحميل
    """
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "image/*,*/*",
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"🖼️ Image download failed: HTTP {resp.status} for {url[:80]}")
                    return None
                
                # 🔴 تحقق إن الـ Content-Type فعلاً صورة
                content_type = resp.headers.get("Content-Type", "")
                if content_type and "text/html" in content_type:
                    logger.warning(f"🖼️ Got HTML instead of image for {url[:80]}")
                    return None
                
                # تحديد الامتداد من Content-Type
                if "png" in content_type:
                    ext = "png"
                elif "webp" in content_type:
                    ext = "webp"
                elif "gif" in content_type:
                    ext = "gif"
                else:
                    ext = "jpg"
                
                # إنشاء اسم ملف فريد
                file_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                file_path = os.path.join(output_dir, f"img_{file_hash}.{ext}")
                
                data = await resp.read()
                
                # 🔴 تحقق إن البيانات مش صغيرة أوي (أقل من 500 بايت = مش صورة حقيقية)
                if len(data) < 500:
                    logger.warning(f"🖼️ Image too small ({len(data)} bytes) — probably not a real image: {url[:80]}")
                    return None
                
                with open(file_path, 'wb') as f:
                    f.write(data)
                
                return file_path
        
    except Exception as e:
        logger.warning(f"🖼️ Image download error: {e}")
        return None


async def download_image_bytes(url: str) -> Optional[bytes]:
    """تحميل صورة من رابط والرجوع بالبيانات الخام (bytes)
    
    🔴 ده مخصص لواتساب — لأن واتساب بيبعت الصور كـ base64
    Returns: bytes أو None لو فشل التحميل
    """
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "image/*,*/*",
                },
            ) as resp:
                if resp.status != 200:
                    return None
                
                # تحقق إن الـ Content-Type فعلاً صورة
                content_type = resp.headers.get("Content-Type", "")
                if content_type and "text/html" in content_type:
                    return None
                
                data = await resp.read()
                
                # تحقق إن البيانات مش صغيرة أوي
                if len(data) < 500:
                    return None
                
                return data
        
    except Exception as e:
        logger.warning(f"🖼️ Image download bytes error: {e}")
        return None


async def download_images(results: List[Dict], output_dir: str = "/tmp") -> List[str]:
    """تحميل عدة صور من نتائج البحث — يرجع مسارات ملفات
    
    Args:
        results: قائمة نتائج البحث (Dict objects فيها url/full_url/thumbnail)
        output_dir: مجلد الحفظ
    
    Returns: قائمة مسارات الملفات المحملة
    """
    if not results:
        return []
    
    file_paths = []
    
    for r in results:
        # بنفضل الـ URL الكامل، بعدين الـ regular، بعدين الـ thumbnail
        url = r.get("full_url") or r.get("url") or r.get("thumbnail", "")
        if not url:
            continue
        
        path = await download_image(url, output_dir)
        if path:
            file_paths.append(path)
    
    return file_paths


async def download_images_bytes(results: List[Dict]) -> List[bytes]:
    """تحميل عدة صور من نتائج البحث — يرجع bytes لكل صورة
    
    🔴 ده مخصص لواتساب — لأن واتساب بيبعت الصور كـ base64
    Args:
        results: قائمة نتائج البحث (Dict objects فيها url/full_url/thumbnail)
    
    Returns: قائمة bytes لكل صورة اتحملت بنجاح
    """
    if not results:
        return []
    
    images_bytes = []
    
    for r in results:
        # بنفضل الـ URL الكامل، بعدين الـ regular، بعدين الـ thumbnail
        url = r.get("full_url") or r.get("url") or r.get("thumbnail", "")
        if not url:
            continue
        
        data = await download_image_bytes(url)
        if data:
            images_bytes.append(data)
    
    return images_bytes


def format_image_results(results: List[Dict], lang: str = "ar") -> str:
    """تنسيق نتائج بحث الصور للعرض"""
    if not results:
        return "❌ مفيش نتائج" if lang == "ar" else "❌ No results"
    
    if lang == "ar":
        text = f"🖼️ *نتائج بحث الصور* ({len(results)} صورة)\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        
        for i, r in enumerate(results):
            desc = r.get('description', 'بدون وصف')[:60]
            author = r.get('author', '')
            source = r.get('source', '')
            size = f"{r.get('width', 0)}×{r.get('height', 0)}"
            
            text += f"*{i+1}.* {desc}\n"
            if author:
                text += f"📸 {author}"
            if source:
                text += f" | 📁 {source}"
            text += "\n\n"
    else:
        text = f"🖼️ *Image Search Results* ({len(results)} images)\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        
        for i, r in enumerate(results):
            desc = r.get('description', 'No description')[:60]
            author = r.get('author', '')
            source = r.get('source', '')
            
            text += f"*{i+1}.* {desc}\n"
            if author:
                text += f"📸 {author}"
            if source:
                text += f" | 📁 {source}"
            text += "\n\n"
    
    return text
