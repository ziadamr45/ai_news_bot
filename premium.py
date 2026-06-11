"""
نظام الاشتراك المتميز - Premium System
إدارة خطط Free و Premium و Premium+ مع تتبع الاستخدام
+ نظام Workspace (ملاحظات، ملفات، روابط، أبحاث)
+ نظام Smart Alerts (اشتراك في مواضيع + إشعارات)
"""

import logging
import os
import time as _time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# Timezone
CAIRO_TZ = timezone(timedelta(hours=2))

# ═══════════════════════════════════════
# ⚡ كاش خطة المستخدم - Plan Cache
 # ═══════════════════════════════════════
# بدل ما نعمل DB query مع كل رسالة، بنخزن الخطة في الذاكرة لمدة دقيقة
# ده بيقلل 10-15 DB query لكل رسالة!
_plan_cache: Dict[int, tuple] = {}  # {user_id: (plan, expiry_timestamp)}
_PLAN_CACHE_TTL = 60  # دقيقة واحدة

# كاش الاستخدام - Usage Cache
_usage_cache: Dict[int, tuple] = {}  # {user_id: (usage_dict, expiry_timestamp)}
_USAGE_CACHE_TTL = 30  # 30 ثانية

# ═══════════════════════════════════════
# حدود الخطط - Plan Limits
# ═══════════════════════════════════════

PLAN_LIMITS = {
    "free": {
        "ai_messages_per_day": 20,
        "pdf_analyses_per_day": 3,
        "image_analyses_per_day": 5,
        "youtube_summaries_per_day": 3,
        "searches_per_day": 5,
        "deep_searches_per_day": 0,  # Premium only
        "image_generations_per_day": 0,  # Premium only 🎨
        "image_edits_per_day": 0,  # Premium only 🖌️
        "downloads_per_day": 0,  # Premium only 📥 تحميل من أي منصة
        "video_searches_per_day": 0,  # Premium only 🎬 فيديو بالبحث
        "audio_searches_per_day": 0,  # Premium only 🎵 صوت بالبحث
        "photo_searches_per_day": 3,  # 🖼️ بحث صور — مجاني 3/يوم
        "study_mode": False,
        "long_term_memory": False,
        "voice_assistant": False,
        "priority_access": False,
        "premium_models": False,
        "workspace": False,
        "smart_alerts": False,
        "weekly_reports": False,
        "vision_pro": False,  # Premium vision features
        "image_gen": False,  # 🎨 إنشاء الصور — بريميوم بس
        "image_edit": False,  # 🖌️ تعديل الصور — بريميوم بس
    },
    "premium": {
        "ai_messages_per_day": -1,  # unlimited
        "pdf_analyses_per_day": -1,
        "image_analyses_per_day": -1,
        "youtube_summaries_per_day": -1,
        "searches_per_day": -1,
        "deep_searches_per_day": -1,
        "image_generations_per_day": -1,  # 🎨 إنشاء صور غير محدود
        "image_edits_per_day": -1,  # 🖌️ تعديل صور غير محدود
        "downloads_per_day": -1,  # 📥 تحميل غير محدود
        "video_searches_per_day": -1,  # 🎬 فيديو بالبحث غير محدود
        "audio_searches_per_day": -1,  # 🎵 صوت بالبحث غير محدود
        "photo_searches_per_day": -1,  # 🖼️ بحث صور غير محدود
        "study_mode": True,
        "long_term_memory": True,
        "voice_assistant": True,
        "priority_access": True,
        "premium_models": True,
        "workspace": True,
        "smart_alerts": True,
        "weekly_reports": True,
        "vision_pro": True,  # Premium vision features
        "image_gen": True,  # 🎨 إنشاء الصور
        "image_edit": True,  # 🖌️ تعديل الصور
    },
    "premium_plus": {
        # Future ready - same as premium for now
        "ai_messages_per_day": -1,
        "pdf_analyses_per_day": -1,
        "image_analyses_per_day": -1,
        "youtube_summaries_per_day": -1,
        "searches_per_day": -1,
        "deep_searches_per_day": -1,
        "image_generations_per_day": -1,
        "image_edits_per_day": -1,
        "downloads_per_day": -1,
        "video_searches_per_day": -1,
        "audio_searches_per_day": -1,
        "photo_searches_per_day": -1,
        "study_mode": True,
        "long_term_memory": True,
        "voice_assistant": True,
        "priority_access": True,
        "premium_models": True,
        "workspace": True,
        "smart_alerts": True,
        "weekly_reports": True,
        "vision_pro": True,
        "image_gen": True,
        "image_edit": True,
    }
}

DEVELOPER_TELEGRAM = "@ziadamr"
DEVELOPER_WHATSAPP = "01203551789"
DEVELOPER_WHATSAPP_URL = "https://wa.me/201203551789"


def _get_db():
    """Get database connection from memory module"""
    from memory import _get_db, _is_postgres, _execute
    return _get_db()


def _is_postgres():
    """Check if using PostgreSQL"""
    from memory import _is_postgres
    return _is_postgres()


def _execute(query, params=(), fetch=False, fetchone=False):
    """Execute query using memory module's database"""
    from memory import _execute
    return _execute(query, params, fetch=fetch, fetchone=fetchone)


def init_premium_tables():
    """Create premium-related tables"""
    try:
        if _is_postgres():
            _execute("""
                CREATE TABLE IF NOT EXISTS premium_users (
                    user_id BIGINT PRIMARY KEY,
                    plan TEXT DEFAULT 'free',
                    premium_since TEXT DEFAULT NULL,
                    premium_expires TEXT DEFAULT NULL,
                    granted_by TEXT DEFAULT NULL,
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS usage_tracking (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    date TEXT NOT NULL,
                    ai_messages INTEGER DEFAULT 0,
                    pdf_analyses INTEGER DEFAULT 0,
                    image_analyses INTEGER DEFAULT 0,
                    youtube_summaries INTEGER DEFAULT 0,
                    searches INTEGER DEFAULT 0,
                    deep_searches INTEGER DEFAULT 0,
                    UNIQUE(user_id, date),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS workspace_items (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                    updated_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS smart_alerts (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    topic TEXT NOT NULL,
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                    last_notified TEXT DEFAULT NULL,
                    UNIQUE(user_id, topic),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS premium_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    action TEXT NOT NULL,
                    plan_before TEXT DEFAULT 'free',
                    plan_after TEXT DEFAULT 'free',
                    granted_by TEXT DEFAULT NULL,
                    expires TEXT DEFAULT NULL,
                    created_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
                );
            """)
            _execute("CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_tracking(user_id, date);")
            _execute("CREATE INDEX IF NOT EXISTS idx_workspace_user ON workspace_items(user_id, item_type);")
            _execute("CREATE INDEX IF NOT EXISTS idx_alerts_user ON smart_alerts(user_id, active);")
            _execute("CREATE INDEX IF NOT EXISTS idx_premium_history_user ON premium_history(user_id, created_at DESC);")
        else:
            _execute("""
                CREATE TABLE IF NOT EXISTS premium_users (
                    user_id INTEGER PRIMARY KEY,
                    plan TEXT DEFAULT 'free',
                    premium_since TEXT DEFAULT NULL,
                    premium_expires TEXT DEFAULT NULL,
                    granted_by TEXT DEFAULT NULL,
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS usage_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    ai_messages INTEGER DEFAULT 0,
                    pdf_analyses INTEGER DEFAULT 0,
                    image_analyses INTEGER DEFAULT 0,
                    youtube_summaries INTEGER DEFAULT 0,
                    searches INTEGER DEFAULT 0,
                    deep_searches INTEGER DEFAULT 0,
                    UNIQUE(user_id, date),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS workspace_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS smart_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    last_notified TEXT DEFAULT NULL,
                    UNIQUE(user_id, topic),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                );
            """)
            _execute("""
                CREATE TABLE IF NOT EXISTS premium_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    plan_before TEXT DEFAULT 'free',
                    plan_after TEXT DEFAULT 'free',
                    granted_by TEXT DEFAULT NULL,
                    expires TEXT DEFAULT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                );
            """)
            _execute("CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_tracking(user_id, date);")
            _execute("CREATE INDEX IF NOT EXISTS idx_workspace_user ON workspace_items(user_id, item_type);")
            _execute("CREATE INDEX IF NOT EXISTS idx_alerts_user ON smart_alerts(user_id, active);")
            _execute("CREATE INDEX IF NOT EXISTS idx_premium_history_user ON premium_history(user_id, created_at DESC);")

        # Migration: إضافة عمود deep_searches لو مش موجود
        _migrate_add_deep_searches()
        # Migration: إضافة أعمدة image_generations و image_edits
        _migrate_add_image_gen_edits()

        logger.info("✅ Premium tables initialized")
    except Exception as e:
        logger.warning(f"Premium tables init error (may already exist): {e}")


def _migrate_add_image_gen_edits():
    """إضافة أعمدة image_generations و image_edits في usage_tracking"""
    try:
        if _is_postgres():
            _execute("ALTER TABLE usage_tracking ADD COLUMN IF NOT EXISTS image_generations INTEGER DEFAULT 0")
            _execute("ALTER TABLE usage_tracking ADD COLUMN IF NOT EXISTS image_edits INTEGER DEFAULT 0")
        else:
            db = _get_db()
            cursor = db.execute("PRAGMA table_info(usage_tracking)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'image_generations' not in columns:
                db.execute("ALTER TABLE usage_tracking ADD COLUMN image_generations INTEGER DEFAULT 0")
            if 'image_edits' not in columns:
                db.execute("ALTER TABLE usage_tracking ADD COLUMN image_edits INTEGER DEFAULT 0")
            db.commit()
    except Exception as e:
        logger.debug(f"Image gen/edits migration: {e}")


def _migrate_add_deep_searches():
    """إضافة عمود deep_searches في usage_tracking لو مش موجود"""
    try:
        if _is_postgres():
            _execute("ALTER TABLE usage_tracking ADD COLUMN IF NOT EXISTS deep_searches INTEGER DEFAULT 0")
        else:
            db = _get_db()
            cursor = db.execute("PRAGMA table_info(usage_tracking)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'deep_searches' not in columns:
                db.execute("ALTER TABLE usage_tracking ADD COLUMN deep_searches INTEGER DEFAULT 0")
                db.commit()
    except Exception:
        pass


# ═══════════════════════════════════════
# إدارة الخطة - Plan Management
# ═══════════════════════════════════════

def get_user_plan(user_id: int) -> str:
    """Get user's current plan (free, premium, or premium_plus) — ⚡ مع كاش"""
    # ⚡ كاش: لو الخطة متخزنة ومش انتهت صلاحيتها
    if user_id in _plan_cache:
        plan, expiry = _plan_cache[user_id]
        if _time.time() < expiry:
            return plan
    
    from memory import _ensure_user_in_db
    _ensure_user_in_db(user_id)
    
    ph = "%s" if _is_postgres() else "?"
    row = _execute(
        f"SELECT plan FROM premium_users WHERE user_id = {ph}",
        (user_id,), fetchone=True
    )
    if row:
        plan = row[0]
    else:
        # Create default entry
        _execute(
            f"INSERT INTO premium_users (user_id, plan) VALUES ({ph}, 'free')",
            (user_id,)
        )
        plan = "free"
    
    # ⚡ حفظ في الكاش
    _plan_cache[user_id] = (plan, _time.time() + _PLAN_CACHE_TTL)
    return plan


def is_premium(user_id: int) -> bool:
    """Check if user has premium plan (or premium_plus)"""
    plan = get_user_plan(user_id)
    return plan in ("premium", "premium_plus")


def get_premium_info(user_id: int) -> dict:
    """الحصول على معلومات الاشتراك Premium كاملة
    
    Returns: {
        "plan": str,           # "free", "premium", "premium_plus"
        "is_premium": bool,    # هل هو بريميوم
        "premium_since": str,  # متى بدأ البريميوم
        "premium_expires": str,# متى بينتهي (None = مدى الحياة)
        "granted_by": str,     # مين فعله
        "expires_display": str,# عرض نصي لتاريخ الانتهاء
        "remaining_days": int, # كم يوم باقي (0 = مدى الحياة أو خلص, -1 = مش بريميوم)
    }
    """
    from memory import _ensure_user_in_db
    _ensure_user_in_db(user_id)
    
    ph = "%s" if _is_postgres() else "?"
    row = _execute(
        f"SELECT plan, premium_since, premium_expires, granted_by FROM premium_users WHERE user_id = {ph}",
        (user_id,), fetchone=True
    )
    
    result = {
        "plan": "free",
        "is_premium": False,
        "premium_since": None,
        "premium_expires": None,
        "granted_by": None,
        "expires_display": "—",
        "remaining_days": -1,
    }
    
    if row:
        result["plan"] = row[0]
        result["is_premium"] = row[0] in ("premium", "premium_plus")
        result["premium_since"] = row[1]
        result["premium_expires"] = row[2]
        result["granted_by"] = row[3]
    
    if result["is_premium"]:
        if result["premium_expires"]:
            try:
                expires_dt = datetime.fromisoformat(result["premium_expires"])
                now = datetime.now(CAIRO_TZ)
                remaining = expires_dt - now
                result["remaining_days"] = max(0, remaining.days)
                if remaining.days > 0:
                    result["expires_display"] = f"{remaining.days} يوم (ينتهي {expires_dt.strftime('%Y-%m-%d')})"
                else:
                    hours_left = max(0, remaining.seconds // 3600)
                    if hours_left > 0:
                        result["expires_display"] = f"أقل من يوم ({hours_left} ساعة — ينتهي {expires_dt.strftime('%Y-%m-%d %H:%M')})"
                    else:
                        result["expires_display"] = f"بينتهي قريب ({expires_dt.strftime('%Y-%m-%d')})"
            except Exception:
                result["expires_display"] = result["premium_expires"][:10] if result["premium_expires"] else "—"
        else:
            result["remaining_days"] = 0  # 0 = مدى الحياة
            result["expires_display"] = "مدى الحياة 🔓"
    
    return result


def _log_premium_history(user_id: int, action: str, plan_before: str = "free", plan_after: str = "free",
                          granted_by: str = None, expires: str = None):
    """تسجيل حدث Premium في سجل التاريخ
    
    Args:
        action: "grant" أو "revoke" أو "expire" أو "renew"
        plan_before: الخطة قبل التغيير
        plan_after: الخطة بعد التغيير
        granted_by: مين فعّل الشيل
        expires: تاريخ الانتهاء (لو grant/renew)
    """
    try:
        now = datetime.now(CAIRO_TZ).isoformat()
        phs = ["%s"] * 7 if _is_postgres() else ["?"] * 7
        _execute(
            f"""INSERT INTO premium_history 
            (user_id, action, plan_before, plan_after, granted_by, expires, created_at) 
            VALUES ({phs[0]}, {phs[1]}, {phs[2]}, {phs[3]}, {phs[4]}, {phs[5]}, {phs[6]})""",
            (user_id, action, plan_before, plan_after, granted_by, expires, now)
        )
    except Exception as e:
        logger.warning(f"⚠️ Could not log premium history for user {user_id}: {e}")


def get_premium_history(user_id: int, limit: int = 20) -> list:
    """الحصول على سجل تاريخ Premium للمستخدم
    
    Returns: List of dicts with: action, plan_before, plan_after, granted_by, expires, created_at
    """
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    rows = _execute(
        f"SELECT action, plan_before, plan_after, granted_by, expires, created_at "
        f"FROM premium_history WHERE user_id = {ph1} ORDER BY created_at DESC LIMIT {ph2}",
        (user_id, limit),
        fetch=True
    )
    if rows:
        return [
            {
                "action": r[0],
                "plan_before": r[1],
                "plan_after": r[2],
                "granted_by": r[3],
                "expires": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
    return []


def get_user_stats(user_id: int) -> dict:
    """الحصول على إحصائيات شاملة عن المستخدم — بدون بيانات حساسة
    
    ⚠️ البيانات الحساسة اللي مش بتترجع:
    - محتوى المحادثات (conversations)
    - ذكريات المستخدم (user_memories) 
    - المفضلات التفصيلية (favorites content)
    - عناصر Workspace التفصيلية (workspace content)
    
    بيرجع بس إحصائيات عامة وعددات — بدون محتوى فعلي
    """
    from memory import _ensure_user_in_db, get_user, get_interests, get_favorite_companies
    _ensure_user_in_db(user_id)
    
    result = {
        "user_id": user_id,
        "found": False,
    }
    
    try:
        # ═══ بيانات أساسية ═══
        user_data = get_user(user_id)
        if not user_data:
            return result
        result["found"] = True
        
        result["name"] = user_data.get("name", "")
        result["profile_name"] = user_data.get("profile_name", "")  # 🔴 الاسم الأصلي من البروفايل (منفصل عن الاسم المفضل)
        result["language"] = user_data.get("language", "ar")
        result["platform"] = user_data.get("platform", "telegram")
        result["created_at"] = user_data.get("created_at", "")
        result["last_interaction"] = user_data.get("last_interaction", "")
        result["subscribed"] = user_data.get("subscribed", False)
        result["news_time"] = user_data.get("news_time", "09:00")
        result["notification_enabled"] = bool(user_data.get("notification_enabled", 1))
        
        # ═══ إحصائيات الاستخدام العام ═══
        result["commands_used"] = user_data.get("commands_used", 0)
        result["chat_count"] = user_data.get("chat_count", 0)
        
        # ═══ معلومات الخطة الحالية ═══
        premium_info = get_premium_info(user_id)
        result["plan"] = premium_info["plan"]
        result["is_premium"] = premium_info["is_premium"]
        result["premium_since"] = premium_info["premium_since"]
        result["premium_expires"] = premium_info["premium_expires"]
        result["premium_remaining_days"] = premium_info["remaining_days"]
        result["premium_expires_display"] = premium_info["expires_display"]
        result["premium_granted_by"] = premium_info["granted_by"]
        
        # ═══ كم مدة على الخطة الحالية ═══
        if premium_info["premium_since"]:
            try:
                since_dt = datetime.fromisoformat(premium_info["premium_since"])
                now = datetime.now(CAIRO_TZ)
                days_on_plan = (now - since_dt).days
                result["days_on_current_plan"] = days_on_plan
                if days_on_plan > 30:
                    months = days_on_plan // 30
                    remaining_days = days_on_plan % 30
                    result["time_on_current_plan"] = f"{months} شهر و {remaining_days} يوم"
                else:
                    result["time_on_current_plan"] = f"{days_on_plan} يوم"
            except Exception:
                result["days_on_current_plan"] = 0
                result["time_on_current_plan"] = "مش محدد"
        else:
            result["days_on_current_plan"] = 0
            result["time_on_current_plan"] = "مش محدد"
        
        # ═══ كم مدة على البوت ═══
        if result["created_at"]:
            try:
                created_dt = datetime.fromisoformat(result["created_at"])
                now = datetime.now(CAIRO_TZ)
                days_on_bot = (now - created_dt).days
                result["days_on_bot"] = days_on_bot
                if days_on_bot >= 365:
                    years = days_on_bot // 365
                    remaining = days_on_bot % 365
                    months = remaining // 30
                    result["time_on_bot"] = f"{years} سنة و {months} شهر"
                elif days_on_bot >= 30:
                    months = days_on_bot // 30
                    remaining = days_on_bot % 30
                    result["time_on_bot"] = f"{months} شهر و {remaining} يوم"
                else:
                    result["time_on_bot"] = f"{days_on_bot} يوم"
            except Exception:
                result["days_on_bot"] = 0
                result["time_on_bot"] = "مش محدد"
        else:
            result["days_on_bot"] = 0
            result["time_on_bot"] = "مش محدد"
        
        # ═══ تاريخ Premium ═══
        history = get_premium_history(user_id, limit=50)
        result["premium_grant_count"] = len([h for h in history if h["action"] == "grant"])
        result["premium_revoke_count"] = len([h for h in history if h["action"] == "revoke"])
        result["premium_history"] = history[:10]  # آخر 10 أحداث بس
        
        # ═══ استخدام اليوم ═══
        result["today_usage"] = get_usage(user_id)
        
        # ═══ إجمالي الاستخدام عبر الوقت (من usage_tracking) ═══
        ph = "%s" if _is_postgres() else "?"
        total_row = _execute(
            f"SELECT "
            f"COALESCE(SUM(ai_messages), 0), "
            f"COALESCE(SUM(pdf_analyses), 0), "
            f"COALESCE(SUM(image_analyses), 0), "
            f"COALESCE(SUM(youtube_summaries), 0), "
            f"COALESCE(SUM(searches), 0), "
            f"COALESCE(SUM(deep_searches), 0), "
            f"COALESCE(SUM(image_generations), 0), "
            f"COALESCE(SUM(image_edits), 0), "
            f"COUNT(*) "
            f"FROM usage_tracking WHERE user_id = {ph}",
            (user_id,), fetchone=True
        )
        if total_row:
            result["total_usage"] = {
                "ai_messages": total_row[0],
                "pdf_analyses": total_row[1],
                "image_analyses": total_row[2],
                "youtube_summaries": total_row[3],
                "searches": total_row[4],
                "deep_searches": total_row[5],
                "image_generations": total_row[6],
                "image_edits": total_row[7],
                "active_days": total_row[8],
            }
        else:
            result["total_usage"] = {"ai_messages": 0, "pdf_analyses": 0, "image_analyses": 0,
                                      "youtube_summaries": 0, "searches": 0, "deep_searches": 0,
                                      "image_generations": 0, "image_edits": 0, "active_days": 0}
        
        # ═══ اهتمامات ═══
        result["interests"] = get_interests(user_id)
        result["favorite_companies"] = get_favorite_companies(user_id)
        
        # ═══ عدد المواضيع المتعلمة ═══
        from memory import get_learning_progress
        learning = get_learning_progress(user_id)
        result["learning_topics_count"] = len(learning)
        
        # ═══ عدد المفضلات ═══
        ph = "%s" if _is_postgres() else "?"
        fav_row = _execute(
            f"SELECT COUNT(*) FROM favorites WHERE user_id = {ph}",
            (user_id,), fetchone=True
        )
        result["favorites_count"] = fav_row[0] if fav_row else 0
        
        # ═══ عدد عناصر Workspace ═══
        result["workspace_count"] = get_workspace_count(user_id)
        
        # ═══ عدد التنبيهات الذكية ═══
        alerts = get_user_alerts(user_id)
        result["smart_alerts_count"] = len(alerts)
        
        # ═══ حالة الحظر ═══
        ph = "%s" if _is_postgres() else "?"
        ban_row = _execute(
            f"SELECT reason, banned_at, banned_by, warning_count FROM banned_users WHERE user_id = {ph}",
            (user_id,), fetchone=True
        )
        if ban_row:
            result["banned"] = True
            result["ban_reason"] = ban_row[0]
            result["ban_date"] = ban_row[1]
            result["banned_by"] = ban_row[2]
            result["warning_count"] = ban_row[3]
        else:
            result["banned"] = False
            result["warning_count"] = 0
        
        # ═══ حالة الأدمن ═══
        try:
            from admin import is_admin
            result["is_admin"] = is_admin(user_id)
        except Exception:
            result["is_admin"] = False
        
    except Exception as e:
        logger.error(f"❌ Error getting user stats for {user_id}: {e}")
        result["error"] = str(e)
    
    return result


def grant_premium(user_id: int, granted_by: str = "admin", expires: str = None, plan: str = "premium"):
    """Grant premium to a user"""
    from memory import _ensure_user_in_db
    _ensure_user_in_db(user_id)
    
    # 🔴 تسجيل الخطة القديمة قبل التغيير (عشان الـ history)
    old_plan = get_user_plan(user_id)
    
    now = datetime.now(CAIRO_TZ).isoformat()
    ph1, ph2, ph3, ph4 = ("%s", "%s", "%s", "%s") if _is_postgres() else ("?", "?", "?", "?")
    
    # Upsert
    existing = _execute(
        f"SELECT user_id FROM premium_users WHERE user_id = {ph1}",
        (user_id,), fetchone=True
    )
    if existing:
        _execute(
            f"UPDATE premium_users SET plan = {ph1}, premium_since = {ph2}, premium_expires = {ph3}, granted_by = {ph4} WHERE user_id = {ph1}",
            (plan, now, expires, granted_by, user_id)
        )
    else:
        ph5 = "%s" if _is_postgres() else "?"
        _execute(
            f"INSERT INTO premium_users (user_id, plan, premium_since, premium_expires, granted_by) VALUES ({ph1}, {ph2}, {ph3}, {ph4}, {ph5})",
            (user_id, plan, now, expires, granted_by)
        )
    
    # 🔴 تسجيل في premium_history
    _log_premium_history(user_id, action="grant", plan_before=old_plan, plan_after=plan, granted_by=granted_by, expires=expires)
    
    logger.info(f"⭐ Premium granted to user {user_id} (plan: {plan})")
    # ⚡ مسح الكاش عشان التغيير يظهر فوراً
    _plan_cache.pop(user_id, None)
    _usage_cache.pop(user_id, None)


def revoke_premium(user_id: int):
    """Revoke premium from a user"""
    # 🔴 تسجيل الخطة القديمة قبل الشيل (عشان الـ history)
    old_plan = get_user_plan(user_id)
    
    ph = "%s" if _is_postgres() else "?"
    _execute(
        f"UPDATE premium_users SET plan = {ph}, premium_expires = NULL WHERE user_id = {ph}",
        ("free", user_id)
    )
    
    # 🔴 تسجيل في premium_history
    _log_premium_history(user_id, action="revoke", plan_before=old_plan, plan_after="free")
    
    logger.info(f"❌ Premium revoked for user {user_id}")
    # ⚡ مسح الكاش عشان التغيير يظهر فوراً
    _plan_cache.pop(user_id, None)
    _usage_cache.pop(user_id, None)


def get_all_premium_users(platform: str = None):
    """الحصول على كل مشتركي Premium، اختياري فلترة حسب المنصة"""
    try:
        if platform:
            ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
            rows = _execute(
                f"SELECT pu.user_id, pu.plan, pu.premium_since, pu.premium_expires, pu.granted_by "
                f"FROM premium_users pu JOIN user_profiles up ON pu.user_id = up.user_id "
                f"WHERE pu.plan != {ph1} AND up.platform = {ph2}",
                ("free", platform), fetch=True
            )
        else:
            ph = "%s" if _is_postgres() else "?"
            rows = _execute(
                f"SELECT user_id, plan, premium_since, premium_expires, granted_by FROM premium_users WHERE plan != {ph}",
                ("free",), fetch=True
            )
        if rows:
            return [
                {
                    "user_id": r[0],
                    "plan": r[1],
                    "premium_since": r[2],
                    "premium_expires": r[3],
                    "granted_by": r[4],
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning(f"Error getting premium users: {e}")
    return []


# ═══════════════════════════════════════
# تتبع الاستخدام - Usage Tracking
# ═══════════════════════════════════════

def _get_today_key() -> str:
    """Get today's date key for usage tracking"""
    return datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")


def _ensure_usage_row(user_id: int, date_key: str):
    """Ensure usage row exists for user+date"""
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    row = _execute(
        f"SELECT id FROM usage_tracking WHERE user_id = {ph1} AND date = {ph2}",
        (user_id, date_key), fetchone=True
    )
    if not row:
        _execute(
            f"INSERT INTO usage_tracking (user_id, date, ai_messages, pdf_analyses, image_analyses, youtube_summaries, searches, deep_searches) VALUES ({ph1}, {ph2}, 0, 0, 0, 0, 0, 0)",
            (user_id, date_key)
        )


def get_usage(user_id: int) -> Dict:
    """Get today's usage for user — ⚡ مع كاش"""
    # ⚡ كاش: لو الاستخدام متخزن ومش انتهت صلاحيتها
    if user_id in _usage_cache:
        usage, expiry = _usage_cache[user_id]
        if _time.time() < expiry:
            return usage
    
    date_key = _get_today_key()
    _ensure_usage_row(user_id, date_key)
    
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    row = _execute(
        f"SELECT ai_messages, pdf_analyses, image_analyses, youtube_summaries, searches, deep_searches FROM usage_tracking WHERE user_id = {ph1} AND date = {ph2}",
        (user_id, date_key), fetchone=True
    )
    if row:
        usage = {
            "ai_messages": row[0],
            "pdf_analyses": row[1],
            "image_analyses": row[2],
            "youtube_summaries": row[3],
            "searches": row[4],
            "deep_searches": row[5] if len(row) > 5 else 0,
        }
    else:
        usage = {"ai_messages": 0, "pdf_analyses": 0, "image_analyses": 0, "youtube_summaries": 0, "searches": 0, "deep_searches": 0}
    
    # ⚡ حفظ في الكاش
    _usage_cache[user_id] = (usage, _time.time() + _USAGE_CACHE_TTL)
    return usage


def reset_user_usage(user_id: int) -> bool:
    """
    إعادة تعيين حدود الاستخدام اليومية لمستخدم معين (صفر كل العدادات)
    بيستخدمها الأدمن عشان يرجع الحد المجاني لمستخدم خلص كوته
    
    Returns: True لو الاتمام بنجاح، False لو فشل
    """
    date_key = _get_today_key()
    _ensure_usage_row(user_id, date_key)
    
    try:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        _execute(
            f"""UPDATE usage_tracking 
            SET ai_messages = 0, 
                pdf_analyses = 0, 
                image_analyses = 0, 
                youtube_summaries = 0, 
                searches = 0, 
                deep_searches = 0,
                image_generations = 0,
                image_edits = 0
            WHERE user_id = {ph1} AND date = {ph2}""",
            (user_id, date_key)
        )
        logger.info(f"🔄 Usage reset for user {user_id} on {date_key}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to reset usage for user {user_id}: {e}")
        return False


def increment_usage(user_id: int, feature: str, count: int = 1):
    """Increment usage counter for a feature"""
    date_key = _get_today_key()
    _ensure_usage_row(user_id, date_key)
    
    valid_features = ["ai_messages", "pdf_analyses", "image_analyses", "youtube_summaries", "searches", "deep_searches", "image_generations", "image_edits"]
    if feature not in valid_features:
        return
    
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    _execute(
        f"UPDATE usage_tracking SET {feature} = {feature} + {count} WHERE user_id = {ph1} AND date = {ph2}",
        (user_id, date_key)
    )
    # ⚡ مسح كاش الاستخدام عشان الرقم يتحدث
    _usage_cache.pop(user_id, None)


# ═══════════════════════════════════════
# فحص الحدود - Limit Checks
# ═══════════════════════════════════════

def check_limit(user_id: int, feature: str, username: str = None) -> Dict:
    """
    Check if user can use a feature.
    Returns: {"allowed": bool, "remaining": int, "limit": int, "plan": str}

    الأدمن (@ziadamr) يتجاوز كل الحدود — كل حاجة مفتوحة
    """
    # ═══ Admin Bypass — الأدمن مبيتحكمش فيه أي Limits ═══
    try:
        from admin import is_admin
        if is_admin(user_id, username):
            return {"allowed": True, "remaining": -1, "limit": -1, "plan": "admin"}
    except Exception:
        pass

    plan = get_user_plan(user_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    limit = limits.get(feature, 0)
    
    # -1 means unlimited
    if limit == -1:
        return {"allowed": True, "remaining": -1, "limit": -1, "plan": plan}
    
    # Boolean features (deep_search, study_mode, etc.)
    if isinstance(limit, bool):
        return {"allowed": limit, "remaining": 1 if limit else 0, "limit": limit, "plan": plan}
    
    # Numeric limits - map feature key to usage key
    usage_key_map = {
        "ai_messages_per_day": "ai_messages",
        "pdf_analyses_per_day": "pdf_analyses",
        "image_analyses_per_day": "image_analyses",
        "youtube_summaries_per_day": "youtube_summaries",
        "searches_per_day": "searches",
        "deep_searches_per_day": "deep_searches",
        "image_generations_per_day": "image_generations",  # 🎨
        "image_edits_per_day": "image_edits",  # 🖌️
    }
    
    usage = get_usage(user_id)
    usage_key = usage_key_map.get(feature, feature)
    used = usage.get(usage_key, 0)
    remaining = max(0, limit - used)
    
    return {"allowed": used < limit, "remaining": remaining, "limit": limit, "plan": plan}


def can_use_ai_message(user_id: int) -> bool:
    return check_limit(user_id, "ai_messages_per_day")["allowed"]

def can_use_pdf(user_id: int) -> bool:
    return check_limit(user_id, "pdf_analyses_per_day")["allowed"]

def can_use_image(user_id: int) -> bool:
    return check_limit(user_id, "image_analyses_per_day")["allowed"]

def can_use_youtube(user_id: int) -> bool:
    return check_limit(user_id, "youtube_summaries_per_day")["allowed"]

def can_use_search(user_id: int) -> bool:
    return check_limit(user_id, "searches_per_day")["allowed"]

def can_use_deep_search(user_id: int) -> bool:
    return check_limit(user_id, "deep_searches_per_day")["allowed"]

def can_use_study_mode(user_id: int) -> bool:
    return check_limit(user_id, "study_mode")["allowed"]

def can_use_memory(user_id: int) -> bool:
    return check_limit(user_id, "long_term_memory")["allowed"]

def can_use_voice(user_id: int) -> bool:
    return check_limit(user_id, "voice_assistant")["allowed"]

def can_use_workspace(user_id: int) -> bool:
    return check_limit(user_id, "workspace")["allowed"]

def can_use_smart_alerts(user_id: int) -> bool:
    return check_limit(user_id, "smart_alerts")["allowed"]

def can_use_premium_models(user_id: int) -> bool:
    return check_limit(user_id, "premium_models")["allowed"]

def can_use_image_gen(user_id: int) -> bool:
    """فحص هل المستخدم يقدر ينشئ صور (بريميوم بس)"""
    return check_limit(user_id, "image_gen")["allowed"]

def can_use_image_edit(user_id: int) -> bool:
    """فحص هل المستخدم يقدر يعدل صور (بريميوم بس)"""
    return check_limit(user_id, "image_edit")["allowed"]


# ═══════════════════════════════════════
# استخدام متبقي - Remaining Usage
# ═══════════════════════════════════════

def get_remaining_usage(user_id: int, lang: str = "ar") -> str:
    """Returns formatted string of remaining limits for free users"""
    plan = get_user_plan(user_id)
    if plan in ("premium", "premium_plus"):
        if lang == "ar":
            return "⭐ <i>مشترك Premium — استخدام غير محدود!</i>"
        else:
            return "⭐ <i>Premium subscriber — unlimited usage!</i>"

    # Admin check
    try:
        from admin import is_admin
        if is_admin(user_id):
            if lang == "ar":
                return "👑 <i>أدمن — مفيش Limits!</i>"
            else:
                return "👑 <i>Admin — no limits!</i>"
    except Exception:
        pass

    usage = get_usage(user_id)
    limits = PLAN_LIMITS["free"]
    
    if lang == "ar":
        parts = []
        # AI messages
        remaining = limits["ai_messages_per_day"] - usage.get("ai_messages", 0)
        parts.append(f"💬 رسائل: {max(0, remaining)}/{limits['ai_messages_per_day']}")
        # PDF
        remaining = limits["pdf_analyses_per_day"] - usage.get("pdf_analyses", 0)
        parts.append(f"📄 PDF: {max(0, remaining)}/{limits['pdf_analyses_per_day']}")
        # Images
        remaining = limits["image_analyses_per_day"] - usage.get("image_analyses", 0)
        parts.append(f"🖼️ صور: {max(0, remaining)}/{limits['image_analyses_per_day']}")
        # YouTube
        remaining = limits["youtube_summaries_per_day"] - usage.get("youtube_summaries", 0)
        parts.append(f"🎬 يوتيوب: {max(0, remaining)}/{limits['youtube_summaries_per_day']}")
        # Searches
        remaining = limits["searches_per_day"] - usage.get("searches", 0)
        parts.append(f"🔍 بحث: {max(0, remaining)}/{limits['searches_per_day']}")

        return "📊 <i>" + " | " + " | ".join(parts) + "</i>"
    else:
        parts = []
        remaining = limits["ai_messages_per_day"] - usage.get("ai_messages", 0)
        parts.append(f"💬 Msgs: {max(0, remaining)}/{limits['ai_messages_per_day']}")
        remaining = limits["pdf_analyses_per_day"] - usage.get("pdf_analyses", 0)
        parts.append(f"📄 PDF: {max(0, remaining)}/{limits['pdf_analyses_per_day']}")
        remaining = limits["image_analyses_per_day"] - usage.get("image_analyses", 0)
        parts.append(f"🖼️ Img: {max(0, remaining)}/{limits['image_analyses_per_day']}")
        remaining = limits["youtube_summaries_per_day"] - usage.get("youtube_summaries", 0)
        parts.append(f"🎬 YT: {max(0, remaining)}/{limits['youtube_summaries_per_day']}")
        remaining = limits["searches_per_day"] - usage.get("searches", 0)
        parts.append(f"🔍 Search: {max(0, remaining)}/{limits['searches_per_day']}")

        return "📊 <i>" + " | " + " | ".join(parts) + "</i>"


# ═══════════════════════════════════════
# نظام Workspace - Workspace System
# ═══════════════════════════════════════

def add_workspace_item(user_id: int, item_type: str, title: str, content: str = "", url: str = "", tags: list = None):
    """إضافة عنصر للـ Workspace
    item_type: note, file, link, research
    """
    from memory import _ensure_user_in_db
    _ensure_user_in_db(user_id)
    
    import json
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    now = datetime.now().isoformat()
    phs = ["%s"] * 7 if _is_postgres() else ["?"] * 7
    _execute(
        f"INSERT INTO workspace_items (user_id, item_type, title, content, url, tags, created_at, updated_at) VALUES ({', '.join(phs[:6])}, {phs[4]}, {phs[5]})",
        (user_id, item_type, title[:200], content[:2000], url, tags_json, now, now)
    )


def get_workspace_items(user_id: int, item_type: str = None) -> List[Dict]:
    """الحصول على عناصر الـ Workspace"""
    if item_type:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        rows = _execute(
            f"SELECT id, item_type, title, content, url, tags, created_at FROM workspace_items WHERE user_id = {ph1} AND item_type = {ph2} ORDER BY created_at DESC",
            (user_id, item_type),
            fetch=True
        )
    else:
        ph = "%s" if _is_postgres() else "?"
        rows = _execute(
            f"SELECT id, item_type, title, content, url, tags, created_at FROM workspace_items WHERE user_id = {ph} ORDER BY created_at DESC",
            (user_id,),
            fetch=True
        )
    
    import json
    if rows:
        result = []
        for r in rows:
            item = {
                "id": r[0], "item_type": r[1], "title": r[2],
                "content": r[3], "url": r[4],
                "tags": json.loads(r[5]) if isinstance(r[5], str) else r[5],
                "created_at": r[6],
            }
            result.append(item)
        return result
    return []


def delete_workspace_item(user_id: int, item_id: int):
    """حذف عنصر من الـ Workspace"""
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    _execute(f"DELETE FROM workspace_items WHERE id = {ph1} AND user_id = {ph2}", (item_id, user_id))


def get_workspace_count(user_id: int) -> int:
    """عدد عناصر الـ Workspace"""
    ph = "%s" if _is_postgres() else "?"
    row = _execute(
        f"SELECT COUNT(*) FROM workspace_items WHERE user_id = {ph}",
        (user_id,), fetchone=True
    )
    return row[0] if row else 0


def format_workspace_display(user_id: int, lang: str = "ar") -> str:
    """تنسيق عرض الـ Workspace"""
    items = get_workspace_items(user_id)
    
    if lang == "ar":
        text = "🗂️ <b>مساحة العمل — Workspace</b>\n━━━━━━━━━━━━━━━━━\n\n"
    else:
        text = "🗂️ <b>Workspace</b>\n━━━━━━━━━━━━━━━━━\n\n"
    
    if not items:
        if lang == "ar":
            text += "💭 مساحة العمل فاضية.\n\n💡 احفظ ملاحظات أو روابط أو أبحاث هنا!\n\nالأوامر:\n→ <code>/workspace add note العنوان | المحتوى</code>\n→ <code>/workspace add link العنوان | الرابط</code>\n→ <code>/workspace add research العنوان | المحتوى</code>"
        else:
            text += "💭 Workspace is empty.\n\n💡 Save notes, links, or research here!\n\nCommands:\n→ <code>/workspace add note Title | Content</code>\n→ <code>/workspace add link Title | URL</code>\n→ <code>/workspace add research Title | Content</code>"
        return text
    
    type_icons = {"note": "📝", "file": "📄", "link": "🔗", "research": "🔬"}
    
    for item in items[:20]:
        icon = type_icons.get(item["item_type"], "📌")
        text += f"{icon} <b>{item['title']}</b>\n"
        if item.get("content"):
            content_preview = item["content"][:100]
            text += f"   {content_preview}\n"
        if item.get("url"):
            text += f"   🔗 {item['url']}\n"
        text += "\n"
    
    if len(items) > 20:
        if lang == "ar":
            text += f"... و{len(items) - 20} عنصر تاني\n"
        else:
            text += f"... and {len(items) - 20} more items\n"
    
    return text


# ═══════════════════════════════════════
# نظام Smart Alerts - Smart Alerts System
# ═══════════════════════════════════════

def subscribe_alert(user_id: int, topic: str) -> bool:
    """اشتراك في تنبيهات موضوع"""
    from memory import _ensure_user_in_db
    _ensure_user_in_db(user_id)
    
    now = datetime.now().isoformat()
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    
    try:
        if _is_postgres():
            _execute(
                """INSERT INTO smart_alerts (user_id, topic, active, created_at) VALUES (%s, %s, 1, %s)
                ON CONFLICT(user_id, topic) DO UPDATE SET active = 1""",
                (user_id, topic.lower().strip(), now)
            )
        else:
            _execute(
                """INSERT INTO smart_alerts (user_id, topic, active, created_at) VALUES (?, ?, 1, ?)
                ON CONFLICT(user_id, topic) DO UPDATE SET active = 1""",
                (user_id, topic.lower().strip(), now)
            )
        return True
    except Exception as e:
        logger.error(f"Error subscribing alert: {e}")
        return False


def unsubscribe_alert(user_id: int, topic: str) -> bool:
    """إلغاء اشتراك في تنبيهات موضوع"""
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    _execute(
        f"UPDATE smart_alerts SET active = 0 WHERE user_id = {ph1} AND topic = {ph2}",
        (user_id, topic.lower().strip())
    )
    return True


def get_user_alerts(user_id: int, active_only: bool = True) -> List[Dict]:
    """الحصول على تنبيهات المستخدم"""
    if active_only:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        rows = _execute(
            f"SELECT id, topic, active, created_at, last_notified FROM smart_alerts WHERE user_id = {ph1} AND active = {ph2}",
            (user_id, 1),
            fetch=True
        )
    else:
        ph = "%s" if _is_postgres() else "?"
        rows = _execute(
            f"SELECT id, topic, active, created_at, last_notified FROM smart_alerts WHERE user_id = {ph}",
            (user_id,),
            fetch=True
        )
    
    if rows:
        return [
            {
                "id": r[0], "topic": r[1], "active": bool(r[2]),
                "created_at": r[3], "last_notified": r[4],
            }
            for r in rows
        ]
    return []


def get_all_active_alerts() -> List[Dict]:
    """الحصول على كل التنبيهات النشطة (للبث)"""
    ph = "%s" if _is_postgres() else "?"
    rows = _execute(
        f"SELECT user_id, topic FROM smart_alerts WHERE active = {ph}",
        (1,),
        fetch=True
    )
    if rows:
        return [{"user_id": r[0], "topic": r[1]} for r in rows]
    return []


def update_alert_notified(user_id: int, topic: str):
    """تحديث آخر إشعار لموضوع"""
    now = datetime.now().isoformat()
    ph1, ph2, ph3 = ("%s", "%s", "%s") if _is_postgres() else ("?", "?", "?")
    _execute(
        f"UPDATE smart_alerts SET last_notified = {ph1} WHERE user_id = {ph2} AND topic = {ph3}",
        (now, user_id, topic)
    )


def format_alerts_display(user_id: int, lang: str = "ar") -> str:
    """تنسيق عرض التنبيهات"""
    alerts = get_user_alerts(user_id)
    
    if lang == "ar":
        text = "🔔 <b>التنبيهات الذكية — Smart Alerts</b>\n━━━━━━━━━━━━━━━━━\n\n"
    else:
        text = "🔔 <b>Smart Alerts</b>\n━━━━━━━━━━━━━━━━━\n\n"
    
    if not alerts:
        if lang == "ar":
            text += "💭 معندكش تنبيهات مشترك فيها.\n\n💡 اشترك في مواضيع وهابعتلك إشعار أول بأول!\n\nالأوامر:\n→ <code>/alerts add openai</code>\n→ <code>/alerts add machine learning</code>\n→ <code>/alerts remove openai</code>\n\n⭐ متاح للمشتركين Premium بس"
        else:
            text += "💭 No active alerts.\n\n💡 Subscribe to topics and I'll notify you!\n\nCommands:\n→ <code>/alerts add openai</code>\n→ <code>/alerts add machine learning</code>\n→ <code>/alerts remove openai</code>\n\n⭐ Premium only feature"
        return text
    
    if lang == "ar":
        text += "تنبيهاتك النشطة:\n\n"
    else:
        text += "Your active alerts:\n\n"
    
    for alert in alerts:
        text += f"  🔔 {alert['topic']}\n"
    
    if lang == "ar":
        text += f"\n💡 <code>/alerts remove [موضوع]</code> عشان تلغي اشتراك"
    else:
        text += f"\n💡 <code>/alerts remove [topic]</code> to unsubscribe"
    
    return text


# ═══════════════════════════════════════
# رسائل الاشتراك - Subscription Messages
# ═══════════════════════════════════════

def premium_required_message(feature: str, lang: str = "ar") -> str:
    """Message shown when user tries a premium-only feature"""
    if lang == "ar":
        return f"""⭐ <b>الميزة دي للمشتركين Premium بس!</b>

الميزة: {feature}

🆓 <b>الخطة المجانية:</b>
• 20 رسالة AI في اليوم
• 3 تحليلات PDF في اليوم
• 5 تحليلات صور في اليوم
• 3 ملخصات YouTube في اليوم
• 5 عمليات بحث في اليوم
• 3 عمليات بحث صور في اليوم 🖼️
• نموذج AI أساسي

⭐ <b>خطة Premium:</b>
• رسائل AI غير محدودة 💬
• تحليل PDF غير محدود 📄
• تحليل صور غير محدود + Vision Pro 👁️
• ملخصات YouTube غير محدودة 🎬
• بحث غير محدود 🔍
• تحميل وسائط من أي منصة 📥
  (YouTube, Instagram, TikTok, Facebook, Twitter...)
• فيديو بالبحث غير محدود 🎬
• صوت بالبحث غير محدود 🎵
• بحث صور غير محدود 🖼️
• إنشاء صور بالذكاء الاصطناعي 🎨
• تعديل صور بالذكاء الاصطناعي 🖌️
• وضع الدراسة 📚
• ذاكرة طويلة المدى 🧠
• مساعد صوتي 🎙️
• نماذج AI أقوى ومتقدمة 🤖
• مساحة عمل شخصية 🗂️
• تنبيهات ذكية 🔔
• تقارير أسبوعية 📊
• أولوية في الاستجابة ⚡

📩 <b>للاشتراك في My Bro Premium يرجى التواصل مع المطور:</b>

📩 تواصل مع المطور على واتساب:
📱 {DEVELOPER_WHATSAPP_URL}"""
    else:
        return f"""⭐ <b>This feature is Premium only!</b>

Feature: {feature}

🆓 <b>Free Plan:</b>
• 20 AI messages per day
• 3 PDF analyses per day
• 5 image analyses per day
• 3 YouTube summaries per day
• 5 searches per day
• 3 photo searches per day 🖼️
• Basic AI model

⭐ <b>Premium Plan:</b>
• Unlimited AI messages 💬
• Unlimited PDF analysis 📄
• Unlimited image analysis + Vision Pro 👁️
• Unlimited YouTube summaries 🎬
• Unlimited search 🔍
• Media downloads from any platform 📥
  (YouTube, Instagram, TikTok, Facebook, Twitter...)
• Unlimited video search 🎬
• Unlimited audio search 🎵
• Unlimited photo search 🖼️
• AI Image Generation 🎨
• AI Image Editing 🖌️
• Study Mode 📚
• Long-term Memory 🧠
• Voice Assistant 🎙️
• Advanced Premium AI models 🤖
• Personal Workspace 🗂️
• Smart Alerts 🔔
• Weekly Reports 📊
• Priority Access ⚡

📩 <b>To subscribe to My Bro Premium, contact the developer:</b>

📩 Contact the developer on WhatsApp:
📱 {DEVELOPER_WHATSAPP_URL}"""


def limit_reached_message(feature: str, remaining: int, limit: int, lang: str = "ar") -> str:
    """Message shown when daily limit is reached"""
    if lang == "ar":
        return f"""⚠️ <b>وصلت للحد اليومي!</b>

{feature}: استخدمت {limit} من {limit} اليوم

💡 الحد بيرجع تاني بكرة
⭐ ترقية لـ Premium عشان استخدام غير محدود!

📩 تواصل مع المطور على واتساب:
📱 {DEVELOPER_WHATSAPP_URL}"""
    else:
        return f"""⚠️ <b>Daily limit reached!</b>

{feature}: used {limit} of {limit} today

💡 Limit resets tomorrow
⭐ Upgrade to Premium for unlimited usage!

📩 Contact developer on WhatsApp:
📱 {DEVELOPER_WHATSAPP_URL}"""


def get_premium_keyboard(lang: str = "ar", user_id: int = None) -> "InlineKeyboardMarkup":
    """Get premium purchase keyboard
    
    🔴 FIX: لو المستخدم Premium أو أدمن → مفيش أزرار (الرسالة نفسها بتقول إنه مشترك)
    لو المستخدم مجاني → بيظهر زرار التواصل عشان يشترك
    
    شلنا زرار "مزايا Premium" لأنه بيعيد نفس الرسالة - ملوش لازمة
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    # فحص نوع المستخدم
    is_premium_user = False
    is_admin_user = False
    if user_id:
        try:
            from admin import is_admin
            is_admin_user = is_admin(user_id)
            if not is_admin_user:
                is_premium_user = is_premium(user_id)
        except Exception:
            pass
    
    # لو Premium أو أدمن → مفيش أزرار (هو أصلاً مشترك، الرسالة بتقول كده)
    if is_premium_user or is_admin_user:
        return InlineKeyboardMarkup([])
    
    # مستخدم مجاني → اعرضله زرار التواصل عشان يشترك بس
    if lang == "ar":
        keyboard = [
            [
                InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/ziadamr"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📩 Contact Developer", url=f"https://t.me/ziadamr"),
            ],
        ]
    
    return InlineKeyboardMarkup(keyboard)


def premium_features_message(lang: str = "ar", user_id: int = None) -> str:
    """Detailed premium features message
    
    لو المستخدم Premium أو أدمن → مبيظهرش معلومات الاشتراك (هو أصلاً مشترك)
    لو المستخدم مجاني → بيظهر معلومات التواصل عشان يشترك
    """
    # فحص نوع المستخدم
    is_premium_user = False
    is_admin_user = False
    if user_id:
        try:
            from admin import is_admin
            is_admin_user = is_admin(user_id)
            if not is_admin_user:
                is_premium_user = is_premium(user_id)
        except Exception:
            pass
    
    already_subscribed = is_premium_user or is_admin_user
    
    if lang == "ar":
        features = """⭐ <b>مزايا My Bro Premium</b>
━━━━━━━━━━━━━━━━━

💬 <b>رسائل AI غير محدودة</b>
تحدث مع My Bro بلا حدود - بدون قيود يومية

📄 <b>تحليل PDF غير محدود</b>
ارفع كتب وأبحاث ومستندات وهحللها كلها

🖼️ <b>تحليل صور غير محدود</b>
حلل أي عدد من الصور والسكريينشوتات

🎬 <b>ملخصات YouTube غير محدودة</b>
ابعت أي فيديو وهلخصلك محتواه

🔍 <b>بحث غير محدود</b>
بحث شامل من مصادر متعددة

📚 <b>وضع الدراسة</b>
خطط دراسية، كويزات، امتحانات، ملاحظات مراجعة

🧠 <b>ذاكرة طويلة المدى</b>
باحفظ اسمك، اهتماماتك، وتاريخ محادثاتك

🎙️ <b>مساعد صوتي</b>
ابعت رسائل صوتية وهرد عليك

🤖 <b>نماذج AI أقوى</b>
نماذج متقدمة ومتخصصة — ردود أذكى وأشمل

👁️ <b>Vision Pro</b>
تحليل صور متقدم غير محدود بدقة أعلى

🎨 <b>إنشاء صور بالذكاء الاصطناعي</b>
وصف نصي وهعملك صورة منه

🖌️ <b>تعديل صور بالذكاء الاصطناعي</b>
غيّر الخلفية، الألوان، والستايل بوصف نصي

📥 <b>تحميل وسائط من أي منصة</b>
حمّل فيديوهات وصور من YouTube, Instagram, TikTok وغيرها

🗂️ <b>مساحة عمل شخصية</b>
احفظ ملاحظات، روابط، أبحاث في مكان واحد

🔔 <b>تنبيهات ذكية</b>
اشترك في مواضيع وهابعتلك إشعار أول بأول

📊 <b>تقارير أسبوعية</b>
ملخص أسبوعي بنبعتلك كل جمعة

⚡ <b>أولوية في الاستجابة</b>
ردود أسرع مع نماذج أقوى"""
        if already_subscribed:
            features += "\n\n━━━━━━━━━━━━━━━━━\n✅ <b>أنت مشترك Premium — استمتع بكل المزايا!</b>"
        else:
            features += "\n\n━━━━━━━━━━━━━━━━━\n📩 <b>للاشتراك تواصل مع المطور على واتساب:</b>\n📱 " + DEVELOPER_WHATSAPP_URL
        return features
    else:
        features = """⭐ <b>My Bro Premium Features</b>
━━━━━━━━━━━━━━━━━

💬 <b>Unlimited AI Messages</b>
Chat with My Bro without limits - no daily restrictions

📄 <b>Unlimited PDF Analysis</b>
Upload books, papers, and documents for analysis

🖼️ <b>Unlimited Image Analysis</b>
Analyze any number of images and screenshots

🎬 <b>Unlimited YouTube Summaries</b>
Send any video and get a content summary

🔍 <b>Unlimited Search</b>
Comprehensive multi-source search

📚 <b>Study Mode</b>
Study plans, quizzes, exams, revision notes

🧠 <b>Long-term Memory</b>
Remembers your name, interests, and conversation history

🎙️ <b>Voice Assistant</b>
Send voice messages and I'll respond

🤖 <b>Advanced AI Models</b>
Specialized premium models — smarter, more detailed responses

👁️ <b>Vision Pro</b>
Advanced unlimited image analysis with higher precision

🎨 <b>AI Image Generation</b>
Describe what you want and I'll create it

🖌️ <b>AI Image Editing</b>
Change backgrounds, colors, and style with text descriptions

📥 <b>Media Downloads from Any Platform</b>
Download videos and images from YouTube, Instagram, TikTok and more

🗂️ <b>Personal Workspace</b>
Save notes, links, research in one place

🔔 <b>Smart Alerts</b>
Subscribe to topics and get notified instantly

📊 <b>Weekly Reports</b>
Weekly summary sent to you every Friday

⚡ <b>Priority Access</b>
Faster responses with more powerful models"""
        if already_subscribed:
            features += "\n\n━━━━━━━━━━━━━━━━━\n✅ <b>You're a Premium subscriber — enjoy all features!</b>"
        else:
            features += "\n\n━━━━━━━━━━━━━━━━━\n📩 <b>To subscribe, contact the developer on WhatsApp:</b>\n📱 " + DEVELOPER_WHATSAPP_URL
        return features
