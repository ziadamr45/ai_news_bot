"""
🔵 Apify YouTube Video Downloader — Fallback رابع
منصة Apify لتحميل فيديوهات اليوتيوب عبر actors

🔴 المسار:
1. بنبعت طلب تشغيل actor للـ Apify API
2. بنستنى الـ run يخلص
3. بنجيب النتائج من الـ dataset
4. بنحمل الفيديو من الرابط المباشر

🔴 الميزة: مش بيتأثر بـ YouTube bot detection خالص — سيرفرات مختلفة تماماً

🔴 Actors المتاحة:
- primary: randominique/youtube-video-downloader (مجاني/رخيص)
- fallback: youtube.video.downloader/youtube-video-downloader
"""

import os
import re
import logging
import asyncio
import tempfile

import aiohttp

logger = logging.getLogger("apify_download")

# ═══════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════

APIFY_API_KEY: str = os.environ.get("APIFY_API_KEY", "")
APIFY_BASE_URL = "https://api.apify.com/v2"

# 🔴 YouTube video downloader actors — بنجربهم بالترتيب
APIFY_ACTORS = [
    {
        "id": "randominique~youtube-video-downloader",
        "name": "YouTube Video Downloader (randominique)",
    },
    {
        "id": "youtube.video.downloader~youtube-video-downloader",
        "name": "YouTube Video Downloader (official)",
    },
]

# أقصى وقت انتظار للـ actor run (ثواني)
MAX_RUN_WAIT = 120

# ═══════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════

def _is_configured() -> bool:
    """هل Apify مضبوط؟"""
    return bool(APIFY_API_KEY)


async def _start_actor_run(actor_id: str, run_input: dict) -> dict | None:
    """تشغيل actor على Apify وانتظار النتيجة
    
    Returns: dict فيه {data: [...]} أو None لو فشل
    """
    if not _is_configured():
        logger.warning("🔵 Apify: API key not configured")
        return None
    
    # تحويل actor ID للـ URL format (نحول ~ لـ /)
    actor_path = actor_id.replace("~", "/")
    
    # Step 1: تشغيل الـ actor
    run_url = f"{APIFY_BASE_URL}/acts/{actor_path}/runs?token={APIFY_API_KEY}"
    
    headers = {
        "Content-Type": "application/json",
    }
    
    logger.info(f"🔵 Apify: Starting actor {actor_id}...")
    
    timeout = aiohttp.ClientTimeout(total=MAX_RUN_WAIT + 30)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Start the run
            async with session.post(run_url, headers=headers, json=run_input) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.warning(f"🔵 Apify: Failed to start actor {actor_id} (status={resp.status}, body={body[:200]})")
                    return None
                
                run_data = await resp.json()
                run_id = run_data.get("data", {}).get("id", "")
                
                if not run_id:
                    logger.warning(f"🔵 Apify: No run ID returned for {actor_id}")
                    return None
                
                logger.info(f"🔵 Apify: Actor run started — run_id={run_id}")
            
            # Step 2: انتظار انتهاء الـ run
            status_url = f"{APIFY_BASE_URL}/actor-runs/{run_id}?token={APIFY_API_KEY}"
            
            poll_interval = 3  # كل 3 ثواني
            elapsed = 0
            
            while elapsed < MAX_RUN_WAIT:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                async with session.get(status_url) as status_resp:
                    if status_resp != 200:
                        # Try to read anyway
                        try:
                            status_data = await status_resp.json()
                        except:
                            continue
                    else:
                        status_data = await status_resp.json()
                    
                    run_status = status_data.get("data", {}).get("status", "")
                    
                    if run_status == "SUCCEEDED":
                        logger.info(f"🔵 Apify: Run {run_id} succeeded!")
                        break
                    elif run_status in ("FAILED", "ABORTED", "TIMED-OUT"):
                        logger.warning(f"🔵 Apify: Run {run_id} failed with status={run_status}")
                        return None
                    else:
                        logger.info(f"🔵 Apify: Run {run_id} status={run_status} (elapsed={elapsed}s)")
            else:
                logger.warning(f"🔵 Apify: Run {run_id} timed out after {MAX_RUN_WAIT}s")
                return None
            
            # Step 3: جلب النتائج من الـ dataset
            dataset_id = run_data.get("data", {}).get("defaultDatasetId", "")
            
            if not dataset_id:
                # نجرب من status data
                dataset_id = status_data.get("data", {}).get("defaultDatasetId", "")
            
            if not dataset_id:
                logger.warning(f"🔵 Apify: No dataset ID for run {run_id}")
                return None
            
            dataset_url = f"{APIFY_BASE_URL}/datasets/{dataset_id}/items?token={APIFY_API_KEY}&format=json"
            
            async with session.get(dataset_url) as dataset_resp:
                if dataset_resp.status != 200:
                    body = await dataset_resp.text()
                    logger.warning(f"🔵 Apify: Failed to get dataset (status={dataset_resp.status})")
                    return None
                
                items = await dataset_resp.json()
                
                if not items:
                    logger.warning(f"🔵 Apify: Empty dataset for run {run_id}")
                    return None
                
                logger.info(f"🔵 Apify: Got {len(items)} results from dataset")
                return {"data": items, "run_id": run_id}
    
    except asyncio.TimeoutError:
        logger.warning(f"🔵 Apify: Timeout for actor {actor_id}")
        return None
    except Exception as e:
        logger.error(f"🔵 Apify: Error running actor {actor_id}: {e}")
        return None


async def _download_file_from_url(url: str, output_dir: str, filename: str = "") -> dict | None:
    """تحميل ملف من رابط مباشر
    
    Returns: dict {filepath, filename, size} أو None
    """
    if not url:
        return None
    
    try:
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"🔵 Apify: Download failed (status={resp.status})")
                    return None
                
                # استخراج اسم الملف من الـ headers أو الرابط
                if not filename:
                    content_disp = resp.headers.get("Content-Disposition", "")
                    if "filename=" in content_disp:
                        filename = content_disp.split("filename=")[-1].strip('"').strip("'")
                    else:
                        filename = url.split("/")[-1].split("?")[0] or "video.mp4"
                
                # تأكد إن الامتداد موجود
                if not any(filename.endswith(ext) for ext in [".mp4", ".mp3", ".webm", ".mkv", ".m4a"]):
                    filename += ".mp4"
                
                filepath = os.path.join(output_dir, filename)
                file_size = 0
                
                with open(filepath, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):  # 1MB chunks
                        f.write(chunk)
                        file_size += len(chunk)
                
                if file_size == 0:
                    logger.warning("🔵 Apify: Downloaded file is empty")
                    try: os.remove(filepath)
                    except: pass
                    return None
                
                logger.info(f"🔵 Apify: Downloaded {file_size / (1024*1024):.1f}MB → {filepath}")
                return {
                    "filepath": filepath,
                    "filename": filename,
                    "size": file_size,
                }
    
    except asyncio.TimeoutError:
        logger.warning("🔵 Apify: File download timed out")
        return None
    except Exception as e:
        logger.error(f"🔵 Apify: File download error: {e}")
        return None


# ═══════════════════════════════════════
# Main download function
# ═══════════════════════════════════════

async def download_youtube_apify(
    url: str,
    quality: str = "best",
    output_dir: str = "",
) -> dict | None:
    """تحميل فيديو يوتيوب عبر Apify — Fallback رابع
    
    🔴 المسار:
    1. نبعت رابط اليوتيوب لـ Apify actor
    2. الـ actor بيحمل الفيديو ويرجع روابط مباشرة
    3. بنحمل الفيديو من الرابط المباشر
    
    Args:
        url: رابط يوتيوب
        quality: best/medium/low/audio
        output_dir: مجلد التحميل
    
    Returns:
        dict فيه {success, filepath, filename, title, size, height, duration}
        أو None لو فشل
    """
    if not _is_configured():
        logger.warning("🔵 Apify: API key not configured, skipping")
        return None
    
    if not output_dir:
        output_dir = tempfile.mkdtemp(prefix="apify_dl_")
    
    is_audio = quality == "audio"
    
    # تحويل الجودة
    quality_map = {"best": "1080p", "medium": "720p", "low": "480p", "audio": "720p"}
    apify_quality = quality_map.get(quality, "720p")
    
    # ═══ نجرب كل actor بالترتيب ═══
    for actor in APIFY_ACTORS:
        actor_id = actor["id"]
        actor_name = actor["name"]
        
        logger.info(f"🔵 Apify: Trying actor {actor_name} for {url[:80]}")
        
        # بناء الـ input حسب الـ actor
        run_input = _build_actor_input(actor_id, url, apify_quality, is_audio)
        
        # تشغيل الـ actor
        result = await _start_actor_run(actor_id, run_input)
        
        if not result or not result.get("data"):
            logger.warning(f"🔵 Apify: Actor {actor_name} returned no data, trying next...")
            continue
        
        items = result["data"]
        
        # استخراج بيانات الفيديو من النتائج
        video_info = _extract_video_info(items, quality)
        
        if not video_info:
            logger.warning(f"🔵 Apify: No video info from {actor_name}, trying next...")
            continue
        
        download_url = video_info.get("download_url", "")
        
        if not download_url:
            logger.warning(f"🔵 Apify: No download URL from {actor_name}, trying next...")
            continue
        
        # تحميل الفيديو من الرابط المباشر
        safe_title = re.sub(r'[^\w\-.]', '_', video_info.get("title", "video")[:80])
        ext = ".mp3" if is_audio else ".mp4"
        filename = safe_title + ext
        
        logger.info(f"🔵 Apify: Downloading from {download_url[:100]}...")
        
        download_result = await _download_file_from_url(download_url, output_dir, filename)
        
        if download_result:
            return {
                "success": True,
                "filepath": download_result["filepath"],
                "filename": download_result["filename"],
                "title": video_info.get("title", "YouTube Video"),
                "size": download_result["size"],
                "height": video_info.get("height", 720),
                "duration": video_info.get("duration", 0),
            }
        else:
            logger.warning(f"🔵 Apify: File download failed from {actor_name}")
            continue
    
    # كل الـ actors فشلوا
    logger.warning(f"🔵 Apify: All actors failed for {url[:80]}")
    return None


def _build_actor_input(actor_id: str, url: str, quality: str, is_audio: bool) -> dict:
    """بناء input حسب نوع الـ actor"""
    
    # 🔴 كل actor ليه input schema مختلف
    # بنحاول نبني input مناسب لكل واحد
    
    if "randominique" in actor_id:
        # randominique/youtube-video-downloader
        return {
            "url": url,
            "quality": quality,
        }
    
    elif "youtube.video.downloader" in actor_id:
        # youtube.video.downloader/youtube-video-downloader
        return {
            "urls": [url],
            "quality": quality,
        }
    
    # Default input
    return {
        "url": url,
        "quality": quality,
    }


def _extract_video_info(items: list, quality: str = "best") -> dict | None:
    """استخراج بيانات الفيديو من نتائج الـ Apify dataset
    
    🔴 النتائج ممكن تكون بأشكال مختلفة حسب الـ actor
    بنحاول نستخرج:
    - download_url / url / videoUrl
    - title
    - duration
    - height (quality)
    """
    if not items:
        return None
    
    # ناخذ أول نتيجة
    item = items[0]
    
    # 🔴 استخراج رابط التحميل — بنجرب أسماء مختلفة
    download_url = (
        item.get("downloadUrl") or
        item.get("download_url") or
        item.get("videoUrl") or
        item.get("video_url") or
        item.get("url") or
        item.get("streamUrl") or
        item.get("stream_url") or
        ""
    )
    
    # 🔴 لو فيه formats أو videos array — نختار الأنسب
    if not download_url:
        # بنبحث في الـ nested structures
        for key in ["formats", "videos", "streams", "qualities"]:
            formats = item.get(key, [])
            if isinstance(formats, list) and formats:
                # نختار أفضل جودة أو اللي تناسب الطلب
                best = _pick_best_format(formats, quality)
                if best:
                    download_url = best.get("url") or best.get("downloadUrl") or best.get("download_url", "")
                    if download_url:
                        break
    
    if not download_url:
        logger.warning(f"🔵 Apify: No download URL found in item keys: {list(item.keys())}")
        return None
    
    title = (
        item.get("title") or
        item.get("name") or
        item.get("videoTitle") or
        item.get("video_title") or
        "YouTube Video"
    )
    
    duration = (
        item.get("duration") or
        item.get("lengthSeconds") or
        item.get("length_seconds") or
        0
    )
    
    height = (
        item.get("height") or
        item.get("resolution") or
        720
    )
    
    # لو الـ height نص (زي "1080p")
    if isinstance(height, str):
        height_match = re.search(r'(\d+)', height)
        height = int(height_match.group(1)) if height_match else 720
    
    return {
        "download_url": download_url,
        "title": title,
        "duration": int(duration) if duration else 0,
        "height": int(height) if height else 720,
    }


def _pick_best_format(formats: list, quality: str = "best") -> dict | None:
    """اختيار أفضل format من القائمة حسب الجودة المطلوبة"""
    if not formats:
        return None
    
    quality_heights = {
        "best": 1080,
        "medium": 720,
        "low": 480,
        "audio": 720,  # الجودة مش مهمة للأوديو
    }
    
    target_height = quality_heights.get(quality, 720)
    
    best_match = None
    best_diff = float('inf')
    
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        
        fmt_height = fmt.get("height") or fmt.get("resolution") or 0
        if isinstance(fmt_height, str):
            h_match = re.search(r'(\d+)', fmt_height)
            fmt_height = int(h_match.group(1)) if h_match else 0
        
        # بنختار الـ format الأقرب للجودة المطلوبة (من الأعلى)
        diff = target_height - int(fmt_height)
        
        # نفاضل الجودة الأقرب (من فوق مش من تحت)
        if diff >= 0 and diff < best_diff:
            best_diff = diff
            best_match = fmt
        elif diff < 0 and best_match is None:
            # لو مفيش جودة كافية — نختار الأعلى المتاح
            best_match = fmt
    
    return best_match
