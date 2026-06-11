"""
Supabase Storage integration module for the My Bro bot project.

Handles uploading, deleting, and managing files in Supabase Storage.
Uses aiohttp for async HTTP requests and SERVICE_ROLE_KEY for authentication.
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
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET: str = os.environ.get("SUPABASE_BUCKET", "downloads")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_FILE_SIZE: int = 2 * 1024 * 1024 * 1024  # 2 GB

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


# ---------------------------------------------------------------------------
# Public URL
# ---------------------------------------------------------------------------

def get_public_url(storage_path: str) -> str:
    """Generate a public URL for a file stored in Supabase Storage."""
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------

async def _do_upload(
    storage_path: str,
    data: bytes,
    content_type: str,
) -> dict | None:
    """Core upload logic shared by *upload_file* and *upload_bytes*."""
    if not _is_configured():
        logger.warning("Supabase is not configured; skipping upload")
        return None

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
    }

    logger.info("Upload started → %s", storage_path)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url, headers=headers, data=data) as resp:
                if resp.status in (200, 201):
                    public_url = get_public_url(storage_path)
                    logger.info("Upload completed → %s (URL: %s)", storage_path, public_url)
                    return {
                        "success": True,
                        "url": public_url,
                        "storage_path": storage_path,
                        "file_size": len(data),
                    }
                else:
                    body = await resp.text()
                    logger.warning(
                        "Upload failed → %s (status=%d, body=%s)",
                        storage_path,
                        resp.status,
                        body,
                    )
                    return None
    except Exception:
        logger.exception("Upload exception → %s", storage_path)
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

    Returns ``{"success": True, "url": ..., "storage_path": ..., "file_size": ...}``
    on success, or ``None`` on failure.
    """
    if not _is_configured():
        logger.warning("Supabase is not configured; skipping upload")
        return None

    # --- Validate local file ---
    path = Path(file_path)
    if not path.exists():
        logger.warning("File does not exist: %s", file_path)
        return None

    file_size = path.stat().st_size
    if file_size == 0:
        logger.warning("File is empty: %s", file_path)
        return None

    if file_size > MAX_FILE_SIZE:
        logger.warning("File exceeds 2 GB limit (%d bytes): %s", file_size, file_path)
        return None

    # --- Validate content type ---
    if not _validate_content_type(content_type):
        logger.warning("Content type not allowed: %s", content_type)
        return None

    # --- Build storage path ---
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    unique_id = str(uuid4())[:8]
    safe_name = _sanitize_filename(filename)
    storage_path = f"{platform}/{date_str}/{unique_id}_{safe_name}"

    # --- Read & upload ---
    try:
        data = path.read_bytes()
    except Exception:
        logger.exception("Failed to read file: %s", file_path)
        return None

    result = await _do_upload(storage_path, data, content_type)
    if result is not None:
        logger.info("URL generated: %s", result["url"])
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
        logger.warning("Supabase is not configured; skipping upload")
        return None

    file_size = len(file_bytes)
    if file_size == 0:
        logger.warning("Byte payload is empty; skipping upload")
        return None

    if file_size > MAX_FILE_SIZE:
        logger.warning("Byte payload exceeds 2 GB limit (%d bytes)", file_size)
        return None

    if not _validate_content_type(content_type):
        logger.warning("Content type not allowed: %s", content_type)
        return None

    # --- Build storage path ---
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    unique_id = str(uuid4())[:8]
    safe_name = _sanitize_filename(filename)
    storage_path = f"{platform}/{date_str}/{unique_id}_{safe_name}"

    result = await _do_upload(storage_path, file_bytes, content_type)
    if result is not None:
        logger.info("URL generated: %s", result["url"])
    return result


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------

async def delete_file(storage_path: str) -> bool:
    """Delete a file from Supabase Storage. Returns ``True`` on success."""
    if not _is_configured():
        logger.warning("Supabase is not configured; skipping delete")
        return False

    delete_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }

    logger.info("Deleting file → %s", storage_path)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(delete_url, headers=headers) as resp:
                if resp.status in (200, 204):
                    logger.info("Deleted successfully → %s", storage_path)
                    return True
                else:
                    body = await resp.text()
                    logger.warning(
                        "Delete failed → %s (status=%d, body=%s)",
                        storage_path,
                        resp.status,
                        body,
                    )
                    return False
    except Exception:
        logger.exception("Delete exception → %s", storage_path)
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
        logger.warning("Supabase is not configured; skipping cleanup")
        return 0

    list_url = f"{SUPABASE_URL}/storage/v1/object/list/{SUPABASE_BUCKET}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    deleted = 0

    try:
        async with aiohttp.ClientSession() as session:
            # --- List top-level "platform" folders ---
            async with session.post(
                list_url,
                headers=headers,
                json={"prefix": "", "limit": 1000, "offset": 0},
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Cleanup: failed to list bucket (status=%d, body=%s)", resp.status, body)
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
                            logger.info("Cleanup: deleted expired file → %s", file_path)
                            deleted += 1

        logger.info("Cleanup complete: %d file(s) deleted", deleted)

    except Exception:
        logger.exception("Cleanup exception")

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
# format_download_link  (sync)
# ---------------------------------------------------------------------------

def format_download_link(
    url: str,
    title: str,
    file_size_mb: float,
    platform: str,
    lang: str = "ar",
) -> str:
    """Format a download-link message for the user.

    Currently the message does not embed *title*, *file_size_mb*, or *platform*
    in the output text (they are accepted for potential future use).
    """
    if lang == "ar":
        return (
            "📥 الملف كبير للإرسال المباشر.\n\n"
            f"🔗 رابط التحميل:\n{url}"
        )
    else:
        return (
            "📥 File is too large for direct sending.\n\n"
            f"🔗 Download link:\n{url}"
        )
