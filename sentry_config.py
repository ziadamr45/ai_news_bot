"""
Sentry Observability Configuration
====================================
Centralized Sentry SDK setup for the entire bot.

- Automatic error capture (unhandled exceptions)
- Performance monitoring (optional, low sample rate)
- Structured breadcrumbs for key events
- Tag-based filtering (platform, environment, version)
- Integration with existing error_monitor.py (dual reporting)
- Telegram alert forwarding (critical errors → developer's Telegram)

Usage:
    # At the very top of your entry point (bot.py, etc.):
    from sentry_config import init_sentry
    init_sentry()

    # Capture errors manually:
    from sentry_config import capture_exception, capture_message, set_tag, add_breadcrumb

Environment Variables:
    SENTRY_DSN       — Required. Your Sentry project DSN.
    SENTRY_ENV       — Optional. Environment name (production, staging, development). Default: "production"
    SENTRY_TRACES    — Optional. Sample rate for performance (0.0 to 1.0). Default: "0.1" (10%)
    SENTRY_PROFILES  — Optional. Sample rate for profiling (0.0 to 1.0). Default: "0.1" (10%)
"""

import os
import logging
import traceback

logger = logging.getLogger(__name__)

# ── State ──────────────────────────────────────────────────────────────
_sentry_initialized = False

# ── Telegram Alert Throttling ──────────────────────────────────────────
# Prevent spamming the developer with the same error repeatedly
_last_telegram_alert_time = {}  # {error_signature: last_sent_timestamp}
_TELEGRAM_ALERT_COOLDOWN = 300  # 5 minutes between same-error alerts
_TELEGRAM_ALERT_ENABLED = os.environ.get("SENTRY_TELEGRAM_ALERTS", "1") == "1"


def _send_telegram_alert(exc: BaseException, context: dict | None = None):
    """
    Send error alert to developer's Telegram chat.
    Uses rate-limiting to avoid spam — same error type won't be sent
    more than once every 5 minutes.
    """
    if not _TELEGRAM_ALERT_ENABLED:
        return

    import time as _time

    # Rate-limit: same error type → max once every 5 minutes
    error_sig = f"{type(exc).__name__}:{str(exc)[:100]}"
    now = _time.time()
    last_sent = _last_telegram_alert_time.get(error_sig, 0)
    if now - last_sent < _TELEGRAM_ALERT_COOLDOWN:
        return  # Skip — already sent recently

    _last_telegram_alert_time[error_sig] = now

    try:
        from config import BOT_TOKEN, DEVELOPER_USER_ID

        # Build a clean alert message
        exc_type = type(exc).__name__
        exc_msg = str(exc)[:200]

        # Get the most relevant frame (last frame in our code)
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        # Take last 3 lines of traceback for brevity
        tb_short = "".join(tb_lines[-3:]).strip()[:500]

        # Context info
        ctx_str = ""
        if context:
            ctx_parts = [f"{k}={v}" for k, v in list(context.items())[:5]]
            ctx_str = "\n📊 ".join([""] + ctx_parts)

        alert_msg = (
            f"🚨 <b>Sentry Alert</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"❌ <b>{exc_type}</b>: {exc_msg}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"<code>{tb_short}</code>"
            f"{ctx_str}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🔍 <a href=\"https://qudra-tech-d0.sentry.io\">Open Sentry Dashboard</a>"
        )

        # Send via Telegram Bot API (fire-and-forget)
        import requests
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": DEVELOPER_USER_ID,
            "text": alert_msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        # 3 second timeout, don't wait for response
        try:
            requests.post(url, json=payload, timeout=3)
        except Exception:
            pass  # Don't let Telegram alert failure break anything

    except Exception as e:
        # Never let alert sending break the main flow
        logger.debug(f"Telegram alert failed: {e}")


def init_sentry() -> bool:
    """
    Initialize Sentry SDK if SENTRY_DSN is configured.

    Returns True if Sentry was initialized, False otherwise.
    Safe to call multiple times — will only init once.
    """
    global _sentry_initialized
    if _sentry_initialized:
        return True

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("🐦 Sentry: No SENTRY_DSN configured — observability disabled")
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("🐦 Sentry: sentry-sdk not installed — pip install sentry-sdk")
        return False

    # ── Configuration ──────────────────────────────────────────────────
    environment = os.environ.get("SENTRY_ENV", "production").strip()
    traces_sample_rate = float(os.environ.get("SENTRY_TRACES", "0.1"))
    profiles_sample_rate = float(os.environ.get("SENTRY_PROFILES", "0.1"))

    # Clamp sample rates to valid range
    traces_sample_rate = max(0.0, min(1.0, traces_sample_rate))
    profiles_sample_rate = max(0.0, min(1.0, profiles_sample_rate))

    try:
        # Import version info lazily — config.py may not be fully loaded yet
        try:
            from config import BOT_NAME, BOT_VERSION
            release = f"{BOT_NAME.lower().replace(' ', '-')}@{BOT_VERSION}"
        except Exception:
            release = "ai-news-bot@unknown"

        # Custom before_send hook — forwards critical errors to Telegram
        def _before_send(event, hint):
            """Forward captured exceptions to Telegram for instant alerts."""
            try:
                if hint.get("exc_info"):
                    exc_type, exc_value, exc_tb = hint["exc_info"]
                    if exc_value and isinstance(exc_value, Exception):
                        # Build context from event tags/extra
                        ctx = {}
                        tags = event.get("tags", {})
                        if tags:
                            ctx.update(dict(tags[:5]) if isinstance(tags, list) else dict(list(tags.items())[:5]))
                        _send_telegram_alert(exc_value, context=ctx if ctx else None)
            except Exception:
                pass  # Never break event sending
            return event

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            # Don't send PII (phone numbers, chat IDs, etc.)
            send_default_pii=False,
            # Attach stack traces to all log messages
            attach_stacktrace=True,
            # Forward errors to Telegram before sending to Sentry
            before_send=_before_send,
            # Integration defaults are fine:
            #   - auto-enabling LoggingIntegration
            #   - auto-enabling AioHttpIntegration (for WhatsApp webhook)
            #   - auto-enabling ThreadPoolIntegration
        )

        # Set useful global tags
        sentry_sdk.set_tag("bot_platform", "telegram+whatsapp")
        sentry_sdk.set_tag("runtime", "railway")

        _sentry_initialized = True
        logger.info(
            f"🐦 Sentry: Initialized ✓ | env={environment} | "
            f"traces={traces_sample_rate:.0%} | profiles={profiles_sample_rate:.0%} | "
            f"release={release}"
        )
        return True

    except Exception as e:
        logger.warning(f"🐦 Sentry: Failed to initialize — {e}")
        return False


# ── Convenience Wrappers ───────────────────────────────────────────────
# These are safe to call even if Sentry is not initialized.

def capture_exception(exc: BaseException, **kwargs) -> str | None:
    """Capture an exception in Sentry + forward to Telegram. Returns event_id or None."""
    # Always try Telegram alert (even if Sentry is not initialized)
    _send_telegram_alert(exc, context=kwargs.get("context"))

    if not _sentry_initialized:
        return None
    try:
        import sentry_sdk
        return sentry_sdk.capture_exception(exc, **kwargs)
    except Exception:
        return None


def capture_message(msg: str, level: str = "info", **kwargs) -> str | None:
    """Capture a message in Sentry. Returns event_id or None."""
    if not _sentry_initialized:
        return None
    try:
        import sentry_sdk
        return sentry_sdk.capture_message(msg, level=level, **kwargs)
    except Exception:
        return None


def set_tag(key: str, value: str) -> None:
    """Set a tag on all future Sentry events."""
    if not _sentry_initialized:
        return
    try:
        import sentry_sdk
        sentry_sdk.set_tag(key, value)
    except Exception:
        pass


def set_context(name: str, data: dict) -> None:
    """Set context data (appears in event details)."""
    if not _sentry_initialized:
        return
    try:
        import sentry_sdk
        sentry_sdk.set_context(name, data)
    except Exception:
        pass


def add_breadcrumb(
    category: str,
    message: str,
    level: str = "info",
    data: dict | None = None,
) -> None:
    """Add a breadcrumb trail to Sentry events."""
    if not _sentry_initialized:
        return
    try:
        import sentry_sdk
        sentry_sdk.add_breadcrumb(
            category=category,
            message=message,
            level=level,
            data=data or {},
        )
    except Exception:
        pass


def start_transaction(name: str, op: str = "task"):
    """Start a Sentry performance transaction. Returns a no-op if not initialized."""
    if not _sentry_initialized:
        return _NoOpTransaction()
    try:
        import sentry_sdk
        return sentry_sdk.start_transaction(name=name, op=op)
    except Exception:
        return _NoOpTransaction()


class _NoOpTransaction:
    """Fallback when Sentry is not initialized — all calls are no-ops."""
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def finish(self, *args):
        pass
    def set_status(self, *args):
        pass
    def set_tag(self, *args):
        pass
    def set_data(self, *args):
        pass


# ── Integration with existing error_monitor.py ─────────────────────────
async def record_error_and_sentry(error_type: str, error_msg: str = "", exc: BaseException | None = None):
    """
    Record error in both the existing error_monitor AND Sentry.
    Use this as a drop-in replacement for error_monitor.record_error().
    """
    # 1. Existing in-memory error tracking
    try:
        from handlers.error_monitor import record_error
        await record_error(error_type, error_msg)
    except Exception:
        pass

    # 2. Sentry capture + Telegram alert
    if exc is not None:
        set_context("error_detail", {"error_type": error_type, "error_msg": error_msg[:500]})
        capture_exception(exc)
    elif error_msg:
        capture_message(f"[{error_type}] {error_msg[:200]}", level="error")
