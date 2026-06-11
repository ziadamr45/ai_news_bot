"""
Image Search Module 🔍🖼️
بحث عن صور وتحميلها

🔴 كيف بيشتغل:
1. بيبحث في DuckDuckGo + Bing + Pexels + Pixabay + Unsplash في نفس الوقت (parallel)
2. بيدمج النتائج وبيخلطها عشان التنوع
3. بيرجع قائمة صور فيها: رابط، صورة مصغرة، حجم، مصدر، مصور
4. بيقدر يحمّل الصور ويبعتها

🔴 الميزات:
- بحث صور بالكلمات المفتاحية
- تحديد عدد الصور المطلوبة (1-15)
- تحميل الصور وإرسالها مباشرة
- Parallel search = أسرع = نتائج أكتر
- DuckDuckGo = صور أشخاص وشخصيات حقيقية من الويب (مجاني!)
- Bing = صور من الويب (optional — لو متوفر API key)
- Pexels · Pixabay · Unsplash = صور ستوك احترافية

🔴 محتاج API keys (اختياري — DuckDuckGo مش محتاج أي حاجة!):
- BING_SEARCH_API_KEY — من azure.microsoft.com (optional — محتاج فيزا)
- PEXELS_API_KEY — من pexels.com/api (مجاني)
- PIXABAY_API_KEY — من pixabay.com/api/docs (مجاني)
- UNSPLASH_ACCESS_KEY — من unsplash.com/developers (مجاني)
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
# DuckDuckGo Image Search (بحث الويب — مجاني ومش محتاج API key!)
# 🔴 الأفضل للأشخاص والشخصيات المحددة لأنه بيفهرس الويب كله
# مش زي Pexels/Pixabay اللي بيشتغلوا بصور ستوك بس
# ═══════════════════════════════════════

async def search_images_duckduckgo(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام DuckDuckGo Images — لا يحتاج API key
    
    🔴 ده البحث الأساسي للأشخاص والشخصيات لأنه:
    1. مجاني ومش محتاج API key أو فيزا
    2. بيفهرس الويب كله (مش ستوك بس) — يلاقي صور أشخاص حقيقيين
    3. ddgs موجود في requirements.txt
    4. بيرجع روابط صور مباشرة (مش صفحات ويب)
    
    🔴 الفرق عن Pexels/Pixabay/Unsplash:
    دول مواقع صور ستوك — صور عامة واحترافية بس مش صور أشخاص حقيقيين.
    لو المستخدم بيدور على "محمد صلاح" بيجيب صور ستوك عن كورة.
    DuckDuckGo بيفهرس الويب كله فهيلاقي صورة محمد صلاح نفسه.
    
    🔴 FIX v3:
    - بنطلب count * 3 نتائج عشان لو فشل تحميل بعض الصور يفضل فيه بدائل
    - بنفعل safesearch=on عشان نمنع الصور غير المناسبة
    - بنرجع كل النتائج مش بس count عشان الهاندلر يكمل يحمل لحد ما يوصل للعدد المطلوب
    """
    try:
        from ddgs import DDGS
        
        # 🔴 بنطلب عدد أكبر من النتائج عشان نوفر بدائل لو فشل التحميل
        search_count = min(count * 3, 30)
        
        def _sync_search():
            results = []
            with DDGS() as ddgs:
                search_results = list(ddgs.images(
                    query, 
                    max_results=search_count,
                    safesearch="on",  # 🔴 فلترة المحتوى غير المناسب
                ))
                for item in search_results:
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
            logger.info(f"🖼️ DuckDuckGo image search: {len(results)} results for '{query}' (requested {search_count})")
            return results
        return None
        
    except ImportError:
        logger.warning("ddgs not installed — DuckDuckGo image search unavailable")
        return None
    except Exception as e:
        logger.warning(f"DuckDuckGo image search error: {e}")
        return None


# ═══════════════════════════════════════
# Unsplash API (أساسي — صور احترافية)
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
# Pexels API (أساسي — صور عالية الجودة)
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
# Pixabay API (أساسي — صور مجانية كتير)
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
# Bing Image Search API (الأفضل للأشخاص والشخصيات المحددة)
# ═══════════════════════════════════════

async def search_images_bing(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور باستخدام Bing Image Search API
    
    🔴 الأفضل للأشخاص والشخصيات المحددة لأنه بيفهرس الويب كله
    مش زي Pexels/Pixabay اللي بيشتغلوا بصور ستوك بس
    
    🔴 محتاج BING_SEARCH_API_KEY في الـ env vars
    مجاني: 1000 طلب/شهر من azure.microsoft.com
    
    🔴 كيف تجيب الـ API key:
    1. روح azure.microsoft.com
    2. اعمل حساب مجاني
    3. أنشئ resource من نوع "Bing Search v7"
    4. خد الـ Key 1 أو Key 2
    5. حطه في BING_SEARCH_API_KEY
    """
    bing_key = os.environ.get("BING_SEARCH_API_KEY", "")
    if not bing_key:
        return None
    
    try:
        import aiohttp
        
        url = "https://api.bing.microsoft.com/v7.0/images/search"
        params = {
            "q": query,
            "count": min(count, 30),
            "offset": 0,
            "mkt": "ar-SA" if any('\u0600' <= c <= '\u06FF' for c in query) else "en-US",
            "safeSearch": "Moderate",
            "imageType": "Photo",
            "size": "Large",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"Ocp-Apim-Subscription-Key": bing_key},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Bing Image API failed: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                results_raw = data.get("value", [])
                
                results = []
                for item in results_raw[:count]:
                    # 🔴 Bing بيرجع thumbnail و contentUrl و hostPageUrl
                    thumbnail = item.get("thumbnailUrl", "")
                    content_url = item.get("contentUrl", "")
                    host_page = item.get("hostPageUrl", "")
                    
                    # نفضل الـ contentUrl (صورة مباشرة) على الـ hostPageUrl
                    best_url = content_url or host_page or thumbnail
                    
                    results.append({
                        "url": best_url,
                        "thumbnail": thumbnail,
                        "full_url": content_url or best_url,
                        "width": item.get("width", 0),
                        "height": item.get("height", 0),
                        "description": item.get("name", ""),
                        "author": item.get("copyright", ""),
                        "source": "Bing",
                        "download_url": content_url or best_url,
                        "host_page": host_page,
                    })
                
                return results
        
    except Exception as e:
        logger.warning(f"Bing Image search error: {e}")
        return None


# ═══════════════════════════════════════
# بحث صور — Parallel Search (DuckDuckGo + Bing + Pexels + Pixabay + Unsplash)
# ═══════════════════════════════════════

async def search_images(query: str, count: int = 3) -> Optional[List[Dict]]:
    """بحث صور — Parallel search من DuckDuckGo + Bing + Pexels + Pixabay + Unsplash
    
    🔴 FIX v3: DuckDuckGo Images هو البحث الأساسي للويب!
    - DuckDuckGo — بيفهرس الويب كله، الأفضل للأشخاص والشخصيات (مجاني، مش محتاج API key!)
    - Bing — لو متوفر BING_SEARCH_API_KEY (optional — محتاج فيزا على Azure)
    - Pexels API — صور ستوك عالية الجودة (محتاج PEXELS_API_KEY)
    - Pixabay API — صور ستوك مجانية كتير (محتاج PIXABAY_API_KEY)
    - Unsplash API — صور ستوك احترافية (محتاج UNSPLASH_ACCESS_KEY)
    
    🔴 ليه DuckDuckGo مهم:
    Pexels/Pixabay/Unsplash دول مواقع صور ستوك — صور عامة واحترافية بس مش صور
    أشخاص حقيقيين. لو المستخدم بيدور على "محمد صلاح" أو "ال أهرامات" أو
    أي حاجة محددة، DuckDuckGo هيلاقيها لأنه بيفهرس الويب كله مش ستوك بس.
    
    🔴 أولوية النتائج:
    - بنحط نتائج DuckDuckGo/Bing الأول (أكثر دقة للبحث عن أشخاص/أشياء محددة)
    - بعدين بنخلط مع نتائج الستوك عشان التنوع
    
    Args:
        query: كلمة البحث
        count: عدد الصور المطلوبة (1-15)
    
    Returns:
        قائمة نتائج أو None لو فشل البحث كله
    """
    count = max(MIN_IMAGE_COUNT, min(count, MAX_IMAGE_COUNT))
    
    # 🔴 FIX v2: بنبحث في الـ 4 APIs في نفس الوقت (parallel) بدل fallback chain
    # كل API بيرجع count نتائج، وبندمجهم وبنختار أفضل count
    import asyncio
    
    search_tasks = [
        ("DuckDuckGo", search_images_duckduckgo),
        ("Bing", search_images_bing),  # optional — لو متوفر BING_SEARCH_API_KEY
        ("Pexels", search_images_pexels),
        ("Pixabay", search_images_pixabay),
        ("Unsplash", search_images_unsplash),
    ]
    
    # بنشغل كل البحث في نفس الوقت
    tasks = []
    for name, method in search_tasks:
        tasks.append(method(query, count))
    
    results_list = await asyncio.gather(*tasks, return_exceptions=True)
    
    # بنجمع كل النتائج الناجحة — بنحط نتائج الويب الأول (DuckDuckGo/Bing)
    web_results = []  # DuckDuckGo + Bing = نتائج من الويب (أشخاص وشخصيات)
    stock_results = []  # Pexels + Pixabay + Unsplash = صور ستوك
    
    for i, result in enumerate(results_list):
        name = search_tasks[i][0]
        if isinstance(result, Exception):
            logger.warning(f"🖼️ Image search ({name}) error: {result}")
            continue
        if result and len(result) > 0:
            logger.info(f"🖼️ Image search ({name}): {len(result)} results for '{query}'")
            if name in ("DuckDuckGo", "Bing"):
                web_results.extend(result)
            else:
                stock_results.extend(result)
        else:
            logger.debug(f"🖼️ Image search ({name}): no results")
    
    # 🔴 بنحط نتائج الويب الأول (أكثر دقة للأشخاص والشخصيات)
    # بعدين نخلط مع نتائج الستوك عشان التنوع
    all_results = web_results + stock_results
    
    if all_results:
        # 🔴 نزيل التكرار بناءً على الـ URL
        seen_urls = set()
        unique_results = []
        for r in all_results:
            url = r.get("url", "") or r.get("thumbnail", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(r)
        
        # 🔴 نرجع العدد المطلوب (أو أكتر شوية عشان لو فشل تحميل بعض الصور)
        return_count = min(count * 2, len(unique_results))  # بنرجع ضعف العدد عشان نعوض عن فشل التحميل
        return unique_results[:return_count]
    
    logger.warning(f"🖼️ All image search APIs failed for '{query}'")
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
