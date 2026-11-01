"""
نظام سياق المحادثة - Conversational Context Window System
يتم تحميله قبل كل رد AI لضمان استمرارية المحادثة

يشمل:
- تحميل ملف المستخدم الكامل (اسم، لغة، اهتمامات، شركات مفضلة)
- ذاكرة قصيرة المدى (آخر 50 رسالة)
- ذاكرة طويلة المدى (اهتمامات، مواضيع متكررة، تفضيلات)
- استرجاع دلالي للذكريات المتعلقة بالرسالة الحالية
- حقن السياق كامل في الـ prompt
- تسجيل تصحيحي لحجم السياق والبيانات المحملة

⚡ v2: Parallel DB queries + caching for speed optimization
"""

import logging
import time
import re
import threading
from typing import Dict, List, Optional, Any
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

from memory import (
    get_user, get_interests, get_favorite_companies,
    get_recent_conversations, get_learned_topics,
    get_memories, get_learning_progress,
    detect_interests, save_memory,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# إعدادات السياق - Context Settings
# ═══════════════════════════════════════

MAX_SHORT_TERM_MESSAGES = 100  # أقصى عدد رسائل قصيرة المدى (كان 50)
CONTEXT_MESSAGES_FOR_AI = 50   # عدد الرسائل المرسلة فعليًا للـ AI (default)
CONTEXT_CHAR_LIMIT = 1500     # أقصى عدد حروف لكل رسالة في السياق (كان 1000، اتزود عشان السياق أطول)
CONTEXT_MESSAGES_PREMIUM = 80  # ⭐ Premium: 80 رسالة سياق (كان 50)
CONTEXT_CHAR_LIMIT_PREMIUM = 2000  # ⭐ Premium: حروف أكتر لكل رسالة (كان 1000)
MAX_MEMORY_ENTRIES = 10        # أقصى عدد ذكريات طويلة المدى مسترجعة
MAX_INTERESTS_DISPLAY = 15     # أقصى عدد اهتمامات في السياق
MIN_KEYWORD_LENGTH = 3         # أقل طول كلمة للبحث الدلالي


# ═══════════════════════════════════════
# ⚡ كاش السياق - Context Caches
# ═══════════════════════════════════════

# كاش المواضيع المتكررة — بيتم حسابه من 50+ محادثة بالـ regex كل مرة
# نخزنه لمدة 5 دقايق عشان نوفر المعالجة
_frequent_topics_cache: OrderedDict = OrderedDict()
_FREQUENT_TOPICS_TTL = 300  # 5 دقائق
_MAX_FREQ_TOPICS_CACHE = 200

# كاش بيانات المستخدم الأساسية — بيانات بتيجي من DB كل رسالة
_user_data_cache: OrderedDict = OrderedDict()
_USER_DATA_TTL = 300  # 5 دقائق
_MAX_USER_DATA_CACHE = 200

# Thread pool للـ parallel DB queries
_db_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ctx_db_")


def _get_cached_freq_topics(user_id: int) -> Optional[List[str]]:
    """البحث عن المواضيع المتكررة في الكاش"""
    if user_id in _frequent_topics_cache:
        topics, ts = _frequent_topics_cache[user_id]
        if time.time() - ts < _FREQUENT_TOPICS_TTL:
            return topics
        else:
            del _frequent_topics_cache[user_id]
    return None


def _set_cached_freq_topics(user_id: int, topics: List[str]):
    """تخزين المواضيع المتكررة في الكاش"""
    _frequent_topics_cache[user_id] = (topics, time.time())
    # تنظيف الكاش لو حجمه أكبر من الحد
    while len(_frequent_topics_cache) > _MAX_FREQ_TOPICS_CACHE:
        _frequent_topics_cache.popitem(last=False)


def _get_cached_user_data(user_id: int) -> Optional[Dict]:
    """البحث عن بيانات المستخدم في الكاش"""
    if user_id in _user_data_cache:
        data, ts = _user_data_cache[user_id]
        if time.time() - ts < _USER_DATA_TTL:
            return data
        else:
            del _user_data_cache[user_id]
    return None


def _set_cached_user_data(user_id: int, data: Dict):
    """تخزين بيانات المستخدم في الكاش"""
    _user_data_cache[user_id] = (data, time.time())
    # تنظيف الكاش لو حجمه أكبر من الحد
    while len(_user_data_cache) > _MAX_USER_DATA_CACHE:
        _user_data_cache.popitem(last=False)


def invalidate_user_cache(user_id: int):
    """إلغاء كاش المستخدم — يتندف لما المستخدم يحدث بياناته"""
    _frequent_topics_cache.pop(user_id, None)
    _user_data_cache.pop(user_id, None)


# ═══════════════════════════════════════
# ملف المستخدم - User Profile Loader
# ═══════════════════════════════════════

def load_user_profile(user_id: int) -> Dict[str, Any]:
    """تحميل ملف المستخدم الكامل قبل كل رد
    
    Returns:
        Dict with: name, language, interests, favorite_companies,
        subscribed, plan, chat_count, commands_used
    """
    try:
        user = get_user(user_id)
        profile = {
            "name": user.get("name", ""),
            "language": user.get("language", "ar"),
            "interests": user.get("interests", []),
            "favorite_companies": user.get("favorite_companies", []),
            "subscribed": user.get("subscribed", False),
            "chat_count": user.get("chat_count", 0),
            "commands_used": user.get("commands_used", 0),
            "response_length": user.get("response_length", "medium"),
        }
        
        # إضافة حالة Premium
        try:
            from premium import get_user_plan
            profile["plan"] = get_user_plan(user_id)
        except Exception:
            profile["plan"] = "free"
        
        return profile
    except Exception as e:
        logger.warning(f"Error loading user profile for {user_id}: {e}")
        return {
            "name": "", "language": "ar", "interests": [],
            "favorite_companies": [], "subscribed": False,
            "plan": "free", "chat_count": 0, "commands_used": 0,
            "response_length": "medium",
        }


# ═══════════════════════════════════════
# ذاكرة قصيرة المدى - Short Term Memory
# ═══════════════════════════════════════

def load_short_term_memory(user_id: int, limit: int = CONTEXT_MESSAGES_FOR_AI, is_premium_user: bool = False) -> List[Dict]:
    """تحميل آخر رسائل المحادثة كسياق قصير المدى
    
    Returns:
        List of {"role": "user"|"assistant", "content": str}
        مرتبة زمنيًا (الأقدم أولًا)
    """
    try:
        conversations = get_recent_conversations(user_id, limit)
        # تحويل role من "user"/"bot" إلى "user"/"assistant"
        # 🔴 Premium بيحصل على حروف أكتر لكل رسالة في السياق
        char_limit = CONTEXT_CHAR_LIMIT_PREMIUM if is_premium_user else CONTEXT_CHAR_LIMIT
        messages = []
        for c in reversed(conversations):  # reversed لأنها مرتبة DESC
            role = "user" if c['role'] == 'user' else "assistant"
            messages.append({
                "role": role,
                "content": c['content'][:char_limit]  # truncate لكل رسالة
            })
        return messages
    except Exception as e:
        logger.warning(f"Error loading short-term memory for {user_id}: {e}")
        return []


# ═══════════════════════════════════════
# ذاكرة طويلة المدى - Long Term Memory
# ═══════════════════════════════════════

def load_long_term_memory(user_id: int, current_message: str = "", conversations: List[Dict] = None) -> Dict[str, Any]:
    """تحميل الذاكرة طويلة المدى - اهتمامات، مواضيع متكررة، تفضيلات
    
    يشمل:
    - الاهتمامات المحفوظة
    - المواضيع المتعلمة ومستوياتها
    - الشركات المفضلة
    - الذكريات المحفوظة يدويًا
    - استرجاع دلالي: ذكريات متعلقة بالرسالة الحالية
    ⚡ لو conversations متpassed، بيوفر DB query
    """
    long_term = {
        "interests": [],
        "learned_topics": [],
        "favorite_companies": [],
        "saved_memories": [],
        "relevant_memories": [],  # ذكريات متعلقة بالرسالة الحالية
        "frequent_topics": [],    # مواضيع متكررة في المحادثات
    }
    
    try:
        # 1. الاهتمامات
        interests = get_interests(user_id)
        long_term["interests"] = interests[:MAX_INTERESTS_DISPLAY]
        
        # 2. المواضيع المتعلمة
        learning = get_learning_progress(user_id)
        long_term["learned_topics"] = [
            {"topic": l["topic"], "level": l["level"]} 
            for l in learning[:10]
        ]
        
        # 3. الشركات المفضلة
        long_term["favorite_companies"] = get_favorite_companies(user_id)[:10]
        
        # 4. الذكريات المحفوظة
        memories = get_memories(user_id)
        if memories:
            long_term["saved_memories"] = [
                {"key": m["key"], "value": m["value"][:200], "category": m.get("category", "general")}
                for m in memories[:MAX_MEMORY_ENTRIES]
                if m.get("category") != "system"  # استبعاد ذكريات النظام
            ]
        
        # 5. استرجاع دلالي: ذكريات متعلقة بالرسالة الحالية
        if current_message:
            long_term["relevant_memories"] = _retrieve_relevant_memories(
                user_id, current_message, memories
            )
        
        # 6. المواضيع المتكررة (من آخر 50 محادثة)
        # ⚡ بنمرر conversations عشان نعمل DB query واحد بس
        # ⚡ بنستخدم كاش عشان نوفر المعالجة
        long_term["frequent_topics"] = _extract_frequent_topics(user_id, conversations=conversations)
        
    except Exception as e:
        logger.warning(f"Error loading long-term memory for {user_id}: {e}")
    
    return long_term


def _retrieve_relevant_memories(user_id: int, current_message: str, 
                                 all_memories: List = None) -> List[Dict]:
    """استرجاع دلالي للذكريات المتعلقة بالرسالة الحالية
    
    يبحث عن تطابق كلمات مفتاحية بين الرسالة والذكريات المحفوظة
    وليس مجرد تحميل كل شيء — فقط المتعلق فعليًا
    """
    relevant = []
    current_lower = current_message.lower()
    
    # استخراج كلمات مفتاحية من الرسالة الحالية
    current_keywords = set(re.findall(r'\w+', current_lower))
    current_keywords = {kw for kw in current_keywords if len(kw) >= MIN_KEYWORD_LENGTH}
    
    if not current_keywords:
        return relevant
    
    # البحث في الذكريات
    if all_memories is None:
        try:
            all_memories = get_memories(user_id)
        except Exception:
            return relevant
    
    for memory in all_memories:
        if memory.get("category") == "system":
            continue  # استبعاد ذكريات النظام
        
        key_lower = memory.get("key", "").lower()
        value_lower = memory.get("value", "").lower()
        
        # حساب درجة التطابق
        memory_text = f"{key_lower} {value_lower}"
        memory_keywords = set(re.findall(r'\w+', memory_text))
        memory_keywords = {kw for kw in memory_keywords if len(kw) >= MIN_KEYWORD_LENGTH}
        
        # عدد الكلمات المشتركة
        overlap = current_keywords & memory_keywords
        
        if overlap:
            relevant.append({
                "key": memory["key"],
                "value": memory["value"][:200],
                "category": memory.get("category", "general"),
                "relevance_score": len(overlap),
            })
    
    # ترتيب حسب درجة التطابق
    relevant.sort(key=lambda x: x["relevance_score"], reverse=True)
    
    return relevant[:5]  # أعلى 5 ذكريات متعلقة


def _extract_frequent_topics(user_id: int, conversations: List[Dict] = None) -> List[str]:
    """استخراج المواضيع المتكررة من آخر 50 محادثة
    
    يحلل كلمات المستخدم المتكررة لتحديد المواضيع اللي بيتكلم عنها كتير
    ⚡ لو conversations متpassed، مش هنعمل DB query تاني
    ⚡ بنستخدم كاش لمدة 5 دقايق عشان نوفر المعالجة
    """
    # ⚡ كاش — لو المواضيع متخزنة ومش انتهت صلاحيتها
    cached = _get_cached_freq_topics(user_id)
    if cached is not None:
        return cached
    
    try:
        if conversations is None:
            conversations = get_recent_conversations(user_id, MAX_SHORT_TERM_MESSAGES)
        if not conversations:
            _set_cached_freq_topics(user_id, [])
            return []
        
        # كلمات المستخدم فقط
        user_words = []
        stop_words = {
            # العربية
            "انا", "انت", "هو", "هي", "احنا", "هم", "ده", "دي", "دول",
            "في", "علي", "من", "عن", "مع", "الي", "اللي", "لا", "نعم",
            "ايه", "ليه", "ازاي", "امتى", "فين", "هل", "لو", "بس",
            "دا", "دي", "ده", "ال", "عامل", "عايز", "عايزة", "عندي",
            # الإنجليزية
            "the", "and", "for", "are", "but", "not", "you", "all",
            "can", "had", "her", "was", "one", "our", "out", "day",
            "get", "has", "him", "his", "how", "its", "may", "new",
            "now", "old", "see", "way", "who", "did", "let", "say",
            "she", "too", "use", "what", "when", "will", "with", "this",
            "that", "have", "from", "they", "been", "said", "each",
            "which", "their", "there", "would", "about", "could",
            "other", "into", "more", "very", "just", "know", "want",
        }
        
        for c in conversations:
            if c['role'] == 'user':
                words = re.findall(r'\w+', c['content'].lower())
                for w in words:
                    if len(w) >= MIN_KEYWORD_LENGTH and w not in stop_words:
                        user_words.append(w)
        
        if not user_words:
            _set_cached_freq_topics(user_id, [])
            return []
        
        # أعلى 10 كلمات متكررة
        counter = Counter(user_words)
        result = [word for word, count in counter.most_common(10) if count >= 2]
        _set_cached_freq_topics(user_id, result)
        return result
        
    except Exception as e:
        logger.debug(f"Error extracting frequent topics: {e}")
        return []


# ═══════════════════════════════════════
# ⚡ تحميل بيانات المستخدم بالتوازي - Parallel User Data Loading
# ═══════════════════════════════════════

def _load_parallel_user_data(user_id: int) -> Dict[str, Any]:
    """تحميل بيانات المستخدم الأساسية بالتوازي من DB
    
    ⚡ بدل ما نعمل 6-7 استعلامات ورا بعض، بنعملهم بالتوازي
    ده بيقلل الوقت من ~500ms لـ ~100ms
    
    Returns:
        Dict with: interests, learning_progress, favorite_companies, memories, user_data
    """
    results = {
        "interests": [],
        "learning_progress": [],
        "favorite_companies": [],
        "memories": [],
        "user_data": {},
    }
    
    try:
        futures = {}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="par_db_") as executor:
            # ⚡ تشغيل كل استعلام في thread منفصل
            futures[executor.submit(get_interests, user_id)] = "interests"
            futures[executor.submit(get_learning_progress, user_id)] = "learning_progress"
            futures[executor.submit(get_favorite_companies, user_id)] = "favorite_companies"
            futures[executor.submit(get_memories, user_id)] = "memories"
            futures[executor.submit(get_user, user_id)] = "user_data"
            
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    logger.debug(f"Parallel load error for {key}: {e}")
    except Exception as e:
        logger.warning(f"Parallel user data loading failed for {user_id}: {e}")
        # Fallback: نحمل البيانات بالطريقة العادية
        try:
            results["interests"] = get_interests(user_id)
        except Exception:
            pass
        try:
            results["learning_progress"] = get_learning_progress(user_id)
        except Exception:
            pass
        try:
            results["favorite_companies"] = get_favorite_companies(user_id)
        except Exception:
            pass
        try:
            results["memories"] = get_memories(user_id)
        except Exception:
            pass
        try:
            results["user_data"] = get_user(user_id)
        except Exception:
            pass
    
    return results


# ═══════════════════════════════════════
# بناء السياق الكامل - Build Full Context
# ═══════════════════════════════════════

def build_context_for_ai(user_id: int, current_message: str, 
                          language: str = "ar", username: str = None) -> Dict[str, Any]:
    """بناء السياق الكامل قبل كل رد AI
    
    هذه الدالة الرئيسية التي يتم استدعاؤها قبل كل رد:
    1. تحميل ملف المستخدم
    2. تحميل ذاكرة قصيرة المدى (آخر رسائل)
    3. تحميل ذاكرة طويلة المدى (اهتمامات + تفضيلات)
    4. استرجاع ذكريات متعلقة بالرسالة الحالية
    5. كشف اهتمامات جديدة
    6. تسجيل تصحيحي
    
    ⚡ v2: DB queries بالتوازي + كاش عشان أسرع
    
    Returns:
        Dict with:
        - profile: User profile data
        - short_term: List of recent conversation messages for AI
        - long_term: Long-term memory data
        - context_text: Formatted context string for system prompt
        - debug: Debug info (sizes, counts)
    """
    start_time = time.time()
    
    # ⚡ Step 1: تحديد خطة المستخدم (مرة واحدة بس!)
    # premium.py عنده كاش 60 ثانية، فده سريع
    is_premium_user = False
    user_plan = "free"
    try:
        from premium import get_user_plan
        from admin import is_admin
        is_admin_user = is_admin(user_id)
        user_plan = get_user_plan(user_id)
        if is_admin_user or user_plan in ("premium", "premium_plus"):
            context_limit = CONTEXT_MESSAGES_PREMIUM  # ⭐ Premium: 80 رسالة سياق
            is_premium_user = True
        else:
            context_limit = 10  # 🆓 Free: 10 رسائل سياق (⚡提速: 20→10 — input tokens أقل)
    except Exception:
        context_limit = CONTEXT_MESSAGES_FOR_AI
    
    # ⚡ Step 2: تحميل بيانات المستخدم بالتوازي (6-7 استعلامات بدل ورا بعض)
    par_data = _load_parallel_user_data(user_id)
    
    # بناء الـ profile من البيانات المحملة بالتوازي
    user_data = par_data.get("user_data", {})
    profile = {
        "name": user_data.get("name", ""),
        "language": user_data.get("language", "ar"),
        "interests": user_data.get("interests", []),
        "favorite_companies": user_data.get("favorite_companies", []),
        "subscribed": user_data.get("subscribed", False),
        "chat_count": user_data.get("chat_count", 0),
        "commands_used": user_data.get("commands_used", 0),
        "response_length": user_data.get("response_length", "medium"),
        "plan": user_plan,
    }
    
    # ⚡ Step 3: تحميل ذاكرة قصيرة المدى
    short_term = load_short_term_memory(user_id, context_limit, is_premium_user=is_premium_user)
    
    # ⚡ Step 4: بناء الذاكرة طويلة المدى من البيانات المحملة بالتوازي
    # (مش محتاجين نعمل DB queries تاني — البيانات عندنا بالفعل!)
    interests = par_data.get("interests", [])
    learning_progress = par_data.get("learning_progress", [])
    favorite_companies = par_data.get("favorite_companies", [])
    memories = par_data.get("memories", [])
    
    long_term = {
        "interests": interests[:MAX_INTERESTS_DISPLAY],
        "learned_topics": [
            {"topic": l["topic"], "level": l["level"]} 
            for l in learning_progress[:10]
        ],
        "favorite_companies": favorite_companies[:10],
        "saved_memories": [],
        "relevant_memories": [],
        "frequent_topics": [],
    }
    
    # معالجة الذكريات
    if memories:
        long_term["saved_memories"] = [
            {"key": m["key"], "value": m["value"][:200], "category": m.get("category", "general")}
            for m in memories[:MAX_MEMORY_ENTRIES]
            if m.get("category") != "system"
        ]
        
        # استرجاع دلالي
        if current_message:
            long_term["relevant_memories"] = _retrieve_relevant_memories(
                user_id, current_message, memories
            )
    
    # المواضيع المتكررة (بنستخدم كاش)
    long_term["frequent_topics"] = _extract_frequent_topics(user_id, conversations=short_term)
    
    # Step 5: كشف اهتمامات جديدة من الرسالة الحالية (fire-and-forget)
    try:
        detect_interests(user_id, current_message)
    except Exception:
        pass
    
    # Step 6: بناء نص السياق للـ system prompt
    context_text = _format_context_for_prompt(profile, long_term, language)
    
    # Step 7: معلومات تصحيحية
    elapsed = time.time() - start_time
    
    debug_info = {
        "context_build_time_ms": round(elapsed * 1000, 1),
        "profile_loaded": bool(profile.get("name")),
        "short_term_messages": len(short_term),
        "long_term_interests": len(long_term.get("interests", [])),
        "long_term_learned": len(long_term.get("learned_topics", [])),
        "long_term_memories": len(long_term.get("saved_memories", [])),
        "relevant_memories": len(long_term.get("relevant_memories", [])),
        "frequent_topics": len(long_term.get("frequent_topics", [])),
        "context_text_length": len(context_text),
    }
    
    logger.info(
        f"🧠 Context built for user {user_id}: "
        f"short_term={len(short_term)} msgs, "
        f"interests={len(long_term.get('interests', []))}, "
        f"relevant={len(long_term.get('relevant_memories', []))}, "
        f"context_size={len(context_text)} chars, "
        f"time={elapsed*1000:.0f}ms"
    )
    
    return {
        "profile": profile,
        "short_term": short_term,
        "long_term": long_term,
        "context_text": context_text,
        "debug": debug_info,
        "is_premium_user": is_premium_user,  # ⚡ بنرجعها عشان م حد يفحص تاني
    }


def _format_context_for_prompt(profile: Dict, long_term: Dict, language: str = "ar") -> str:
    """تنسيق السياق كنص يُحقن في system prompt
    
    البنية:
    ═══ معلومات المستخدم ═══
    - الاسم: ...
    - اللغة: ...
    - الخطة: ...
    
    ═══ اهتمامات المستخدم ═══
    - OpenAI, ChatGPT, ...
    
    ═══ مواضيع يتابعها ═══
    - ...
    
    ═══ شركات يتابعها ═══
    - OpenAI, Google, ...
    
    ═══ مواضيع متكررة ═══
    - ...
    
    ═══ ذكريات متعلقة ═══
    - ...
    """
    parts = []
    
    if language == "ar":
        # معلومات المستخدم الأساسية
        if profile.get("name"):
            parts.append(f"اسم المستخدم: {profile['name']}")
        parts.append(f"اللغة المفضلة: {'العربية' if profile.get('language') == 'ar' else 'English'}")
        if profile.get("plan") and profile["plan"] != "free":
            parts.append(f"الخطة: Premium")
        
        # الاهتمامات
        interests = long_term.get("interests", [])
        if interests:
            parts.append(f"اهتمامات المستخدم: {', '.join(interests)}")
        
        # المواضيع المتعلمة
        learned = long_term.get("learned_topics", [])
        if learned:
            learned_str = ", ".join(
                f"{l['topic']} ({l['level']})" for l in learned
            )
            parts.append(f"مواضيع تعلمها: {learned_str}")
        
        # الشركات المفضلة
        companies = long_term.get("favorite_companies", [])
        if companies:
            parts.append(f"شركات يتابعها: {', '.join(companies)}")
        
        # المواضيع المتكررة
        frequent = long_term.get("frequent_topics", [])
        if frequent:
            parts.append(f"مواضيع بيتكلم عنها كتير: {', '.join(frequent)}")
        
        # الذكريات المتعلقة بالرسالة الحالية
        relevant = long_term.get("relevant_memories", [])
        if relevant:
            parts.append("═══ ذكريات متعلقة بالرسالة الحالية ═══")
            for r in relevant[:3]:
                parts.append(f"- {r['key']}: {r['value']}")
        
        # الذكريات المحفوظة
        saved = long_term.get("saved_memories", [])
        if saved:
            parts.append("ذكريات محفوظة:")
            for m in saved[:5]:
                parts.append(f"- {m['key']}: {m['value']}")
        
        # تعليمات للـ AI
        if parts:
            header = "═══ معلومات عن المستخدم (استخدمها عشان تخصّص ردك وتفتكره) ═══"
            instruction = (
                "\n═══ تعليمات مهمة ═══\n"
                "- لو المستخدم بيتكلم عن موضوع اهتم بيه قبل كده، اذكر إنك فاكر اهتمامه ده\n"
                "- لو بيسأل عن أخبار، ركز على شركات واهتماماته المفضلة\n"
                "- لو المستخدم premium، عامله كعميل مهم وقدم خدمة متميزة\n"
                "- استخدم اسم المستخدم لو معروف عشان التحسس شخصي\n"
                "- ماتكررش نفس المعلومات اللي قلتها في رسائل سابقة"
            )
            return header + "\n" + "\n".join(parts) + instruction
    
    else:  # English
        if profile.get("name"):
            parts.append(f"User's name: {profile['name']}")
        parts.append(f"Preferred language: {'Arabic' if profile.get('language') == 'ar' else 'English'}")
        if profile.get("plan") and profile["plan"] != "free":
            parts.append(f"Plan: Premium")
        
        interests = long_term.get("interests", [])
        if interests:
            parts.append(f"User interests: {', '.join(interests)}")
        
        learned = long_term.get("learned_topics", [])
        if learned:
            learned_str = ", ".join(
                f"{l['topic']} ({l['level']})" for l in learned
            )
            parts.append(f"Learned topics: {learned_str}")
        
        companies = long_term.get("favorite_companies", [])
        if companies:
            parts.append(f"Followed companies: {', '.join(companies)}")
        
        frequent = long_term.get("frequent_topics", [])
        if frequent:
            parts.append(f"Frequently discussed topics: {', '.join(frequent)}")
        
        relevant = long_term.get("relevant_memories", [])
        if relevant:
            parts.append("═══ Memories relevant to current message ═══")
            for r in relevant[:3]:
                parts.append(f"- {r['key']}: {r['value']}")
        
        saved = long_term.get("saved_memories", [])
        if saved:
            parts.append("Saved memories:")
            for m in saved[:5]:
                parts.append(f"- {m['key']}: {m['value']}")
        
        if parts:
            header = "═══ User information (use this to personalize your response and remember them) ═══"
            instruction = (
                "\n═══ Important instructions ═══\n"
                "- If the user is talking about a topic they're interested in, acknowledge their interest\n"
                "- If asking about news, focus on their followed companies and interests\n"
                "- If the user is premium, treat them as a valued customer\n"
                "- Use the user's name if known for personalization\n"
                "- Don't repeat information you already shared in previous messages"
            )
            return header + "\n" + "\n".join(parts) + instruction
    
    return ""


# ═══════════════════════════════════════
# حفظ تلقائي للذكريات - Auto-Save Memories
# ═══════════════════════════════════════

def auto_save_conversation_memory(user_id: int, user_message: str, bot_response: str):
    """حفظ ذكريات تلقائيًا من المحادثة
    
    يستخرج معلومات مهمة من المحادثة ويحفظها كذكريات طويلة المدى:
    - تفضيلات صريحة (أنا بحب، أنا بكره، أنا مش عايز)
    - معلومات شخصية (اسمي، شغلي، بلدي)
    - مواضيع اهتمام جديدة
    """
    try:
        user_lower = user_message.lower()
        
        # 1. كشف التفضيلات الصريحة
        _detect_and_save_preferences(user_id, user_message, user_lower)
        
        # 2. كشف المعلومات الشخصية
        _detect_and_save_personal_info(user_id, user_message, user_lower)
        
        # 3. كشف اهتمامات جديدة (already done by detect_interests, but ensure)
        try:
            detect_interests(user_id, user_message)
        except Exception:
            pass
        
        # ⚡ إلغاء كاش المواضيع المتكررة عشان يتحسب من تاني مع الرسالة الجديدة
        _frequent_topics_cache.pop(user_id, None)
        
    except Exception as e:
        logger.debug(f"Auto-save memory error (non-critical): {e}")


def _detect_and_save_preferences(user_id: int, message: str, message_lower: str):
    """كشف وحفظ التفضيلات الصريحة للمستخدم"""
    # أنماط التفضيلات
    preference_patterns = [
        # العربية - بحب / بكره / بفضل / مش عايز
        (r'(?:أنا|انا)\s*(?:بحب|بحبها|بحبه|عاجبني|بحبها)\s+(.+?)(?:\.|،|$)', "preference_like"),
        (r'(?:أنا|انا)\s*(?:بكره|مش بحب|مش عاجبني|مش بحبه)\s+(.+?)(?:\.|،|$)', "preference_dislike"),
        (r'(?:أنا|انا)\s*(?:بفضل|بختار|عايز|عايزة)\s+(.+?)(?:\.|،|على|$)', "preference_choice"),
        # الإنجليزية
        (r'i\s+(?:love|like|enjoy|prefer)\s+(.+?)(?:\.|,|$)', "preference_like"),
        (r'i\s+(?:hate|dislike|don\'t like)\s+(.+?)(?:\.|,|$)', "preference_dislike"),
        (r'i\s+(?:prefer|would rather|want)\s+(.+?)(?:\.|,|over|$)', "preference_choice"),
    ]
    
    for pattern, category in preference_patterns:
        matches = re.findall(pattern, message_lower)
        for match in matches:
            preference = match.strip()[:200]
            if len(preference) >= 3:
                try:
                    save_memory(user_id, f"{category}_{preference[:50]}", preference, category)
                    logger.info(f"💾 Auto-saved preference for user {user_id}: {category} = {preference[:50]}")
                except Exception:
                    pass


def _detect_and_save_personal_info(user_id: int, message: str, message_lower: str):
    """كشف وحفظ معلومات شخصية يذكرها المستخدم
    
    ⭐ لما المستخدم يقول اسمه، بنحفظه في الذاكرة وبنحدث اسمه في الملف الشخصي كمان
    عشان البوت يستخدم الاسم اللي المستخدم بيحبه — مش بس الاسم من الحساب
    """
    info_patterns = [
        # الاسم — مع أنماط أكتر للعامية المصرية
        (r'(?:اسمي|أسمي|اسمى|أسمى|اسمي هو|ناديني ب|عايزك تناديني|كنّي ب|call me|my name is|i\'m called|you can call me)\s+(.+?)(?:\.|،|and|و|$)', "personal_name"),
        # المهنة
        (r'(?:شغلي|عملي|مجالي|أنا\s*(?:مطور|مهندس|طبيب|محامي|طالب|مصمم|مبرمج)|i\s*(?:am|work as)\s*(?:a|an)?\s*(?:developer|engineer|doctor|lawyer|student|designer|programmer))\s*(.+?)(?:\.|،|$)', "personal_job"),
        # البلد
        (r'(?:أنا من|انا من|بلدي|من بلد|i am from|i\'m from|my country)\s+(.+?)(?:\.|،|$)', "personal_location"),
    ]
    
    for pattern, category in info_patterns:
        matches = re.findall(pattern, message_lower)
        for match in matches:
            info = match.strip()[:200]
            if len(info) >= 2:
                try:
                    save_memory(user_id, category, info, "personal_info")
                    logger.info(f"💾 Auto-saved personal info for user {user_id}: {category} = {info[:50]}")
                    
                    # ⭐ Update the user's name in their profile too!
                    # When the user says "اسمي أحمد", we update the `name` field in user_profiles
                    # so the bot always uses their preferred name instead of just the profile name
                    if category == "personal_name":
                        preferred_name = info.strip()
                        # Capitalize first letter
                        if preferred_name:
                            preferred_name = preferred_name[0].upper() + preferred_name[1:]
                        try:
                            from memory import update_user
                            update_user(user_id, {"name": preferred_name})
                            logger.info(f"✏️ Updated user {user_id} preferred name to: {preferred_name}")
                            # ⚡ إلغاء كاش المستخدم
                            invalidate_user_cache(user_id)
                        except Exception as e:
                            logger.warning(f"Could not update user name in profile: {e}")
                except Exception:
                    pass
