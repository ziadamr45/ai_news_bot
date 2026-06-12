"""Download handlers package - split from download_handlers.py for maintainability.

Re-exports everything for backward compatibility.
"""

# ═══════════════════════════════════════════════════════════════
# From utils.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.utils import (
    # Audio quality helpers
    _is_audio_quality,
    _get_audio_bitrate,
    _ensure_audio_only,
    _send_telegram_audio,

    # Cookies helpers
    _get_cookies_file,
    _cookies_status,
    _merge_cookies,
    _COOKIES_FILE,

    # Platform / URL detection
    _detect_platform,
    _is_direct_media_url,
    _extract_url,
    _is_threads_url,
    URL_PATTERNS,
    GENERAL_URL_PATTERN,
    IMAGE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    _USER_AGENT,
    _THREADS_URL_PATTERN,

    # FFmpeg
    _is_ffmpeg_available,
    _FFMPEG_AVAILABLE,

    # URL caching
    _store_url,
    _retrieve_url,
    _download_urls,
    _URL_CACHE_TTL,

    # Quality keyboards
    _get_quality_keyboard,
    _get_audio_quality_keyboard,

    # Cobalt / YouTube constants
    _COBALT_PUBLIC_API,
    _is_youtube_url,
    _YOUTUBE_URL_PATTERN,

    # Deno
    _DENO_PATH,
    _ensure_deno_in_path,

    # yt-dlp player clients
    _YOUTUBE_PLAYER_CLIENTS,
)

# ═══════════════════════════════════════════════════════════════
# From threads.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.threads import (
    _find_thread_items,
    _parse_threads_post,
    _threads_playwright_download,
    _download_threads_media,
    _threads_cobalt_download,
    _threads_download_media,
    _threads_rapidapi_download,
)

# ═══════════════════════════════════════════════════════════════
# From ytdlp_core.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.ytdlp_core import (
    # yt-dlp update management
    _log_ytdlp_version,
    _YTDLP_UPDATE_INTERVAL,
    _ytdlp_last_update_time,
    _ytdlp_updating,
    _do_ytdlp_update,
    _auto_update_ytdlp,
    _ytdlp_periodic_updater,
    trigger_ytdlp_update,
    should_update_ytdlp,

    # Download commands
    download_command,
    _process_download_request,
    _download_direct_image,
    _download_direct_audio,

    # Cobalt helpers
    _try_cobalt_for_youtube,
    _cobalt_api_request,
    _try_cobalt_download,

    # yt-dlp options
    _get_ydl_opts,

    # Main download function
    _download_with_ytdlp,
)

# ═══════════════════════════════════════════════════════════════
# From callbacks.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.callbacks import (
    handle_download_callback,
    cookies_command,
    handle_cookies_file,
)

# Explicit __all__ for `from handlers.downloads import *`
__all__ = [
    # Audio quality helpers
    "_is_audio_quality", "_get_audio_bitrate", "_ensure_audio_only", "_send_telegram_audio",
    # Cookies helpers
    "_get_cookies_file", "_cookies_status", "_merge_cookies", "_COOKIES_FILE",
    # Platform / URL detection
    "_detect_platform", "_is_direct_media_url", "_extract_url", "_is_threads_url",
    "URL_PATTERNS", "GENERAL_URL_PATTERN",
    "IMAGE_EXTENSIONS", "AUDIO_EXTENSIONS", "VIDEO_EXTENSIONS",
    "_USER_AGENT", "_THREADS_URL_PATTERN",
    # FFmpeg
    "_is_ffmpeg_available", "_FFMPEG_AVAILABLE",
    # URL caching
    "_store_url", "_retrieve_url", "_download_urls", "_URL_CACHE_TTL",
    # Quality keyboards
    "_get_quality_keyboard", "_get_audio_quality_keyboard",
    # Cobalt / YouTube constants
    "_COBALT_PUBLIC_API", "_is_youtube_url", "_YOUTUBE_URL_PATTERN",
    # Deno
    "_DENO_PATH", "_ensure_deno_in_path",
    # yt-dlp player clients
    "_YOUTUBE_PLAYER_CLIENTS",
    # Threads
    "_find_thread_items", "_parse_threads_post",
    "_threads_playwright_download", "_download_threads_media",
    "_threads_cobalt_download", "_threads_download_media", "_threads_rapidapi_download",
    # yt-dlp update management
    "_log_ytdlp_version", "_YTDLP_UPDATE_INTERVAL",
    "_ytdlp_last_update_time", "_ytdlp_updating",
    "_do_ytdlp_update", "_auto_update_ytdlp", "_ytdlp_periodic_updater",
    "trigger_ytdlp_update", "should_update_ytdlp",
    # Download commands
    "download_command", "_process_download_request",
    "_download_direct_image", "_download_direct_audio",
    # Cobalt helpers
    "_try_cobalt_for_youtube", "_cobalt_api_request", "_try_cobalt_download",
    # yt-dlp options
    "_get_ydl_opts",
    # Main download function
    "_download_with_ytdlp",
    # Callbacks and cookies command
    "handle_download_callback", "cookies_command", "handle_cookies_file",
]
