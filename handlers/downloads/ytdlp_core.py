"""Backward-compatibility shim — re-exports everything from the ytdlp package.

This file exists so that existing code using:
    from handlers.downloads.ytdlp_core import X
continues to work after the split into handlers.downloads.ytdlp.*.
"""

from handlers.downloads.ytdlp import *  # noqa: F401,F403
