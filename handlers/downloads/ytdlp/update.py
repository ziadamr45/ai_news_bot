"""yt-dlp auto-update management.

Functions for logging version, performing updates, and periodic background updates.
"""

import logging
import subprocess
import time

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# 🔴 yt-dlp Auto-Update System v2
# - يتحدث تلقائيًا كل ساعة
# - يتحدث فورًا لو YouTube رفض التحميل (bot detection)
# - يتحدث عند تشغيل البوت
# - بيستخدم --break-system-packages عشان Railway
# ═══════════════════════════════════════

_ytdlp_last_update_time = 0        # آخر مرة اتحديث فيها
_YTDLP_UPDATE_INTERVAL = 3600      # كل ساعة (3600 ثانية)
_ytdlp_updating = False            # منع تحديثات متزامنة


def _log_ytdlp_version():
    """تسجيل نسخة yt-dlp عشان نعرف لو محتاجة تحديث"""
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
        logger.info(f"📦 yt-dlp version: {version}")
        return version
    except Exception:
        try:
            result = subprocess.run(
                ['yt-dlp', '--version'],
                capture_output=True, timeout=5, text=True
            )
            logger.info(f"📦 yt-dlp CLI version: {result.stdout.strip()}")
            return result.stdout.strip()
        except Exception:
            logger.warning("📦 yt-dlp version could not be determined")
            return "unknown"


def _do_ytdlp_update(reason: str = "scheduled") -> bool:
    """تحديث yt-dlp — يرجع True لو اتحديث فعلًا"""
    global _ytdlp_last_update_time, _ytdlp_updating
    
    if _ytdlp_updating:
        logger.info(f"📦 yt-dlp update already in progress, skipping ({reason})")
        return False
    
    _ytdlp_updating = True
    try:
        import yt_dlp
        current_version = getattr(yt_dlp.version, '__version__', '0')
        logger.info(f"📦 yt-dlp auto-update ({reason}): current={current_version}")
        
        # التحديث باستخدام pip مع --break-system-packages (مهم لـ Railway)
        result = subprocess.run(
            [subprocess.sys.executable, '-m', 'pip', 'install', '--upgrade', 
             'yt-dlp', '--break-system-packages'],
            capture_output=True, timeout=180, text=True
        )
        
        _ytdlp_last_update_time = time.time()
        
        if result.returncode == 0:
            # نتحقق لو فعلًا اتحديث
            try:
                # لازم نعمل reload عشان النسخة الجديدة تشتغل
                import importlib
                importlib.reload(yt_dlp)
                new_version = getattr(yt_dlp.version, '__version__', 'unknown')
            except Exception:
                new_version = _log_ytdlp_version()
            
            if new_version != current_version:
                logger.info(f"📦 ✅ yt-dlp UPDATED: {current_version} → {new_version} ({reason})")
                return True
            else:
                logger.info(f"📦 yt-dlp already up to date: {current_version} ({reason})")
                return False
        else:
            logger.warning(f"📦 yt-dlp auto-update failed: {result.stderr[:300]}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"📦 yt-dlp auto-update timed out ({reason})")
        return False
    except Exception as e:
        logger.warning(f"📦 yt-dlp auto-update error: {e}")
        return False
    finally:
        _ytdlp_updating = False


def _auto_update_ytdlp():
    """تحديث yt-dlp عند تشغيل البوت"""
    _do_ytdlp_update(reason="startup")


def _ytdlp_periodic_updater():
    """تحديث yt-dlp كل ساعة في الـ background"""
    while True:
        time.sleep(_YTDLP_UPDATE_INTERVAL)
        try:
            _do_ytdlp_update(reason="hourly")
        except Exception as e:
            logger.warning(f"📦 yt-dlp periodic update error: {e}")


def trigger_ytdlp_update():
    """تحديث yt-dlp فورًا — يتنادي لو YouTube رفض التحميل
    
    يستخدمها الكود لو شاف خطأ bot detection أو sign in
    """
    import threading as _th
    _th.Thread(target=_do_ytdlp_update, args=("bot_detection",), daemon=True).start()


def should_update_ytdlp() -> bool:
    """هل محتاجين نحدث yt-dlp؟ — بنستخدمها لو التحميل فشل عشان نشوف السبب"""
    time_since_update = time.time() - _ytdlp_last_update_time
    return time_since_update > _YTDLP_UPDATE_INTERVAL


# تسجيل النسخ + تحديث تلقائي عند تشغيل الموديول
try:
    _log_ytdlp_version()
except Exception:
    pass

# 🔴 تحديث yt-dlp في الـ background عند التشغيل
import threading
try:
    _update_thread = threading.Thread(target=_auto_update_ytdlp, daemon=True)
    _update_thread.start()
    logger.info("📦 yt-dlp startup update started in background")
except Exception:
    pass

# 🔴 تحديث دوري كل ساعة في الـ background
try:
    _periodic_thread = threading.Thread(target=_ytdlp_periodic_updater, daemon=True)
    _periodic_thread.start()
    logger.info(f"📦 yt-dlp periodic updater started (every {_YTDLP_UPDATE_INTERVAL}s)")
except Exception:
    pass
