"""ytdlp package — split from ytdlp_core.py for maintainability.

Re-exports all public names from sub-modules for backward compatibility.
"""

# ═══════════════════════════════════════════════════════════════
# From update.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.ytdlp.update import (
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
)

# ═══════════════════════════════════════════════════════════════
# From commands.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.ytdlp.commands import (
    # Download commands
    download_command,
    _process_download_request,
    _download_direct_image,
    _download_direct_audio,
)

# ═══════════════════════════════════════════════════════════════
# From cobalt.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.ytdlp.cobalt import (
    # Cobalt helpers
    _try_cobalt_for_youtube,
    _cobalt_api_request,
    _try_cobalt_download,
)

# ═══════════════════════════════════════════════════════════════
# From options.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.ytdlp.options import (
    # yt-dlp options
    _get_ydl_opts,
)

# ═══════════════════════════════════════════════════════════════
# From download_main.py
# ═══════════════════════════════════════════════════════════════
from handlers.downloads.ytdlp.download_main import (
    # Main download function
    _download_with_ytdlp,
)

# Explicit __all__ for `from handlers.downloads.ytdlp import *`
__all__ = [
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
]
