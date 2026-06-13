"""Download handlers - Threads download methods.

Playwright, RapidAPI, data-sjs, GraphQL, Cobalt approaches for
downloading media from Threads.
"""

import logging
import os
import re

from handlers.downloads.utils import (
    _is_threads_url,
    _THREADS_URL_PATTERN,
    _USER_AGENT,
    _ensure_audio_only,
    _get_audio_bitrate,
)

logger = logging.getLogger(__name__)


def _find_thread_items(obj, depth=0, max_depth=25):
    """بحث recursive في JSON عشان نلاقي thread_items أو containing_thread
    
    Threads بيحط بيانات البوست في هيكل متداخل عميق:
    - require > [...] > [__bbox, {result: {data: {containing_thread: {thread_items}}}}]
    - أو: thread_items مباشرة
    """
    if depth > max_depth or obj is None:
        return None
    
    if isinstance(obj, dict):
        # 🔴 الأولوية: containing_thread (البوست الرئيسي)
        if "containing_thread" in obj:
            ct = obj["containing_thread"]
            if isinstance(ct, dict) and "thread_items" in ct:
                return ct["thread_items"]
        
        # thread_items مباشرة
        if "thread_items" in obj:
            return obj["thread_items"]
        
        # search في القيم
        for v in obj.values():
            result = _find_thread_items(v, depth + 1, max_depth)
            if result is not None:
                return result
    
    elif isinstance(obj, list):
        for item in obj:
            result = _find_thread_items(item, depth + 1, max_depth)
            if result is not None:
                return result
    
    return None


def _parse_threads_post(post: dict) -> dict | None:
    """استخراج بيانات الميديا من post object واحد
    
    الهيكل:
    - video_versions: [{url, width, height}, ...] — فيديو بجودات مختلفة
    - image_versions2.candidates: [{url, width, height}, ...] — صورة بأحجام مختلفة
    - carousel_media: [...] — ألبوم (صور/فيديوهات متعددة)
    - caption.text — النص
    - user.username — اسم المستخدم
    """
    if not isinstance(post, dict):
        return None
    
    result = {
        "video_url": None,
        "image_url": None,
        "title": "Threads Post",
        "username": "",
        "is_carousel": False,
        "carousel": [],
    }
    
    # 🔴 فيديو — نختار أعلى جودة (أول عنصر)
    video_versions = post.get("video_versions", [])
    if video_versions and isinstance(video_versions, list):
        # أول عنصر = أعلى جودة
        best = video_versions[0] if isinstance(video_versions[0], dict) else {}
        result["video_url"] = best.get("url")
        if result["video_url"]:
            result["video_url"] = result["video_url"].replace("\\u0026", "&").replace("\\/", "/")
    
    # 🔴 صورة — نختار أكبر حجم
    if not result["video_url"]:
        img_v2 = post.get("image_versions2", {})
        if isinstance(img_v2, dict):
            candidates = img_v2.get("candidates", [])
            if candidates and isinstance(candidates, list):
                best_img = candidates[0] if isinstance(candidates[0], dict) else {}
                result["image_url"] = best_img.get("url")
                if result["image_url"]:
                    result["image_url"] = result["image_url"].replace("\\u0026", "&").replace("\\/", "/")
    
    # 🔴 ألبوم (carousel) — لو فيه صور/فيديوهات متعددة
    carousel = post.get("carousel_media", [])
    if carousel and isinstance(carousel, list):
        result["is_carousel"] = True
        for media in carousel:
            if not isinstance(media, dict):
                continue
            # فيديو في الألبوم
            cv = media.get("video_versions", [])
            if cv and isinstance(cv, list):
                best_c = cv[0] if isinstance(cv[0], dict) else {}
                c_url = best_c.get("url", "").replace("\\u0026", "&").replace("\\/", "/")
                if c_url:
                    result["carousel"].append({"url": c_url, "is_video": True})
                    continue
            # صورة في الألبوم
            ci = media.get("image_versions2", {})
            if isinstance(ci, dict):
                cc = ci.get("candidates", [])
                if cc and isinstance(cc, list):
                    best_ci = cc[0] if isinstance(cc[0], dict) else {}
                    c_url = best_ci.get("url", "").replace("\\u0026", "&").replace("\\/", "/")
                    if c_url:
                        result["carousel"].append({"url": c_url, "is_video": False})
    
    # 🔴 عنوان / نص
    caption = post.get("caption")
    if isinstance(caption, dict):
        result["title"] = caption.get("text", "Threads Post")[:200]
    elif isinstance(caption, str):
        result["title"] = caption[:200]
    
    # 🔴 اسم المستخدم
    user = post.get("user", {})
    if isinstance(user, dict):
        result["username"] = user.get("username", "")
    
    # لو فيه بيانات مفيدة
    if result["video_url"] or result["image_url"] or result["carousel"]:
        return result
    
    return None



async def _threads_playwright_download(url: str, tmpdir: str, quality: str = "best") -> dict | None:
    """تحميل فيديو/صورة من Threads باستخدام Playwright (headless browser)
    
    🔴 ده الحل الأضمن عشان:
    - yt-dlp مش بيدعم Threads (مفيش extractor)
    - الـ HTML مش فيه video data (SPA — client-rendered)
    - GraphQL بيرجع null بدون session cookie
    - Playwright بيرندر الصفحة بالكامل ويسحب رابط الفيديو من الـ <video> tag
    
    Returns: dict فيه {success, file_path, title, is_video, file_size} أو None
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("🧵 Threads: Playwright not installed, skipping headless browser method")
        return None
    
    # 🔴 حوّل threads.com → threads.net (Playwright بيتعامل مع الـ redirect صح)
    normalized_url = url
    if 'threads.com' in normalized_url:
        normalized_url = normalized_url.replace('threads.com', 'threads.net')
    
    # 🔴 شيل الـ tracking parameters زي ?xmt=
    clean_url = re.sub(r'\?xmt=.*$', '', normalized_url)
    clean_url = re.sub(r'\?utm_.*$', '', clean_url)
    # شيل أي query params مش لازمة
    if '?' in clean_url:
        base_url = clean_url.split('?')[0]
        # احتفظ بـ post ID بس
        clean_url = base_url
    
    logger.info(f"🧵 Threads: Trying Playwright headless browser for {clean_url[:80]}")
    
    try:
        async with async_playwright() as p:
            # 🔴 Launch headless Chromium
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 720},
                locale='en-US',
            )
            
            page = await context.new_page()
            
            try:
                # 🔴 Navigate to the Threads post
                await page.goto(clean_url, wait_until='networkidle', timeout=30000)
                
                # 🔴 استنى شوية عشان الفيديو يتحمل
                await page.wait_for_timeout(3000)
                
                # 🔴 استخرج رابط الفيديو من الـ <video> tag
                video_url = await page.evaluate('''
                    () => {
                        const video = document.querySelector('video');
                        if (video) {
                            return video.src || video.currentSrc || 
                                   (video.querySelector('source') ? video.querySelector('source').src : null);
                        }
                        return null;
                    }
                ''')
                
                # 🔴 لو ملقيناش video.src، نجرب نلاقيه في الـ network requests
                if not video_url:
                    # نجرب نلاقي رابط الفيديو من الـ performance entries
                    video_url = await page.evaluate('''
                        () => {
                            const entries = performance.getEntriesByType('resource');
                            for (const entry of entries) {
                                if (entry.name && entry.name.includes('cdninstagram.com') && 
                                    (entry.name.includes('.mp4') || entry.name.includes('video'))) {
                                    return entry.name;
                                }
                            }
                            return null;
                        }
                    ''')
                
                # 🔴 لو لسه ملقيناش، نجرب نضغط على الفيديو عشان يشتغل
                if not video_url:
                    try:
                        play_button = await page.query_selector('[data-pressable-container="true"]')
                        if play_button:
                            await play_button.click()
                            await page.wait_for_timeout(2000)
                            
                            video_url = await page.evaluate('''
                                () => {
                                    const video = document.querySelector('video');
                                    if (video) {
                                        return video.src || video.currentSrc;
                                    }
                                    return null;
                                }
                            ''')
                    except Exception:
                        pass
                
                # 🔴 استخرج عنوان البوست
                title = await page.evaluate('''
                    () => {
                        // جرّب selector مختلفين للعنوان
                        const selectors = [
                            'div[data-pressable-container="true"] span',
                            'span.x1lliihq',
                            'div[role="main"] span',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim().length > 5) {
                                return el.textContent.trim().substring(0, 200);
                            }
                        }
                        return document.title || 'Threads Post';
                    }
                ''')
                
                # 🔴 لو ملقيناش فيديو، نجرب نلاقي صورة
                image_url = None
                if not video_url:
                    image_url = await page.evaluate('''
                        () => {
                            const img = document.querySelector('article img[src*="fbcdn"]') ||
                                       document.querySelector('article img[src*="cdninstagram"]');
                            if (img) {
                                return img.src;
                            }
                            return null;
                        }
                    ''')
                
                await browser.close()
                
            except Exception as nav_err:
                await browser.close()
                logger.warning(f"🧵 Threads: Playwright navigation error: {nav_err}")
                return None
        
        # 🔴 الحمل الميديا اللي لقيناها
        if video_url:
            logger.info(f"🧵 Threads: Playwright found video URL: {video_url[:100]}...")
            
            import aiohttp
            file_path = os.path.join(tmpdir, "threads_video.mp4")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    video_url,
                    headers={'Referer': 'https://www.threads.net/', 'User-Agent': 'Mozilla/5.0'},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"🧵 Threads: Video download failed with status {resp.status}")
                        return None
                    
                    file_size = 0
                    with open(file_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                            file_size += len(chunk)
                    
                    if file_size < 1000:
                        try: os.remove(file_path)
                        except: pass
                        logger.warning(f"🧵 Threads: Downloaded file too small ({file_size} bytes)")
                        return None
            
            return {
                "success": True,
                "file_path": file_path,
                "file_size": file_size,
                "title": title or "Threads Post",
                "is_video": True,
                "method": "playwright",
            }
        
        elif image_url:
            logger.info(f"🧵 Threads: Playwright found image URL: {image_url[:100]}...")
            
            import aiohttp
            file_path = os.path.join(tmpdir, "threads_image.jpg")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    image_url,
                    headers={'Referer': 'https://www.threads.net/', 'User-Agent': 'Mozilla/5.0'},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"🧵 Threads: Image download failed with status {resp.status}")
                        return None
                    
                    file_size = 0
                    with open(file_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                            file_size += len(chunk)
                    
                    if file_size < 500:
                        try: os.remove(file_path)
                        except: pass
                        return None
            
            return {
                "success": True,
                "file_path": file_path,
                "file_size": file_size,
                "title": title or "Threads Post",
                "is_video": False,
                "method": "playwright",
            }
        
        else:
            logger.warning("🧵 Threads: Playwright could not find any media on the page")
            return None
    
    except asyncio.TimeoutError:
        logger.warning("🧵 Threads: Playwright timed out")
        return None
    except Exception as e:
        logger.warning(f"🧵 Threads: Playwright error: {e}")
        return None




async def _download_threads_media(url: str, tmpdir: str, quality: str = "best") -> dict | None:
    """تحميل فيديو/صورة من Threads — الحل النهائي v5
    
    🔴 الترتيب (محدث 2025-06):
    0. Playwright headless browser — الأضمن (بيرندر الصفحة ويسحب الفيديو)
    1. RapidAPI — سريع لو المفتاح متاح
    2. data-sjs JSON parsing — استخراج من <script data-sjs> tags في HTML
       ⚠️ ملاحظة: Threads بيبقي video_versions=null في الـ HTML دلوقتي!
       بس image_versions2 لسه شغال → بنستخدمه للصور
    3. GraphQL API — طلب مباشر من threads.com/api/graphql
    4. Cobalt API — خدمة مفتوحة المصدر كـ fallback
    
    🔴 تغييرات v5:
    - إضافة Playwright كطريقة أولى (الأضمن — الـ SPA بيتعمل render كامل)
    - شيل الـ tracking parameters (?xmt=, ?utm_) من الروابط
    - لا fallback لـ yt-dlp (مش بيدعم Threads)
    
    Returns: dict فيه {success, file_path, title, is_video, file_size} أو None
    """
    import aiohttp
    import json as _json
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
    }
    
    # 🔴 FIX v5: شيل الـ tracking parameters (?xmt=, ?utm_) من الروابط
    clean_url = re.sub(r'\?xmt=.*$', '', url)
    clean_url = re.sub(r'\?utm_.*$', '', clean_url)
    if '?' in clean_url:
        base = clean_url.split('?')[0]
        clean_url = base
    
    # 🔴 FIX v4: threads.net بيعمل redirect لـ threads.com دلوقتي
    # نوحد الرابط — كلاهما يقبلوا threads.com و threads.net
    # بنحتفظ بالرابط الأصلي وبنجرب الاتنين لو الاول فشل
    normalized_url = clean_url
    # حوّل threads.com → threads.net للتوافق (الاتنين بيرجعوا نفس البيانات)
    # بس threads.net أضمن عشان الـ redirect بيتعامل معاه صح
    if 'threads.com' in normalized_url:
        normalized_url = normalized_url.replace('threads.com', 'threads.net')
    
    # 🔴 FIX v4: بنجرب الاتنين threads.net و threads.com لو الاول فشل
    urls_to_try = [normalized_url]
    if 'threads.net' in normalized_url:
        urls_to_try.append(normalized_url.replace('threads.net', 'threads.com'))
    elif 'threads.com' in normalized_url:
        urls_to_try.append(normalized_url.replace('threads.com', 'threads.net'))
    
    # ═══════════════════════════════════════
    # الطريقة 0: Playwright headless browser — الأضمن!
    # 🔴 بيرندر الصفحة بالكامل ويسحب رابط الفيديو من <video> tag
    # ═══════════════════════════════════════
    try:
        pw_result = await _threads_playwright_download(url, tmpdir, quality)
        if pw_result:
            logger.info(f"🧵 Threads: Playwright succeeded! ({pw_result.get('method', 'playwright')})")
            return pw_result
        else:
            logger.warning("🧵 Threads: Playwright failed, trying other methods...")
    except Exception as e:
        logger.warning(f"🧵 Threads: Playwright error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 1: RapidAPI — سريع لو المفتاح متاح
    # ═══════════════════════════════════════
    try:
        from config import RAPIDAPI_KEY
        
        if RAPIDAPI_KEY:
            logger.info(f"🧵 Threads: Trying RapidAPI first (most reliable for video) for {url[:80]}")
            
            rapidapi_result = await _threads_rapidapi_download(url, tmpdir, headers, quality)
            if rapidapi_result:
                rapidapi_result["method"] = "rapidapi"
                return rapidapi_result
            else:
                logger.warning("🧵 Threads: RapidAPI failed, trying other methods...")
        else:
            logger.info("🧵 Threads: No RAPIDAPI_KEY configured, skipping RapidAPI")
    
    except Exception as e:
        logger.warning(f"🧵 Threads: RapidAPI error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 1: data-sjs JSON Parsing
    # 🔴 ملاحظة: video_versions بيبقي null في الـ HTML دلوقتي!
    # بس image_versions2 لسه شغال → بنستخدمه للصور
    # ═══════════════════════════════════════
    html_data = None  # بنخزن الـ HTML عشان نستخدمه في GraphQL
    for attempt_url in urls_to_try:
        try:
            logger.info(f"🧵 Threads: Trying data-sjs parsing for {attempt_url[:80]}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(attempt_url, headers=headers, 
                                      timeout=aiohttp.ClientTimeout(total=30),
                                      allow_redirects=True) as resp:
                    final_url = str(resp.url)
                    
                    if resp.status != 200:
                        logger.warning(f"🧵 Threads: Page returned status {resp.status}")
                        continue
                    
                    html = await resp.text()
                    
                    # 🔴 FIX: حتى لو الـ redirect راح لصفحة error،
                    # Threads بيبعت البيانات في الـ HTML أصلًا!
                    # صفحة error=? بتحتوي على الـ data-sjs scripts بالفيديو
                    # لازم نحاول parse في كل الحالات
                    
                    if html and len(html) > 500:
                        html_data = html  # خزن للـ GraphQL
                        
                        # 🔴 نبحث عن <script type="application/json" data-sjs>
                        script_pattern = r'<script[^>]*type="application/json"[^>]*data-sjs[^>]*>(.*?)</script>'
                        scripts = re.findall(script_pattern, html, re.DOTALL | re.IGNORECASE)
                        
                        logger.info(f"🧵 Threads: Found {len(scripts)} data-sjs script tags")
                        
                        for i, script_content in enumerate(scripts):
                            if '"ScheduledServerJS"' not in script_content and 'thread_items' not in script_content:
                                continue
                            
                            try:
                                data = _json.loads(script_content)
                            except _json.JSONDecodeError:
                                continue
                            
                            # 🔴 بحث recursive عن thread_items
                            thread_items = _find_thread_items(data)
                            
                            if thread_items and isinstance(thread_items, list):
                                logger.info(f"🧵 Threads: Found thread_items with {len(thread_items)} items")
                                
                                for item in thread_items:
                                    if not isinstance(item, dict):
                                        continue
                                    
                                    post = item.get("post", item)
                                    parsed = _parse_threads_post(post)
                                    if parsed:
                                        # 🔴 FIX v4: لو video_url موجود (مش null) → نحمل
                                        # لو image_url بس → نحمل الصورة
                                        # لو الاتنين null → نكمل للطريقة التالية
                                        has_video = bool(parsed.get('video_url'))
                                        has_image = bool(parsed.get('image_url'))
                                        has_carousel = len(parsed.get('carousel', [])) > 0
                                        
                                        logger.info(f"🧵 Threads: Parsed post — video={has_video} image={has_image} carousel={has_carousel}")
                                        
                                        if has_video or has_image or has_carousel:
                                            result = await _threads_download_media(parsed, tmpdir, headers, quality)
                                            if result:
                                                result["method"] = "data_sjs"
                                                return result
                            
                            logger.warning(f"🧵 Threads: Script #{i} had no usable media (video_versions is null)")
            
            # لو وصلنا هنا → data-sjs مفيش فيديو → نكمل
            break  # مفيش داعي نجرب الـ URL التاني
            
        except asyncio.TimeoutError:
            logger.warning("🧵 Threads: data-sjs request timed out")
        except Exception as e:
            logger.warning(f"🧵 Threads: data-sjs parsing error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 2: GraphQL API — طلب مباشر
    # 🔴 FIX v4: doc_ids محدثة + بنستخدم threads.com بدل threads.net
    # ═══════════════════════════════════════
    try:
        logger.info(f"🧵 Threads: Trying GraphQL API for {url[:80]}")
        
        # استخراج post shortcode من الرابط
        post_code = None
        match = re.search(r'/post/([A-Za-z0-9_-]+)', url)
        if not match:
            match = re.search(r'/t/([A-Za-z0-9_-]+)', url)
        if match:
            post_code = match.group(1)
        
        if post_code:
            # 🔴 FIX v4: نستخرج LSD token من الـ HTML اللي حملناه
            lsd_token = ''
            if html_data:
                lsd_match = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', html_data)
                if lsd_match:
                    lsd_token = lsd_match.group(1)
            
            graphql_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'x-ig-app-id': '238260118697367',
                'x-fb-lsd': lsd_token,
                'content-type': 'application/x-www-form-urlencoded',
                'Accept': '*/*',
                'Origin': 'https://www.threads.net',
                'Referer': url,
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
            }
            
            async with aiohttp.ClientSession() as session:
                # 🔴 FIX v4: doc_ids محدثة + بنجرب الاتنين threads.net و threads.com
                # doc_id القديم 5587632691339264 بيرجع data=null
                # بنجرب doc_ids جديدة من الـ JS bundles
                doc_ids = [
                    '5587632691339264',  # القديم (ممكن يشتغل لو الـ variables صح)
                    '27448316234780989',  # BarcelonaLightboxDialogRootViewerQuery
                    '27125403363779788',  # BarcelonaLightboxDialogRootQuery
                ]
                
                for doc_id in doc_ids:
                    try:
                        payload = {
                            'lsd': lsd_token,
                            'variables': _json.dumps({"postID": post_code}),
                            'doc_id': doc_id,
                        }
                        
                        for api_origin in ['https://www.threads.net', 'https://www.threads.com']:
                            try:
                                async with session.post(
                                    f'{api_origin}/api/graphql',
                                    headers=graphql_headers,
                                    data=payload,
                                    timeout=aiohttp.ClientTimeout(total=15)
                                ) as resp:
                                    if resp.status != 200:
                                        continue
                                    try:
                                        gql_data = await resp.json()
                                        text_str = _json.dumps(gql_data)
                                        
                                        # 🔴 لو فيه errors → جرب doc_id التالي
                                        if 'errors' in gql_data:
                                            err_msg = gql_data['errors'][0].get('message', '')[:60]
                                            logger.debug(f"🧵 Threads: GraphQL doc_id {doc_id} @ {api_origin}: {err_msg}")
                                            continue
                                        
                                        # 🔴 لو data=null → جرب doc_id التاني
                                        if gql_data.get('data', {}).get('data') is None:
                                            continue
                                        
                                        thread_items = _find_thread_items(gql_data)
                                        
                                        if thread_items and isinstance(thread_items, list):
                                            for item in thread_items:
                                                if not isinstance(item, dict):
                                                    continue
                                                post = item.get("post", item)
                                                parsed = _parse_threads_post(post)
                                                if parsed and (parsed.get('video_url') or parsed.get('image_url')):
                                                    logger.info(f"🧵 Threads: GraphQL found media!")
                                                    result = await _threads_download_media(parsed, tmpdir, headers, quality)
                                                    if result:
                                                        result["method"] = "graphql"
                                                        return result
                                    except:
                                        pass
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"🧵 Threads: GraphQL doc_id {doc_id} failed: {e}")
        else:
            logger.warning("🧵 Threads: Could not extract post code from URL for GraphQL")
    
    except Exception as e:
        logger.warning(f"🧵 Threads: GraphQL error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 3: Cobalt API — خدمة مفتوحة المصدر
    # 🔴 Cobalt بيدعم Threads وبيشتغل من غير API key
    # ═══════════════════════════════════════
    try:
        cobalt_result = await _threads_cobalt_download(url, tmpdir, headers, quality)
        if cobalt_result:
            cobalt_result["method"] = "cobalt"
            return cobalt_result
    except Exception as e:
        logger.debug(f"🧵 Threads: Cobalt error: {e}")
    
    logger.warning(f"🧵 Threads: All methods failed for {url[:80]}")
    logger.warning("🧵 Threads: NOTE — Threads changed their API and video URLs are no longer in HTML. RapidAPI key is recommended.")
    return None




async def _threads_cobalt_download(url: str, tmpdir: str, headers: dict, quality: str = "best") -> dict | None:
    """تحميل من Threads عبر Cobalt API — خدمة مفتوحة المصدر
    
    Cobalt بيدعم Threads وبيقدر يجيب روابط الفيديو اللي مش موجودة في الـ HTML
    
    🔴 ملاحظة: Cobalt API instances بتتغير، بنجرب أكتر من واحد
    """
    import aiohttp
    
    # 🔴 Cobalt API instances (مفتوحة المصدر)
    cobalt_instances = [
        'https://api.cobalt.tools',
        'https://cobalt-api.kwiatekmiki.com',
    ]
    
    for api_url in cobalt_instances:
        try:
            api_headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
            payload = {
                'url': url,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    headers=api_headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        continue
                    
                    data = await resp.json()
                    status = data.get('status', '')
                    
                    if status == 'redirect' or status == 'tunnel':
                        # 🔴 رابط التحميل المباشر
                        download_url = data.get('url', '')
                        if download_url:
                            logger.info(f"🧵 Threads: Cobalt got download URL from {api_url}")
                            
                            # تحديد نوع الملف
                            is_video = '.mp4' in download_url or 'video' in data.get('filename', '')
                            ext = "mp4" if is_video else "jpg"
                            file_path = os.path.join(tmpdir, f"threads_cobalt.{ext}")
                            timeout = 120 if is_video else 60
                            
                            dl_headers = dict(headers)
                            dl_headers['Referer'] = 'https://www.threads.net/'
                            
                            async with session.get(download_url, headers=dl_headers,
                                                  timeout=aiohttp.ClientTimeout(total=timeout)) as dl_resp:
                                if dl_resp.status != 200:
                                    continue
                                
                                file_size = 0
                                with open(file_path, 'wb') as f:
                                    async for chunk in dl_resp.content.iter_chunked(8192):
                                        f.write(chunk)
                                        file_size += len(chunk)
                                
                                if file_size < 1000:
                                    try: os.remove(file_path)
                                    except: pass
                                    continue
                            
                            return {
                                "success": True,
                                "file_path": file_path,
                                "file_size": file_size,
                                "title": "Threads Post",
                                "is_video": is_video,
                            }
                    
                    elif status == 'picker':
                        # 🔴 عندنا اختيارات (carousel) → نحمل أول واحد
                        picker = data.get('picker', [])
                        if picker and isinstance(picker, list):
                            first = picker[0]
                            download_url = first.get('url', '')
                            if download_url:
                                is_video = first.get('type', '') == 'video'
                                ext = "mp4" if is_video else "jpg"
                                file_path = os.path.join(tmpdir, f"threads_cobalt.{ext}")
                                
                                async with session.get(download_url, headers={'Referer': 'https://www.threads.net/'},
                                                      timeout=aiohttp.ClientTimeout(total=120)) as dl_resp:
                                    if dl_resp.status != 200:
                                        continue
                                    file_size = 0
                                    with open(file_path, 'wb') as f:
                                        async for chunk in dl_resp.content.iter_chunked(8192):
                                            f.write(chunk)
                                            file_size += len(chunk)
                                
                                if file_size < 1000:
                                    try: os.remove(file_path)
                                    except: pass
                                    continue
                                
                                return {
                                    "success": True,
                                    "file_path": file_path,
                                    "file_size": file_size,
                                    "title": "Threads Post",
                                    "is_video": is_video,
                                }
                    
                    elif status == 'error':
                        logger.debug(f"🧵 Threads: Cobalt error: {data.get('error', {}).get('code', 'unknown')}")
                    
        except asyncio.TimeoutError:
            logger.debug(f"🧵 Threads: Cobalt {api_url} timed out")
        except Exception as e:
            logger.debug(f"🧵 Threads: Cobalt {api_url} error: {e}")
    
    return None




async def _threads_download_media(parsed: dict, tmpdir: str, headers: dict, quality: str = "best") -> dict | None:
    """تحميل الميديا من parsed Threads post data
    
    بيتعامل مع: فيديو واحد، صورة واحدة، أو ألبوم (carousel)
    """
    import aiohttp
    
    username = parsed.get("username", "")
    title = parsed.get("title", "Threads Post")
    if username and title == "Threads Post":
        title = f"@{username} on Threads"
    
    # 🔴 أولوية: فيديو > صورة > أول عنصر في الألبوم
    media_url = None
    is_video = False
    
    if parsed.get("video_url"):
        media_url = parsed["video_url"]
        is_video = True
    elif parsed.get("image_url"):
        media_url = parsed["image_url"]
        is_video = False
    elif parsed.get("carousel") and len(parsed["carousel"]) > 0:
        first = parsed["carousel"][0]
        media_url = first.get("url")
        is_video = first.get("is_video", False)
    
    if not media_url:
        return None
    
    # 🔴 لو الجودة مش best وفيه فيديو، بنحاول نختار الجودة المناسبة
    if is_video and quality != "best" and parsed.get("video_url"):
        # video_versions مرتبة من أعلى جودة لأقلها
        # لو المستخدم طلب medium أو low، مش لازم نعمل حاجة لأننا بنحمل أعلى جودة بس
        pass
    
    try:
        if is_video:
            logger.info(f"🧵 Threads: Downloading video from {media_url[:100]}...")
            ext = "mp4"
            file_path = os.path.join(tmpdir, f"threads_video.{ext}")
            timeout = 120
        else:
            logger.info(f"🧵 Threads: Downloading image from {media_url[:100]}...")
            ext = "jpg"
            file_path = os.path.join(tmpdir, f"threads_image.{ext}")
            timeout = 60
        
        dl_headers = dict(headers)
        dl_headers['Referer'] = 'https://www.threads.net/'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url, headers=dl_headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    logger.warning(f"🧵 Threads: Download failed with status {resp.status}")
                    return None
                
                file_size = 0
                with open(file_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
                        file_size += len(chunk)
                
                if file_size < 1000:
                    logger.warning(f"🧵 Threads: File too small ({file_size} bytes) — probably error page")
                    try: os.remove(file_path)
                    except: pass
                    return None
        
        return {
            "success": True,
            "file_path": file_path,
            "file_size": file_size,
            "title": title,
            "is_video": is_video,
        }
    
    except asyncio.TimeoutError:
        logger.warning("🧵 Threads: Download timed out")
        return None
    except Exception as e:
        logger.warning(f"🧵 Threads: Download error: {e}")
        return None




async def _threads_rapidapi_download(url: str, tmpdir: str, headers: dict, quality: str = "best") -> dict | None:
    """تحميل من Threads عبر RapidAPI — fallback أخير
    
    Endpoint: POST https://threads-downloader.p.rapidapi.com/v1/threads/download
    Body: {"url": "https://www.threads.net/@user/post/CODE"}
    
    Response expected:
    - success: true/false
    - data.medias[] — قائمة بروابط التحميل
    - data.medias[].url — رابط الميديا
    - data.medias[].type — "video" أو "image"
    - data.caption — نص البوست
    """
    import aiohttp
    import json as _json
    
    try:
        from config import RAPIDAPI_KEY
        
        api_url = "https://threads-downloader.p.rapidapi.com/v1/threads/download"
        
        api_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": "threads-downloader.p.rapidapi.com",
        }
        
        payload = {"url": url}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=api_headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    resp_text = await resp.text()
                    logger.warning(f"🧵 Threads: RapidAPI returned status {resp.status}: {resp_text[:200]}")
                    return None
                
                data = await resp.json()
                
                # 🔴 نتأكد إن الـ API رجع success
                if not data.get("success", True):
                    logger.warning(f"🧵 Threads: RapidAPI error: {data.get('message', 'Unknown error')}")
                    return None
                
                # 🔴 استخراج بيانات الميديا من الرد
                # الهيكل الممكن:
                # 1. data.medias[] — قائمة بروابط التحميل
                # 2. data.video_url / data.image_url — رابط واحد
                # 3. data.download_url — رابط واحد
                download_url = None
                is_video = True
                title = "Threads Post"
                
                inner = data.get("data", data)
                
                # 🔴 الطريقة 1: medias array (الأحدث)
                medias = inner.get("medias", [])
                if isinstance(medias, list) and len(medias) > 0:
                    first_media = medias[0] if isinstance(medias[0], dict) else {}
                    download_url = first_media.get("url") or first_media.get("download_url")
                    media_type = first_media.get("type", "").lower()
                    is_video = media_type == "video" or first_media.get("is_video", True)
                    logger.info(f"🧵 Threads: RapidAPI medias[0] type={media_type}")
                
                # 🔴 الطريقة 2: video_url / image_url مباشرة
                if not download_url:
                    download_url = (
                        inner.get("video_url") or
                        inner.get("download_url") or
                        inner.get("url")
                    )
                    if not download_url:
                        download_url = inner.get("image_url") or inner.get("thumbnail_url")
                        if download_url:
                            is_video = False
                
                # 🔴 الطريقة 3: video_urls array
                if not download_url:
                    video_urls = inner.get("video_urls", [])
                    if isinstance(video_urls, list) and len(video_urls) > 0:
                        first = video_urls[0]
                        download_url = first.get("url") if isinstance(first, dict) else first
                
                # 🔴 العنوان
                title = inner.get("caption") or inner.get("title") or inner.get("text") or "Threads Post"
                
                if not download_url:
                    logger.warning(f"🧵 Threads: RapidAPI returned no download URL. Response: {str(data)[:300]}")
                    return None
                
                logger.info(f"🧵 Threads: RapidAPI got download URL — is_video={is_video}")
                
                # 🔴 تحميل الملف
                dl_headers = dict(headers)
                dl_headers['Referer'] = 'https://www.threads.net/'
                
                if is_video:
                    file_path = os.path.join(tmpdir, "threads_video.mp4")
                    timeout = 120
                else:
                    file_path = os.path.join(tmpdir, "threads_image.jpg")
                    timeout = 60
                
                async with session.get(download_url, headers=dl_headers, timeout=aiohttp.ClientTimeout(total=timeout)) as dl_resp:
                    if dl_resp.status != 200:
                        logger.warning(f"🧵 Threads: RapidAPI download failed with status {dl_resp.status}")
                        return None
                    
                    file_size = 0
                    with open(file_path, 'wb') as f:
                        async for chunk in dl_resp.content.iter_chunked(8192):
                            f.write(chunk)
                            file_size += len(chunk)
                    
                    if file_size < 1000:
                        logger.warning(f"🧵 Threads: RapidAPI file too small ({file_size} bytes)")
                        try: os.remove(file_path)
                        except: pass
                        return None
                
                return {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "title": title,
                    "is_video": is_video,
                }
    
    except asyncio.TimeoutError:
        logger.warning("🧵 Threads: RapidAPI timed out")
        return None
    except Exception as e:
        logger.warning(f"🧵 Threads: RapidAPI error: {e}")
        return None


# ═══════════════════════════════════════
# كشف ffmpeg - FFmpeg Availability Check
# ═══════════════════════════════════════



