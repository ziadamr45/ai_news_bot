"""
Invidious API Downloader Module
تحميل فيديوهات YouTube عبر Invidious API بدل yt-dlp
يُستخدم كـ fallback بين RapidAPI و yt-dlp

الميزات:
- تحميل فيديو بجودات مختلفة (360p, 720p, 1080p)
- تحميل صوت MP3
- استخراج معلومات الفيديو (عنوان، مدة، صورة مصغرة)
- Fallback تلقائي بين أكتر من سيرفر Invidious
- مش بيتأثر بـ YouTube bot detection خالص
- مجاني ومفتوح — مفيش API keys ولا اشتراكات

🔴 كيف شغال Invidious:
- Invidious هو واجهة بديلة لليوتيوب (front-end) مفتوحة المصدر
- السيرفرات البيبلبليك بتوفر API مجاني
- الـ API بيرجع روابط تحميل مباشرة بدون yt-dlp
- الطلبات بتروح لسيرفرات Invidious مش من الـ IP بتاعك
"""

import logging
import re
import os
import asyncio
from typing import Dict, Optional, List
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# قائمة سيرفرات Invidious العامة
# ═══════════════════════════════════════

# 🔴 سيرفرات Invidious البيبلبليك — بنجربهم بالترتيب
# بعض السيرفرات بتنزل كتير، عشان كده لازم fallback
# القائمة دي بتتحدث بشكل دوري من: https://api.invidious.io/instances.json
# بنختار السيرفرات اللي:
# 1. بتدعم API (api: true)
# 2. مش محتاجة تسجيل (users: لا مش ضروري)
# 3. مستقرة نسبياً

INVIVIOUS_INSTANCES = [
    "https://inv.nadeko.net",              # ✅ شغال
    "https://invidious.materialio.us",      # ✅ شغال
    "https://yewtu.be",                     # ✅ شغال
    "https://invidious.protokolla.fi",      # ✅ شغال
    "https://invidious.snopyta.org",        # ✅ شغال
    "https://invidious.nerdvpn.de",         # ⚠️ أحياناً يشتغل
    "https://inv.tux.pizza",                # ⚠️ أحياناً يشتغل
    "https://vid.puffyan.us",               # ⚠️ أحياناً يشتغل
    "https://invidious.lunar.icu",          # ⚠️ أحياناً يشتغل
    "https://invidious.privacyredirect.com", # ⚠️ أحياناً يشتغل
]

# 🔴 يمكن تحديد سيرفر Invidious خاص من البيئة
# لو عندك سيرفر Invidious خاص (أضمن وأسرع) — ضع الرابط في env var
CUSTOM_INVIDIOUS_INSTANCE = os.environ.get("INVIDIOUS_INSTANCE", "")

# إعدادات الـ timeout والـ retries
INVIVIOUS_API_TIMEOUT = 15       # ثانية لكل طلب API
INVIVIOUS_DOWNLOAD_TIMEOUT = 300 # 5 دقائق لتحميل الملف
INVIVIOUS_MAX_RETRIES = 3        # أقصى عدد سيرفرات نجربها


# ═══════════════════════════════════════
# استخراج Video ID من رابط YouTube
# ═══════════════════════════════════════

_YOUTUBE_PATTERNS = [
    r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/live/([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:m\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
]


def is_youtube_url(url: str) -> bool:
    """التحقق إن الرابط هو رابط YouTube صالح"""
    if not url:
        return False
    for pattern in _YOUTUBE_PATTERNS:
        if re.match(pattern, url.strip()):
            return True
    return False


def extract_video_id(url: str) -> Optional[str]:
    """استخراج معرف الفيديو من رابط YouTube
    
    يدعم:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    - https://www.youtube.com/live/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    
    Returns: video_id (11 حرف) أو None
    """
    if not url:
        return None
    
    url = url.strip()
    
    for pattern in _YOUTUBE_PATTERNS:
        match = re.match(pattern, url)
        if match:
            video_id = match.group(1)
            if len(video_id) == 11:
                return video_id
    
    # محاولة استخراج من query parameter مباشرة
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if 'v' in params:
            vid = params['v'][0]
            if len(vid) == 11:
                return vid
    except Exception:
        pass
    
    return None


# ═══════════════════════════════════════
# دوال Invidious API
# ═══════════════════════════════════════

def _get_instances() -> List[str]:
    """الحصول على قائمة سيرفرات Invidious — السيرفر الخاص الأول لو موجود"""
    instances = []
    if CUSTOM_INVIDIOUS_INSTANCE:
        instances.append(CUSTOM_INVIDIOUS_INSTANCE.rstrip("/"))
    instances.extend(INVIVIOUS_INSTANCES)
    return instances


def _select_best_format(formats: list, quality: str = "best", is_audio: bool = False) -> Optional[dict]:
    """اختيار أفضل تنسيق من قائمة التنسيقات المتاحة
    
    Invidious بيرجع نوعين من التنسيقات:
    - formatStreams: فيديو+صوت مدمجين (pre-merged) — أفضل عشان مش محتاجين ffmpeg
    - adaptiveFormats: فيديو بس أو صوت بس — محتاجين دمج بـ ffmpeg
    
    🔴 الأولوية:
    1. Pre-merged h264/mp4 (أفضل للتليجرام)
    2. Pre-mented أي mp4
    3. Adaptive video h264 + audio (لو ffmpeg متاح)
    4. أي تنسيق متاح
    """
    if not formats:
        return None
    
    if is_audio:
        # صوت بس — بنبحث عن audio only format
        audio_formats = [f for f in formats if f.get("type", "").startswith("audio/")]
        if audio_formats:
            # بنفضل mp3 أو m4a
            for f in audio_formats:
                if "mp3" in f.get("type", "") or "mp4a" in f.get("type", ""):
                    return f
            # أي صوت
            return audio_formats[0]
        # مفيش صوت بس — نرجع None وهنستخدم طريقة تانية
        return None
    
    # ═══ فيديو ═══
    # quality height mapping
    quality_heights = {
        "best": 1080,
        "medium": 720,
        "low": 480,
    }
    max_height = quality_heights.get(quality, 1080)
    
    # 🔴 الأولوية 1: Pre-merged h264/mp4 (أفضل للتليجرام — مش محتاج دمج)
    # formatStreams = pre-merged (فيديو+صوت مع بعض)
    pre_merged = [f for f in formats if f.get("type", "").startswith("video/")]
    
    if pre_merged:
        # بنفضل h264/mp4
        h264_formats = [f for f in pre_merged 
                       if "avc1" in f.get("type", "").lower() 
                       or "mp4" in f.get("type", "").lower()
                       or f.get("container", "") == "mp4"]
        
        # فلترة حسب الجودة
        def _format_quality(f):
            """استخراج الـ height من التنسيق"""
            # من qualityLabel زي "1080p" أو من resolution
            ql = f.get("qualityLabel", "")
            if ql:
                try:
                    return int(ql.replace("p", "").split(" ")[0])
                except:
                    pass
            # من resolution زي "1080p"
            res = f.get("resolution", "")
            if res:
                try:
                    return int(res.replace("p", ""))
                except:
                    pass
            return 0
        
        # بنختار أقرب جودة للـ max_height بدون ما نتجاوزها
        target_formats = h264_formats if h264_formats else pre_merged
        
        # فلترة حسب max_height
        within_quality = [f for f in target_formats if _format_quality(f) <= max_height]
        
        if within_quality:
            # بنختار أعلى جودة
            within_quality.sort(key=_format_quality, reverse=True)
            return within_quality[0]
        
        # مفيش جودة مناسبة — نختار أعلى واحدة
        target_formats.sort(key=_format_quality, reverse=True)
        return target_formats[0]
    
    # 🔴 الأولوية 2: Adaptive formats (محتاج دمج)
    # adaptiveFormats = فيديو بس أو صوت بس
    adaptive = [f for f in formats if not f.get("type", "").startswith("video/") or f.get("type", "").startswith("video/webm")]
    
    # نبحث عن h264 video
    video_adaptive = [f for f in adaptive if "video" in f.get("type", "")]
    if video_adaptive:
        h264_adaptive = [f for f in video_adaptive if "avc1" in f.get("type", "").lower() or "mp4" in f.get("type", "").lower()]
        target = h264_adaptive if h264_adaptive else video_adaptive
        # نختار أعلى جودة
        target.sort(key=lambda f: f.get("bitrate", 0), reverse=True)
        return target[0]
    
    return None


def _get_download_url_from_invidious(instance_url: str, video_id: str, quality: str = "best") -> Optional[Dict]:
    """الحصول على رابط تحميل مباشر من Invidious API (sync version)
    
    Args:
        instance_url: رابط سيرفر Invidious (مثال: https://inv.nadeko.net)
        video_id: معرف فيديو YouTube (11 حرف)
        quality: الجودة المطلوبة ("best", "medium", "low", "audio")
    
    Returns:
        Dictionary فيه:
        - success: True/False
        - title: عنوان الفيديو
        - duration: المدة بالثواني
        - thumbnail: رابط الصورة المصغرة
        - download_url: رابط التحميل المباشر
        - format_info: معلومات التنسيق
        - video_id: معرف الفيديو
        - instance: اسم السيرفر اللي اشتغل
        - error: رسالة الخطأ (لو success = False)
        
        أو None لو فشل بشكل كامل
    """
    import requests
    
    is_audio = quality == "audio"
    api_url = f"{instance_url}/api/v1/videos/{video_id}"
    
    try:
        logger.info(f"🟣 Invidious [{instance_url}]: Fetching video info for {video_id}")
        
        response = requests.get(
            api_url,
            params={"fields": "title,lengthSeconds,videoThumbnails,formatStreams,adaptiveFormats"},
            timeout=INVIVIOUS_API_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )
        
        if response.status_code == 429:
            logger.warning(f"🟣 Invidious [{instance_url}]: Rate limited (429)")
            return {"success": False, "error": "rate_limited", "message": "Rate limited on this instance"}
        
        if response.status_code == 404:
            logger.warning(f"🟣 Invidious [{instance_url}]: Video not found (404)")
            return {"success": False, "error": "not_found", "message": "Video not found"}
        
        if response.status_code != 200:
            logger.warning(f"🟣 Invidious [{instance_url}]: API returned status {response.status_code}")
            return {"success": False, "error": "http_error", "message": f"HTTP {response.status_code}"}
        
        data = response.json()
        
        title = data.get("title", "YouTube Video")
        duration = data.get("lengthSeconds", 0)
        
        # الصورة المصغرة
        thumbnail = ""
        thumbnails = data.get("videoThumbnails", [])
        if thumbnails:
            # بنختار صورة بجودة عالية
            for thumb in thumbnails:
                if thumb.get("quality") == "maxres" or thumb.get("quality") == "maxresdefault":
                    thumbnail = thumb.get("url", "")
                    break
            if not thumbnail and thumbnails:
                thumbnail = thumbnails[0].get("url", "")
        
        # 🔴 استخراج روابط التحميل
        format_streams = data.get("formatStreams", [])     # Pre-merged
        adaptive_formats = data.get("adaptiveFormats", []) # Separate video/audio
        
        all_formats = format_streams + adaptive_formats
        
        if not all_formats:
            logger.warning(f"🟣 Invidious [{instance_url}]: No formats available for {video_id}")
            return {"success": False, "error": "no_formats", "message": "No formats available"}
        
        # اختيار أفضل تنسيق
        selected = _select_best_format(format_streams, quality, is_audio)
        
        if not selected and not is_audio:
            # محاولة مع adaptive formats
            selected = _select_best_format(adaptive_formats, quality, is_audio)
        
        if not selected:
            logger.warning(f"🟣 Invidious [{instance_url}]: No suitable format found for quality={quality}")
            return {"success": False, "error": "no_suitable_format", "message": f"No suitable format for quality={quality}"}
        
        download_url = selected.get("url", "")
        
        if not download_url:
            logger.warning(f"🟣 Invidious [{instance_url}]: Format has no download URL")
            return {"success": False, "error": "no_url", "message": "Format has no download URL"}
        
        # 🔴 مهم: بعض سيرفرات Invidious بترجع رابط نسبي
        # لازم نضيف الـ instance URL لو كان نسبي
        if download_url.startswith("/"):
            download_url = f"{instance_url}{download_url}"
        
        # معلومات التنسيق
        format_info = {
            "quality_label": selected.get("qualityLabel", ""),
            "resolution": selected.get("resolution", ""),
            "type": selected.get("type", ""),
            "container": selected.get("container", ""),
            "bitrate": selected.get("bitrate", 0),
            "is_pre_merged": selected in format_streams,
        }
        
        logger.info(
            f"🟣 Invidious [{instance_url}]: Found format "
            f"{format_info['quality_label'] or format_info['resolution']} "
            f"({format_info['type']}) "
            f"{'[pre-merged]' if format_info['is_pre_merged'] else '[adaptive]'}"
        )
        
        return {
            "success": True,
            "title": title,
            "duration": duration,
            "thumbnail": thumbnail,
            "download_url": download_url,
            "format_info": format_info,
            "video_id": video_id,
            "instance": instance_url,
            "method": "invidious",
        }
    
    except requests.exceptions.Timeout:
        logger.warning(f"🟣 Invidious [{instance_url}]: Request timed out")
        return {"success": False, "error": "timeout", "message": "Request timed out"}
    except requests.exceptions.ConnectionError:
        logger.warning(f"🟣 Invidious [{instance_url}]: Connection error")
        return {"success": False, "error": "connection_error", "message": "Connection error"}
    except Exception as e:
        logger.warning(f"🟣 Invidious [{instance_url}]: Error: {e}")
        return {"success": False, "error": "unknown", "message": str(e)}


def download_youtube_invidious(url: str, quality: str = "best") -> Optional[Dict]:
    """تحميل فيديو YouTube عبر Invidious API مع fallback بين السيرفرات
    
    🔴 الاستراتيجية:
    1. نجرب السيرفر الخاص لو موجود (INVIDIOUS_INSTANCE env)
    2. نجرب كل سيرفر عام بالترتيب
    3. نرجع أول نتيجة ناجحة
    
    Args:
        url: رابط YouTube
        quality: الجودة المطلوبة ("best", "medium", "low", "audio")
    
    Returns:
        نفس الـ dictionary من _get_download_url_from_invidious
        أو None لو كل السيرفرات فشلت
    """
    # التحقق من الرابط
    if not is_youtube_url(url):
        return {"success": False, "error": "not_youtube", "message": "Not a YouTube URL"}
    
    # استخراج معرف الفيديو
    video_id = extract_video_id(url)
    if not video_id:
        return {"success": False, "error": "invalid_url", "message": "Invalid YouTube URL"}
    
    instances = _get_instances()
    max_retries = min(INVIVIOUS_MAX_RETRIES, len(instances))
    
    logger.info(f"🟣 Invidious: Starting download for {video_id} quality={quality} (trying {max_retries} instances)")
    
    last_error = None
    
    for i, instance in enumerate(instances[:max_retries]):
        result = _get_download_url_from_invidious(instance, video_id, quality)
        
        if result and result.get("success"):
            logger.info(f"🟣 Invidious: Successfully got download URL from {instance}")
            return result
        
        if result:
            last_error = result.get("error", "unknown")
        
        # لو السيرفر rate-limitedنا أو مش متاح — نكمل للسيرفر اللي بعده
        if i < max_retries - 1:
            logger.info(f"🟣 Invidious: Instance {instance} failed, trying next...")
    
    logger.warning(f"🟣 Invidious: All {max_retries} instances failed for {video_id}")
    return {
        "success": False,
        "error": last_error or "all_instances_failed",
        "message": f"All {max_retries} Invidious instances failed",
    }


async def download_youtube_invidious_async(url: str, quality: str = "best") -> Optional[Dict]:
    """نسخة async من download_youtube_invidious — بتشغل الدالة العادية في thread منفصل
    
    عشان متعطلش الـ event loop في التليجرام/الواتساب
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: download_youtube_invidious(url, quality)
    )
    return result


async def download_youtube_invidious_file(url: str, quality: str = "best", output_dir: str = "/tmp") -> Optional[Dict]:
    """تحميل فيديو YouTube وحفظه كملف محلي عبر Invidious
    
    🔴 الميزة: بنحمّل الملف من رابط الـ proxy بتاع Invidious
    الـ proxy بيحمّل الفيديو من YouTube ويرسلوله — يعني:
    - الـ IP بتاعنا مش بيظهر لليوتيوب
    - مفيش bot detection
    - لكن السيرفر بيأكل bandwidth
    
    Returns:
        Dictionary فيه:
        - success: True/False
        - title: عنوان الفيديو
        - duration: المدة
        - thumbnail: رابط الصورة المصغرة
        - file_path: مسار الملف المحلي
        - file_size: حجم الملف بالبايت
        - video_id: معرف الفيديو
        - method: "invidious"
    """
    import aiohttp
    
    # الحصول على رابط التحميل
    result = await download_youtube_invidious_async(url, quality)
    
    if not result or not result.get("success"):
        return result
    
    download_url = result.get("download_url")
    if not download_url:
        result["success"] = False
        result["error"] = "no_download_url"
        result["message"] = "No download URL available"
        return result
    
    video_id = result.get("video_id", "video")
    is_audio = quality == "audio"
    ext = "mp3" if is_audio else "mp4"
    file_path = os.path.join(output_dir, f"invidious_{video_id}_{quality}.{ext}")
    
    logger.info(f"🟣 Invidious: Downloading file to {file_path}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=INVIVIOUS_DOWNLOAD_TIMEOUT),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": result.get("instance", "") + "/",
                }
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"🟣 Invidious: Download failed with status {resp.status}")
                    result["success"] = False
                    result["error"] = "download_failed"
                    result["message"] = f"Download failed: HTTP {resp.status}"
                    return result
                
                file_size = 0
                with open(file_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
                        file_size += len(chunk)
                
                if file_size == 0:
                    logger.warning(f"🟣 Invidious: Downloaded file is empty")
                    try:
                        os.remove(file_path)
                    except:
                        pass
                    result["success"] = False
                    result["error"] = "empty_file"
                    result["message"] = "Downloaded file is empty"
                    return result
                
                result["file_path"] = file_path
                result["file_size"] = file_size
                
                logger.info(f"🟣 Invidious: Download succeeded! Size: {file_size // (1024*1024)}MB")
                
                return result
    
    except asyncio.TimeoutError:
        logger.warning(f"🟣 Invidious: Download timed out")
        result["success"] = False
        result["error"] = "download_timeout"
        result["message"] = "Download timed out"
        return result
    except Exception as e:
        logger.warning(f"🟣 Invidious: Download error: {e}")
        result["success"] = False
        result["error"] = "download_error"
        result["message"] = str(e)
        return result


def get_youtube_info_invidious(url: str) -> Optional[Dict]:
    """استخراج معلومات الفيديو من YouTube عبر Invidious بدون تحميل
    
    بيستخدم Invidious API عشان يجيب عنوان ومدة الفيديو
    أسرع من yt-dlp لأنه بيجيب JSON بس
    """
    if not is_youtube_url(url):
        return None
    
    video_id = extract_video_id(url)
    if not video_id:
        return None
    
    instances = _get_instances()
    
    for instance in instances[:2]:  # نجرب سيرفرين بس
        result = _get_download_url_from_invidious(instance, video_id, "low")
        if result and result.get("success"):
            return {
                "title": result.get("title", ""),
                "video_id": video_id,
                "thumbnail": result.get("thumbnail", ""),
                "duration": result.get("duration", 0),
                "url": url,
            }
    
    return None


# ═══════════════════════════════════════
# فحص صحة السيرفرات
# ═══════════════════════════════════════

def check_invidious_health() -> Dict:
    """فحص حالة سيرفرات Invidious — للأدمن"""
    import requests
    
    results = {
        "total_instances": len(_get_instances()),
        "custom_instance": CUSTOM_INVIDIOUS_INSTANCE or "not set",
        "instances_status": [],
    }
    
    for instance in _get_instances():
        try:
            resp = requests.get(
                f"{instance}/api/v1/stats",
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                stats = resp.json()
                results["instances_status"].append({
                    "instance": instance,
                    "status": "ok",
                    "software": stats.get("software", "unknown"),
                    "version": stats.get("version", "unknown"),
                })
            else:
                results["instances_status"].append({
                    "instance": instance,
                    "status": f"error ({resp.status_code})",
                })
        except Exception as e:
            results["instances_status"].append({
                "instance": instance,
                "status": f"error ({type(e).__name__})",
            })
    
    healthy = sum(1 for s in results["instances_status"] if s.get("status") == "ok")
    results["healthy_count"] = healthy
    
    return results
