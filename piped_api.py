"""
Piped API Downloader Module
تحميل فيديوهات YouTube عبر Piped API بدل yt-dlp
يُستخدم كـ fallback بعد yt-dlp و Invidious

الميزات:
- تحميل فيديو بجودات مختلفة (360p, 720p, 1080p)
- تحميل صوت MP3
- استخراج معلومات الفيديو (عنوان، مدة، صورة مصغرة)
- Fallback تلقائي بين أكتر من سيرفر Piped
- مش بيتأثر بـ YouTube bot detection خالص
- مجاني ومفتوح — مفيش API keys ولا اشتراكات

🔴 كيف شغال Piped:
- Piped هو واجهة بديلة لليوتيوب (front-end) مفتوحة المصدر
- السيرفرات البيبلبليك بتوفر API مجاني
- الـ API بيرجع روابط تحميل مباشرة بدون yt-dlp
- الطلبات بتروح لسيرفرات Piped مش من الـ IP بتاعك
- Piped مختلف عن Invidious — بيستخدم NewPipe Extractor
- أحياناً بيشتغل لما Invidious يبقى منطفي

🔴 الفرق بين Piped و Invidious:
- Invidious: مشغل فيديو + API — سيرفرات كتير بس بتقع كتير
- Piped: مشغل فيديو + API — سيرفرات أقل بس مستقرة أكتر
- Piped بيرجع الـ streams بشكل مختلف (videoStreams + audioStreams)
- Piped بيفضل يرجع proxy URL مش direct URL — ده أفضل عشان الـ IP مش يبان
"""

import logging
import re
import os
import asyncio
import subprocess
from typing import Dict, Optional, List
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# قائمة سيرفرات Piped العامة
# ═══════════════════════════════════════

# 🔴 سيرفرات Piped البيبلبليك — بنجربهم بالترتيب
# بعض السيرفرات بتنزل كتير، عشان كده لازم fallback
# القائمة دي بتتحدث بشكل دوري من: https://piped-instances.kavin.rocks/
# بنختار السيرفرات اللي:
# 1. بتدعم API
# 2. مستقرة نسبياً
# 3. مش بطيئة

PIPED_INSTANCES = [
    "https://api.piped.private.coffee",    # ✅ شغال (أكتر واحد مستقر)
    "https://pipedapi.kavin.rocks",         # ⚠️ أحياناً يشتغل (الرسمي)
    "https://pipedapi.adminforge.de",        # ⚠️ أحياناً يشتغل
    "https://pipedapi.r4fo.com",             # ⚠️ أحياناً يشتغل
    "https://api.piped.projectsegfau.lt",    # ⚠️ أحياناً يشتغل
    "https://pipedapi.in.projectsegfau.lt",  # ⚠️ أحياناً يشتغل
    "https://pipedapi.moomoo.me",            # ⚠️ أحياناً يشتغل
    "https://pipedapi.leptons.xyz",          # ⚠️ أحياناً يشتغل
]

# 🔴 يمكن تحديد سيرفر Piped خاص من البيئة
CUSTOM_PIPED_INSTANCE = os.environ.get("PIPED_INSTANCE", "")

# إعدادات الـ timeout والـ retries
PIPED_API_TIMEOUT = 15        # ثانية لكل طلب API
PIPED_DOWNLOAD_TIMEOUT = 300  # 5 دقائق لتحميل الملف
PIPED_MAX_RETRIES = 3         # أقصى عدد سيرفرات نجربها


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
# دوال Piped API
# ═══════════════════════════════════════

def _get_instances() -> List[str]:
    """الحصول على قائمة سيرفرات Piped — السيرفر الخاص الأول لو موجود"""
    instances = []
    if CUSTOM_PIPED_INSTANCE:
        instances.append(CUSTOM_PIPED_INSTANCE.rstrip("/"))
    instances.extend(PIPED_INSTANCES)
    return instances


def _select_best_stream(streams: list, quality: str = "best", is_audio: bool = False) -> Optional[dict]:
    """اختيار أفضل stream من قائمة الـ streams المتاحة
    
    Piped بيرجع نوعين من الـ streams:
    - videoStreams: فيديو (مع أو بدون صوت) — فيه quality, videoQuality, mimeType
    - audioStreams: صوت بس — فيه bitrate, mimeType
    
    🔴 الأولوية للفيديو:
    1. Pre-merged (فيديو+صوت) h264/mp4 (أفضل للتليجرام — مش محتاج دمج)
    2. Pre-merged أي mp4
    3. Video only h264 + audio (لو ffmpeg متاح)
    4. أي stream متاح
    """
    if not streams:
        return None
    
    if is_audio:
        # صوت بس — بنبحث عن audio stream
        # بنفضل m4a أو mp3
        for s in streams:
            mime = s.get("mimeType", "")
            if "mp4a" in mime or "mp3" in mime or "m4a" in mime:
                return s
        # أي صوت — بنختار أعلى bitrate
        if streams:
            streams_sorted = sorted(streams, key=lambda s: s.get("bitrate", 0), reverse=True)
            return streams_sorted[0]
        return None
    
    # ═══ فيديو ═══
    quality_heights = {
        "best": 1080,
        "medium": 720,
        "low": 480,
    }
    max_height = quality_heights.get(quality, 1080)
    
    # بنحاول نلاقي pre-merged (فيديو+صوت مع بعض)
    # Piped بيرجع "videoOnly: false" لو فيه صوت مدمج
    pre_merged = [s for s in streams if not s.get("videoOnly", True)]
    video_only = [s for s in streams if s.get("videoOnly", False)]
    
    # 🔴 الأولوية 1: Pre-merged h264/mp4
    if pre_merged:
        h264_pre = [s for s in pre_merged 
                    if "avc1" in s.get("mimeType", "").lower() 
                    or "mp4" in s.get("mimeType", "").lower()]
        
        target = h264_pre if h264_pre else pre_merged
        
        # فلترة حسب الجودة
        def _get_height(s):
            q = s.get("quality", "") or s.get("videoQuality", "")
            if isinstance(q, int):
                return q
            try:
                return int(str(q).replace("p", ""))
            except:
                return 0
        
        within_quality = [s for s in target if _get_height(s) <= max_height]
        
        if within_quality:
            within_quality.sort(key=_get_height, reverse=True)
            return within_quality[0]
        
        # مفيش جودة مناسبة — نختار أعلى واحدة
        target.sort(key=_get_height, reverse=True)
        return target[0]
    
    # 🔴 الأولوية 2: Video only (محتاج دمج مع audio)
    if video_only:
        h264_only = [s for s in video_only 
                     if "avc1" in s.get("mimeType", "").lower() 
                     or "mp4" in s.get("mimeType", "").lower()]
        
        target = h264_only if h264_only else video_only
        
        def _get_height(s):
            q = s.get("quality", "") or s.get("videoQuality", "")
            if isinstance(q, int):
                return q
            try:
                return int(str(q).replace("p", ""))
            except:
                return 0
        
        within_quality = [s for s in target if _get_height(s) <= max_height]
        
        if within_quality:
            within_quality.sort(key=_get_height, reverse=True)
            return within_quality[0]
        
        target.sort(key=_get_height, reverse=True)
        return target[0]
    
    return None


def _get_download_from_piped(instance_url: str, video_id: str, quality: str = "best") -> Optional[Dict]:
    """الحصول على رابط تحميل مباشر من Piped API (sync version)
    
    🔴 Piped API Structure:
    GET /streams/{video_id}
    
    Response:
    {
        "title": "...",
        "duration": 123,
        "thumbnailUrl": "...",
        "videoStreams": [...],
        "audioStreams": [...],
        ...
    }
    
    كل stream فيه:
    - url: رابط التحميل (proxy URL)
    - mimeType: "video/mp4" أو "video/webm" أو "audio/mp4a-latm" إلخ
    - quality: "720p" أو رقم
    - videoQuality: نفس quality بس أوضح
    - bitrate: bitrate بالبت/ثانية
    - videoOnly: true لو فيديو بس (محتاج دمج مع audio)
    """
    import requests
    
    is_audio = quality == "audio"
    api_url = f"{instance_url}/streams/{video_id}"
    
    try:
        logger.info(f"🟢 Piped [{instance_url}]: Fetching video info for {video_id}")
        
        response = requests.get(
            api_url,
            timeout=PIPED_API_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )
        
        if response.status_code == 429:
            logger.warning(f"🟢 Piped [{instance_url}]: Rate limited (429)")
            return {"success": False, "error": "rate_limited", "message": "Rate limited on this instance"}
        
        if response.status_code == 404:
            logger.warning(f"🟢 Piped [{instance_url}]: Video not found (404)")
            return {"success": False, "error": "not_found", "message": "Video not found"}
        
        if response.status_code != 200:
            logger.warning(f"🟢 Piped [{instance_url}]: API returned status {response.status_code}")
            return {"success": False, "error": "http_error", "message": f"HTTP {response.status_code}"}
        
        data = response.json()
        
        title = data.get("title", "YouTube Video")
        duration = data.get("duration", 0)
        thumbnail = data.get("thumbnailUrl", "")
        
        # 🔴 استخراج الـ streams
        video_streams = data.get("videoStreams", [])
        audio_streams = data.get("audioStreams", [])
        
        if not video_streams and not audio_streams:
            logger.warning(f"🟢 Piped [{instance_url}]: No streams available for {video_id}")
            return {"success": False, "error": "no_streams", "message": "No streams available"}
        
        # اختيار أفضل stream
        if is_audio:
            selected = _select_best_stream(audio_streams, quality, is_audio=True)
        else:
            selected = _select_best_stream(video_streams, quality, is_audio=False)
            # لو الـ stream video only — هنحتاج ندمجه مع audio
            audio_for_merge = None
            if selected and selected.get("videoOnly", False):
                audio_for_merge = _select_best_stream(audio_streams, quality, is_audio=True)
        
        if not selected:
            logger.warning(f"🟢 Piped [{instance_url}]: No suitable stream found for quality={quality}")
            return {"success": False, "error": "no_suitable_stream", "message": f"No suitable stream for quality={quality}"}
        
        download_url = selected.get("url", "")
        
        if not download_url:
            logger.warning(f"🟢 Piped [{instance_url}]: Stream has no download URL")
            return {"success": False, "error": "no_url", "message": "Stream has no download URL"}
        
        # معلومات التنسيق
        mime = selected.get("mimeType", "")
        q_label = selected.get("quality", "") or selected.get("videoQuality", "")
        is_video_only = selected.get("videoOnly", False)
        is_pre_merged = not is_video_only
        
        format_info = {
            "quality_label": str(q_label),
            "mimeType": mime,
            "bitrate": selected.get("bitrate", 0),
            "is_pre_merged": is_pre_merged,
            "is_video_only": is_video_only,
            "container": "mp4" if "mp4" in mime.lower() else "webm" if "webm" in mime.lower() else "unknown",
        }
        
        logger.info(
            f"🟢 Piped [{instance_url}]: Found stream "
            f"{q_label} ({mime}) "
            f"{'[pre-merged]' if is_pre_merged else '[video-only, needs merge]'}"
        )
        
        result = {
            "success": True,
            "title": title,
            "duration": duration,
            "thumbnail": thumbnail,
            "download_url": download_url,
            "format_info": format_info,
            "video_id": video_id,
            "instance": instance_url,
            "method": "piped",
        }
        
        # لو video only — نضيف رابط الصوت عشان ندمجهم
        if is_video_only and not is_audio:
            if audio_for_merge:
                result["audio_url"] = audio_for_merge.get("url", "")
                result["needs_merge"] = True
                logger.info(f"🟢 Piped: Video-only stream, audio URL added for merge")
            else:
                logger.warning(f"🟢 Piped: Video-only stream but no audio available for merge")
                result["needs_merge"] = False
        
        return result
    
    except requests.exceptions.Timeout:
        logger.warning(f"🟢 Piped [{instance_url}]: Request timed out")
        return {"success": False, "error": "timeout", "message": "Request timed out"}
    except requests.exceptions.ConnectionError:
        logger.warning(f"🟢 Piped [{instance_url}]: Connection error")
        return {"success": False, "error": "connection_error", "message": "Connection error"}
    except Exception as e:
        logger.warning(f"🟢 Piped [{instance_url}]: Error: {e}")
        return {"success": False, "error": "unknown", "message": str(e)}


def download_youtube_piped(url: str, quality: str = "best") -> Optional[Dict]:
    """تحميل معلومات فيديو YouTube عبر Piped API مع fallback بين السيرفرات
    
    🔴 الاستراتيجية:
    1. نجرب السيرفر الخاص لو موجود (PIPED_INSTANCE env)
    2. نجرب كل سيرفر عام بالترتيب
    3. نرجع أول نتيجة ناجحة
    
    Args:
        url: رابط YouTube
        quality: الجودة المطلوبة ("best", "medium", "low", "audio")
    
    Returns:
        نفس الـ dictionary من _get_download_from_piped
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
    max_retries = min(PIPED_MAX_RETRIES, len(instances))
    
    logger.info(f"🟢 Piped: Starting for {video_id} quality={quality} (trying {max_retries} instances)")
    
    last_error = None
    
    for i, instance in enumerate(instances[:max_retries]):
        result = _get_download_from_piped(instance, video_id, quality)
        
        if result and result.get("success"):
            logger.info(f"🟢 Piped: Successfully got download URL from {instance}")
            return result
        
        if result:
            last_error = result.get("error", "unknown")
        
        if i < max_retries - 1:
            logger.info(f"🟢 Piped: Instance {instance} failed, trying next...")
    
    logger.warning(f"🟢 Piped: All {max_retries} instances failed for {video_id}")
    return {
        "success": False,
        "error": last_error or "all_instances_failed",
        "message": f"All {max_retries} Piped instances failed",
    }


async def download_youtube_piped_async(url: str, quality: str = "best") -> Optional[Dict]:
    """نسخة async من download_youtube_piped — بتشغل الدالة العادية في thread منفصل"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: download_youtube_piped(url, quality)
    )
    return result


def _merge_video_audio(video_path: str, audio_path: str, output_path: str) -> bool:
    """دمج فيديو وصوت باستخدام ffmpeg
    
    Piped أحياناً بيرجع فيديو لوحده وصوت لوحده
    لازم ندمجهم بـ ffmpeg عشان نحصل على ملف شامل
    """
    try:
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-movflags', '+faststart',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode == 0 and os.path.exists(output_path):
            return True
        else:
            logger.warning(f"🟢 Piped: ffmpeg merge failed: {result.stderr.decode()[:200]}")
            return False
    except Exception as e:
        logger.warning(f"🟢 Piped: ffmpeg merge error: {e}")
        return False


async def download_youtube_piped_file(url: str, quality: str = "best", output_dir: str = "/tmp") -> Optional[Dict]:
    """تحميل فيديو YouTube وحفظه كملف محلي عبر Piped
    
    🔴 الميزة: بنحمّل الملف من رابط الـ proxy بتاع Piped
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
        - method: "piped"
        - format_info: معلومات التنسيق
    """
    import aiohttp
    
    # الحصول على رابط التحميل
    result = await download_youtube_piped_async(url, quality)
    
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
    needs_merge = result.get("needs_merge", False)
    audio_url = result.get("audio_url", "")
    
    ext = "mp3" if is_audio else "mp4"
    file_path = os.path.join(output_dir, f"piped_{video_id}_{quality}.{ext}")
    
    logger.info(f"🟢 Piped: Downloading file to {file_path}")
    
    try:
        async with aiohttp.ClientSession() as session:
            # 🔴 تحميل الفيديو
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=PIPED_DOWNLOAD_TIMEOUT),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": result.get("instance", "") + "/",
                }
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"🟢 Piped: Download failed with status {resp.status}")
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
                    logger.warning(f"🟢 Piped: Downloaded file is empty")
                    try:
                        os.remove(file_path)
                    except:
                        pass
                    result["success"] = False
                    result["error"] = "empty_file"
                    result["message"] = "Downloaded file is empty"
                    return result
            
            # 🔴 لو محتاج دمج (video only + audio)
            if needs_merge and audio_url:
                logger.info(f"🟢 Piped: Video-only stream, downloading audio for merge...")
                
                audio_path = os.path.join(output_dir, f"piped_{video_id}_audio.m4a")
                merged_path = os.path.join(output_dir, f"piped_{video_id}_{quality}_merged.mp4")
                
                try:
                    async with session.get(
                        audio_url,
                        timeout=aiohttp.ClientTimeout(total=PIPED_DOWNLOAD_TIMEOUT),
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Referer": result.get("instance", "") + "/",
                        }
                    ) as audio_resp:
                        if audio_resp.status == 200:
                            audio_size = 0
                            with open(audio_path, 'wb') as af:
                                async for chunk in audio_resp.content.iter_chunked(8192):
                                    af.write(chunk)
                                    audio_size += len(chunk)
                            
                            if audio_size > 0:
                                # دمج بـ ffmpeg
                                logger.info(f"🟢 Piped: Merging video + audio with ffmpeg...")
                                loop = asyncio.get_event_loop()
                                merge_ok = await loop.run_in_executor(
                                    None,
                                    lambda: _merge_video_audio(file_path, audio_path, merged_path)
                                )
                                
                                if merge_ok:
                                    # حذف الملفات المؤقتة واستخدام المدمج
                                    try:
                                        os.remove(file_path)
                                        os.remove(audio_path)
                                    except:
                                        pass
                                    file_path = merged_path
                                    file_size = os.path.getsize(merged_path)
                                    logger.info(f"🟢 Piped: Merge succeeded! Size: {file_size // (1024*1024)}MB")
                                else:
                                    # فشل الدمج — نستخدم الفيديو لوحده
                                    logger.warning(f"🟢 Piped: Merge failed, using video-only file")
                                    try:
                                        os.remove(audio_path)
                                    except:
                                        pass
                                    result["format_info"]["is_pre_merged"] = False
                                    result["format_info"]["note"] = "Video only (no audio) - merge failed"
                            else:
                                logger.warning(f"🟢 Piped: Audio download was empty")
                                try:
                                    os.remove(audio_path)
                                except:
                                    pass
                        else:
                            logger.warning(f"🟢 Piped: Audio download failed with status {audio_resp.status}")
                except Exception as merge_err:
                    logger.warning(f"🟢 Piped: Audio download/merge error: {merge_err}")
            
            result["file_path"] = file_path
            result["file_size"] = file_size
            
            logger.info(f"🟢 Piped: Download succeeded! Size: {file_size // (1024*1024)}MB")
            
            return result
    
    except asyncio.TimeoutError:
        logger.warning(f"🟢 Piped: Download timed out")
        result["success"] = False
        result["error"] = "download_timeout"
        result["message"] = "Download timed out"
        return result
    except Exception as e:
        logger.warning(f"🟢 Piped: Download error: {e}")
        result["success"] = False
        result["error"] = "download_error"
        result["message"] = str(e)
        return result


def get_youtube_info_piped(url: str) -> Optional[Dict]:
    """استخراج معلومات الفيديو من YouTube عبر Piped بدون تحميل
    
    بيستخدم Piped API عشان يجيب عنوان ومدة الفيديو
    أسرع من yt-dlp لأنه بيجيب JSON بس
    """
    if not is_youtube_url(url):
        return None
    
    video_id = extract_video_id(url)
    if not video_id:
        return None
    
    instances = _get_instances()
    
    for instance in instances[:2]:  # نجرب سيرفرين بس
        result = _get_download_from_piped(instance, video_id, "low")
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

def check_piped_health() -> Dict:
    """فحص حالة سيرفرات Piped — للأدمن"""
    import requests
    
    results = {
        "total_instances": len(_get_instances()),
        "custom_instance": CUSTOM_PIPED_INSTANCE or "not set",
        "instances_status": [],
    }
    
    for instance in _get_instances():
        try:
            resp = requests.get(
                f"{instance}/trending?region=US",
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                results["instances_status"].append({
                    "instance": instance,
                    "status": "ok",
                })
            else:
                results["instances_status"].append({
                    "instance": instance,
                    "status": f"http_{resp.status_code}",
                })
        except Exception as e:
            results["instances_status"].append({
                "instance": instance,
                "status": f"error: {str(e)[:50]}",
            })
    
    return results
