"""
YouTube RapidAPI Downloader Module
تحميل فيديوهات YouTube عبر RapidAPI بدل yt-dlp
يُستخدم من التليجرام والواتساب معاً

الميزات:
- تحميل فيديو بجودات مختلفة (360p, 720p, 1080p)
- تحميل صوت MP3
- استخراج معلومات الفيديو (عنوان، مدة، صورة مصغرة)
- معالجة كاملة للأخطاء
- يوتيوب فقط — باقي المنصات بتستخدم yt-dlp زي ما هي
"""

import logging
import re
import time
import asyncio
from typing import Dict, Optional, List
import os

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات RapidAPI
# ═══════════════════════════════════════

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "954c145890msh6247d4f60dc5f4ap110a87jsnc70ba761c0de")
RAPIDAPI_HOST = "youtube-mp41.p.rapidapi.com"
RAPIDAPI_BASE_URL = f"https://{RAPIDAPI_HOST}"

# الجودات المتاحة
AVAILABLE_FORMATS = {
    "mp3": "🎵 صوت MP3",
    "360": "📹 360p",
    "480": "📹 480p",
    "720": "📹 720p HD",
    "1080": "📹 1080p Full HD",
    "1440": "📹 1440p 2K",
    "4k": "📹 4K Ultra HD",
}

# الجودة الافتراضية
DEFAULT_VIDEO_FORMAT = "720"
DEFAULT_AUDIO_FORMAT = "mp3"

# إعدادات Polling
POLL_INTERVAL = 3        # ثواني بين كل فحص
POLL_MAX_ATTEMPTS = 40   # أقصى عدد محاولات (40 × 3 = 120 ثانية)


# ═══════════════════════════════════════
# التحقق من روابط YouTube
# ═══════════════════════════════════════

# أنماط روابط YouTube
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
# الدالة الرئيسية: download_youtube()
# ═══════════════════════════════════════

def download_youtube(url: str, format: str = "720") -> Optional[Dict]:
    """تحميل فيديو YouTube عبر RapidAPI
    
    Args:
        url: رابط YouTube (youtube.com أو youtu.be)
        format: الجودة المطلوبة:
            - "mp3": صوت فقط
            - "360": فيديو 360p
            - "480": فيديو 480p
            - "720": فيديو 720p HD (افتراضي)
            - "1080": فيديو 1080p Full HD
            - "1440": فيديو 1440p 2K
            - "4k": فيديو 4K Ultra HD
    
    Returns:
        Dictionary فيه:
        - success: True/False
        - title: عنوان الفيديو
        - duration: المدة
        - thumbnail: رابط الصورة المصغرة
        - download_url: رابط التحميل المباشر
        - format: الجودة المطلوبة
        - video_id: معرف الفيديو
        - error: رسالة الخطأ (لو success = False)
        
        أو None لو فشل بشكل كامل
    """
    # التحقق من الرابط
    if not is_youtube_url(url):
        return {
            "success": False,
            "error": "not_youtube",
            "message": "هذا الرابط ليس رابط يوتيوب. من فضلك استخدم yt-dlp للمنصات الأخرى.",
        }
    
    # استخراج معرف الفيديو
    video_id = extract_video_id(url)
    if not video_id:
        return {
            "success": False,
            "error": "invalid_url",
            "message": "رابط يوتيوب مش صالح. تأكد إن الرابط صحيح.",
        }
    
    # التحقق من الجودة
    if format not in AVAILABLE_FORMATS:
        format = DEFAULT_VIDEO_FORMAT
    
    try:
        import requests
        
        headers = {
            "x-rapidapi-host": RAPIDAPI_HOST,
            "x-rapidapi-key": RAPIDAPI_KEY,
            "Content-Type": "application/json",
        }
        
        # ═══ الخطوة 1: بدء التحميل ═══
        logger.info(f"🎬 YouTube RapidAPI: Initiating download for {video_id} format={format}")
        
        init_response = requests.get(
            f"{RAPIDAPI_BASE_URL}/api/v1/download",
            headers=headers,
            params={"id": video_id, "format": format},
            timeout=30,
        )
        
        # معالجة أخطاء HTTP
        if init_response.status_code == 401:
            return {
                "success": False,
                "error": "unauthorized",
                "message": "مفتاح API مش صالح. تواصل مع الدعم.",
            }
        elif init_response.status_code == 403:
            return {
                "success": False,
                "error": "forbidden",
                "message": "مش مصرح لك. ممكن الاشتراك خلص أو مش متاح.",
            }
        elif init_response.status_code == 429:
            return {
                "success": False,
                "error": "rate_limited",
                "message": "خلصت حدود الباقة. جرب تاني بعد شوية.",
            }
        elif init_response.status_code >= 500:
            return {
                "success": False,
                "error": "server_error",
                "message": "الخدمة مش متاحة حالياً. جرب تاني بعد شوية.",
            }
        elif init_response.status_code != 200:
            return {
                "success": False,
                "error": "http_error",
                "message": f"خطأ من الخدمة ({init_response.status_code}). جرب تاني.",
            }
        
        init_data = init_response.json()
        
        # استخراج progressId
        progress_id = init_data.get("progressId") or init_data.get("id") or init_data.get("jobId")
        title = init_data.get("title", "")
        
        if not progress_id:
            # ممكن الـ API رجع النتيجة مباشرة
            download_url = init_data.get("downloadUrl") or init_data.get("download_url") or init_data.get("url")
            if download_url:
                return {
                    "success": True,
                    "title": title or "فيديو YouTube",
                    "duration": init_data.get("duration", ""),
                    "thumbnail": init_data.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"),
                    "download_url": download_url,
                    "format": format,
                    "video_id": video_id,
                }
            
            logger.error(f"YouTube RapidAPI: No progressId in response: {init_data}")
            return {
                "success": False,
                "error": "no_progress_id",
                "message": "الخدمة رجعت رد مش متوقع. جرب تاني.",
            }
        
        logger.info(f"🎬 YouTube RapidAPI: Got progressId={progress_id}, title={title}")
        
        # ═══ الخطوة 2: انتظار التحميل (Polling) ═══
        for attempt in range(POLL_MAX_ATTEMPTS):
            time.sleep(POLL_INTERVAL)
            
            progress_response = requests.get(
                f"{RAPIDAPI_BASE_URL}/api/v1/progress",
                headers=headers,
                params={"id": progress_id},
                timeout=30,
            )
            
            if progress_response.status_code != 200:
                logger.warning(f"YouTube RapidAPI: Progress check returned {progress_response.status_code}")
                continue
            
            progress_data = progress_response.json()
            
            # فحص هل التحميل خلص
            finished = progress_data.get("finished", False)
            download_url = progress_data.get("downloadUrl") or progress_data.get("download_url") or progress_data.get("url")
            
            if finished and download_url:
                logger.info(f"✅ YouTube RapidAPI: Download ready for {video_id}")
                
                return {
                    "success": True,
                    "title": title or progress_data.get("title", "فيديو YouTube"),
                    "duration": progress_data.get("duration", ""),
                    "thumbnail": progress_data.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"),
                    "download_url": download_url,
                    "format": format,
                    "video_id": video_id,
                }
            
            # فحص هل في خطأ
            error_msg = progress_data.get("error") or progress_data.get("message")
            if error_msg and "something went wrong" in str(error_msg).lower():
                # ممكن الفيديو محذوف أو خاص
                logger.warning(f"YouTube RapidAPI: Error in progress: {error_msg}")
                continue
            
            # log التقدم
            progress_pct = progress_data.get("progress", 0)
            if attempt % 5 == 0:
                logger.info(f"🎬 YouTube RapidAPI: Progress {progress_pct}% for {video_id}")
        
        # لو وصلنا هنا يعني التحميل أخد وقت طويل أوي
        logger.error(f"YouTube RapidAPI: Timeout waiting for {video_id}")
        return {
            "success": False,
            "error": "timeout",
            "message": "التحميل أخد وقت طويل أوي. جرب تاني.",
        }
        
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "timeout",
            "message": "الخدمة استجابتها بطيئة. جرب تاني.",
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": "connection_error",
            "message": "مش قادر أوصل بالخدمة. جرب تاني.",
        }
    except Exception as e:
        logger.error(f"YouTube RapidAPI error: {e}", exc_info=True)
        return {
            "success": False,
            "error": "unknown",
            "message": f"حصل خطأ غير متوقع. جرب تاني.",
        }


# ═══════════════════════════════════════
# نسخة Async من الدالة الرئيسية
# ═══════════════════════════════════════

async def download_youtube_async(url: str, format: str = "720") -> Optional[Dict]:
    """نسخة async من download_youtube — بتشغل الدالة العادية في thread منفصل
    
    عشان متعطلش الـ event loop في التليجرام/الواتساب
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: download_youtube(url, format)
    )
    return result


# ═══════════════════════════════════════
# تحميل الفيديو كملف محلي
# ═══════════════════════════════════════

def download_youtube_file(url: str, format: str = "720", output_dir: str = "/tmp") -> Optional[Dict]:
    """تحميل فيديو YouTube وحفظه كملف محلي
    
    Returns:
        نفس الـ dictionary من download_youtube +:
        - file_path: مسار الملف المحلي
        - file_size: حجم الملف بالبايت
    """
    result = download_youtube(url, format)
    
    if not result or not result.get("success"):
        return result
    
    download_url = result.get("download_url")
    if not download_url:
        return result
    
    try:
        import requests
        
        video_id = result.get("video_id", "video")
        
        # تحديد الامتداد
        if format == "mp3":
            ext = "mp3"
        else:
            ext = "mp4"
        
        file_path = os.path.join(output_dir, f"yt_{video_id}_{format}.{ext}")
        
        logger.info(f"📥 Downloading file from RapidAPI to {file_path}")
        
        response = requests.get(download_url, stream=True, timeout=120)
        
        if response.status_code != 200:
            logger.error(f"Failed to download file: HTTP {response.status_code}")
            result["success"] = False
            result["error"] = "download_failed"
            result["message"] = "فشل تحميل الملف من الخدمة."
            return result
        
        file_size = 0
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    file_size += len(chunk)
        
        result["file_path"] = file_path
        result["file_size"] = file_size
        
        logger.info(f"✅ File downloaded: {file_path} ({file_size} bytes)")
        
        return result
        
    except Exception as e:
        logger.error(f"File download error: {e}", exc_info=True)
        result["success"] = False
        result["error"] = "file_download_error"
        result["message"] = "فشل حفظ الملف محلياً."
        return result


async def download_youtube_file_async(url: str, format: str = "720", output_dir: str = "/tmp") -> Optional[Dict]:
    """نسخة async من download_youtube_file"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: download_youtube_file(url, format, output_dir)
    )
    return result


# ═══════════════════════════════════════
# استخراج معلومات الفيديو فقط (بدون تحميل)
# ═══════════════════════════════════════

def get_youtube_info(url: str) -> Optional[Dict]:
    """استخراج معلومات الفيديو من YouTube بدون تحميل
    
    بيستخدم RapidAPI عشان يجيب عنوان ومدة الفيديو
    """
    if not is_youtube_url(url):
        return None
    
    video_id = extract_video_id(url)
    if not video_id:
        return None
    
    try:
        import requests
        
        headers = {
            "x-rapidapi-host": RAPIDAPI_HOST,
            "x-rapidapi-key": RAPIDAPI_KEY,
            "Content-Type": "application/json",
        }
        
        # نبدأ تحميل بالجودة الأقل عشان نستخرج المعلومات بس
        response = requests.get(
            f"{RAPIDAPI_BASE_URL}/api/v1/download",
            headers=headers,
            params={"id": video_id, "format": "360"},
            timeout=30,
        )
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        return {
            "title": data.get("title", ""),
            "video_id": video_id,
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
            "url": url,
        }
        
    except Exception as e:
        logger.error(f"Get YouTube info error: {e}")
        return None


# ═══════════════════════════════════════
# رسائل الخطأ حسب اللغة
# ═══════════════════════════════════════

def get_error_message(error_code: str, lang: str = "ar") -> str:
    """رسائل الخطأ حسب نوع الخطأ واللغة"""
    messages = {
        "ar": {
            "not_youtube": "❌ هذا الرابط ليس رابط يوتيوب. من فضلك استخدم /download للمنصات الأخرى.",
            "invalid_url": "❌ رابط يوتيوب مش صالح. تأكد إن الرابط صحيح.",
            "unauthorized": "❌ مفتاح API مش صالح. تواصل مع الدعم @ziadamr",
            "forbidden": "❌ مش مصرح لك. ممكن الاشتراك خلص.",
            "rate_limited": "❌ خلصت حدود التحميل لهذا الشهر. جرب الشهر الجاي.",
            "server_error": "❌ الخدمة مش متاحة حالياً. جرب تاني بعد شوية.",
            "timeout": "❌ التحميل أخد وقت طويل أوي. جرب تاني.",
            "connection_error": "❌ مش قادر أوصل بالخدمة. جرب تاني.",
            "download_failed": "❌ فشل تحميل الملف. جرب تاني.",
            "no_progress_id": "❌ الخدمة رجعت رد مش متوقع. جرب تاني.",
            "unknown": "❌ حصل خطأ غير متوقع. جرب تاني.",
            "video_private": "❌ الفيديو خاص أو محذوف. جرب فيديو تاني.",
            "file_too_large": "❌ الملف كبير أوي عشان نبعتو. جرب جودة أقل.",
        },
        "en": {
            "not_youtube": "❌ This is not a YouTube link. Use /download for other platforms.",
            "invalid_url": "❌ Invalid YouTube URL. Make sure the link is correct.",
            "unauthorized": "❌ Invalid API key. Contact support @ziadamr",
            "forbidden": "❌ Access denied. Subscription may have expired.",
            "rate_limited": "❌ Monthly download limit reached. Try next month.",
            "server_error": "❌ Service unavailable. Try again later.",
            "timeout": "❌ Download took too long. Try again.",
            "connection_error": "❌ Cannot connect to service. Try again.",
            "download_failed": "❌ Failed to download file. Try again.",
            "no_progress_id": "❌ Unexpected response from service. Try again.",
            "unknown": "❌ Unexpected error. Try again.",
            "video_private": "❌ Video is private or deleted. Try another video.",
            "file_too_large": "❌ File too large to send. Try a lower quality.",
        },
    }
    
    lang_messages = messages.get(lang, messages["ar"])
    return lang_messages.get(error_code, lang_messages.get("unknown", "❌ Error. Try again."))
