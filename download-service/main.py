"""
🎬 YouTube Download Service
سيرفر تحميل خاص بيشتغل على VPS بـ IP نظيف
بيحل مشكلة حظر YouTube على Railway

المسار:
1. البوت يبعت URL + quality للسيرفر
2. السيرفر بيحمل الفيديو بـ yt-dlp (IP نظيف = مفيش حظر)
3. السيرفر بيرفع الفيديو على Supabase (streaming)
4. السيرفر بيرجع رابط Supabase للبوت
5. البوت يبعت الرابط للمستخدم

🔴 مفيش تحميل في الرام — كله streaming!
"""

import os
import re
import sys
import json
import time
import logging
import tempfile
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Query, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import aiohttp
import yt_dlp

# ═══ Logging ═══
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("download-service")

# ═══ Config ═══
API_KEY = os.environ.get("API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/").removesuffix("/rest/v1").removesuffix("/rest")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "Downloads")
PORT = int(os.environ.get("PORT", "8080"))

# ═══ Size limits ═══
PLATFORM_SIZE_LIMITS = {
    "telegram": 50 * 1024 * 1024,   # 50MB — direct send limit
    "whatsapp": 100 * 1024 * 1024,  # 100MB — direct send limit
}
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024  # 2GB — Supabase max

# ═══ Quality format strings ═══
QUALITY_FORMATS = {
    "best": (
        'bestvideo[vcodec^=avc1][height<=1080]+bestaudio/'
        'bestvideo[ext=mp4][height<=1080]+bestaudio/'
        'bestvideo[height<=1080]+bestaudio/'
        'best[ext=mp4][height<=1080][acodec!=none]/'
        'best[acodec!=none][height<=1080]/'
        'best[height<=1080]/'
        'best'
    ),
    "medium": (
        'bestvideo[vcodec^=avc1][height<=720]+bestaudio/'
        'bestvideo[ext=mp4][height<=720]+bestaudio/'
        'bestvideo[height<=720]+bestaudio/'
        'best[ext=mp4][height<=720][acodec!=none]/'
        'best[acodec!=none][height<=720]/'
        'best[height<=720]/'
        'best'
    ),
    "low": (
        'best[ext=mp4][height<=480][acodec!=none]/'
        'best[acodec!=none][height<=480]/'
        'best[height<=480]/'
        'best'
    ),
    "audio": 'bestaudio/best',
}

QUALITY_LABELS = {"best": "1080p", "medium": "720p", "low": "480p", "audio": "MP3"}


# ═══ Supabase Upload (Streaming) ═══
async def upload_to_supabase(file_path: str, filename: str, content_type: str, platform: str) -> dict | None:
    """Upload file to Supabase Storage using streaming (no memory loading)"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.error("☁️ Supabase not configured")
        return None

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return None

    # Build storage path
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    unique_id = str(uuid4())[:8]
    safe_name = re.sub(r'[^\w\-.]', '_', filename)
    storage_path = f"{platform}/{date_str}/{unique_id}_{safe_name}"

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
        "Content-Length": str(file_size),
    }

    logger.info(f"☁️ Uploading {file_size / 1024 / 1024:.1f}MB → {storage_path}")

    CHUNK_SIZE = 2 * 1024 * 1024  # 2MB chunks

    async def _file_generator():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    timeout = aiohttp.ClientTimeout(total=600)  # 10 min

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(upload_url, headers=headers, data=_file_generator()) as resp:
                if resp.status in (200, 201):
                    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"
                    logger.info(f"☁️ Upload OK → {public_url}")
                    return {
                        "success": True,
                        "url": public_url,
                        "storage_path": storage_path,
                    }
                else:
                    body = await resp.text()
                    logger.error(f"☁️ Upload failed ({resp.status}): {body[:200]}")
                    return None
    except Exception as e:
        logger.error(f"☁️ Upload error: {e}")
        return None


# ═══ Download with yt-dlp ═══
def _download_video(url: str, quality: str, output_dir: str) -> dict | None:
    """Download video using yt-dlp — runs synchronously in thread"""
    
    is_audio = quality == "audio"
    
    # Build options
    format_str = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    
    output_template = os.path.join(output_dir, "%(title).80s.%(ext)s")
    
    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 5,
        'no_check_certificates': True,
        'format': format_str,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        },
    }
    
    if not is_audio:
        ydl_opts['merge_output_format'] = 'mp4'
        ydl_opts['remux_video'] = 'mp4'
    else:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    
    # Try with cookies first
    cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
    if os.path.exists(cookies_path):
        try:
            with open(cookies_path, 'r') as f:
                if f.read().strip() and len(f.read()) > 50:
                    ydl_opts['cookiefile'] = cookies_path
        except:
            pass
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if not info:
                return None
            
            # Find the downloaded file
            downloaded_files = os.listdir(output_dir)
            if not downloaded_files:
                return None
            
            filepath = os.path.join(output_dir, downloaded_files[0])
            file_size = os.path.getsize(filepath)
            
            if file_size == 0:
                os.remove(filepath)
                return None
            
            # Extract info
            title = info.get("title", "Video")
            duration = info.get("duration", 0)
            height = info.get("height", 720)
            
            # Get actual video codec
            vcodec = ""
            for dl in info.get("requested_downloads", []):
                vcodec = dl.get("vcodec", "").split(".")[0]
                if dl.get("height"):
                    height = max(height or 0, dl["height"])
            
            return {
                "filepath": filepath,
                "title": title,
                "duration": int(duration) if duration else 0,
                "height": height or 720,
                "size": file_size,
                "vcodec": vcodec or "h264",
                "quality_label": QUALITY_LABELS.get(quality, quality),
            }
    
    except Exception as e:
        logger.error(f"❌ yt-dlp download error: {e}")
        return None


def _download_video_with_fallback(url: str, quality: str, output_dir: str) -> dict | None:
    """Try downloading with multiple methods"""
    
    # Method 1: Default + deno (if available)
    result = _download_video(url, quality, output_dir)
    if result:
        return result
    
    logger.warning("⚠️ Default download failed, trying player_client fallback...")
    
    # Method 2: Try with player_client
    for pc in ['android', 'ios', 'mweb', 'tv', 'web']:
        try:
            logger.info(f"🔧 Trying player_client: {pc}")
            
            output_template = os.path.join(output_dir, f"%(title).80s.%(ext)s")
            is_audio = quality == "audio"
            format_str = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
            
            ydl_opts = {
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 2,
                'no_check_certificates': True,
                'format': format_str,
                'extractor_args': {'youtube': {'player_client': [pc]}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                },
            }
            
            if not is_audio:
                ydl_opts['merge_output_format'] = 'mp4'
                ydl_opts['remux_video'] = 'mp4'
            else:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    downloaded_files = os.listdir(output_dir)
                    if downloaded_files:
                        filepath = os.path.join(output_dir, downloaded_files[0])
                        file_size = os.path.getsize(filepath)
                        if file_size > 0:
                            return {
                                "filepath": filepath,
                                "title": info.get("title", "Video"),
                                "duration": int(info.get("duration", 0) or 0),
                                "height": info.get("height", 720) or 720,
                                "size": file_size,
                                "vcodec": "h264",
                                "quality_label": QUALITY_LABELS.get(quality, quality),
                            }
        except Exception as e:
            logger.warning(f"⚠️ player_client {pc} failed: {e}")
            continue
    
    return None


# ═══ FFmpeg h264 conversion ═══
def _convert_to_h264(filepath: str) -> str:
    """Convert video to h264 if needed for Telegram compatibility"""
    try:
        # Check current codec
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', filepath],
            capture_output=True, timeout=10, text=True
        )
        codec = probe.stdout.strip().split('\n')[0] if probe.stdout.strip() else ""
        
        if codec in ("h264", "avc1", "avc", "mpeg4", ""):
            return filepath  # Already compatible
        
        logger.info(f"🔧 Converting {codec} → h264 for compatibility")
        converted = filepath + "_h264.mp4"
        result = subprocess.run(
            ['ffmpeg', '-i', filepath, '-c:v', 'libx264', '-preset', 'fast',
             '-crf', '23', '-c:a', 'aac', '-b:a', '128k',
             '-movflags', '+faststart', '-y', converted],
            capture_output=True, timeout=180
        )
        if result.returncode == 0 and os.path.exists(converted) and os.path.getsize(converted) > 0:
            os.remove(filepath)
            return converted
        else:
            if os.path.exists(converted):
                os.remove(converted)
            return filepath
    except:
        return filepath


# ═══ FastAPI App ═══
app = FastAPI(title="Download Service", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "download-service", "version": "1.0.0"}


@app.get("/download")
async def download(
    url: str = Query(..., description="Video URL"),
    quality: str = Query("best", description="Quality: best, medium, low, audio"),
    platform: str = Query("telegram", description="Platform: telegram, whatsapp"),
    lang: str = Query("ar", description="Language: ar, en"),
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    """
    Download a video and upload to Supabase.
    
    Returns the Supabase URL + metadata.
    The bot then sends this URL to the user.
    """
    start_time = time.time()
    
    # Auth check
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Validate quality
    if quality not in QUALITY_FORMATS:
        raise HTTPException(status_code=400, detail=f"Invalid quality: {quality}. Use: best, medium, low, audio")
    
    logger.info(f"📥 Download request: url={url[:80]} quality={quality} platform={platform}")
    
    # Create temp directory
    tmpdir = tempfile.mkdtemp(prefix="dl_svc_")
    
    try:
        # Step 1: Download with yt-dlp (in thread to not block)
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _download_video_with_fallback, url, quality, tmpdir),
            timeout=300  # 5 min max
        )
        
        if not result:
            logger.error(f"❌ Download failed: {url[:80]}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "download_failed", "message": "Could not download the video"}
            )
        
        filepath = result["filepath"]
        title = result["title"]
        duration = result["duration"]
        height = result["height"]
        size = result["size"]
        vcodec = result["vcodec"]
        quality_label = result["quality_label"]
        size_mb = size / (1024 * 1024)
        
        logger.info(f"✅ Downloaded: {title[:50]} ({size_mb:.1f}MB, {quality_label})")
        
        # Step 2: Convert to h264 if needed (for Telegram)
        if quality != "audio" and platform == "telegram":
            filepath = _convert_to_h264(filepath)
            size = os.path.getsize(filepath)
            size_mb = size / (1024 * 1024)
        
        # Step 3: Upload to Supabase
        is_audio = quality == "audio"
        content_type = "audio/mpeg" if is_audio else "video/mp4"
        ext = ".mp3" if is_audio else ".mp4"
        safe_name = re.sub(r'[^\w\-.]', '_', title[:80]) + ext
        
        upload_result = await upload_to_supabase(filepath, safe_name, content_type, platform)
        
        if not upload_result or not upload_result.get("success"):
            logger.error(f"❌ Supabase upload failed for {title[:50]}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "upload_failed", "message": "Could not upload to cloud"}
            )
        
        # Step 4: Format response
        download_url = upload_result["url"]
        elapsed = int(time.time() - start_time)
        
        # Format message for the bot
        if lang == "ar":
            cloud_msg = (
                f"☁️ الملف كبير للإرسال المباشر ({size_mb:.1f}MB)\n\n"
                f"📥 تم رفعه على السحابة بنجاح!\n\n"
                f"🔗 رابط التحميل:\n{download_url}\n\n"
                f"⏰ الرابط صالح لمدة 24 ساعة\n"
                f"📁 {safe_name}"
            )
            if title:
                cloud_msg = f"🎬 {title}\n\n" + cloud_msg
        else:
            cloud_msg = (
                f"☁️ File is too large for direct sending ({size_mb:.1f}MB)\n\n"
                f"📥 Uploaded to cloud successfully!\n\n"
                f"🔗 Download link:\n{download_url}\n\n"
                f"⏰ Link valid for 24 hours\n"
                f"📁 {safe_name}"
            )
            if title:
                cloud_msg = f"🎬 {title}\n\n" + cloud_msg
        
        response = {
            "success": True,
            "url": download_url,
            "cloud_msg": cloud_msg,
            "title": title,
            "duration": duration,
            "height": height,
            "size_mb": round(size_mb, 1),
            "size": size,
            "quality": quality_label,
            "vcodec": vcodec,
            "is_audio": is_audio,
            "elapsed_seconds": elapsed,
            "filename": safe_name,
        }
        
        logger.info(f"✅ Complete: {title[:50]} → {download_url[:60]}... ({elapsed}s)")
        return response
    
    except asyncio.TimeoutError:
        logger.error(f"❌ Download timed out: {url[:80]}")
        return JSONResponse(
            status_code=408,
            content={"success": False, "error": "timeout", "message": "Download timed out (5 min)"}
        )
    
    except Exception as e:
        logger.error(f"❌ Download error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "internal_error", "message": str(e)}
        )
    
    finally:
        # Cleanup
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except:
            pass


@app.get("/info")
async def get_info(
    url: str = Query(..., description="Video URL"),
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    """Get video info without downloading"""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                formats = info.get("formats", [])
                return {
                    "success": True,
                    "title": info.get("title", ""),
                    "duration": info.get("duration", 0),
                    "thumbnail": info.get("thumbnail", ""),
                    "available_qualities": list(set(
                        f.get("height") for f in formats if f.get("height")
                    )),
                    "views": info.get("view_count", 0),
                }
            return {"success": False, "error": "no_info"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 Download Service starting on port {PORT}")
    logger.info(f"☁️ Supabase: {'✅ configured' if SUPABASE_URL else '❌ not configured'}")
    logger.info(f"🔑 API Key: {'✅ set' if API_KEY else '⚠️ not set (open access)'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
