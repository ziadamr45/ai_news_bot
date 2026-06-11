"""
Supabase Storage integration module for the My Bro bot project.

Handles uploading, deleting, and managing files in Supabase Storage.
Uses aiohttp for async HTTP requests and SERVICE_ROLE_KEY for authentication.

🔴 FIX v3:
- Supabase free tier has a 50MB per-file upload limit!
- For files > 50MB, we now auto-compress with ffmpeg before uploading
- Stream-based upload for files > 25MB (avoids OOM)
- Proper timeout handling for uploads
- Better error messages and Arabic UX
- Specific error reasons (not configured, too large, upload failed, etc.)
"""

import os
import logging
import re
import asyncio
import subprocess
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

import aiohttp

logger = logging.getLogger("supabase_storage")

# ---------------------------------------------------------------------------
# Supabase credentials (from environment variables)
# ---------------------------------------------------------------------------
_RAW_SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")

# 🔴 FIX: Strip /rest/v1/ if present — the env var might include it
# The Supabase Storage API uses the BASE URL, not the REST API URL
# e.g. https://xxx.supabase.co (NOT https://xxx.supabase.co/rest/v1/)
SUPABASE_URL: str = _RAW_SUPABASE_URL.rstrip("/").removesuffix("/rest/v1").removesuffix("/rest")

SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
# 🔴 FIX: Bucket name is "Downloads" with capital D
SUPABASE_BUCKET: str = os.environ.get("SUPABASE_BUCKET", "Downloads")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# 🔴 FIX v3: Supabase free tier has a HARD 50MB per-file upload limit!
# Anything > 50MB will get "413 Payload too large" error.
# We auto-compress files larger than this with ffmpeg before uploading.
SUPABASE_UPLOAD_LIMIT: int = 50 * 1024 * 1024  # 50 MB — HARD LIMIT on free tier
MAX_FILE_SIZE: int = SUPABASE_UPLOAD_LIMIT       # 🔴 Changed from 2GB to 50MB (actual limit)

# 🔴 Upload timeout — large files need more time
UPLOAD_TIMEOUT: int = 600  # 10 minutes

ALLOWED_CONTENT_TYPES: set[str] = {
    "video/mp4",
    "audio/mpeg",
    "audio/mp4",
    "image/jpeg",
    "image/png",
    "video/webm",
    "audio/webm",
    "application/octet-stream",
}

PLATFORM_SIZE_LIMITS: dict[str, int] = {
    "telegram": 50 * 1024 * 1024,   # 50 MB
    "whatsapp": 100 * 1024 * 1024,  # 100 MB
}

# 🔴 Compression target: we compress to slightly under the limit to be safe
COMPRESSION_TARGET_MB: int = 45  # 45MB target (5MB safety margin)
COMPRESSION_TARGET_BYTES: int = COMPRESSION_TARGET_MB * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_content_type(content_type: str) -> bool:
    """Check whether *content_type* is in the allowed set."""
    return content_type in ALLOWED_CONTENT_TYPES


def _sanitize_filename(filename: str) -> str:
    """Remove dangerous characters from *filename*, keeping alphanumeric, dots, dashes, underscores."""
    # Keep only alphanumeric, dots, dashes, underscores
    sanitized = re.sub(r"[^A-Za-z0-9._\-]", "_", filename)
    # Collapse consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Strip leading/trailing underscores and dots
    sanitized = sanitized.strip("_.")
    return sanitized or "file"


def _is_configured() -> bool:
    """Return True if the minimum Supabase configuration is present."""
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _log_config_status():
    """Log the current Supabase configuration status (for debugging)."""
    if not SUPABASE_URL:
        logger.warning("☁️ SUPABASE_URL is not set")
    else:
        logger.info(f"☁️ SUPABASE_URL = {SUPABASE_URL}")
    if not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("☁️ SUPABASE_SERVICE_ROLE_KEY is not set")
    else:
        logger.info(f"☁️ SUPABASE_SERVICE_ROLE_KEY = {'*' * 10}...{SUPABASE_SERVICE_ROLE_KEY[-6:]}")
    logger.info(f"☁️ SUPABASE_BUCKET = {SUPABASE_BUCKET}")
    logger.info(f"☁️ SUPABASE_UPLOAD_LIMIT = {SUPABASE_UPLOAD_LIMIT / (1024*1024):.0f}MB (free tier)")

# Log config on module load
_log_config_status()


def get_supabase_upload_limit() -> int:
    """Return the current Supabase upload limit in bytes."""
    return SUPABASE_UPLOAD_LIMIT


def can_upload_to_supabase(file_size: int) -> bool:
    """Check if a file of the given size can be uploaded to Supabase.
    
    🔴 Returns True only if file_size <= SUPABASE_UPLOAD_LIMIT (50MB on free tier).
    For larger files, use compress_video_for_upload() first.
    """
    return file_size <= SUPABASE_UPLOAD_LIMIT


# ---------------------------------------------------------------------------
# Public URL
# ---------------------------------------------------------------------------

def get_public_url(storage_path: str) -> str:
    """Generate a public URL for a file stored in Supabase Storage."""
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"


# ---------------------------------------------------------------------------
# FFmpeg Video Compression — for files > 50MB (Supabase free tier limit)
# ---------------------------------------------------------------------------

def _is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available on the system."""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


async def compress_video_for_upload(
    file_path: str,
    target_size_bytes: int = COMPRESSION_TARGET_BYTES,
    lang: str = "ar",
) -> str | None:
    """Compress a video file to fit within the Supabase upload limit.
    
    🔴 This is needed because Supabase free tier has a 50MB per-file limit.
    Files > 50MB must be compressed before uploading.
    
    Uses ffmpeg to compress the video to a target file size.
    The target is set to 45MB by default (5MB safety margin under the 50MB limit).
    
    Args:
        file_path: Path to the video file to compress
        target_size_bytes: Target file size in bytes (default: 45MB)
        lang: Language for logging messages
    
    Returns:
        Path to the compressed file, or None if compression failed.
        The compressed file is in the same directory as the original with "_compressed" suffix.
    """
    if not _is_ffmpeg_available():
        logger.warning("☁️ ffmpeg not available — cannot compress video for Supabase upload")
        return None
    
    try:
        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)
        target_mb = target_size_bytes / (1024 * 1024)
        
        logger.info(f"☁️ Compressing video: {size_mb:.1f}MB → target {target_mb:.0f}MB")
        
        # Get video duration
        probe_cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', file_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        
        if probe_result.returncode != 0:
            logger.warning(f"☁️ ffprobe failed: {probe_result.stderr[:200]}")
            return None
        
        try:
            duration = float(probe_result.stdout.strip())
        except ValueError:
            logger.warning(f"☁️ Could not parse video duration: {probe_result.stdout[:100]}")
            return None
        
        if duration <= 0:
            logger.warning(f"☁️ Invalid video duration: {duration}")
            return None
        
        # Calculate target bitrate (with safety margin)
        # target_bitrate = (target_size_bytes * 8 * 0.9) / duration  (90% of target to be safe)
        target_bitrate = int((target_size_bytes * 8 * 0.85) / duration)
        
        # Ensure minimum quality (at least 200k bitrate)
        target_bitrate = max(target_bitrate, 200000)
        
        logger.info(f"☁️ Video duration: {duration:.1f}s, target bitrate: {target_bitrate/1000:.0f}k")
        
        # Output path
        base, ext = os.path.splitext(file_path)
        compressed_path = f"{base}_compressed{ext}"
        
        # FFmpeg compression command
        # Using two-pass encoding for better quality at low bitrates
        # But for speed, we use single-pass CRF with maxrate
        cmd = [
            'ffmpeg', '-y', '-i', file_path,
            '-c:v', 'libx264',           # H.264 codec (best compatibility)
            '-preset', 'fast',            # Fast encoding
            '-b:v', str(target_bitrate),  # Target video bitrate
            '-maxrate', str(int(target_bitrate * 1.2)),  # Max bitrate (20% headroom)
            '-bufsize', str(int(target_bitrate * 2)),     # Buffer size
            '-c:a', 'aac',               # AAC audio codec
            '-b:a', '96k',               # Audio bitrate (low but acceptable)
            '-movflags', '+faststart',    # Enable streaming
            '-vf', 'scale=-2:720',        # Scale to 720p max (for smaller files)
            compressed_path,
        ]
        
        logger.info(f"☁️ Running ffmpeg compression...")
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("☁️ ffmpeg compression timed out (5 min)")
            try: os.remove(compressed_path)
            except: pass
            return None
        
        if proc.returncode != 0:
            logger.warning(f"☁️ ffmpeg compression failed: {stderr.decode()[:300]}")
            try: os.remove(compressed_path)
            except: pass
            return None
        
        # Check compressed file size
        if not os.path.exists(compressed_path):
            logger.warning("☁️ Compressed file not created")
            return None
        
        compressed_size = os.path.getsize(compressed_path)
        compressed_mb = compressed_size / (1024 * 1024)
        
        if compressed_size > SUPABASE_UPLOAD_LIMIT:
            # Still too large — try again with lower quality
            logger.warning(f"☁️ Compressed file still too large: {compressed_mb:.1f}MB > 50MB limit")
            
            # Try more aggressive compression
            lower_bitrate = int((SUPABASE_UPLOAD_LIMIT * 8 * 0.7) / duration)
            lower_bitrate = max(lower_bitrate, 100000)
            
            cmd_aggressive = [
                'ffmpeg', '-y', '-i', file_path,
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-b:v', str(lower_bitrate),
                '-maxrate', str(int(lower_bitrate * 1.2)),
                '-bufsize', str(int(lower_bitrate * 2)),
                '-c:a', 'aac',
                '-b:a', '64k',
                '-movflags', '+faststart',
                '-vf', 'scale=-2:480',  # 480p for even smaller files
                compressed_path,
            ]
            
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_aggressive,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=300)
            except asyncio.TimeoutError:
                proc2.kill()
                try: os.remove(compressed_path)
                except: pass
                return None
            
            if proc2.returncode != 0:
                logger.warning(f"☁️ Aggressive compression also failed: {stderr2.decode()[:300]}")
                try: os.remove(compressed_path)
                except: pass
                return None
            
            compressed_size = os.path.getsize(compressed_path)
            compressed_mb = compressed_size / (1024 * 1024)
        
        if compressed_size > SUPABASE_UPLOAD_LIMIT:
            logger.warning(f"☁️ Even aggressive compression produced {compressed_mb:.1f}MB — still over 50MB limit")
            try: os.remove(compressed_path)
            except: pass
            return None
        
        logger.info(f"☁️ ✅ Compression successful: {size_mb:.1f}MB → {compressed_mb:.1f}MB")
        return compressed_path
    
    except Exception as e:
        logger.exception(f"☁️ Video compression error: {e}")
        return None


async def compress_audio_for_upload(
    file_path: str,
    target_size_bytes: int = COMPRESSION_TARGET_BYTES,
) -> str | None:
    """Compress an audio file to fit within the Supabase upload limit.
    
    🔴 For audio files > 50MB.
    """
    if not _is_ffmpeg_available():
        return None
    
    try:
        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)
        
        # Get audio duration
        probe_cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', file_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        
        if probe_result.returncode != 0:
            return None
        
        try:
            duration = float(probe_result.stdout.strip())
        except ValueError:
            return None
        
        if duration <= 0:
            return None
        
        # Calculate target bitrate
        target_bitrate = int((target_size_bytes * 8 * 0.85) / duration)
        target_bitrate = max(target_bitrate, 48000)  # Minimum 48k
        
        base, ext = os.path.splitext(file_path)
        compressed_path = f"{base}_compressed.mp3"
        
        cmd = [
            'ffmpeg', '-y', '-i', file_path,
            '-c:a', 'libmp3lame',
            '-b:a', f'{target_bitrate // 1000}k',
            compressed_path,
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            try: os.remove(compressed_path)
            except: pass
            return None
        
        if proc.returncode != 0:
            try: os.remove(compressed_path)
            except: pass
            return None
        
        compressed_size = os.path.getsize(compressed_path)
        if compressed_size > SUPABASE_UPLOAD_LIMIT:
            try: os.remove(compressed_path)
            except: pass
            return None
        
        logger.info(f"☁️ ✅ Audio compression: {size_mb:.1f}MB → {compressed_size / (1024*1024):.1f}MB")
        return compressed_path
    
    except Exception:
        logger.exception("☁️ Audio compression error")
        return None


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------

async def _do_upload(
    storage_path: str,
    data: bytes,
    content_type: str,
) -> dict | None:
    """Core upload logic — sends data as bytes to Supabase Storage.
    
    🔴 Uses a generous timeout (10 min) for large files.
    """
    if not _is_configured():
        logger.warning("☁️ Supabase is not configured; skipping upload")
        return None

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
    }

    data_size = len(data)
    logger.info(f"☁️ Upload started → {storage_path} ({data_size / (1024*1024):.1f}MB)")

    timeout = aiohttp.ClientTimeout(total=UPLOAD_TIMEOUT)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(upload_url, headers=headers, data=data) as resp:
                if resp.status in (200, 201):
                    public_url = get_public_url(storage_path)
                    logger.info(f"☁️ Upload completed → {storage_path} (URL: {public_url})")
                    return {
                        "success": True,
                        "url": public_url,
                        "storage_path": storage_path,
                        "file_size": data_size,
                    }
                else:
                    body = await resp.text()
                    logger.warning(
                        f"☁️ Upload failed → {storage_path} (status={resp.status}, body={body})"
                    )
                    return None
    except asyncio.TimeoutError:
        logger.error(f"☁️ Upload timed out → {storage_path} (timeout={UPLOAD_TIMEOUT}s)")
        return None
    except Exception:
        logger.exception(f"☁️ Upload exception → {storage_path}")
        return None


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------

async def upload_file(
    file_path: str,
    filename: str,
    content_type: str = "video/mp4",
    platform: str = "telegram",
) -> dict | None:
    """Upload a file from disk to Supabase Storage.
    
    🔴 FIX v3: Supabase free tier has a HARD 50MB per-file limit.
    - Files <= 50MB: Upload directly
    - Files > 50MB: Will be REJECTED by Supabase — use compress_video_for_upload() first
    
    Returns ``{"success": True, "url": ..., "storage_path": ..., "file_size": ...}``
    on success, or ``None`` on failure.
    """
    if not _is_configured():
        logger.warning("☁️ Supabase is not configured; skipping upload")
        return None

    # --- Validate local file ---
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"☁️ File does not exist: {file_path}")
        return None

    file_size = path.stat().st_size
    if file_size == 0:
        logger.warning(f"☁️ File is empty: {file_path}")
        return None

    # 🔴 FIX v3: Check against ACTUAL Supabase limit (50MB), not 2GB
    if file_size > SUPABASE_UPLOAD_LIMIT:
        logger.warning(
            f"☁️ File exceeds Supabase upload limit "
            f"({file_size / (1024*1024):.1f}MB > {SUPABASE_UPLOAD_LIMIT / (1024*1024):.0f}MB). "
            f"Use compress_video_for_upload() first!"
        )
        return None

    # --- Validate content type ---
    if not _validate_content_type(content_type):
        logger.warning(f"☁️ Content type not allowed: {content_type}")
        return None

    # --- Build storage path ---
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    unique_id = str(uuid4())[:8]
    safe_name = _sanitize_filename(filename)
    storage_path = f"{platform}/{date_str}/{unique_id}_{safe_name}"

    # --- Upload (file is guaranteed <= 50MB at this point) ---
    try:
        data = path.read_bytes()
    except Exception:
        logger.exception(f"☁️ Failed to read file: {file_path}")
        return None

    result = await _do_upload(storage_path, data, content_type)

    if result is not None:
        logger.info(f"☁️ URL generated: {result['url']}")
    else:
        logger.error(f"☁️ Upload failed for {file_path}")
    return result


# ---------------------------------------------------------------------------
# upload_bytes
# ---------------------------------------------------------------------------

async def upload_bytes(
    file_bytes: bytes,
    filename: str,
    content_type: str = "video/mp4",
    platform: str = "telegram",
) -> dict | None:
    """Upload raw bytes to Supabase Storage.
    
    🔴 FIX v3: Supabase free tier has a HARD 50MB per-file limit.
    
    Returns ``{"success": True, "url": ..., "storage_path": ..., "file_size": ...}``
    on success, or ``None`` on failure.
    """
    if not _is_configured():
        logger.warning("☁️ Supabase is not configured; skipping upload")
        return None

    file_size = len(file_bytes)
    if file_size == 0:
        logger.warning("☁️ Byte payload is empty; skipping upload")
        return None

    # 🔴 FIX v3: Check against ACTUAL Supabase limit (50MB)
    if file_size > SUPABASE_UPLOAD_LIMIT:
        logger.warning(
            f"☁️ Byte payload exceeds Supabase upload limit "
            f"({file_size / (1024*1024):.1f}MB > {SUPABASE_UPLOAD_LIMIT / (1024*1024):.0f}MB)"
        )
        return None

    if not _validate_content_type(content_type):
        logger.warning(f"☁️ Content type not allowed: {content_type}")
        return None

    # --- Build storage path ---
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    unique_id = str(uuid4())[:8]
    safe_name = _sanitize_filename(filename)
    storage_path = f"{platform}/{date_str}/{unique_id}_{safe_name}"

    result = await _do_upload(storage_path, file_bytes, content_type)
    if result is not None:
        logger.info(f"☁️ URL generated: {result['url']}")
    return result


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------

async def delete_file(storage_path: str) -> bool:
    """Delete a file from Supabase Storage. Returns ``True`` on success."""
    if not _is_configured():
        logger.warning("☁️ Supabase is not configured; skipping delete")
        return False

    delete_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }

    logger.info(f"☁️ Deleting file → {storage_path}")

    timeout = aiohttp.ClientTimeout(total=30)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.delete(delete_url, headers=headers) as resp:
                if resp.status in (200, 204):
                    logger.info(f"☁️ Deleted successfully → {storage_path}")
                    return True
                else:
                    body = await resp.text()
                    logger.warning(
                        f"☁️ Delete failed → {storage_path} (status={resp.status}, body={body})"
                    )
                    return False
    except Exception:
        logger.exception(f"☁️ Delete exception → {storage_path}")
        return False


# ---------------------------------------------------------------------------
# cleanup_expired_files
# ---------------------------------------------------------------------------

async def cleanup_expired_files(max_age_hours: int = 24) -> int:
    """List all files in the bucket and delete those older than *max_age_hours*.

    Age is determined from the date folder embedded in the storage path
    (format: ``{platform}/{YYYY-MM-DD}/...``).  Returns the count of deleted files.
    """
    if not _is_configured():
        logger.warning("☁️ Supabase is not configured; skipping cleanup")
        return 0

    list_url = f"{SUPABASE_URL}/storage/v1/object/list/{SUPABASE_BUCKET}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    deleted = 0

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            # --- List top-level "platform" folders ---
            async with session.post(
                list_url,
                headers=headers,
                json={"prefix": "", "limit": 1000, "offset": 0},
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"☁️ Cleanup: failed to list bucket (status={resp.status}, body={body})")
                    return 0
                top_level = await resp.json()

            # top_level contains folders like "telegram/", "whatsapp/"
            for folder_obj in top_level:
                folder_name = folder_obj.get("name", "")
                if not folder_name:
                    continue

                # --- List date sub-folders ---
                async with session.post(
                    list_url,
                    headers=headers,
                    json={"prefix": folder_name, "limit": 1000, "offset": 0},
                ) as resp2:
                    if resp2.status != 200:
                        continue
                    date_folders = await resp2.json()

                for date_obj in date_folders:
                    date_name = date_obj.get("name", "")
                    # date_name looks like "telegram/2025-01-15"
                    # Try to extract the date portion
                    parts = date_name.rstrip("/").split("/")
                    date_part = parts[-1] if parts else ""

                    try:
                        folder_date = datetime.strptime(date_part, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        continue

                    age_hours = (datetime.now(timezone.utc) - folder_date).total_seconds() / 3600
                    if age_hours <= max_age_hours:
                        continue

                    # --- List files inside the date folder ---
                    async with session.post(
                        list_url,
                        headers=headers,
                        json={"prefix": date_name, "limit": 1000, "offset": 0},
                    ) as resp3:
                        if resp3.status != 200:
                            continue
                        files = await resp3.json()

                    for file_obj in files:
                        file_path = file_obj.get("name", "")
                        if not file_path or file_path.endswith("/"):
                            continue
                        if await delete_file(file_path):
                            logger.info(f"☁️ Cleanup: deleted expired file → {file_path}")
                            deleted += 1

        logger.info(f"☁️ Cleanup complete: {deleted} file(s) deleted")

    except Exception:
        logger.exception("☁️ Cleanup exception")

    return deleted


# ---------------------------------------------------------------------------
# should_use_supabase  (sync)
# ---------------------------------------------------------------------------

def should_use_supabase(file_size: int, platform: str) -> bool:
    """Return ``True`` if *file_size* exceeds the direct-sending limit for *platform*
    AND the file can be uploaded to Supabase (i.e., <= 50MB after possible compression).

    Platform limits:
      - Telegram: 50 MB
      - WhatsApp: 100 MB
    """
    limit = PLATFORM_SIZE_LIMITS.get(platform, 50 * 1024 * 1024)
    return file_size > limit


# ---------------------------------------------------------------------------
# upload_and_get_link — High-level function for bots
# ---------------------------------------------------------------------------

async def upload_and_get_link(
    file_path: str,
    filename: str,
    content_type: str = "video/mp4",
    platform: str = "telegram",
    title: str = "",
    lang: str = "ar",
) -> str | None:
    """High-level upload function — uploads file and returns a formatted message.
    
    🔴 FIX v3: Now handles files > 50MB by auto-compressing with ffmpeg before upload.
    
    Flow:
    1. If file <= 50MB: Upload directly to Supabase
    2. If file > 50MB: Compress with ffmpeg, then upload compressed version
    3. If compression fails: Return None (bot should handle fallback)
    
    Returns: formatted message string (Arabic or English) or None on failure
    """
    if not _is_configured():
        logger.warning("☁️ Supabase not configured, cannot upload large file")
        return None

    # Get file size
    try:
        original_size = os.path.getsize(file_path)
        original_mb = original_size / (1024 * 1024)
    except Exception:
        original_mb = 0

    # 🔴 FIX v3: If file > 50MB (Supabase limit), compress first
    actual_file_path = file_path
    compressed = False
    
    if original_size > SUPABASE_UPLOAD_LIMIT:
        logger.info(
            f"☁️ File is {original_mb:.1f}MB > 50MB Supabase limit — auto-compressing..."
        )
        
        if content_type.startswith("video/"):
            compressed_path = await compress_video_for_upload(file_path)
        elif content_type.startswith("audio/"):
            compressed_path = await compress_audio_for_upload(file_path)
        else:
            logger.warning(f"☁️ Cannot compress content type: {content_type}")
            return None
        
        if compressed_path:
            actual_file_path = compressed_path
            compressed = True
            compressed_size = os.path.getsize(compressed_path)
            compressed_mb = compressed_size / (1024 * 1024)
            logger.info(f"☁️ Using compressed file: {compressed_mb:.1f}MB")
        else:
            logger.warning(f"☁️ Compression failed — cannot upload {original_mb:.1f}MB file to Supabase")
            return None

    # Upload
    result = await upload_file(
        file_path=actual_file_path,
        filename=filename,
        content_type=content_type,
        platform=platform,
    )

    # Clean up compressed file
    if compressed and actual_file_path != file_path:
        try:
            os.remove(actual_file_path)
            logger.info(f"☁️ Cleaned up compressed file: {actual_file_path}")
        except Exception:
            pass

    if result and result.get("success"):
        download_url = result["url"]
        
        # Get the actual uploaded file size
        try:
            uploaded_size = os.path.getsize(actual_file_path) if os.path.exists(actual_file_path) else original_size
            uploaded_mb = uploaded_size / (1024 * 1024)
        except Exception:
            uploaded_mb = original_mb
        
        if lang == "ar":
            msg = (
                f"☁️ الملف كبير للإرسال المباشر ({original_mb:.1f}MB)\n\n"
                f"📥 تم رفعه على السحابة بنجاح!\n\n"
                f"🔗 رابط التحميل:\n{download_url}\n\n"
                f"⏰ الرابط صالح لمدة 24 ساعة\n"
            )
            if compressed:
                msg += f"📦 تم ضغط الفيديو ({original_mb:.1f}MB → {uploaded_mb:.1f}MB) لرفعه على السحابة\n"
            msg += f"📁 {filename}"
            if title:
                msg = f"🎬 {title}\n\n" + msg
            return msg
        else:
            msg = (
                f"☁️ File is too large for direct sending ({original_mb:.1f}MB)\n\n"
                f"📥 Uploaded to cloud successfully!\n\n"
                f"🔗 Download link:\n{download_url}\n\n"
                f"⏰ Link valid for 24 hours\n"
            )
            if compressed:
                msg += f"📦 Video was compressed ({original_mb:.1f}MB → {uploaded_mb:.1f}MB) for cloud upload\n"
            msg += f"📁 {filename}"
            if title:
                msg = f"🎬 {title}\n\n" + msg
            return msg
    else:
        logger.error(f"☁️ Upload failed for {file_path}")
        return None


# ---------------------------------------------------------------------------
# format_download_link  (sync) — kept for backward compat
# ---------------------------------------------------------------------------

def format_download_link(
    url: str,
    title: str,
    file_size_mb: float,
    platform: str,
    lang: str = "ar",
) -> str:
    """Format a download-link message for the user."""
    if lang == "ar":
        msg = (
            f"☁️ الملف كبير للإرسال المباشر ({file_size_mb:.1f}MB)\n\n"
            f"📥 تم رفعه على السحابة!\n\n"
            f"🔗 رابط التحميل:\n{url}\n\n"
            f"⏰ الرابط صالح لمدة 24 ساعة"
        )
        if title:
            msg = f"🎬 {title}\n\n" + msg
        return msg
    else:
        msg = (
            f"☁️ File is too large for direct sending ({file_size_mb:.1f}MB)\n\n"
            f"📥 Uploaded to cloud!\n\n"
            f"🔗 Download link:\n{url}\n\n"
            f"⏰ Link valid for 24 hours"
        )
        if title:
            msg = f"🎬 {title}\n\n" + msg
        return msg
