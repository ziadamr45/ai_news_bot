"""
نظام الذاكرة المتقدم - Advanced Memory System
يستخدم SQLite لتخزين دائم يتجاوز إعادة تشغيل البوت

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
import sqlite3
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime

from config import DATA_DIR, USERS_FILE, DATABASE_PATH

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# إعداد قاعدة البيانات - Database Setup
# ═══════════════════════════════════════

_local = threading.local()


def _get_db() -> sqlite3.Connection:
    """الحصول على اتصال قاعدة البيانات (thread-local)"""
    if not hasattr(_local, 'connection') or _local.connection is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _local.connection = sqlite3.connect(DATABASE_PATH, timeout=10)
        _local.connection.row_factory = sqlite3.Row
        _local.connection.execute("PRAGMA journal_mode=WAL")
        _local.connection.execute("PRAGMA foreign_keys=ON")
    return _local.connection


def init_database():
    """إنشاء جداول قاعدة البيانات لو مش موجودة"""
    db = _get_db()
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
            chat_count INTEGER DEFAULT 0
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

        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_learning_user ON learning_progress(user_id);
        CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id, category);
        CREATE INDEX IF NOT EXISTS idx_memories_user ON user_memories(user_id, category);
    """)
    db.commit()
    logger.info("Database initialized successfully")


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


def _ensure_user_in_db(user_id: int):
    """التأكد إن المستخدم موجود في قاعدة البيانات"""
    db = _get_db()
    row = db.execute("SELECT user_id FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        now = datetime.now().isoformat()
        db.execute(
            """INSERT OR IGNORE INTO user_profiles
            (user_id, name, language, news_time, sources, subscribed, interests,
             favorite_companies, created_at, last_interaction, commands_used, chat_count)
            VALUES (?, ?, 'ar', '09:00', '[]', 0, '[]', '[]', ?, ?, 0, 0)""",
            (user_id, '', now, now)
        )
        db.commit()


# ═══════════════════════════════════════
# ملف المستخدم - User Profile
# ═══════════════════════════════════════

def get_user(user_id: int) -> Dict:
    _ensure_user_in_db(user_id)
    db = _get_db()
    row = db.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        data = dict(row)
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


def update_user(user_id: int, updates: Dict[str, Any]):
    _ensure_user_in_db(user_id)
    db = _get_db()

    # تحويل lists إلى JSON strings
    for key in ['sources', 'interests', 'favorite_companies']:
        if key in updates and isinstance(updates[key], list):
            updates[key] = json.dumps(updates[key], ensure_ascii=False)

    if 'subscribed' in updates:
        updates['subscribed'] = 1 if updates['subscribed'] else 0

    updates['last_interaction'] = datetime.now().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [user_id]
    db.execute(f"UPDATE user_profiles SET {set_clause} WHERE user_id = ?", values)
    db.commit()

    # sync مع JSON القديم
    try:
        all_users = _load_all_users()
        uid = str(user_id)
        if uid not in all_users:
            all_users[uid] = {}
        for k, v in updates.items():
            if k == 'subscribed':
                all_users[uid][k] = bool(v)
            elif k in ('sources', 'interests', 'favorite_companies') and isinstance(v, str):
                try:
                    all_users[uid][k] = json.loads(v)
                except:
                    all_users[uid][k] = v
            else:
                all_users[uid][k] = v
        _save_all_users(all_users)
    except Exception as e:
        logger.debug(f"JSON sync error (non-critical): {e}")


# ═══════════════════════════════════════
# إعدادات المستخدم - User Preferences
# ═══════════════════════════════════════

def get_language(user_id: int) -> str:
    user = get_user(user_id)
    return user.get("language", "ar")

def set_language(user_id: int, language: str):
    update_user(user_id, {"language": language})

def get_news_time(user_id: int) -> str:
    user = get_user(user_id)
    return user.get("news_time", "09:00")

def set_news_time(user_id: int, time_str: str):
    update_user(user_id, {"news_time": time_str})

def get_sources(user_id: int) -> list:
    user = get_user(user_id)
    return user.get("sources", [])

def set_sources(user_id: int, sources: list):
    update_user(user_id, {"sources": sources})


# ═══════════════════════════════════════
# الاشتراك - Subscription
# ═══════════════════════════════════════

def subscribe_user(user_id: int):
    update_user(user_id, {"subscribed": True})

def unsubscribe_user(user_id: int):
    update_user(user_id, {"subscribed": False})

def is_subscribed(user_id: int) -> bool:
    user = get_user(user_id)
    return user.get("subscribed", False)

def get_all_subscribers() -> List[Dict]:
    db = _get_db()
    rows = db.execute(
        "SELECT user_id, language, news_time, name FROM user_profiles WHERE subscribed = 1"
    ).fetchall()
    if rows:
        return [dict(r) for r in rows]
    # fallback
    all_users = _load_all_users()
    subscribers = []
    for uid, data in all_users.items():
        if data.get("subscribed", False):
            subscribers.append({
                "user_id": int(uid), "language": data.get("language", "ar"),
                "news_time": data.get("news_time", "09:00"), "name": data.get("name", ""),
            })
    return subscribers

def get_subscriber_count() -> int:
    return len(get_all_subscribers())

def increment_command_count(user_id: int):
    db = _get_db()
    _ensure_user_in_db(user_id)
    db.execute(
        "UPDATE user_profiles SET commands_used = commands_used + 1, last_interaction = ? WHERE user_id = ?",
        (datetime.now().isoformat(), user_id)
    )
    db.commit()

def increment_chat_count(user_id: int):
    db = _get_db()
    _ensure_user_in_db(user_id)
    db.execute(
        "UPDATE user_profiles SET chat_count = chat_count + 1, last_interaction = ? WHERE user_id = ?",
        (datetime.now().isoformat(), user_id)
    )
    db.commit()


# ═══════════════════════════════════════
# ذاكرة المحادثات - Conversation Memory
# ═══════════════════════════════════════

MAX_CONVERSATIONS = 50

def save_conversation(user_id: int, role: str, content: str):
    """حفظ رسالة في ذاكرة المحادثات"""
    _ensure_user_in_db(user_id)
    db = _get_db()
    # حفظ الرسالة
    db.execute(
        "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, role, content[:1000], datetime.now().isoformat())
    )
    # حذف القديم لو عدى الحد
    db.execute(
        """DELETE FROM conversations WHERE id IN (
            SELECT id FROM conversations WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT -1 OFFSET ?
        )""",
        (user_id, MAX_CONVERSATIONS)
    )
    db.commit()


def get_recent_conversations(user_id: int, limit: int = 10) -> List[Dict]:
    """الحصول على آخر محادثات المستخدم"""
    db = _get_db()
    rows = db.execute(
        "SELECT role, content, timestamp FROM conversations WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


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
    db = _get_db()
    db.execute(
        """INSERT INTO learning_progress (user_id, topic, level, learned_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, topic) DO UPDATE SET level = ?, learned_at = ?""",
        (user_id, topic, level, datetime.now().isoformat(), level, datetime.now().isoformat())
    )
    db.commit()


def get_learning_progress(user_id: int) -> List[Dict]:
    """الحصول على كل تقدم التعلم"""
    db = _get_db()
    rows = db.execute(
        "SELECT topic, level, learned_at FROM learning_progress WHERE user_id = ? ORDER BY learned_at DESC",
        (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


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
    db = _get_db()
    db.execute(
        "INSERT INTO favorites (user_id, category, title, content, url, saved_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, category, title, content[:500], url, datetime.now().isoformat())
    )
    db.commit()


def get_favorites(user_id: int, category: str = None) -> List[Dict]:
    """الحصول على المفضلات"""
    db = _get_db()
    if category:
        rows = db.execute(
            "SELECT id, category, title, content, url, saved_at FROM favorites WHERE user_id = ? AND category = ? ORDER BY saved_at DESC",
            (user_id, category)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, category, title, content, url, saved_at FROM favorites WHERE user_id = ? ORDER BY saved_at DESC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def remove_favorite(user_id: int, favorite_id: int):
    """حذف عنصر من المفضلات"""
    db = _get_db()
    db.execute("DELETE FROM favorites WHERE id = ? AND user_id = ?", (favorite_id, user_id))
    db.commit()


# ═══════════════════════════════════════
# الذاكرة الذكية - Smart Memory
# ═══════════════════════════════════════

def save_memory(user_id: int, key: str, value: str, category: str = "general"):
    """حفظ ذكرى في الذاكرة الذكية"""
    _ensure_user_in_db(user_id)
    db = _get_db()
    db.execute(
        """INSERT INTO user_memories (user_id, key, value, category, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET value = ?, category = ?""",
        (user_id, key, value, category, datetime.now().isoformat(), value, category)
    )
    db.commit()


def get_memories(user_id: int, category: str = None) -> List[Dict]:
    """الحصول على الذكريات"""
    db = _get_db()
    if category:
        rows = db.execute(
            "SELECT id, key, value, category, created_at FROM user_memories WHERE user_id = ? AND category = ? ORDER BY created_at DESC",
            (user_id, category)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, key, value, category, created_at FROM user_memories WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_memory(user_id: int, key: str = None, memory_id: int = None):
    """حذف ذكرى محددة"""
    db = _get_db()
    if memory_id:
        db.execute("DELETE FROM user_memories WHERE id = ? AND user_id = ?", (memory_id, user_id))
    elif key:
        db.execute("DELETE FROM user_memories WHERE key LIKE ? AND user_id = ?", (f"%{key}%", user_id))
    db.commit()


def reset_all_memories(user_id: int):
    """حذف كل الذكريات"""
    db = _get_db()
    db.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM learning_progress WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM favorites WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM user_memories WHERE user_id = ?", (user_id,))
    db.commit()


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

    if lang == "ar":
        text = "🧠 <b>ذاكرتي عنك</b>\n━━━━━━━━━━━━━━━━━\n\n"

        text += f"👤 <b>الاسم:</b> {user.get('name', 'مش محدد')}\n"
        text += f"🌐 <b>اللغة:</b> {'العربية' if user.get('language') == 'ar' else 'English'}\n"
        text += f"📬 <b>مشترك:</b> {'نعم' if user.get('subscribed') else 'لا'}\n"
        text += f"💬 <b>محادثات:</b> {user.get('chat_count', 0)}\n"
        text += f"⚡ <b>أوامر:</b> {user.get('commands_used', 0)}\n\n"

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

        text += f"👤 <b>Name:</b> {user.get('name', 'Not set')}\n"
        text += f"🌐 <b>Language:</b> {'Arabic' if user.get('language') == 'ar' else 'English'}\n"
        text += f"📬 <b>Subscribed:</b> {'Yes' if user.get('subscribed') else 'No'}\n"
        text += f"💬 <b>Chats:</b> {user.get('chat_count', 0)}\n"
        text += f"⚡ <b>Commands:</b> {user.get('commands_used', 0)}\n\n"

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


# ═══════════════════════════════════════
# تهيئة عند الاستيراد - Init on Import
# ═══════════════════════════════════════

try:
    init_database()
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
