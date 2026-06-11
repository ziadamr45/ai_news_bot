"""
Supabase Storage integration module for the My Bro bot project.

Handles uploading, deleting, and managing files in Supabase Storage.
Uses aiohttp for async HTTP requests and SERVICE_ROLE_KEY for authentication.

🔴 FIX v2:
- Bucket name: "Downloads" (capital D) — NOT "downloads"
- SUPABASE_URL handling: strip /rest/v1/ if present (Railway env var may include it)
- Stream-based upload for large files (avoids OOM on 100MB+ files)
- Proper timeout handling for uploads
- Better error messages and Arabic UX
"""

import os
import logging
import re
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
MAX_FILE_SIZE: int = 2 * 1024 * 1024 * 1024  # 2 GB

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

# Log config on module load
_log_config_status()


# ---------------------------------------------------------------------------
# Public URL
# ---------------------------------------------------------------------------

def get_public_url(storage_path: str) -> str:
    """Generate a public URL for a file stored in Supabase Storage."""
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"


# ---------------------------------------------------------------------------
# Upload helpers — Stream-based for large files
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


async def _do_upload_stream(
    storage_path: str,
    file_path: str,
    content_type: str,
    file_size: int,
) -> dict | None:
    """Stream-based upload for large files — reads file in chunks to avoid OOM.

    🔴 Instead of loading the entire file into memory, we stream it directly.
    This is critical for files > 100MB.
    """
    if not _is_configured():
        logger.warning("☁️ Supabase is not configured; skipping upload")
        return None

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
        "Content-Length": str(file_size),
    }

    logger.info(f"☁️ Stream upload started → {storage_path} ({file_size / (1024*1024):.1f}MB)")

    timeout = aiohttp.ClientTimeout(total=UPLOAD_TIMEOUT)

    CHUNK_SIZE = 1024 * 1024  # 1MB chunks

    async def _file_generator():
        """Async generator that reads the file in chunks."""
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                upload_url,
                headers=headers,
                data=_file_generator(),
            ) as resp:
                if resp.status in (200, 201):
                    public_url = get_public_url(storage_path)
                    logger.info(f"☁️ Stream upload completed → {storage_path} (URL: {public_url})")
                    return {
                        "success": True,
                        "url": public_url,
                        "storage_path": storage_path,
                        "file_size": file_size,
                    }
                else:
                    body = await resp.text()
                    logger.warning(
                        f"☁️ Stream upload failed → {storage_path} (status={resp.status}, body={body})"
                    )
                    return None
    except asyncio.TimeoutError:
        logger.error(f"☁️ Stream upload timed out → {storage_path} (timeout={UPLOAD_TIMEOUT}s)")
        return None
    except Exception:
        logger.exception(f"☁️ Stream upload exception → {storage_path}")
        return None


# Need asyncio import for TimeoutError
import asyncio


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

    🔴 FIX v2: Uses stream-based upload for files > 50MB to avoid OOM.

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

    if file_size > MAX_FILE_SIZE:
        logger.warning(f"☁️ File exceeds 2 GB limit ({file_size} bytes): {file_path}")
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

    # --- Choose upload method based on file size ---
    STREAM_THRESHOLD = 50 * 1024 * 1024  # 50MB — use stream above this

    if file_size > STREAM_THRESHOLD:
        # 🔴 Large file — stream upload (avoids OOM)
        result = await _do_upload_stream(storage_path, file_path, content_type, file_size)
    else:
        # Small file — regular upload (loads into memory)
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

    if file_size > MAX_FILE_SIZE:
        logger.warning(f"☁️ Byte payload exceeds 2 GB limit ({file_size} bytes)")
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
    """Return ``True`` if *file_size* exceeds the direct-sending limit for *platform*.

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

    🔴 This is what the bots should call. It:
    1. Uploads the file to Supabase Storage
    2. Returns a formatted message with the download link
    3. Returns None if upload fails

    Returns: formatted message string (Arabic or English) or None on failure
    """
    if not _is_configured():
        logger.warning("☁️ Supabase not configured, cannot upload large file")
        if lang == "ar":
            return None  # Bot will handle the fallback
        return None

    # Get file size for the message
    try:
        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)
    except Exception:
        size_mb = 0

    # Upload
    result = await upload_file(
        file_path=file_path,
        filename=filename,
        content_type=content_type,
        platform=platform,
    )

    if result and result.get("success"):
        download_url = result["url"]
        if lang == "ar":
            msg = (
                f"☁️ الملف كبير للإرسال المباشر ({size_mb:.1f}MB)\n\n"
                f"📥 تم رفعه على السحابة بنجاح!\n\n"
                f"🔗 رابط التحميل:\n{download_url}\n\n"
                f"⏰ الرابط صالح لمدة 24 ساعة\n"
                f"📁 {filename}"
            )
            if title:
                msg = f"🎬 {title}\n\n" + msg
            return msg
        else:
            msg = (
                f"☁️ File is too large for direct sending ({size_mb:.1f}MB)\n\n"
                f"📥 Uploaded to cloud successfully!\n\n"
                f"🔗 Download link:\n{download_url}\n\n"
                f"⏰ Link valid for 24 hours\n"
                f"📁 {filename}"
            )
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
