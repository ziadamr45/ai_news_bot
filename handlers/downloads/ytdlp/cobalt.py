"""Cobalt API helpers for YouTube downloads.

Contains _try_cobalt_for_youtube, _cobalt_api_request, and _try_cobalt_download.
"""

import asyncio
import logging
import os
import re

from handlers.downloads.utils import (
    _is_audio_quality,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# Cobalt Public API — لليوتيوب بس (بدل yt-dlp)
# ═══════════════════════════════════════

# 🔴 Cobalt v6 API (api/json) اتنفصل في نوفمبر 2024
# v7 API بيتطلب JWT — بنستخدمه في المحاولة 8 (Cobalt JWT)
# Self-hosted Cobalt لسه شغال لو عندك COBALT_API_URL

# 🔴 Cobalt API and YouTube URL helpers are imported from utils.py
# (_COBALT_PUBLIC_API, _YOUTUBE_URL_PATTERN, _is_youtube_url)


async def _try_cobalt_for_youtube(url: str, quality: str, tmpdir: str) -> dict | None:
    """تحميل فيديو يوتيوب عبر Cobalt API — Self-Hosted أولاً ثم Public
    
    🔴 بيتعمل ليوتيوب بس — باقي المنصات شغالة بـ yt-dlp زي ما هي
    
    Cobalt API بيشتغل كالتالي:
    - POST للـ API endpoint
    - Payload: {"url": video_url, "vQuality": "720", "filenamePattern": "classic"}
    - لو status == "stream" / "redirect" / "tunnel" → رجّع الـ url
    - لو status == "picker" → رجّع أول رابط في القائمة
    
    يرجع dict فيه:
    - filepath: مسار الملف المحمل
    - filename: اسم الملف
    - title: عنوان الفيديو
    - duration: المدة
    - size: حجم الملف
    
    أو None لو فشل
    """
    import aiohttp
    
    # تحويل الجودة لصيغة Cobalt
    quality_map = {
        "best": "1080",
        "medium": "720",
        "low": "480",
        "audio": "720",  # الجودة مش مهمة للأوديو
    }
    v_quality = quality_map.get(quality, "720")
    
    is_audio = _is_audio_quality(quality)
    
    # ═══ محاولة 1: Self-Hosted Cobalt (COBALT_API_URL) ═══
    # لو عندنا سيرفر Cobalt شغال — ده الأضمن
    try:
        from config import COBALT_API_URL, COBALT_API_KEY
        
        if COBALT_API_URL:
            api_url = COBALT_API_URL.rstrip("/")
            
            # v8 format for self-hosted
            payload = {
                "url": url,
                "videoQuality": v_quality,
                "downloadMode": "audio" if is_audio else "auto",
                "audioFormat": "mp3" if is_audio else "best",
                "filenameStyle": "classic",
                "youtubeVideoCodec": "h264",
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            
            if COBALT_API_KEY:
                headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
            
            logger.info(f"🟠 Cobalt Self-Hosted: requesting download for {url[:80]} (quality={v_quality}, audio={is_audio})")
            
            result = await _cobalt_api_request(api_url, payload, headers, v_quality, is_audio, tmpdir)
            if result:
                return result
            
            logger.warning(f"⚠️ Cobalt Self-Hosted failed, trying next...")
    except Exception as e:
        logger.warning(f"⚠️ Cobalt Self-Hosted error: {e}")
    
    # ═══ محاولة 2: Cobalt Public API (api.cobalt.tools) ═══
    # الـ API الرسمي محتاج API key (JWT) — بنستخدم الـ COBALT_API_KEY لو متاح
    try:
        from config import COBALT_API_KEY
        
        public_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        if COBALT_API_KEY:
            public_headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
        
        # v8 format for public API
        public_payload = {
            "url": url,
            "videoQuality": v_quality,
            "filenameStyle": "classic",
        }
        
        if is_audio:
            public_payload["downloadMode"] = "audio"
            public_payload["audioFormat"] = "mp3"
        
        logger.info(f"🟠 Cobalt Public API: requesting download for {url[:80]}")
        
        result = await _cobalt_api_request("https://api.cobalt.tools", public_payload, public_headers, v_quality, is_audio, tmpdir)
        if result:
            return result
        
        logger.warning(f"⚠️ Cobalt Public API failed")
    except Exception as e:
        logger.warning(f"⚠️ Cobalt Public API error: {e}")
    
    # كل المحاولات فشلت
    logger.warning(f"🟠 All Cobalt methods failed for {url[:80]}")
    return None


async def _cobalt_api_request(api_url: str, payload: dict, headers: dict, 
                               v_quality: str, is_audio: bool, tmpdir: str) -> dict | None:
    """طلب تحميل من أي Cobalt API endpoint — مشتركة بين Self-Hosted و Public
    
    Args:
        api_url: رابط الـ API (بدون trailing slash)
        payload: الـ request payload
        headers: الـ request headers
        v_quality: الجودة (720, 1080, 480)
        is_audio: هل تحميل صوت
        tmpdir: مجلد التحميل المؤقت
    """
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            # الخطوة 1: طلب رابط التحميل من Cobalt
            async with session.post(
                f"{api_url}/",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    resp_text = await resp.text()
                    logger.warning(f"🟠 Cobalt: API returned status {resp.status}: {resp_text[:200]}")
                    return None
                
                data = await resp.json()
            
            status = data.get("status", "")
            
            if status == "error":
                error_code = data.get("error", {})
                if isinstance(error_code, dict):
                    error_code = error_code.get("code", "unknown")
                logger.warning(f"🟠 Cobalt: error response: {error_code}")
                return None
            
            download_url = None
            filename = None
            
            if status in ("stream", "redirect", "tunnel"):
                # رابط مباشر للفيديو
                download_url = data.get("url")
                filename = data.get("filename", "")
            elif status == "picker":
                # محتوى متعدد (carousel, shorts playlist, إلخ)
                picker_items = data.get("picker", [])
                audio_url = data.get("audio")
                if picker_items:
                    # نختار أول عنصر — زي ما المستخدم طلب
                    download_url = picker_items[0].get("url")
                    filename = data.get("filename", "")
                elif audio_url:
                    download_url = audio_url
                    filename = data.get("audioFilename", "audio.mp3")
            else:
                logger.warning(f"🟠 Cobalt: unknown status '{status}'")
                return None
            
            if not download_url:
                logger.warning("🟠 Cobalt: no download URL in response")
                return None
            
            logger.info(f"🟠 Cobalt: got download URL, downloading file...")
            
            # الخطوة 2: تحميل الملف من الرابط
            ext = "mp3" if is_audio else "mp4"
            if not filename:
                filename = f"youtube_download.{ext}"
            # تنظيف اسم الملف
            filename = re.sub(r'[^\w\-.]', '_', filename)
            if not filename.endswith(ext):
                filename = f"{filename.rsplit('.', 1)[0] if '.' in filename else filename}.{ext}"
            
            filepath = os.path.join(tmpdir, filename)
            
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 دقائق للملفات الكبيرة
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.warning(f"🟠 Cobalt: download URL returned status {dl_resp.status}")
                    return None
                
                content_length = dl_resp.headers.get("Content-Length", "unknown")
                logger.info(f"🟠 Cobalt: downloading file (size: {content_length} bytes)...")
                
                with open(filepath, 'wb') as f:
                    async for chunk in dl_resp.content.iter_chunked(8192):
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                logger.warning("🟠 Cobalt: downloaded file is empty")
                os.remove(filepath)
                return None
            
            logger.info(f"🟠 Cobalt: download succeeded! Size: {file_size // (1024*1024)}MB")
            
            return {
                "filepath": filepath,
                "filename": filename,
                "title": filename.rsplit('.', 1)[0] if filename else "YouTube Video",
                "duration": 0,
                "height": int(v_quality) if v_quality.isdigit() else 720,
                "size": file_size,
                "method": "cobalt",
            }
    
    except asyncio.TimeoutError:
        logger.warning("🟠 Cobalt: request timed out")
        return None
    except Exception as e:
        logger.warning(f"🟠 Cobalt: error: {e}")
        return None


# ═══════════════════════════════════════
# تحميل بـ Cobalt Self-Hosted (طبقة إضافية)
# ═══════════════════════════════════════

# 🔴 Cobalt Self-Hosted: طبقة إضافية لو الـ Public API فشل
# بنشغله على سيرفر Railway منفصل ونربطه بالبوت

async def _try_cobalt_download(url: str, quality: str, tmpdir: str) -> dict | None:
    """تحميل فيديو/صوت عبر Cobalt Self-Hosted API
    
    يرجع dict فيه:
    - filepath: مسار الملف المحمل
    - filename: اسم الملف
    - title: عنوان الفيديو (لو موجود)
    - duration: المدة (لو موجودة)
    
    أو None لو فشل
    """
    import aiohttp
    from config import COBALT_API_URL, COBALT_API_KEY
    
    if not COBALT_API_URL:
        logger.info("🔵 Cobalt: COBALT_API_URL not set, skipping")
        return None
    
    api_url = COBALT_API_URL.rstrip("/")
    
    # تحويل الجودة لصيغة Cobalt
    quality_map = {
        "best": "1080",
        "medium": "720",
        "low": "480",
        "audio": "720",  # الجودة مش مهمة للأوديو
    }
    cobalt_quality = quality_map.get(quality, "1080")
    
    is_audio = _is_audio_quality(quality)
    
    payload = {
        "url": url,
        "videoQuality": cobalt_quality,
        "downloadMode": "audio" if is_audio else "auto",
        "audioFormat": "mp3" if is_audio else "best",
        "audioBitrate": "128",
        "filenameStyle": "basic",
        "youtubeVideoCodec": "h264",  # هام لتوافق Telegram/WhatsApp
        "youtubeVideoContainer": "mp4" if not is_audio else "auto",
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    if COBALT_API_KEY:
        headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
    
    logger.info(f"🔵 Cobalt: requesting download for {url[:80]} (quality={cobalt_quality}, audio={is_audio})")
    
    try:
        async with aiohttp.ClientSession() as session:
            # الخطوة 1: طلب رابط التحميل من Cobalt
            async with session.post(
                f"{api_url}/",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"🔵 Cobalt: API returned status {resp.status}")
                    return None
                
                data = await resp.json()
            
            status = data.get("status", "")
            
            if status == "error":
                error_code = data.get("error", {}).get("code", "unknown")
                logger.warning(f"🔵 Cobalt: error response: {error_code}")
                return None
            
            download_url = None
            filename = None
            picker_items = None
            
            if status in ("tunnel", "redirect"):
                download_url = data.get("url")
                filename = data.get("filename", "")
            elif status == "picker":
                # Instagram carousel أو محتوى متعدد
                picker_items = data.get("picker", [])
                audio_url = data.get("audio")
                # نختار أول فيديو من الـ picker
                if picker_items:
                    for item in picker_items:
                        if item.get("type") == "video":
                            download_url = item.get("url")
                            break
                    if not download_url and picker_items:
                        download_url = picker_items[0].get("url")
                elif audio_url:
                    download_url = audio_url
                    filename = data.get("audioFilename", "audio.mp3")
            elif status == "local-processing":
                # Cobalt بيعمل merge محلي — نحتاج نستنى
                tunnel_urls = data.get("tunnel", [])
                output_info = data.get("output", {})
                filename = output_info.get("filename", "")
                if tunnel_urls:
                    download_url = tunnel_urls[0]
            else:
                logger.warning(f"🔵 Cobalt: unknown status '{status}'")
                return None
            
            if not download_url:
                logger.warning("🔵 Cobalt: no download URL in response")
                return None
            
            logger.info(f"🔵 Cobalt: got download URL, downloading file...")
            
            # الخطوة 2: تحميل الملف من رابط الـ tunnel
            ext = "mp3" if is_audio else "mp4"
            if not filename:
                filename = f"cobalt_download.{ext}"
            
            filepath = os.path.join(tmpdir, filename)
            
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 دقائق للملفات الكبيرة
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.warning(f"🔵 Cobalt: download URL returned status {dl_resp.status}")
                    return None
                
                content_length = dl_resp.headers.get("Content-Length", "unknown")
                logger.info(f"🔵 Cobalt: downloading file (size: {content_length} bytes)...")
                
                with open(filepath, 'wb') as f:
                    async for chunk in dl_resp.content.iter_chunked(8192):
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                logger.warning("🔵 Cobalt: downloaded file is empty")
                os.remove(filepath)
                return None
            
            logger.info(f"🔵 Cobalt: download succeeded! Size: {file_size // (1024*1024)}MB")
            
            return {
                "filepath": filepath,
                "filename": filename,
                "title": filename.rsplit('.', 1)[0] if filename else "Video",
                "duration": 0,
                "height": int(cobalt_quality) if cobalt_quality.isdigit() else 720,
                "size": file_size,
                "method": "cobalt",
            }
    
    except asyncio.TimeoutError:
        logger.warning("🔵 Cobalt: request timed out")
        return None
    except Exception as e:
        logger.warning(f"🔵 Cobalt: error: {e}")
        return None
