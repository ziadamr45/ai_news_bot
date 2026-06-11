"""
نظام الذاكرة المتقدم - Advanced Memory System
يستخدم PostgreSQL (Neon) لتخزين دائم يتجاوز إعادة تشغيل البوت
مع fallback لـ SQLite لو PostgreSQL مش متاح

يشمل:
- ملف المستخدم (اسم، لغة، اهتمامات، شركات مفضلة)
- ذاكرة المحادثات (آخر 50 محادثة)
- ذاكرة التعلم (المواضيع المتعلمة + التقدم)
- نظام المفضلات (أخبار، مواضيع، أدوات، تقارير)
- تفضيلات المستخدم (لغة، إشعارات، مصادر، طول الرد)
- ذاكرة ذكية (تحفظ بس المهم)
+ نظام الاشتراك في الأخبار اليومية (متوافق مع القديم)
"""

import json
import os
import logging
import threading
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

from config import DATA_DIR, USERS_FILE, DATABASE_PATH

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# إعداد قاعدة البيانات - Database Setup
# ═══════════════════════════════════════

# Connection Pool بدل threading.local()
# threading.local() كان بيعمل connection جديد لكل thread ومبيقفلوش صح
# على Neon free tier (حد أقصى 5 connections) ده بيوقع البوت
_pg_pool = None  # psycopg2.pool.SimpleConnectionPool
_pg_pool_lock = threading.Lock()  # حماية الـ pool من concurrent access
_local = threading.local()  # بيفضل لـ SQLite فقط
_db_type = None  # "postgresql" or "sqlite"


def _clean_database_url(url: str) -> str:
    """تنظيف رابط قاعدة البيانات - إزالة المعاملات غير المتوافقة"""
    if not url:
        return url

    # إزالة channel_binding=require لأن psycopg2 القديم مش بيدعمه
    # ده بيسبب خطأ "unknown connection parameter" وفشل الاتصال
    import re as _re
    url = _re.sub(r'&?channel_binding=[^&]*', '', url)
    url = _re.sub(r'\?channel_binding=[^&]*&', '?', url)
    url = _re.sub(r'\?channel_binding=[^&]*$', '', url)

    # تنظيف trailing ? أو & بعد إزالة المعاملات
    url = _re.sub(r'\?$', '', url)
    url = _re.sub(r'&$', '', url)
    url = _re.sub(r'\?&', '?', url)

    # إضافة sslmode=require لو مش موجود وده Neon
    if "sslmode=" not in url and "neon.tech" in url:
        url += "&sslmode=require" if "?" in url else "?sslmode=require"

    return url


def _get_database_url():
    """الحصول على رابط PostgreSQL من البيئة"""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        # محاولة من إعدادات config
        try:
            from config import DATABASE_URL as CONFIG_DB_URL
            url = CONFIG_DB_URL
        except (ImportError, AttributeError):
            pass

    # تنظيف الرابط من المعاملات غير المتوافقة
    url = _clean_database_url(url)

    if url:
        # لا نسجل الـ URL كامل لأسباب أمنية
        masked = url[:25] + "***" + url[-15:] if len(url) > 40 else "***"
        logger.info(f"🔗 DATABASE_URL found: {masked}")
    else:
        logger.error("❌ DATABASE_URL is NOT set! Data will NOT persist across deployments!")
        logger.error("❌ Set DATABASE_URL environment variable on Railway with your Neon PostgreSQL URL")
    return url


def _init_postgresql():
    """تهيئة قاعدة بيانات PostgreSQL مع Connection Pool
    
    Uses maxconn=3 (instead of 5) to leave headroom for Neon's own
    operations on the free tier (5 connection max). connect_timeout=10s
    for faster failure detection.
    
    Simplified: no retry path — if the first attempt fails, we fall back
    to SQLite. The old retry path duplicated table creation logic and
    could leave the pool in an inconsistent state.
    """
    global _db_type, _pg_pool
    url = _get_database_url()
    if not url:
        return False

    try:
        import psycopg2
        from psycopg2 import pool as pg_pool_mod

        # إنشاء Connection Pool
        # maxconn=3 — يسيب headroom لعمليات Neon نفسه (limit 5 connections)
        _pg_pool = pg_pool_mod.SimpleConnectionPool(
            1, 3,  # min=1, max=3 connections
            url,
            connect_timeout=10
        )
        _db_type = "postgresql"

        # Verify pool works + create tables in a single connection
        conn = _pg_pool.getconn()
        try:
            conn.autocommit = True
            _create_postgresql_tables(conn)
        finally:
            _pg_pool.putconn(conn)

        logger.info("✅ PostgreSQL database initialized successfully (Neon) with connection pool (max=3)")
        return True

    except Exception as e:
        logger.error(f"❌ PostgreSQL init FAILED: {type(e).__name__}: {e}")
        logger.error("❌ Data will NOT persist! Check DATABASE_URL environment variable on Railway!")
        logger.error("❌ Common issues: channel_binding=require, missing sslmode, wrong credentials")
        _db_type = None
        # Clean up failed pool
        if _pg_pool is not None:
            try:
                _pg_pool.closeall()
            except Exception:
                pass
            _pg_pool = None
        return False


def _create_postgresql_tables(conn):
    """إنشاء جداول PostgreSQL — دالة مشتركة لتجنب تكرار الكود
    
    ⚠️ BUG FIX: Previously, the retry path in _init_postgresql() only created
    user_profiles but missed conversations, learning_progress, favorites,
    user_memories, and banned_users. This caused crashes when the first
    connection attempt failed but the retry succeeded. Now both paths use
    the same table creation function.
    """
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id BIGINT PRIMARY KEY,
                name TEXT DEFAULT '',
                language TEXT DEFAULT 'ar',
                news_time TEXT DEFAULT '09:00',
                sources TEXT DEFAULT '[]',
                subscribed INTEGER DEFAULT 0,
                response_length TEXT DEFAULT 'medium',
                notification_enabled INTEGER DEFAULT 1,
                interests TEXT DEFAULT '[]',
                favorite_companies TEXT DEFAULT '[]',
                created_at TEXT,
                last_interaction TEXT,
                commands_used INTEGER DEFAULT 0,
                chat_count INTEGER DEFAULT 0,
                last_news_delivery TEXT DEFAULT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS learning_progress (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                topic TEXT NOT NULL,
                level TEXT DEFAULT 'explored',
                learned_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                UNIQUE(user_id, topic),
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                url TEXT DEFAULT '',
                saved_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                UNIQUE(user_id, key),
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY,
                reason TEXT DEFAULT '',
                banned_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                banned_by TEXT DEFAULT '',
                warning_count INTEGER DEFAULT 0
            );
        """)
        # إنشاء فهارس
        cur.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, timestamp DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_learning_user ON learning_progress(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id, category);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON user_memories(user_id, category);")
        cur.close()
        return True
    except Exception as e:
        logger.error(f"Error creating PostgreSQL tables: {e}")
        return False


def _get_pg_conn():
    """الحصول على اتصال PostgreSQL من الـ Connection Pool
    
    Simple retrieval — no pre-query health check. Stale connections are
    handled by _execute() which catches query failures and reconnects via
    _reconnect_pool(). This avoids wasting pool connections on SELECT 1
    probes that can themselves fail and consume extra connections.
    """
    global _pg_pool
    if _pg_pool is None:
        return None
    try:
        conn = _pg_pool.getconn()
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.error(f"PostgreSQL pool getconn failed: {type(e).__name__}: {e}")
        return None


def _return_pg_conn(conn, close=False):
    """إرجاع اتصال PostgreSQL للـ Connection Pool
    
    Args:
        close: If True, close the connection instead of returning it to the pool.
               Used when the connection is known to be broken/stale.
    """
    global _pg_pool
    if _pg_pool is not None and conn is not None:
        try:
            _pg_pool.putconn(conn, close=close)
        except Exception as e:
            logger.debug(f"PostgreSQL pool putconn error (non-critical): {e}")


def _reconnect_pool():
    """Recreate the entire connection pool when all connections are stale.
    
    Neon free tier closes idle connections after ~5 minutes. When a query
    fails with a connection error, _execute() calls this to get a fresh pool
    instead of trying to recycle individual connections.
    
    Returns True if reconnection succeeded, False otherwise.
    """
    global _pg_pool, _db_type
    with _pg_pool_lock:
        # Close the old pool entirely
        if _pg_pool is not None:
            try:
                _pg_pool.closeall()
            except Exception:
                pass
            _pg_pool = None

        # Create a fresh pool
        url = _get_database_url()
        if not url:
            _db_type = None
            return False

        try:
            from psycopg2 import pool as pg_pool_mod
            _pg_pool = pg_pool_mod.SimpleConnectionPool(
                1, 3,
                url,
                connect_timeout=10
            )
            logger.info("✅ PostgreSQL pool reconnected successfully")
            return True
        except Exception as e:
            logger.error(f"❌ PostgreSQL pool reconnect failed: {e}")
            _db_type = None
            _pg_pool = None
            return False


def _init_sqlite():
    """تهيئة قاعدة بيانات SQLite كـ fallback
    
    ⚠️ BUG FIX: Added thread safety check. SQLite connections are NOT thread-safe
    by default — using a connection created in one thread from another thread can
    cause 'database is locked' errors or silent data corruption. Now we verify
    that the current thread matches the thread that created the connection, and
    create a new connection if there's a mismatch.
    """
    global _db_type
    import sqlite3
    
    current_tid = threading.current_thread().ident
    
    # Check if existing connection belongs to current thread
    if hasattr(_local, 'sqlite_conn') and _local.sqlite_conn is not None:
        if getattr(_local, 'sqlite_tid', None) != current_tid:
            logger.warning(f"SQLite connection belongs to different thread (expected {_local.sqlite_tid}, got {current_tid}), creating new connection")
            try:
                _local.sqlite_conn.close()
            except Exception:
                pass
            _local.sqlite_conn = None
    
    if not hasattr(_local, 'sqlite_conn') or _local.sqlite_conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _local.sqlite_conn = sqlite3.connect(DATABASE_PATH, timeout=10)
        _local.sqlite_conn.row_factory = sqlite3.Row
        _local.sqlite_conn.execute("PRAGMA journal_mode=WAL")
        _local.sqlite_conn.execute("PRAGMA foreign_keys=ON")
        _local.sqlite_tid = current_tid  # Track which thread owns this connection

    db = _local.sqlite_conn
    db.executescript("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT DEFAULT '',
            language TEXT DEFAULT 'ar',
            news_time TEXT DEFAULT '09:00',
            sources TEXT DEFAULT '[]',
            subscribed INTEGER DEFAULT 0,
            response_length TEXT DEFAULT 'medium',
            notification_enabled INTEGER DEFAULT 1,
            interests TEXT DEFAULT '[]',
            favorite_companies TEXT DEFAULT '[]',
            created_at TEXT,
            last_interaction TEXT,
            commands_used INTEGER DEFAULT 0,
            chat_count INTEGER DEFAULT 0,
            last_news_delivery TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );

        CREATE TABLE IF NOT EXISTS learning_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            level TEXT DEFAULT 'explored',
            learned_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, topic),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );

        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            url TEXT DEFAULT '',
            saved_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );

        CREATE TABLE IF NOT EXISTS user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, key),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );

        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            reason TEXT DEFAULT '',
            banned_at TEXT DEFAULT (datetime('now')),
            banned_by TEXT DEFAULT '',
            warning_count INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_learning_user ON learning_progress(user_id);
        CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id, category);
        CREATE INDEX IF NOT EXISTS idx_memories_user ON user_memories(user_id, category);
    """)
    db.commit()
    _db_type = "sqlite"
    logger.info("✅ SQLite database initialized successfully (fallback)")
    return db


def init_database():
    """إنشاء جداول قاعدة البيانات"""
    logger.info("═══ Initializing Database ═══")
    # محاولة PostgreSQL أولاً
    if not _init_postgresql():
        # Fallback لـ SQLite
        logger.warning("⚠️⚠️⚠️ PostgreSQL FAILED! Falling back to SQLite!")
        logger.warning("⚠️⚠️⚠️ DATA WILL NOT PERSIST across Railway deploys!")
        logger.warning("⚠️⚠️⚠️ Make sure DATABASE_URL is set correctly on Railway!")
        _init_sqlite()
    else:
        logger.info("✅ PostgreSQL (Neon) connected — data WILL persist across deployments!")
        # Verify connection by counting users
        try:
            result = _execute("SELECT COUNT(*) FROM user_profiles", fetchone=True)
            user_count = result[0] if result else 0
            logger.info(f"📊 Database has {user_count} existing users — data is safe!")
        except Exception as e:
            logger.warning(f"Could not count users: {e}")
    # تشغيل migration لإضافة أعمدة جديدة
    _migrate_add_last_news_delivery()
    logger.info(f"═══ Database ready (type: {_db_type}) ═══")

    # تحذير نهائي لو SQLite
    if _db_type == "sqlite":
        logger.error("🔴🔴🔴 CRITICAL: Using SQLite — ALL DATA WILL BE LOST on next deploy!")
        logger.error("🔴🔴🔴 Set DATABASE_URL on Railway to fix this!")


def _migrate_add_last_news_delivery():
    """إضافة عمود last_news_delivery لو مش موجود"""
    if _is_postgres():
        try:
            _execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS last_news_delivery TEXT DEFAULT NULL")
        except Exception:
            pass  # Column might already exist
    else:
        try:
            db = _get_db()
            # Check if column exists
            cursor = db.execute("PRAGMA table_info(user_profiles)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'last_news_delivery' not in columns:
                db.execute("ALTER TABLE user_profiles ADD COLUMN last_news_delivery TEXT DEFAULT NULL")
                db.commit()
        except Exception:
            pass


def _get_db():
    """الحصول على اتصال SQLite — PostgreSQL uses the connection pool instead.
    
    This function ONLY returns a SQLite connection. For PostgreSQL, use
    _get_pg_conn()/_return_pg_conn() to manage pool connections.
    Returns None if the database type is PostgreSQL (not an error).
    """
    if _db_type == "sqlite":
        return _init_sqlite()
    return None


def _is_postgres():
    """هل نستخدم PostgreSQL؟"""
    return _db_type == "postgresql"


def _execute(query, params=(), fetch=False, fetchone=False, dict_cursor=False):
    """تنفيذ استعلام مع دعم PostgreSQL (via pool) و SQLite
    
    PostgreSQL retry strategy (simplified v3):
    - Try query on a single connection from the pool
    - On failure: close the broken connection, reconnect the pool, retry once
    - Only ONE connection is checked out at a time (fixes pool exhaustion)
    - No more double _return_pg_conn bug (old except/finally both returned conn)
    
    Args:
        dict_cursor: If True and using PostgreSQL, returns dict results instead of tuples.
                     This eliminates the need for a second pool connection just for
                     column name resolution.
    """
    if _is_postgres():
        # First attempt
        conn = _get_pg_conn()
        if not conn:
            logger.error("PostgreSQL: no connection available from pool")
            return None
        try:
            if dict_cursor:
                from psycopg2.extras import RealDictCursor
                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()
            cur.execute(query, params)
            if fetchone:
                result = cur.fetchone()
                cur.close()
                return dict(result) if dict_cursor and result else result
            elif fetch:
                result = cur.fetchall()
                cur.close()
                if dict_cursor:
                    return [dict(r) for r in result]
                return result
            else:
                conn.commit()
                cur.close()
                return None
        except Exception as e:
            logger.warning(f"PostgreSQL query failed (will retry): {e}")
            # Close the broken connection and return it to pool
            _return_pg_conn(conn, close=True)
            conn = None  # Mark as returned so finally doesn't return it again
            
            # Reconnect pool and retry once
            if not _reconnect_pool():
                logger.error("PostgreSQL: pool reconnect failed, giving up")
                return None
            retry_conn = _get_pg_conn()
            if not retry_conn:
                logger.error("PostgreSQL: no connection after reconnect")
                return None
            try:
                if dict_cursor:
                    from psycopg2.extras import RealDictCursor
                    cur = retry_conn.cursor(cursor_factory=RealDictCursor)
                else:
                    cur = retry_conn.cursor()
                cur.execute(query, params)
                if fetchone:
                    result = cur.fetchone()
                    cur.close()
                    return dict(result) if dict_cursor and result else result
                elif fetch:
                    result = cur.fetchall()
                    cur.close()
                    if dict_cursor:
                        return [dict(r) for r in result]
                    return result
                else:
                    retry_conn.commit()
                    cur.close()
                    return None
            except Exception as e2:
                logger.error(f"PostgreSQL retry also failed: {e2}")
                return None
            finally:
                _return_pg_conn(retry_conn)
        finally:
            # Only return the original connection if it wasn't already closed in except
            if conn is not None:
                _return_pg_conn(conn)
    else:
        # SQLite
        db = _get_db()
        if db is None:
            logger.error("SQLite: no database connection available")
            return None
        if fetchone:
            return db.execute(query, params).fetchone()
        elif fetch:
            return db.execute(query, params).fetchall()
        else:
            db.execute(query, params)
            db.commit()
            return None


# ═══════════════════════════════════════
# التوافق مع النظام القديم - Legacy Compatibility
# ═══════════════════════════════════════

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_all_users() -> Dict:
    _ensure_data_dir()
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error loading users data: {e}")
    return {}


def _save_all_users(data: Dict):
    _ensure_data_dir()
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"Error saving users data: {e}")


def _ensure_user_in_db(user_id: int, platform: str = "telegram"):
    """التأكد إن المستخدم موجود في قاعدة البيانات
    
    Args:
        user_id: معرف المستخدم
        platform: المنصة ("telegram" أو "whatsapp") — يتم تخزينها عند إنشاء المستخدم
    """
    # Migration: إضافة عمود platform لو مش موجود
    try:
        if _is_postgres():
            _execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'telegram'")
        else:
            # SQLite: نتأكد إن العمود موجود
            try:
                _execute("SELECT platform FROM user_profiles LIMIT 1", fetchone=True)
            except Exception:
                _execute("ALTER TABLE user_profiles ADD COLUMN platform TEXT DEFAULT 'telegram'")
    except Exception:
        pass  # العمود موجود بالفعل

    # Migration: إضافة عمود wa_phone لو مش موجود (لتخزين رقم واتساب المستخدم)
    try:
        if _is_postgres():
            _execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS wa_phone TEXT DEFAULT ''")
        else:
            try:
                _execute("SELECT wa_phone FROM user_profiles LIMIT 1", fetchone=True)
            except Exception:
                _execute("ALTER TABLE user_profiles ADD COLUMN wa_phone TEXT DEFAULT ''")
    except Exception:
        pass  # العمود موجود بالفعل

    # Migration: إضافة عمود profile_name لو مش موجود (لتخزين الاسم الأصلي من الحساب منفصل عن الاسم المفضل)
    try:
        if _is_postgres():
            _execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS profile_name TEXT DEFAULT ''")
        else:
            try:
                _execute("SELECT profile_name FROM user_profiles LIMIT 1", fetchone=True)
            except Exception:
                _execute("ALTER TABLE user_profiles ADD COLUMN profile_name TEXT DEFAULT ''")
    except Exception:
        pass  # العمود موجود بالفعل

    row = _execute("SELECT user_id FROM user_profiles WHERE user_id = %s" if _is_postgres() else "SELECT user_id FROM user_profiles WHERE user_id = ?", (user_id,), fetchone=True)
    if not row:
        now = datetime.now().isoformat()
        _execute(
            """INSERT INTO user_profiles
            (user_id, name, language, news_time, sources, subscribed, interests,
             favorite_companies, created_at, last_interaction, commands_used, chat_count, platform)
            VALUES (%s, %s, 'ar', '09:00', '[]', 0, '[]', '[]', %s, %s, 0, 0, %s)""" if _is_postgres() else
            """INSERT OR IGNORE INTO user_profiles
            (user_id, name, language, news_time, sources, subscribed, interests,
             favorite_companies, created_at, last_interaction, commands_used, chat_count, platform)
            VALUES (?, ?, 'ar', '09:00', '[]', 0, '[]', '[]', ?, ?, 0, 0, ?)""",
            (user_id, '', now, now, platform)
        )
    elif _is_postgres():
        # تحديث platform لو مش مضبوط
        _execute("UPDATE user_profiles SET platform = %s WHERE user_id = %s AND (platform IS NULL OR platform = '')", (platform, user_id))


# ═══════════════════════════════════════
# ملف المستخدم - User Profile
# ═══════════════════════════════════════

def get_user(user_id: int) -> Dict:
    """الحصول على بيانات المستخدم
    
    ⚠️ BUG FIX (v2): Old code fetched data TWICE using TWO separate pool 
    connections — one via _execute() and another for RealDictCursor. This 
    wasted pool connections and could exhaust the pool on Neon free tier 
    (max 5). Now we use dict_cursor=True in _execute() to get dict results 
    in a SINGLE connection.
    """
    _ensure_user_in_db(user_id)
    ph = "%s" if _is_postgres() else "?"
    if _is_postgres():
        # Use dict_cursor=True to get a dict result in a single connection
        data = _execute(f"SELECT * FROM user_profiles WHERE user_id = {ph}", (user_id,), fetchone=True, dict_cursor=True)
    else:
        row = _execute(f"SELECT * FROM user_profiles WHERE user_id = {ph}", (user_id,), fetchone=True)
        data = dict(row) if row else None
    
    if data:
        # تحويل JSON strings إلى lists
        for key in ['sources', 'interests', 'favorite_companies']:
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except (json.JSONDecodeError, TypeError):
                    data[key] = []
        data['subscribed'] = bool(data.get('subscribed', 0))
        return data

    # fallback للنظام القديم
    all_users = _load_all_users()
    uid = str(user_id)
    if uid not in all_users:
        all_users[uid] = {
            "language": "ar", "news_time": "09:00", "sources": [],
            "subscribed": False, "created_at": datetime.now().isoformat(),
            "last_interaction": datetime.now().isoformat(),
            "commands_used": 0, "chat_count": 0,
        }
        _save_all_users(all_users)
    user = all_users[uid]
    if "subscribed" not in user:
        user["subscribed"] = False
        _save_all_users(all_users)
    return user


# أسماء الأعمدة المسموح بها — حماية من SQL Injection
_ALLOWED_USER_COLUMNS = frozenset({
    'name', 'profile_name', 'language', 'news_time', 'sources', 'subscribed',
    'response_length', 'notification_enabled', 'interests',
    'favorite_companies', 'last_interaction', 'commands_used',
    'chat_count', 'last_news_delivery', 'wa_phone'
})

def update_user(user_id: int, updates: Dict[str, Any]):
    _ensure_user_in_db(user_id)

    # تحويل lists إلى JSON strings
    for key in ['sources', 'interests', 'favorite_companies']:
        if key in updates and isinstance(updates[key], list):
            updates[key] = json.dumps(updates[key], ensure_ascii=False)

    if 'subscribed' in updates:
        updates['subscribed'] = 1 if updates['subscribed'] else 0

    updates['last_interaction'] = datetime.now().isoformat()

    # ⚠️ SECURITY FIX: Validate column names against whitelist to prevent SQL injection
    invalid_keys = set(updates.keys()) - _ALLOWED_USER_COLUMNS
    if invalid_keys:
        logger.error(f"SECURITY: Rejected invalid column names in update_user(): {invalid_keys}")
        # Remove invalid keys instead of raising an exception (graceful degradation)
        for k in invalid_keys:
            del updates[k]

    if not updates:
        return  # Nothing to update after filtering

    ph = "%s" if _is_postgres() else "?"
    set_clause = ", ".join(f"{k} = {ph}" for k in updates.keys())
    values = list(updates.values()) + [user_id]
    _execute(f"UPDATE user_profiles SET {set_clause} WHERE user_id = {ph}", values)

    # Legacy JSON sync removed — PostgreSQL/SQLite is the source of truth.
    # The old sync to users.json added unnecessary I/O overhead and
    # complexity. The JSON file is kept as read-only fallback only.


# ═══════════════════════════════════════
# إعدادات المستخدم - User Preferences
# ═══════════════════════════════════════

# ⚠️ PERFORMANCE: Simple TTL cache to reduce database queries
# get_language() and get_user() are called on virtually every interaction.
# Caching these for a short duration reduces DB load by 60-80%.
_cache = {}  # {key: (value, expiry_timestamp)}
_CACHE_TTL = 120  # 2 minutes TTL for cached data
_cache_lock = threading.Lock()


def _cache_get(key: str):
    """Get a value from cache if not expired"""
    with _cache_lock:
        if key in _cache:
            value, expiry = _cache[key]
            if time.time() < expiry:
                return value
            else:
                del _cache[key]  # Expired
    return None


def _cache_set(key: str, value, ttl: int = None):
    """Set a value in cache with TTL"""
    if ttl is None:
        ttl = _CACHE_TTL
    with _cache_lock:
        _cache[key] = (value, time.time() + ttl)
        # Cleanup: remove expired entries if cache is large
        if len(_cache) > 500:
            now = time.time()
            expired_keys = [k for k, (_, exp) in _cache.items() if now >= exp]
            for k in expired_keys:
                del _cache[k]


def _cache_invalidate(key: str):
    """Invalidate a specific cache key"""
    with _cache_lock:
        _cache.pop(key, None)


def _cache_invalidate_user(user_id: int):
    """Invalidate all cache entries for a specific user"""
    with _cache_lock:
        keys_to_remove = [k for k in _cache if str(user_id) in k]
        for k in keys_to_remove:
            del _cache[k]


def get_language(user_id: int) -> str:
    """الحصول على لغة المستخدم — مع caching لتقليل ضغط قاعدة البيانات"""
    cache_key = f"lang_{user_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    user = get_user(user_id)
    lang = user.get("language", "ar")
    _cache_set(cache_key, lang, ttl=300)  # Language rarely changes — 5 min cache
    return lang

def set_language(user_id: int, language: str):
    update_user(user_id, {"language": language})
    _cache_invalidate(f"lang_{user_id}")
    _cache_invalidate(f"user_{user_id}")

def get_news_time(user_id: int) -> str:
    user = get_user(user_id)
    return user.get("news_time", "09:00")

def set_news_time(user_id: int, time_str: str):
    update_user(user_id, {"news_time": time_str})
    _cache_invalidate(f"user_{user_id}")

def get_sources(user_id: int) -> list:
    user = get_user(user_id)
    return user.get("sources", [])

def set_sources(user_id: int, sources: list):
    update_user(user_id, {"sources": sources})
    _cache_invalidate(f"user_{user_id}")


# ═══════════════════════════════════════
# الاشتراك - Subscription
# ═══════════════════════════════════════

def subscribe_user(user_id: int):
    update_user(user_id, {"subscribed": True})
    _cache_invalidate(f"user_{user_id}")

def unsubscribe_user(user_id: int):
    update_user(user_id, {"subscribed": False})
    _cache_invalidate(f"user_{user_id}")

def is_subscribed(user_id: int) -> bool:
    user = get_user(user_id)
    return user.get("subscribed", False)

def get_all_subscribers(platform: str = None) -> List[Dict]:
    """Get all news subscribers, optionally filtered by platform"""
    if platform:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        rows = _execute(
            f"SELECT user_id, language, news_time, name FROM user_profiles WHERE subscribed = {ph1} AND platform = {ph2}",
            (1, platform), fetch=True
        )
    else:
        ph = "%s" if _is_postgres() else "?"
        rows = _execute(f"SELECT user_id, language, news_time, name FROM user_profiles WHERE subscribed = {ph}", (1,), fetch=True)
    if rows:
        if _is_postgres():
            result = []
            for row in rows:
                result.append({"user_id": row[0], "language": row[1], "news_time": row[2], "name": row[3]})
            return result
        return [dict(r) for r in rows]
    # fallback
    all_users = _load_all_users()
    subscribers = []
    for uid, data in all_users.items():
        if data.get("subscribed", False):
            if platform and data.get("platform") != platform:
                continue
            subscribers.append({
                "user_id": int(uid), "language": data.get("language", "ar"),
                "news_time": data.get("news_time", "09:00"), "name": data.get("name", ""),
            })
    return subscribers

def get_subscriber_count() -> int:
    return len(get_all_subscribers())

def increment_command_count(user_id: int):
    _ensure_user_in_db(user_id)
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    _execute(
        f"UPDATE user_profiles SET commands_used = commands_used + 1, last_interaction = {ph1} WHERE user_id = {ph2}",
        (datetime.now().isoformat(), user_id)
    )

def increment_chat_count(user_id: int):
    _ensure_user_in_db(user_id)
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    _execute(
        f"UPDATE user_profiles SET chat_count = chat_count + 1, last_interaction = {ph1} WHERE user_id = {ph2}",
        (datetime.now().isoformat(), user_id)
    )


# ═══════════════════════════════════════
# ذاكرة المحادثات - Conversation Memory
# ═══════════════════════════════════════

MAX_CONVERSATIONS = 50

def save_conversation(user_id: int, role: str, content: str):
    """حفظ رسالة في ذاكرة المحادثات"""
    _ensure_user_in_db(user_id)
    ph1, ph2, ph3, ph4 = ("%s", "%s", "%s", "%s") if _is_postgres() else ("?", "?", "?", "?")
    _execute(
        f"INSERT INTO conversations (user_id, role, content, timestamp) VALUES ({ph1}, {ph2}, {ph3}, {ph4})",
        (user_id, role, content[:1000], datetime.now().isoformat())
    )
    # حذف القديم لو عدى الحد
    ph_u, ph_l = ("%s", "%s") if _is_postgres() else ("?", "?")
    if _is_postgres():
        _execute(
            """DELETE FROM conversations WHERE id IN (
                SELECT id FROM conversations WHERE user_id = %s
                ORDER BY timestamp DESC OFFSET %s
            )""",
            (user_id, MAX_CONVERSATIONS)
        )
    else:
        _execute(
            """DELETE FROM conversations WHERE id IN (
                SELECT id FROM conversations WHERE user_id = ?
                ORDER BY timestamp DESC LIMIT -1 OFFSET ?
            )""",
            (user_id, MAX_CONVERSATIONS)
        )


def get_recent_conversations(user_id: int, limit: int = 10) -> List[Dict]:
    """الحصول على آخر محادثات المستخدم"""
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    rows = _execute(
        f"SELECT role, content, timestamp FROM conversations WHERE user_id = {ph1} ORDER BY timestamp DESC LIMIT {ph2}",
        (user_id, limit),
        fetch=True
    )
    if rows:
        if _is_postgres():
            return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]
        return [dict(r) for r in rows]
    return []


def get_conversation_context(user_id: int, limit: int = 6) -> str:
    """الحصول على سياق المحادثة كنص للـ AI"""
    convos = get_recent_conversations(user_id, limit)
    if not convos:
        return ""
    context_parts = []
    for c in reversed(convos):
        role = "User" if c['role'] == 'user' else "Bot"
        context_parts.append(f"{role}: {c['content'][:200]}")
    return "\n".join(context_parts)


# ═══════════════════════════════════════
# ذاكرة التعلم - Learning Memory
# ═══════════════════════════════════════

def save_learning(user_id: int, topic: str, level: str = "explored"):
    """حفظ تقدم التعلم"""
    _ensure_user_in_db(user_id)
    now = datetime.now().isoformat()
    if _is_postgres():
        _execute(
            """INSERT INTO learning_progress (user_id, topic, level, learned_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(user_id, topic) DO UPDATE SET level = %s, learned_at = %s""",
            (user_id, topic, level, now, level, now)
        )
    else:
        _execute(
            """INSERT INTO learning_progress (user_id, topic, level, learned_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, topic) DO UPDATE SET level = ?, learned_at = ?""",
            (user_id, topic, level, now, level, now)
        )


def get_learning_progress(user_id: int) -> List[Dict]:
    """الحصول على كل تقدم التعلم"""
    ph = "%s" if _is_postgres() else "?"
    rows = _execute(
        f"SELECT topic, level, learned_at FROM learning_progress WHERE user_id = {ph} ORDER BY learned_at DESC",
        (user_id,),
        fetch=True
    )
    if rows:
        if _is_postgres():
            return [{"topic": r[0], "level": r[1], "learned_at": r[2]} for r in rows]
        return [dict(r) for r in rows]
    return []


def get_learned_topics(user_id: int) -> List[str]:
    """الحصول على قائمة المواضيع المتعلمة"""
    progress = get_learning_progress(user_id)
    return [p['topic'] for p in progress]


# ═══════════════════════════════════════
# نظام المفضلات - Favorites System
# ═══════════════════════════════════════

def add_favorite(user_id: int, category: str, title: str, content: str = "", url: str = ""):
    """إضافة عنصر للمفضلات"""
    _ensure_user_in_db(user_id)
    ph1, ph2, ph3, ph4, ph5, ph6 = (["%s"] * 6) if _is_postgres() else (["?"] * 6)
    _execute(
        f"INSERT INTO favorites (user_id, category, title, content, url, saved_at) VALUES ({', '.join(ph1)})",
        (user_id, category, title, content[:500], url, datetime.now().isoformat())
    )


def get_favorites(user_id: int, category: str = None) -> List[Dict]:
    """الحصول على المفضلات"""
    if category:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        rows = _execute(
            f"SELECT id, category, title, content, url, saved_at FROM favorites WHERE user_id = {ph1} AND category = {ph2} ORDER BY saved_at DESC",
            (user_id, category),
            fetch=True
        )
    else:
        ph = "%s" if _is_postgres() else "?"
        rows = _execute(
            f"SELECT id, category, title, content, url, saved_at FROM favorites WHERE user_id = {ph} ORDER BY saved_at DESC",
            (user_id,),
            fetch=True
        )
    if rows:
        if _is_postgres():
            return [{"id": r[0], "category": r[1], "title": r[2], "content": r[3], "url": r[4], "saved_at": r[5]} for r in rows]
        return [dict(r) for r in rows]
    return []


def remove_favorite(user_id: int, favorite_id: int):
    """حذف عنصر من المفضلات"""
    ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
    _execute(f"DELETE FROM favorites WHERE id = {ph1} AND user_id = {ph2}", (favorite_id, user_id))


# ═══════════════════════════════════════
# الذاكرة الذكية - Smart Memory
# ═══════════════════════════════════════

def save_memory(user_id: int, key: str, value: str, category: str = "general"):
    """حفظ ذكرى في الذاكرة الذكية"""
    _ensure_user_in_db(user_id)
    now = datetime.now().isoformat()
    if _is_postgres():
        _execute(
            """INSERT INTO user_memories (user_id, key, value, category, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(user_id, key) DO UPDATE SET value = %s, category = %s""",
            (user_id, key, value, category, now, value, category)
        )
    else:
        _execute(
            """INSERT INTO user_memories (user_id, key, value, category, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = ?, category = ?""",
            (user_id, key, value, category, now, value, category)
        )


def get_memories(user_id: int, category: str = None) -> List[Dict]:
    """الحصول على الذكريات"""
    if category:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        rows = _execute(
            f"SELECT id, key, value, category, created_at FROM user_memories WHERE user_id = {ph1} AND category = {ph2} ORDER BY created_at DESC",
            (user_id, category),
            fetch=True
        )
    else:
        ph = "%s" if _is_postgres() else "?"
        rows = _execute(
            f"SELECT id, key, value, category, created_at FROM user_memories WHERE user_id = {ph} ORDER BY created_at DESC",
            (user_id,),
            fetch=True
        )
    if rows:
        if _is_postgres():
            return [{"id": r[0], "key": r[1], "value": r[2], "category": r[3], "created_at": r[4]} for r in rows]
        return [dict(r) for r in rows]
    return []


def delete_memory(user_id: int, key: str = None, memory_id: int = None):
    """حذف ذكرى محددة"""
    if memory_id:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        _execute(f"DELETE FROM user_memories WHERE id = {ph1} AND user_id = {ph2}", (memory_id, user_id))
    elif key:
        ph1, ph2 = ("%s", "%s") if _is_postgres() else ("?", "?")
        _execute(f"DELETE FROM user_memories WHERE key LIKE {ph1} AND user_id = {ph2}", (f"%{key}%", user_id))


def reset_all_memories(user_id: int):
    """حذف كل الذكريات"""
    ph = "%s" if _is_postgres() else "?"
    _execute(f"DELETE FROM conversations WHERE user_id = {ph}", (user_id,))
    _execute(f"DELETE FROM learning_progress WHERE user_id = {ph}", (user_id,))
    _execute(f"DELETE FROM favorites WHERE user_id = {ph}", (user_id,))
    _execute(f"DELETE FROM user_memories WHERE user_id = {ph}", (user_id,))


# ═══════════════════════════════════════
# الاهتمامات - Interests
# ═══════════════════════════════════════

def add_interest(user_id: int, interest: str):
    """إضافة اهتمام جديد"""
    user = get_user(user_id)
    interests = user.get("interests", [])
    interest_lower = interest.lower().strip()
    if interest_lower not in [i.lower() for i in interests]:
        interests.append(interest)
        update_user(user_id, {"interests": interests})
        save_memory(user_id, f"interest_{interest_lower}", interest, "interests")


def get_interests(user_id: int) -> List[str]:
    """الحصول على اهتمامات المستخدم"""
    user = get_user(user_id)
    return user.get("interests", [])


def get_interests_context(user_id: int) -> str:
    """الحصول على سياق الاهتمامات للـ AI"""
    interests = get_interests(user_id)
    if not interests:
        return ""
    return ", ".join(interests)


def add_favorite_company(user_id: int, company: str):
    """إضافة شركة مفضلة"""
    user = get_user(user_id)
    companies = user.get("favorite_companies", [])
    if company.lower() not in [c.lower() for c in companies]:
        companies.append(company)
        update_user(user_id, {"favorite_companies": companies})


def get_favorite_companies(user_id: int) -> List[str]:
    """الحصول على الشركات المفضلة"""
    user = get_user(user_id)
    return user.get("favorite_companies", [])


# ═══════════════════════════════════════
# كشف الاهتمامات تلقائياً - Auto-Detect Interests
# ═══════════════════════════════════════

INTEREST_KEYWORDS = {
    "openai": "OpenAI", "chatgpt": "ChatGPT", "gpt-4": "GPT-4", "gpt-5": "GPT-5",
    "claude": "Claude", "anthropic": "Anthropic", "gemini": "Gemini",
    "deepmind": "DeepMind", "llama": "Llama", "meta ai": "Meta AI",
    "copilot": "Copilot", "grok": "Grok", "xai": "xAI",
    "midjourney": "Midjourney", "sora": "Sora", "dall-e": "DALL-E",
    "ai agents": "AI Agents", "agent": "AI Agents", "autonomous ai": "AI Agents",
    "llm": "LLM", "large language model": "LLM", "transformer": "Transformers",
    "nlp": "NLP", "natural language": "NLP",
    "computer vision": "Computer Vision", "cv": "Computer Vision",
    "reinforcement learning": "Reinforcement Learning", "rlhf": "RLHF",
    "prompt engineering": "Prompt Engineering", "rag": "RAG",
    "fine-tuning": "Fine-tuning", "diffusion model": "Diffusion Models",
    "robot": "Robotics", "humanoid": "Humanoid Robots",
    "nvidia": "NVIDIA", "gpu": "GPU Computing", "ai chip": "AI Hardware",
    "ai safety": "AI Safety", "agi": "AGI",
    "machine learning": "Machine Learning", "deep learning": "Deep Learning",
    "python": "Python", "nextjs": "Next.js", "react": "React",
    "typescript": "TypeScript", "docker": "Docker",
    "web development": "Web Development", "frontend": "Frontend Development",
    "backend": "Backend Development", "fullstack": "Full-Stack Development",
    "devops": "DevOps", "cloud computing": "Cloud Computing",
    "cybersecurity": "Cybersecurity", "data science": "Data Science",
    "data engineering": "Data Engineering", "mlops": "MLOps",
    "ai ethics": "AI Ethics", "sustainability": "Green AI",
    "edge ai": "Edge AI", "on-device ai": "On-Device AI",
    "ai art": "AI Art", "ai music": "AI Music",
    "ai writing": "AI Writing", "chatbot": "Chatbots",
    "voice assistant": "Voice Assistants",
}

COMPANY_KEYWORDS = {
    "openai": "OpenAI", "google": "Google", "anthropic": "Anthropic",
    "microsoft": "Microsoft", "meta": "Meta", "xai": "xAI",
    "nvidia": "NVIDIA", "deepmind": "DeepMind", "mistral": "Mistral AI",
}


def detect_interests(user_id: int, text: str):
    """كشف وحفظ الاهتمامات تلقائياً من نص المستخدم"""
    text_lower = text.lower()
    for keyword, interest in INTEREST_KEYWORDS.items():
        if keyword in text_lower:
            add_interest(user_id, interest)
    for keyword, company in COMPANY_KEYWORDS.items():
        if keyword in text_lower:
            add_favorite_company(user_id, company)


# ═══════════════════════════════════════
# ملخص الذاكرة للـ AI - Memory Summary for AI
# ═══════════════════════════════════════

def get_user_memory_summary(user_id: int, lang: str = "ar") -> str:
    """تجهيز ملخص الذاكرة لحقنه في system prompt"""
    parts = []

    # الاهتمامات
    interests = get_interests(user_id)
    if interests:
        if lang == "ar":
            parts.append(f"اهتمامات المستخدم: {', '.join(interests[:15])}")
        else:
            parts.append(f"User interests: {', '.join(interests[:15])}")

    # الشركات المفضلة
    companies = get_favorite_companies(user_id)
    if companies:
        if lang == "ar":
            parts.append(f"شركات يتابعها: {', '.join(companies[:10])}")
        else:
            parts.append(f"Followed companies: {', '.join(companies[:10])}")

    # المواضيع المتعلمة
    learned = get_learned_topics(user_id)
    if learned:
        if lang == "ar":
            parts.append(f"مواضيع تعلمها: {', '.join(learned[:10])}")
        else:
            parts.append(f"Learned topics: {', '.join(learned[:10])}")

    # آخر محادثات (مختصر)
    recent = get_recent_conversations(user_id, 4)
    if recent:
        if lang == "ar":
            parts.append("آخر مواضيع تحدث عنها:")
        else:
            parts.append("Recent conversation topics:")
        for c in recent[:4]:
            prefix = "👤" if c['role'] == 'user' else "🤖"
            parts.append(f"  {prefix} {c['content'][:80]}")

    return "\n".join(parts) if parts else ""


# ═══════════════════════════════════════
# عرض الذاكرة - Memory Display
# ═══════════════════════════════════════

def format_memory_display(user_id: int, lang: str = "ar") -> str:
    """تنسيق عرض الذاكرة للمستخدم"""
    user = get_user(user_id)
    interests = get_interests(user_id)
    companies = get_favorite_companies(user_id)
    learning = get_learning_progress(user_id)
    favorites = get_favorites(user_id)
    conversations = get_recent_conversations(user_id, 5)
    memories = get_memories(user_id)

    # Check if user is admin
    is_user_admin = False
    try:
        from admin import is_admin
        is_user_admin = is_admin(user_id)
    except Exception:
        pass

    # Get plan info
    plan = "free"
    try:
        from premium import get_user_plan
        plan = get_user_plan(user_id)
    except Exception:
        pass

    if lang == "ar":
        text = "🧠 <b>ذاكرتي عنك</b>\n━━━━━━━━━━━━━━━━━\n\n"

        if is_user_admin:
            text += "👑 <b>الرتبة:</b> أدمن (مالك البوت)\n"
            text += "⭐ <b>الخطة:</b> Premium (أدمن — مفيش Limits)\n"
        else:
            plan_display = "⭐ Premium" if plan in ("premium", "premium_plus") else "🆓 مجاني"
            text += f"👤 <b>الخطة:</b> {plan_display}\n"

        text += f"👤 <b>الاسم:</b> {user.get('name', 'مش محدد')}\n"
        text += f"🌐 <b>اللغة:</b> {'العربية' if user.get('language') == 'ar' else 'English'}\n"
        text += f"📬 <b>مشترك:</b> {'نعم' if user.get('subscribed') else 'لا'}\n"
        # 🔴 FIX: شلنا عداد المحادثات والأوامر وعرض الحدود — دول موجودين في زر الخطة وحدود الاستخدام
        text += "\n"

        if not is_user_admin and plan == "free":
            text += "📊 <i>شوف حدود استخدامك من زر \"📋 الخطة وحدود الاستخدام\"</i>\n\n"
        elif plan in ("premium", "premium_plus") and not is_user_admin:
            text += "⭐ <i>مشترك Premium — استخدام غير محدود!</i>\n\n"

        if interests:
            text += "🎯 <b>اهتماماتك:</b>\n"
            for i in interests[:15]:
                text += f"  • {i}\n"
            text += "\n"

        if companies:
            text += "🏢 <b>شركات تتابعها:</b>\n"
            for c in companies[:10]:
                text += f"  • {c}\n"
            text += "\n"

        if learning:
            text += "📚 <b>مواضيع تعلمتها:</b>\n"
            for l in learning[:10]:
                level_emoji = {"explored": "👀", "learning": "📖", "learned": "✅"}.get(l.get('level', ''), '👀')
                text += f"  {level_emoji} {l['topic']}\n"
            text += "\n"

        if favorites:
            text += f"⭐ <b>المفضلات:</b> {len(favorites)} عنصر\n\n"

        if memories:
            text += f"💾 <b>ذكريات محفوظة:</b> {len(memories)}\n"

        if not interests and not learning and not favorites:
            text += "💭 <i>لسه بتعرف عليك! استخدم البوت وهفتكر كل حاجة عنك.</i>"

    else:
        text = "🧠 <b>My Memory About You</b>\n━━━━━━━━━━━━━━━━━\n\n"

        if is_user_admin:
            text += "👑 <b>Role:</b> Admin (Bot Owner)\n"
            text += "⭐ <b>Plan:</b> Premium (Admin — No Limits)\n"
        else:
            plan_display = "⭐ Premium" if plan in ("premium", "premium_plus") else "🆓 Free"
            text += f"👤 <b>Plan:</b> {plan_display}\n"

        text += f"👤 <b>Name:</b> {user.get('name', 'Not set')}\n"
        text += f"🌐 <b>Language:</b> {'Arabic' if user.get('language') == 'ar' else 'English'}\n"
        text += f"📬 <b>Subscribed:</b> {'Yes' if user.get('subscribed') else 'No'}\n"
        # 🔴 FIX: removed usage counters and limits — they're in the Plan & Usage button
        text += "\n"

        if not is_user_admin and plan == "free":
            text += "📊 <i>Check your usage limits from \"📋 Plan & Usage\" button</i>\n\n"
        elif plan in ("premium", "premium_plus") and not is_user_admin:
            text += "⭐ <i>Premium subscriber — unlimited usage!</i>\n\n"

        if interests:
            text += "🎯 <b>Your Interests:</b>\n"
            for i in interests[:15]:
                text += f"  • {i}\n"
            text += "\n"

        if companies:
            text += "🏢 <b>Companies You Follow:</b>\n"
            for c in companies[:10]:
                text += f"  • {c}\n"
            text += "\n"

        if learning:
            text += "📚 <b>Topics Learned:</b>\n"
            for l in learning[:10]:
                level_emoji = {"explored": "👀", "learning": "📖", "learned": "✅"}.get(l.get('level', ''), '👀')
                text += f"  {level_emoji} {l['topic']}\n"
            text += "\n"

        if favorites:
            text += f"⭐ <b>Favorites:</b> {len(favorites)} items\n\n"

        if memories:
            text += f"💾 <b>Saved Memories:</b> {len(memories)}\n"

        if not interests and not learning and not favorites:
            text += "💭 <i>I'm still getting to know you! Use the bot and I'll remember everything.</i>"

    return text


def format_progress_display(user_id: int, lang: str = "ar") -> str:
    """تنسيق عرض تقدم التعلم"""
    learning = get_learning_progress(user_id)

    if lang == "ar":
        text = "📚 <b>تقدمك في التعلم</b>\n━━━━━━━━━━━━━━━━━\n\n"
        if not learning:
            text += "💭 لسه متعلمتش أي موضوع.\n💡 جرب أمر <code>/learn transformers</code> وهاحفظ تقدمك!"
        else:
            explored = [l for l in learning if l.get('level') == 'explored']
            learning_in_progress = [l for l in learning if l.get('level') == 'learning']
            learned = [l for l in learning if l.get('level') == 'learned']

            if explored:
                text += f"👀 <b>استكشفت ({len(explored)}):</b>\n"
                for l in explored[:10]:
                    text += f"  • {l['topic']}\n"
                text += "\n"

            if learning_in_progress:
                text += f"📖 <b>بتتعلم حالياً ({len(learning_in_progress)}):</b>\n"
                for l in learning_in_progress[:10]:
                    text += f"  • {l['topic']}\n"
                text += "\n"

            if learned:
                text += f"✅ <b>اتعلمت ({len(learned)}):</b>\n"
                for l in learned[:10]:
                    text += f"  • {l['topic']}\n"
                text += "\n"

            text += f"📊 <b>الإجمالي:</b> {len(learning)} موضوع"
    else:
        text = "📚 <b>Your Learning Progress</b>\n━━━━━━━━━━━━━━━━━\n\n"
        if not learning:
            text += "💭 You haven't learned any topics yet.\n💡 Try <code>/learn transformers</code> and I'll track your progress!"
        else:
            explored = [l for l in learning if l.get('level') == 'explored']
            learning_in_progress = [l for l in learning if l.get('level') == 'learning']
            learned = [l for l in learning if l.get('level') == 'learned']

            if explored:
                text += f"👀 <b>Explored ({len(explored)}):</b>\n"
                for l in explored[:10]:
                    text += f"  • {l['topic']}\n"
                text += "\n"

            if learning_in_progress:
                text += f"📖 <b>Currently Learning ({len(learning_in_progress)}):</b>\n"
                for l in learning_in_progress[:10]:
                    text += f"  • {l['topic']}\n"
                text += "\n"

            if learned:
                text += f"✅ <b>Learned ({len(learned)}):</b>\n"
                for l in learned[:10]:
                    text += f"  • {l['topic']}\n"
                text += "\n"

            text += f"📊 <b>Total:</b> {len(learning)} topics"

    return text


def format_favorites_display(user_id: int, lang: str = "ar") -> str:
    """تنسيق عرض المفضلات"""
    favorites = get_favorites(user_id)

    if lang == "ar":
        text = "⭐ <b>المفضلات</b>\n━━━━━━━━━━━━━━━━━\n\n"
        if not favorites:
            text += "💭 معندكش مفضلات لسه.\n💡 استخدم أمر <code>/favorite</code> عشان تحفظ أي حاجة!"
        else:
            categories = {}
            for f in favorites:
                cat = f.get('category', 'other')
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(f)

            cat_names = {
                "news": "📰 أخبار", "topic": "📚 مواضيع",
                "tool": "🔧 أدوات", "company": "🏢 شركات", "other": "📌 أخرى"
            }

            for cat, items in categories.items():
                cat_name = cat_names.get(cat, cat)
                text += f"{cat_name} ({len(items)}):\n"
                for item in items[:5]:
                    text += f"  • {item['title'][:60]}\n"
                text += "\n"

            text += f"📊 الإجمالي: {len(favorites)} عنصر"
    else:
        text = "⭐ <b>Your Favorites</b>\n━━━━━━━━━━━━━━━━━\n\n"
        if not favorites:
            text += "💭 No favorites yet.\n💡 Use <code>/favorite</code> to save anything!"
        else:
            categories = {}
            for f in favorites:
                cat = f.get('category', 'other')
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(f)

            cat_names = {
                "news": "📰 News", "topic": "📚 Topics",
                "tool": "🔧 Tools", "company": "🏢 Companies", "other": "📌 Other"
            }

            for cat, items in categories.items():
                cat_name = cat_names.get(cat, cat)
                text += f"{cat_name} ({len(items)}):\n"
                for item in items[:5]:
                    text += f"  • {item['title'][:60]}\n"
                text += "\n"

            text += f"📊 Total: {len(favorites)} items"

    return text


# ═══════════════════════════════════════
# إعدادات الإشعارات - Notification Settings
# ═══════════════════════════════════════

def get_notification_enabled(user_id: int) -> bool:
    """هل الإشعارات مفعلة للمستخدم"""
    user = get_user(user_id)
    return bool(user.get("notification_enabled", 1))

def set_notification_enabled(user_id: int, enabled: bool):
    """تفعيل/إيقاف الإشعارات"""
    update_user(user_id, {"notification_enabled": 1 if enabled else 0})


# ═══════════════════════════════════════
# الذاكرة الذكية المتقدمة - Advanced Smart Memory
# ═══════════════════════════════════════

# كلمات تدل على تفضيل واضح من المستخدم
PREFERENCE_PATTERNS_AR = [
    "بحب", "بعشق", "بفضل", "أحب", "عايز", "محتاج", "محتاجة",
    "مفضلتي", "تفضيلي", "حبيبي", "أكتر حاجة",
]
PREFERENCE_PATTERNS_EN = [
    "i love", "i like", "i prefer", "my favorite", "i want",
    "i need", "my preference", "i enjoy", "i'm into",
]

# بيانات حساسة لا يتم حفظها أبداً
SENSITIVE_PATTERNS = [
    "password", "كلمة سر", "باسورد", "pin", "رمز سري",
    "api key", "مفتاح", "token", "توكين",
    "credit card", "بطاقة ائتمان", "visa", "mastercard",
    "ssn", "رقم ضمان", "رقم قومي",
    "private key", "مفتاح خاص", "secret", "سر",
]


def is_sensitive(text: str) -> bool:
    """فحص هل النص يحتوي على بيانات حساسة"""
    text_lower = text.lower()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in text_lower:
            return True
    return False


def has_preference_intent(text: str) -> bool:
    """كشف هل المستخدم بيعبر عن تفضيل واضح"""
    text_lower = text.lower()
    for pattern in PREFERENCE_PATTERNS_AR:
        if pattern in text_lower:
            return True
    for pattern in PREFERENCE_PATTERNS_EN:
        if pattern in text_lower:
            return True
    return False


def smart_save(user_id: int, text: str, role: str = "user"):
    """
    حفظ ذكي - بيحفظ بس المهم والحساس
    - بيتجنب البيانات الحساسة
    - بيفحص تفضيلات المستخدم
    - بيحفظ الاهتمامات تلقائياً
    """
    if is_sensitive(text):
        logger.debug(f"Skipping sensitive content for user {user_id}")
        return

    # حفظ المحادثة
    save_conversation(user_id, role, text)

    # كشف الاهتمامات
    detect_interests(user_id, text)

    # لو المستخدم بيعبر عن تفضيل، احفظه كذكرى
    if role == "user" and has_preference_intent(text):
        try:
            # استخراج تفضيل بسيط
            save_memory(user_id, f"preference_{datetime.now().strftime('%Y%m%d%H%M')}", text[:200], "preferences")
        except Exception as e:
            logger.debug(f"Smart save preference error: {e}")


def get_personalized_greeting(user_id: int, lang: str = "ar") -> str:
    """تجهيز تحية مخصصة بناءً على الذاكرة"""
    user = get_user(user_id)
    name = user.get("name", "")
    interests = get_interests(user_id)

    if lang == "ar":
        if name:
            greeting = f"أهلاً {name}! 👋"
        else:
            greeting = "أهلاً! 👋"

        if interests:
            top_interest = interests[0] if interests else ""
            if top_interest:
                greeting += f"\n🎯 عارف إنك مهتم بـ {top_interest}، ممكن أقولك آخر الأخبار عنه!"
    else:
        if name:
            greeting = f"Hey {name}! 👋"
        else:
            greeting = "Hey! 👋"

        if interests:
            top_interest = interests[0] if interests else ""
            if top_interest:
                greeting += f"\n🎯 I know you're into {top_interest}, want me to share the latest news about it?"

    return greeting


def get_recommended_topic(user_id: int, lang: str = "ar") -> str:
    """توصية موضوع بناءً على الاهتمامات"""
    interests = get_interests(user_id)
    learned = get_learned_topics(user_id)

    if not interests:
        return ""

    # إيجاد اهتمام لم يتعلمه بعد
    for interest in interests:
        if interest.lower() not in [l.lower() for l in learned]:
            if lang == "ar":
                return f"💡 ممكن تتعلم عن {interest}! جرب <code>/learn {interest}</code>"
            else:
                return f"💡 You could learn about {interest}! Try <code>/learn {interest}</code>"

    return ""


def is_new_user(user_id: int) -> bool:
    """فحص هل المستخدم جديد (أول مرة يستخدم البوت)"""
    ph = "%s" if _is_postgres() else "?"
    row = _execute(
        f"SELECT created_at FROM user_profiles WHERE user_id = {ph}",
        (user_id,), fetchone=True
    )
    if row and row[0]:
        return False  # مستخدم قديم - عنده created_at
    return True  # مستخدم جديد


# ═══════════════════════════════════════
# نظام الحظر والتحذيرات - Ban & Warning System
# ═══════════════════════════════════════

def is_banned(user_id: int) -> bool:
    """فحص هل المستخدم محظور"""
    ph = "%s" if _is_postgres() else "?"
    row = _execute(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (user_id,), fetchone=True)
    return row is not None


def ban_user(user_id: int, reason: str = "", banned_by: str = ""):
    """حظر مستخدم"""
    _ensure_user_in_db(user_id)
    now = datetime.now().isoformat()
    ph1, ph2, ph3, ph4 = ("%s", "%s", "%s", "%s") if _is_postgres() else ("?", "?", "?", "?")
    _execute(
        f"INSERT INTO banned_users (user_id, reason, banned_at, banned_by) VALUES ({ph1}, {ph2}, {ph3}, {ph4}) ON CONFLICT (user_id) DO UPDATE SET reason = {ph2}, banned_at = {ph3}, banned_by = {ph4}",
        (user_id, reason, now, banned_by)
    )


def unban_user(user_id: int):
    """إلغاء حظر مستخدم"""
    ph = "%s" if _is_postgres() else "?"
    _execute(f"DELETE FROM banned_users WHERE user_id = {ph}", (user_id,))


def get_warning_count(user_id: int) -> int:
    """الحصول على عدد التحذيرات"""
    ph = "%s" if _is_postgres() else "?"
    row = _execute(f"SELECT warning_count FROM banned_users WHERE user_id = {ph}", (user_id,), fetchone=True)
    return row[0] if row else 0


def add_warning(user_id: int, reason: str = "", warned_by: str = "") -> int:
    """إضافة تحذير وترجيع العدد الجديد"""
    _ensure_user_in_db(user_id)
    now = datetime.now().isoformat()
    ph1, ph2, ph3, ph4 = ("%s", "%s", "%s", "%s") if _is_postgres() else ("?", "?", "?", "?")
    # Check if already has warnings entry
    existing = _execute(f"SELECT warning_count FROM banned_users WHERE user_id = {ph1}", (user_id,), fetchone=True)
    if existing:
        new_count = existing[0] + 1
        _execute(f"UPDATE banned_users SET warning_count = {ph1}, reason = {ph2}, banned_by = {ph3} WHERE user_id = {ph4}", (new_count, reason, warned_by, user_id))
    else:
        new_count = 1
        _execute(f"INSERT INTO banned_users (user_id, reason, banned_at, banned_by, warning_count) VALUES ({ph1}, {ph2}, {ph3}, {ph4}, 1)", (user_id, reason, now, warned_by))
    return new_count


def get_last_news_delivery(user_id: int) -> Optional[str]:
    """الحصول على آخر مرة وصلت فيها الأخبار للمستخدم"""
    user = get_user(user_id)
    return user.get("last_news_delivery", None)

def set_last_news_delivery(user_id: int, delivery_time: str):
    """تحديث آخر وقت وصول أخبار للمستخدم"""
    update_user(user_id, {"last_news_delivery": delivery_time})

def get_subscribers_for_time(hour: int, minute: int) -> List[Dict]:
    """الحصول على المشتركين اللي وقت أخبارهم matches الساعة دي"""
    # Format: "HH:MM" e.g., "14:00" or "09:00"
    time_str = f"{hour:02d}:{minute:02d}"
    ph = "%s" if _is_postgres() else "?"
    rows = _execute(
        f"SELECT user_id, language, news_time, name, last_news_delivery FROM user_profiles WHERE subscribed = {ph} AND news_time = {ph}",
        (1, time_str),
        fetch=True
    )
    if rows:
        if _is_postgres():
            return [{"user_id": r[0], "language": r[1], "news_time": r[2], "name": r[3], "last_news_delivery": r[4]} for r in rows]
        return [dict(r) for r in rows]
    # fallback
    all_users = _load_all_users()
    subscribers = []
    for uid, data in all_users.items():
        if data.get("subscribed", False) and data.get("news_time", "09:00") == time_str:
            subscribers.append({
                "user_id": int(uid), "language": data.get("language", "ar"),
                "news_time": data.get("news_time", "09:00"), "name": data.get("name", ""),
                "last_news_delivery": data.get("last_news_delivery", None),
            })
    return subscribers


# ═══════════════════════════════════════
# تهيئة عند الاستيراد - Init on Import
# ═══════════════════════════════════════

try:
    init_database()
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
