"""
Webhook Server — Handlers, Health Check, Debug, and Server Factory
====================================================================
Extracted from whatsapp/callbacks.py — contains:
- root_handler: Root path endpoint
- webhook_verification: Meta verification endpoint
- webhook_receiver: Receive incoming WhatsApp messages
- process_webhook_body: Synchronous webhook body processor
- health_check: Health check endpoint with DB diagnostics
- debug_whatsapp: Full diagnostic endpoint
- debug_whatsapp_activity: Recent webhook activity endpoint
- create_webhook_app: Webhook app factory
- start_webhook_server: Start the webhook HTTP server
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from aiohttp import web

from whatsapp.state import (
    ADMIN_WA_ID,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_VERIFY_TOKEN,
    WHATSAPP_APP_SECRET,
    WEBHOOK_PORT,
    ALLOWED_WA_NUMBERS,
    _log_event,
    _log_activity,
    _verify_signature,
    _COMMAND_TRIGGERS,
    _webhook_activity_log,
)

from whatsapp.callbacks.message_handler import _handle_incoming_message

logger = logging.getLogger(__name__)


async def root_handler(request: web.Request):
    """Root path — redirect to health check or show basic info"""
    return web.json_response({
        "service": "My Bro — WhatsApp & Telegram AI Bot",
        "version": "4.0",
        "endpoints": {
            "webhook_verification": "GET /whatsapp/webhook",
            "webhook_messages": "POST /whatsapp/webhook",
            "health": "GET /health",
            "diagnostics": "GET /debug/whatsapp",
            "activity_log": "GET /debug/whatsapp/activity",
        },
        "status": "running",
    })


# ═══════════════════════════════════════
# GET /whatsapp/webhook — Meta Verification
# ═══════════════════════════════════════

async def webhook_verification(request: web.Request):
    """Meta verification endpoint."""
    mode = request.query.get("hub.mode", "")
    token = request.query.get("hub.verify_token", "")
    challenge = request.query.get("hub.challenge", "")

    _log_event("IN", "verification_attempt", {
        "mode": mode,
        "token_provided": bool(token),
        "challenge_provided": bool(challenge),
    })

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully!")
        _log_event("OUT", "verification_success", {"challenge": challenge})
        return web.Response(text=challenge, status=200)

    logger.warning(f"❌ WhatsApp webhook verification failed!")
    _log_event("OUT", "verification_failed", {"mode": mode})
    return web.Response(text="Forbidden", status=403)


# ═══════════════════════════════════════
# POST /whatsapp/webhook — Incoming Messages
# ═══════════════════════════════════════

async def webhook_receiver(request: web.Request):
    """Receive incoming WhatsApp messages and status updates."""
    try:
        payload = await request.read()

        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(payload, signature):
            logger.warning(f"❌ Invalid webhook signature")
            _log_activity("signature_failed", {"signature_present": bool(signature), "app_secret_set": bool(WHATSAPP_APP_SECRET)}, "failed")
            return web.Response(text="Unauthorized", status=401)

        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            return web.Response(text="Bad Request", status=400)

        has_messages = False
        has_statuses = False
        try:
            has_messages = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages"))
            has_statuses = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"))
        except (IndexError, KeyError, TypeError):
            pass

        _log_event("IN", "webhook_event", {
            "keys": list(body.keys()),
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
        })

        _log_activity("webhook_post", {
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
            "payload_size": len(payload),
        }, "received")

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    messages = value.get("messages", [])
                    if messages:
                        for message in messages:
                            asyncio.create_task(_handle_incoming_message(message, value))

                    statuses = value.get("statuses", [])
                    if statuses:
                        for status in statuses:
                            _log_event("IN", "status_update", {
                                "message_id": status.get("id"),
                                "status": status.get("status"),
                                "timestamp": status.get("timestamp"),
                                "recipient_id": status.get("recipient_id"),
                            })

                    errors = value.get("errors", [])
                    if errors:
                        for error in errors:
                            logger.error(f"❌ WhatsApp API Error: {error}")
                            _log_event("IN", "api_error", error)
        else:
            logger.warning(f"⚠️ Unknown webhook object type: {body.get('object')}")

        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)
        # 🐦 Sentry — capture webhook processing errors
        from sentry_config import capture_exception, set_context
        set_context("webhook", {"error_type": "webhook_receiver"})
        capture_exception(e)
        return web.Response(text="OK", status=200)


def process_webhook_body(body: dict):
    """Synchronous entry point for processing WhatsApp webhook bodies.
    
    Called from bot.py's simple HTTP server when a POST /whatsapp/webhook
    is received. Processes the webhook body synchronously using the same
    logic as webhook_receiver but without the aiohttp request/response.
    
    Note: This skips signature verification since the simple HTTP server
    handles that separately. The WhatsApp webhook aiohttp server (if running)
    still does full signature verification.
    """
    try:
        has_messages = False
        has_statuses = False
        try:
            has_messages = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages"))
            has_statuses = bool(body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses"))
        except (IndexError, KeyError, TypeError):
            pass

        _log_event("IN", "webhook_event_simple", {
            "object": body.get("object"),
            "has_messages": has_messages,
            "has_statuses": has_statuses,
        })

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    messages = value.get("messages", [])
                    if messages:
                        for message in messages:
                            # Schedule the async handler to run in the existing event loop
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.ensure_future(_handle_incoming_message(message, value), loop=loop)
                                else:
                                    loop.run_until_complete(_handle_incoming_message(message, value))
                            except RuntimeError:
                                # No event loop — create a new one
                                asyncio.run(_handle_incoming_message(message, value))

                    statuses = value.get("statuses", [])
                    if statuses:
                        for status in statuses:
                            _log_event("IN", "status_update", {
                                "message_id": status.get("id"),
                                "status": status.get("status"),
                                "timestamp": status.get("timestamp"),
                                "recipient_id": status.get("recipient_id"),
                            })

                    errors = value.get("errors", [])
                    if errors:
                        for error in errors:
                            logger.error(f"❌ WhatsApp API Error: {error}")
                            _log_event("IN", "api_error", error)
    except Exception as e:
        logger.error(f"❌ process_webhook_body error: {e}", exc_info=True)


async def health_check(request: web.Request):
    """Health check endpoint for Railway — includes DB diagnostics"""
    whatsapp_ok = bool(WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID)
    ai_ok = True
    try:
        from ai_engine import smart_chat
    except Exception:
        ai_ok = False

    # ═══ Database Diagnostics ═══
    db_info = {
        "connected": False,
        "type": "none",
        "persistent": False,
        "tables": {},
        "user_count": 0,
        "error": None,
    }
    try:
        from memory import _is_postgres, _db_type, _pg_pool, _execute
        db_info["type"] = _db_type or "none"
        db_info["connected"] = _db_type is not None
        db_info["persistent"] = _db_type == "postgresql"

        if _db_type == "postgresql":
            db_info["pool_size"] = f"1-3 (maxconn)" if _pg_pool else "N/A"
            # Quick connectivity test
            try:
                result = _execute("SELECT 1 as test", fetchone=True)
                db_info["query_test"] = "ok" if result else "no_result"
            except Exception as e:
                db_info["query_test"] = f"error: {str(e)[:100]}"

        # Count users and table sizes
        if _db_type:
            try:
                user_count = _execute("SELECT COUNT(*) FROM user_profiles", fetchone=True)
                db_info["user_count"] = user_count[0] if user_count else 0
            except Exception:
                pass

            # Table row counts
            for table_name in ['user_profiles', 'conversations', 'user_memories',
                               'learning_progress', 'favorites', 'banned_users']:
                try:
                    count = _execute(f"SELECT COUNT(*) FROM {table_name}", fetchone=True)
                    db_info["tables"][table_name] = count[0] if count else 0
                except Exception:
                    db_info["tables"][table_name] = "error"

            # Premium tables
            try:
                from premium import _is_postgres as _prem_is_pg
                for table_name in ['premium_users', 'usage_tracking', 'workspace_items', 'smart_alerts']:
                    try:
                        count = _execute(f"SELECT COUNT(*) FROM {table_name}", fetchone=True)
                        db_info["tables"][table_name] = count[0] if count else 0
                    except Exception:
                        db_info["tables"][table_name] = "error"
            except Exception:
                pass

        # Check DATABASE_URL availability (masked)
        import os
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            if "neon.tech" in db_url:
                db_info["url_type"] = "neon_postgresql"
            elif db_url.startswith("file:"):
                db_info["url_type"] = "sqlite_local"
            elif "postgresql" in db_url or "postgres://" in db_url:
                db_info["url_type"] = "postgresql_other"
            else:
                db_info["url_type"] = "unknown"
            db_info["url_masked"] = db_url[:25] + "***" + db_url[-15:] if len(db_url) > 40 else "***"
        else:
            db_info["url_type"] = "not_set"
            db_info["error"] = "DATABASE_URL environment variable is not set!"

    except Exception as e:
        db_info["error"] = f"Diagnostic error: {str(e)[:200]}"

    overall_status = "ok" if (whatsapp_ok and ai_ok and db_info["connected"]) else "degraded"
    if not db_info["connected"]:
        overall_status = "critical"

    return web.json_response({
        "status": overall_status,
        "whatsapp": whatsapp_ok,
        "ai": ai_ok,
        "database": db_info,
        "service": "my-bro-whatsapp-webhook",
        "version": "4.0",
        "features": [
            "ai_chat", "audio_transcription", "image_analysis",
            "interactive_buttons", "interactive_lists",
            "commands_full", "read_receipts", "thinking_reactions",
            "quick_action_buttons",
            "news", "breaking_news", "weekly_summary", "trending",
            "web_search", "ask", "learn", "roadmap",
            "company_info", "subscribe", "language",
            "memory", "premium", "settings",
            "study_mode", "quiz", "exam",
            "youtube_summary", "pdf_analysis",
            "image_generation", "image_editing",
            "download", "favorites",
            "admin_system", "ban_system", "broadcast",
            "usage_tracking", "plan_system",
        ],
        "commands_count": len(_COMMAND_TRIGGERS),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ═══════════════════════════════════════
# Debug / Diagnostic Endpoint
# ═══════════════════════════════════════

async def debug_whatsapp(request: web.Request):
    """GET /debug/whatsapp — Full diagnostic"""
    import aiohttp as aio

    verify_token_set = bool(WHATSAPP_VERIFY_TOKEN)
    access_token_set = bool(WHATSAPP_ACCESS_TOKEN)
    phone_number_id_set = bool(WHATSAPP_PHONE_NUMBER_ID)
    app_secret_set = bool(WHATSAPP_APP_SECRET)

    meta_api_status = "unknown"
    token_info = None
    phone_number_info = None

    if WHATSAPP_ACCESS_TOKEN:
        try:
            async with aio.ClientSession() as session:
                url = "https://graph.facebook.com/v21.0/me?fields=id,name"
                headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
                async with session.get(url, headers=headers, timeout=aio.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        token_info = {"app_id": data.get("id", "N/A"), "app_name": data.get("name", "N/A")}
                        meta_api_status = "ok"
                    else:
                        meta_api_status = f"error_{resp.status}"
        except Exception as e:
            meta_api_status = f"error: {str(e)[:100]}"
    else:
        meta_api_status = "not_configured"

    if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
        try:
            async with aio.ClientSession() as session:
                url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}"
                headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
                async with session.get(url, headers=headers, timeout=aio.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        phone_number_info = {
                            "verified_name": data.get("verified_name", "N/A"),
                            "display_phone_number": data.get("display_phone_number", "N/A"),
                            "quality_rating": data.get("quality_rating", "N/A"),
                        }
        except Exception:
            pass

    ai_engine_status = "unknown"
    try:
        from ai_engine import smart_chat
        ai_engine_status = "ok"
    except ImportError as e:
        ai_engine_status = f"import_error: {str(e)[:80]}"
    except Exception as e:
        ai_engine_status = f"error: {str(e)[:80]}"

    groq_status = "unknown"
    try:
        from config import GROQ_API_KEY
        groq_status = "ok" if GROQ_API_KEY else "not_configured"
    except Exception:
        groq_status = "error"

    premium_status = "unknown"
    try:
        from premium import get_user_plan
        premium_status = "ok"
    except Exception as e:
        premium_status = f"error: {str(e)[:80]}"

    admin_status = "unknown"
    try:
        from admin import is_admin
        admin_status = "ok"
    except Exception as e:
        admin_status = f"error: {str(e)[:80]}"

    response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "webhook": {
            "verify_token_set": verify_token_set,
            "app_secret_set": app_secret_set,
        },
        "tokens": {
            "WHATSAPP_ACCESS_TOKEN": "set" if access_token_set else "MISSING",
            "WHATSAPP_PHONE_NUMBER_ID": "set" if phone_number_id_set else "MISSING",
            "WHATSAPP_VERIFY_TOKEN": "set" if verify_token_set else "MISSING",
            "WHATSAPP_APP_SECRET": "set" if app_secret_set else "MISSING",
        },
        "token_info": token_info,
        "phone_number": phone_number_info,
        "meta_api": meta_api_status,
        "ai_engine": ai_engine_status,
        "groq_asr": groq_status,
        "premium_system": premium_status,
        "admin_system": admin_status,
        "admin_wa_id": ADMIN_WA_ID,
        "features": [
            "interactive_buttons", "commands", "read_receipts", "thinking_reactions",
            "audio_transcription", "image_analysis", "pdf_analysis",
            "premium_system", "admin_system", "ban_system", "usage_tracking",
            "study_mode", "youtube_summary", "download", "image_generation",
            "image_editing", "favorites", "memory_system",
        ],
        "allowed_numbers": ALLOWED_WA_NUMBERS if ALLOWED_WA_NUMBERS else "all (no restriction)",
        "diagnosis": [],
    }

    issues = []
    for var_name in ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN"]:
        raw_val = os.environ.get(var_name, "")
        if raw_val.upper() == "PENDING":
            issues.append(f"🔧 {var_name} is set to 'PENDING'")
    if not WHATSAPP_ACCESS_TOKEN:
        issues.append("❌ WHATSAPP_ACCESS_TOKEN is not set")
    if not WHATSAPP_PHONE_NUMBER_ID:
        issues.append("❌ WHATSAPP_PHONE_NUMBER_ID is not set")
    if not WHATSAPP_VERIFY_TOKEN:
        issues.append("❌ WHATSAPP_VERIFY_TOKEN is not set")
    if not WHATSAPP_APP_SECRET:
        issues.append("⚠️ WHATSAPP_APP_SECRET is not set")
    if not issues:
        issues.append("✅ All systems operational")

    response["diagnosis"] = issues
    return web.json_response(response, status=200)


async def debug_whatsapp_activity(request: web.Request):
    """GET /debug/whatsapp/activity — Recent webhook activity."""
    return web.json_response({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_events": len(_webhook_activity_log),
        "events": _webhook_activity_log[-20:],
        "summary": {
            "webhook_posts": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post"),
            "messages_received": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post" and e.get("data", {}).get("has_messages")),
            "status_updates": sum(1 for e in _webhook_activity_log if e["event_type"] == "webhook_post" and e.get("data", {}).get("has_statuses")),
            "signature_failures": sum(1 for e in _webhook_activity_log if e["event_type"] == "signature_failed"),
            "ai_responses_sent": sum(1 for e in _webhook_activity_log if e["event_type"] == "ai_response_sent"),
            "ai_errors": sum(1 for e in _webhook_activity_log if e["event_type"] == "ai_error"),
            "messages_skipped": sum(1 for e in _webhook_activity_log if e["event_type"] == "message_skipped"),
        },
    }, status=200)




# ═══════════════════════════════════════
# Web Server Factory
# ═══════════════════════════════════════

def create_webhook_app() -> web.Application:
    """Create the aiohttp web application with webhook routes"""
    app = web.Application()

    app.router.add_get("/", root_handler)
    app.router.add_get("/whatsapp/webhook", webhook_verification)
    app.router.add_post("/whatsapp/webhook", webhook_receiver)
    app.router.add_get("/health", health_check)
    app.router.add_get("/debug/whatsapp", debug_whatsapp)
    app.router.add_get("/debug/whatsapp/activity", debug_whatsapp_activity)
    logger.info("✅ WhatsApp webhook routes registered")
    logger.info(f"   GET  /whatsapp/webhook — Meta verification")
    logger.info(f"   POST /whatsapp/webhook — Incoming messages → AI engine")
    logger.info(f"   GET  /health — Health check")
    logger.info(f"   GET  /debug/whatsapp — Full diagnostic")
    logger.info(f"   GET  /debug/whatsapp/activity — Webhook activity log")
    logger.info(f"   🔥 AI Integration: smart_chat() with Arabic support")
    logger.info(f"   🎤 Audio: Groq Whisper transcription")
    logger.info(f"   👁️ Vision: Image analysis via NVIDIA/Mistral")
    logger.info(f"   📄 PDF: Document analysis")
    logger.info(f"   🔘 Interactive: Buttons & Lists (like Telegram keyboards)")
    logger.info(f"   📋 Commands: {len(_COMMAND_TRIGGERS)} triggers — full Telegram parity")
    logger.info(f"   💭 Thinking: Reactions only (💭 → ✅)")
    logger.info(f"   📰 News: daily, breaking, weekly, trending, company")
    logger.info(f"   📚 Learning: learn, roadmap, ask, search, study, quiz, exam")
    logger.info(f"   ⚙️ Settings: language, subscribe, memory, premium, plan")
    logger.info(f"   👑 Admin: grant, revoke, ban, unban, broadcast, stats")
    logger.info(f"   ⭐ Premium: plan system, usage tracking, limit enforcement")
    logger.info(f"   🎨 Image Gen & Edit: Premium features")
    logger.info(f"   📥 Download: YouTube/social media")
    logger.info(f"   🎬 YouTube: Summary")
    logger.info(f"   🧠 Memory: view, reset, favorites")
    logger.info(f"   📊 Usage: limits, remaining, plan display")

    logger.info(f"   📋 Config: VERIFY_TOKEN={'✅' if WHATSAPP_VERIFY_TOKEN else '❌'}, "
                f"ACCESS_TOKEN={'✅' if WHATSAPP_ACCESS_TOKEN else '❌'}, "
                f"PHONE_ID={'✅' if WHATSAPP_PHONE_NUMBER_ID else '❌'}, "
                f"APP_SECRET={'✅' if WHATSAPP_APP_SECRET else '⚠️ not set'}")
    logger.info(f"   🔒 Allowed numbers: {ALLOWED_WA_NUMBERS if ALLOWED_WA_NUMBERS else 'all (no restriction)'}")
    logger.info(f"   👑 Admin WA ID: {ADMIN_WA_ID}")

    return app


async def start_webhook_server():
    """Start the webhook HTTP server"""
    app = create_webhook_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()

    logger.info(f"🌐 WhatsApp webhook server listening on port {WEBHOOK_PORT}")
    logger.info(f"🤖 AI Engine: smart_chat() ready for WhatsApp messages!")

    return runner
