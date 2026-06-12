"""Download handlers - now split into handlers/downloads/ package.

All symbols are re-exported here for backward compatibility.
Any code doing `from handlers.download_handlers import X` will still work.
"""
from handlers.downloads import *  # noqa: F401,F403
