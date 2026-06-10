"""
Image Search Module 🔍🖼️
بحث عن صور وتحميلها

🔴 كيف بيشتغل:
1. بيستخدم web search APIs عشان يلاقي صور
2. بيرجع قائمة صور فيها: رابط، صورة مصغرة، حجم، مصدر
3. بيقدر يحمّل الصور ويبعتها

🔴 الميزات:
- بحث صور بالكلمات المفتاحية
- تحديد عدد الصور المطلوبة (1-10)
- تحميل الصور وإرسالها مباشرة
- Fallback بين محركات بحث متعددة
"""

import logging
import os
import asyncio
import re
import tempfile
from typing import Dict, Optional, List
from urllib.parse import quote_plus, urlparse

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات
# ═══════════════════════════════════════

REQUEST_TIMEOUT = 15
MAX_IMAGE_COUNT = 10
MIN_IMAGE_COUNT = 1

# User-Agent
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


async def search_images_unsplash(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام Unsplash API
    
    🔴 Unsplash بيقدم API مجاني للبحث عن صور عالية الجودة
    محتاج UNSPLASH_ACCESS_KEY في الـ env vars
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


async def search_images_pexels(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام Pexels API
    
    🔴 Pexels بيقدم API مجاني للبحث عن صور
    محتاج PEXELS_API_KEY في الـ env vars
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


async def search_images_pixabay(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام Pixabay API
    
    🔴 Pixabay بيقدم API مجاني للبحث عن صور
    محتاج PIXABAY_API_KEY في الـ env vars
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


async def search_images_web(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام web search (Fallback نهائي)
    
    🔴 ده آخر حل لو كل الـ APIs مش متاحة
    بيستخدم DuckDuckGo أو Bing image search
    """
    try:
        from web_search import search_web
        
        # بنستخدم web search عشان نلاقي صفحات فيها صور
        web_results = await search_web(f"{query} image", max_results=count, language="en")
        
        if not web_results:
            return None
        
        results = []
        for item in web_results[:count]:
            link = item.get("link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            
            results.append({
                "url": link,
                "thumbnail": "",
                "full_url": link,
                "width": 0,
                "height": 0,
                "description": f"{title}\n{snippet}",
                "author": "",
                "source": "Web Search",
                "download_url": link,
            })
        
        return results
        
    except Exception as e:
        logger.warning(f"Web image search error: {e}")
        return None


async def search_images(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور — Fallback chain بين محركات بحث متعددة
    
    🔴 الأولوية:
    1. Unsplash API (صور عالية الجودة)
    2. Pexels API (صور مجانية)
    3. Pixabay API (صور مجانية)
    4. Web Search (fallback نهائي)
    
    Args:
        query: كلمة البحث
        count: عدد الصور المطلوبة (1-10)
    
    Returns:
        قائمة نتائج أو None لو فشل البحث كله
    """
    count = max(MIN_IMAGE_COUNT, min(count, MAX_IMAGE_COUNT))
    
    # Fallback chain
    search_methods = [
        ("Unsplash", search_images_unsplash),
        ("Pexels", search_images_pexels),
        ("Pixabay", search_images_pixabay),
        ("Web Search", search_images_web),
    ]
    
    for name, method in search_methods:
        results = await method(query, count)
        if results and len(results) > 0:
            logger.info(f"🖼️ Image search ({name}): {len(results)} results for '{query}'")
            return results
        logger.debug(f"🖼️ Image search ({name}): no results, trying next...")
    
    logger.warning(f"🖼️ All image search methods failed for '{query}'")
    return None


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
                    return None
                
                # تحديد الامتداد من Content-Type
                content_type = resp.headers.get("Content-Type", "")
                if "png" in content_type:
                    ext = "png"
                elif "webp" in content_type:
                    ext = "webp"
                elif "gif" in content_type:
                    ext = "gif"
                else:
                    ext = "jpg"
                
                # إنشاء اسم ملف فريد
                import hashlib
                file_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                file_path = os.path.join(output_dir, f"img_{file_hash}.{ext}")
                
                with open(file_path, 'wb') as f:
                    data = await resp.read()
                    f.write(data)
                
                # التحقق إن الملف مش فاضي
                if os.path.getsize(file_path) < 100:
                    os.remove(file_path)
                    return None
                
                return file_path
        
    except Exception as e:
        logger.warning(f"🖼️ Image download error: {e}")
        return None


async def download_images(results: List[Dict], output_dir: str = "/tmp") -> List[str]:
    """تحميل عدة صور من نتائج البحث
    
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
