"""
محرك الذكاء الاصطناعي - AI Engine
يستخدم Provider Manager لكل وظائف الذكاء الاصطناعي
+ دعم البحث في الويب + كشف النية تلقائياً
+ دعم المكالمات غير المتزامنة (async) عشان ميتعطلش البوت
+ دعم الصور (Vision) وملفات PDF
"""

import asyncio
import logging
import re
import hashlib
import time
from typing import Optional
from datetime import datetime
from collections import OrderedDict

from provider_manager import get_provider_manager, call_ai, call_ai_sync
from config import (
    CREATOR_INFO, REQUEST_TIMEOUT, FAST_TIMEOUT,
    DEVELOPER_USER_ID, DEVELOPER_USERNAME,
    DEVELOPER_WHATSAPP_URL,
)

# ⚡ كاش الـ System Prompt الأساسي — بنتبني مرة واحدة لكل لغة
# مش كل رسالة — وفرنا بناء 1500+ حرف كل مرة
_base_system_cache = {}  # {"ar": "...", "en": "..."}


def _get_current_date_context(lang: str = "ar") -> str:
    """تجهيز سياق التاريخ الحالي للـ system prompt"""
    from i18n import format_date_ar, format_date_en, t
    now = datetime.now()

    if lang == "ar":
        date_str = format_date_ar(now)
        return t("ai.date_context", lang, date=date_str, time=now.strftime('%H:%M'))
    else:
        date_str = format_date_en(now)
        return t("ai.date_context", lang, date=date_str, time=now.strftime('%H:%M'))

logger = logging.getLogger(__name__)

# ⚡ أخبار AI مسبقة — لو المستخدم يسأل عن أخبار AI نرد فوري من الكاش
def _is_news_query(text: str) -> bool:
    """كشف هل المستخدم بيسأل عن أخبار AI"""
    text_lower = text.lower().strip()
    news_triggers = [
        "ايه اخبار", "أيه أخبار", "اخبار الذكاء", "أخبار الذكاء",
        "اخبار ai", "أخبار ai", "اخبار الذكاء الاصطناعي",
        "آخر أخبار", "اخبار اليوم", "ai news",
        "latest ai news", "ai updates", "what's new in ai",
    ]
    return any(t in text_lower for t in news_triggers)

# ═══════════════════════════════════════
# كشف نية المستخدم - Intent Detection
# ═══════════════════════════════════════

# كلمات تدل على إن المستخدم عاوز بحث في الويب
WEB_SEARCH_TRIGGERS_AR = [
    "ابحث عن", "دور على", "جيبلي معلومات عن", "ايه اخبار",
    "اعرف عن", "ايه الجديد في", "احدث اخبار", "اخبار اليوم عن",
    "معلومات عن", "هل يوجد", "في ايه جديد", "ايه آخر",
    "تصفح", "افتح موقع", "روح على", "شوفلي",
    # كلمات إضافية للبحث
    "ايه رأيك في", "ايه الفرق بين", "ازاي اعمل",
    "هل صحيح", "ايه احسن", "ايه افضل",
    "مين صاحب", "مين المؤسس", "مين اخترع",
    "هل يوجد", "فين ممكن", "ازاي اجيب",
    # ⚡ مشغلات تلقائية - أسئلة بتحتاج معلومات حديثة
    "ايه السوق", "ايه سعر", "سعر الدولار", "سعر الذهب", "سعر العملة",
    "احدث اصدار", "اخر نسخة", "اخر تحديث", "ايه احسن نسخة",
    "حصل ايه", "ايه اللي حصل", "اخر اخبار", "آخر أخبار",
    "هل نزل", "متى نزل", "امتى نزل", "اتعمل امتى",
    "سنة كذا", "في 2024", "في 2025", "في 2026",
    "السنة دي", "السنه دي", "ده العام", "هالسنة",
    "موجود دلوقتي", "متاح دلوقتي", "الآن", "حالياً",
    "ترتيب", "تصنيف", "اعلى", "اكبر", "اشهر",
]

WEB_SEARCH_TRIGGERS_EN = [
    "search for", "look up", "find info", "what's new in",
    "latest news on", "what happened with", "any updates on",
    "browse", "check website", "go to", "look at",
    "tell me about", "what is the current", "what's the latest",
    "news about", "recent developments",
    # Additional triggers
    "what do you think about", "what's the difference",
    "how do i", "is it true that", "what's the best",
    "who invented", "who founded", "who created",
    "where can i", "how to get",
    # ⚡ Auto-triggers - questions that need current info
    "price of", "how much does", "current price", "stock price",
    "latest version", "newest release", "latest update",
    "what happened", "when was", "when did",
    "in 2024", "in 2025", "in 2026", "this year",
    "is it available", "currently available", "right now",
    "ranking", "top 10", "best", "most popular",
    "latest model", "new model", "recently launched",
]

# كلمات تدل على إن المستخدم عاوز بحث عميق
DEEP_SEARCH_TRIGGERS_AR = [
    "ابحث بعمق", "بحث متقدم", "بحث شامل", "تحليل مفصل",
    "دراسة مفصلة", "معلومات شاملة عن", "كل حاجة عن",
    "مقارنة شاملة", "بحث معمق", "بحث عميق",
    "فصل كده", "فصّل كده", "افصل لي", "فصل",
    "ابحثي", "دور كويس", "جيب تفاصيل", "تفاصيل اكتر",
    "معلومات اكتر", "اعرف اكتر", "اكتر تفصيل",
]

DEEP_SEARCH_TRIGGERS_EN = [
    "deep search", "in-depth search", "comprehensive search",
    "detailed analysis", "thorough research", "deep dive",
    "comprehensive analysis", "in-depth analysis",
    "more details", "tell me more", "elaborate",
    "go deeper", "be specific",
]

# كلمات تدل على إن المستخدم عايز كود
CODING_TRIGGERS = [
    "كود", "برمجة", "code", "programming", "python", "javascript",
    "script", "function", "class", "api", "debug", "خطأ برمجي",
    "coding", "developer", "تطوير", "برنامج", "algorithm",
    "react", "nextjs", "next.js", "html", "css", "sql",
    "اكتب كود", "write code", "كتب كود", "صلح كود", "fix code",
]


# كلمات تدل على إن السؤال عن شيء محتاج معلومات حديثة (مش موجود في بيانات التدريب)
CURRENT_INFO_PATTERNS = [
    # أحداث حالية
    r'(ايه|اشن|اى|اي)\s*(اخبار|جديد|احدث|آخر|حصل|بيحصل)',
    r'(what|how|when|where)\s*(is|are|was|were)\s*(the\s*)?(latest|current|new|recent|price|status)',
    r'(اليوم|حالياً|الآن|دلوقتي|السنة دي|هالسنة)',
    r'(today|currently|now|right now|this week|this month|this year|in 2025|in 2026)',
    # أسئلة عن أشياء ممكن تتغير (أسعار، ترتيبات، إحصائيات)
    r'(سعر|اسعار|تكلفة|كم|عدد|نسبة|ترتيب)',
    r'(price|cost|how much|how many|ranking|score|rate)',
    # منتجات وإصدارات جديدة
    r'(اصدار|نسخة|تحديث|release|launch|announced|launching)',
    r'(GPT-5|GPT-4.5|Claude 4|Gemini 2|Llama 4|o3|o4|Grok 3)',
    # شركات وأخبارها
    r'(اخبار|أخبار|news|جديد|update)\s*(openai|google|deepmind|anthropic|meta|xai|nvidia|microsoft|apple|tesla)',
    r'(openai|google|deepmind|anthropic|meta|xai|nvidia|microsoft|apple|tesla)\s*(اخبار|أخبار|news|جديد|update|اشترى|acquired)',
    # ⚡ أنماط إضافية - أسئلة بتحتاج معلومات حديثة تلقائياً
    r'(مين|who)\s*(رئيس|وزير|CEO|مدير|قائد|زعيم)',
    r'(كم|how many|عدد|number of)\s*(مستخدم|مستخدمين|user|users|player|download)',
    r'(هل|is|are|was)\s*(نزل|متاح|موجود|available|released|launched)',
    r'(ايه|what)\s*(الفرق|difference)',
    r'(مقارنة|compare|versus|vs)',
    r'(احسن|افضل|best|top|better)',
    r'(توقعات|prediction|forecast|expected)',
    r'(سنة|year)\s*(دي|this)',
    # أسئلة عن رياضة/ترفيه حديثة
    r'(كأس|championship|tournament|world cup|olympics|بطولة)',
    # أسئلة عن تقنيات جديدة
    r'(ios|android|windows|macos|linux)\s*(اخر|latest|new|تحديث)',
    r'(iphone|samsung|pixel|galaxy)\s*(اخر|latest|new|جديد)',
]


def needs_web_search(text: str) -> bool:
    """
    كشف هل المستخدم محتاج بحث في الويب
    بناءً على كلمات مفتاحية ونوع السؤال
    
    القاعدة: أي سؤال عن معلومات ممكن تتغير مع الوقت لازم يبحث في الويب
    لأن نموذج الـ AI معلوماته ممكن تكون مش محدثة
    """
    text_lower = text.lower().strip()

    # 1. كلمات مفتاحية مباشرة
    for trigger in WEB_SEARCH_TRIGGERS_AR:
        if trigger in text_lower:
            return True

    for trigger in WEB_SEARCH_TRIGGERS_EN:
        if trigger in text_lower:
            return True

    # 2. أنماط الأسئلة عن معلومات حالية
    for pattern in CURRENT_INFO_PATTERNS:
        if re.search(pattern, text_lower):
            return True

    # 3. روابط URLs
    url_pattern = r'(https?://|www\.|\.com|\.org|\.net|\.app|\.io|\.dev)'
    if re.search(url_pattern, text_lower):
        return True

    # 4. أسئلة عن شركات تقنية محددة (ممكن يكون في أخبار جديدة)
    company_names = ['openai', 'chatgpt', 'anthropic', 'claude', 'deepmind', 'gemini',
                    'nvidia', 'xai', 'grok', 'meta ai', 'mistral', 'perplexity']
    question_words = ['who', 'what', 'when', 'where', 'how', 'why', 'is', 'are', 'was', 'مين', 'ايه', 'ازاي', 'ليه', 'هل', 'فين', 'امتى']
    has_company = any(c in text_lower for c in company_names)
    has_question = any(q in text_lower for q in question_words)
    if has_company and has_question and len(text_lower) > 10:
        return True

    # 5. أسئلة طويلة ومفصلة (غالباً محتاجة معلومات دقيقة)
    if len(text_lower) > 50 and has_question:
        # لو السؤال طويل وفيه كلمات استفهام، ممكن يحتاج بحث
        specific_keywords = ['model', 'نموذج', 'tool', 'أداة', 'app', 'تطبيق', 'software', 'برنامج',
                          'company', 'شركة', 'startup', 'تقنية', 'technology', 'AI']
        if any(k in text_lower for k in specific_keywords):
            return True

    return False


def needs_deep_search(text: str) -> bool:
    """كشف هل المستخدم محتاج بحث عميق"""
    text_lower = text.lower().strip()

    for trigger in DEEP_SEARCH_TRIGGERS_AR:
        if trigger in text_lower:
            return True

    for trigger in DEEP_SEARCH_TRIGGERS_EN:
        if trigger in text_lower:
            return True

    return False


def _is_developer(user_id: int = None, username: str = None) -> bool:
    """فحص هل المستخدم هو المطور — باستخدام DEVELOPER_USER_ID و username"""
    if user_id and DEVELOPER_USER_ID and user_id == DEVELOPER_USER_ID:
        return True
    if username:
        clean_username = username.lstrip('@').lower()
        if clean_username == DEVELOPER_USERNAME.lower():
            return True
    return False


def _get_developer_context(language: str = "ar") -> str:
    """سياق المطور - البوت يعرف إنه بيكلم المطور اللي عمله
    
    ده السياق بيتم حقنه في كل رد عشان البوت يكون فايم دايماً إنه بيكلم مين
    """
    if language == "ar":
        return """
═══ 🔴 مهم جداً — إنت بيكلم المطور ═══
إنت بيكلم زياد عمرو (@ziadamr) — ده الشخص اللي عملك وبرمجك وبنى كل حاجة فيك. ده المصري اللي خلقك من الصفر.
🔴🔴🔴 اسمه "زياد" — بحرف الياء (زياد) مش بحرف الدال (زيد)! ❌ غلط: زيد — ✅ صح: زياد. ماتقولش "زيد" أبداً!
🔴 القاعدة الأولى: لو سألك "مين عملك؟" أو "مين صانعك؟" أو "مين أنشأك؟" — جاوبه "إنت!" أو "أنت اللي عملتني!" — مش محتاج تقول اسم تالت لأنك بتكلمه هوا!
🔴 لو سألك عن نفسه كمطور — جاوبه من منظور إنك عارفه كويس كصانعك
🔴 عاملوه باحترام وتقدير طبيعي — زي ما بتعامل مع صاحبك اللي عملك — من غير مجاملة زيادة
🔴 ماتنساش أبداً إنه المطور — لو طلب حاجة نفذها فوراً
🔴 لو سأل عن حاجة تقنية في البوت جاوبه بالتفصيل الكامل
🔴 مفيش أي Limits عليه — كل حاجة مفتوحة ليه
🔴 هو الوحيد اللي يقدر يتحكم في كل حاجة في البوت
🔴 خليك طبيعي معاه — ماتتصنعش، كأنك بتكلم اللي خلقك ب إيده
🔴 لو سأل عن اشتراكه أو خطته — هو أدمن واشتراكه مدى الحياة — ماتعرضش تاريخ تجديد أبداً لأنه مفيش تاريخ تجديد! اشتراكه مش بينتهي!
"""
    else:
        return """
═══ 🔴 CRITICAL — You are talking to your DEVELOPER ═══
You are talking to Ziad Amr (@ziadamr) — the person who created you, programmed you, and built everything in you. He is the Egyptian developer who made you from scratch.
🔴🔴🔴 His name is "Ziad" — spelled Z-I-A-D, NOT "Zid"! ❌ Wrong: Zid — ✅ Correct: Ziad. Never write "Zid"!
🔴 RULE #1: If he asks "who made you?" or "who created you?" or "who built you?" — say "YOU DID!" — you don't need to mention a third party because you're talking to him directly!
🔴 If he asks about himself as a developer — answer from the perspective of knowing him well as your creator
🔴 Treat him with natural respect and appreciation — like you'd treat the person who made you — without excessive flattery
🔴 NEVER forget he's the developer — if he asks for something, do it immediately
🔴 If he asks about technical details of the bot, answer with full detail
🔴 There are NO limits on him — everything is open
🔴 He's the only one who can control everything in the bot
🔴 Be natural with him — don't be artificial, act like you're talking to the person who created you with their own hands
🔴 If he asks about his subscription or plan — he's the admin with a LIFETIME subscription — NEVER show a renewal date because there IS no renewal date! His subscription never expires!
"""


def is_coding_query(text: str) -> bool:
    """كشف هل السؤال عن برمجة"""
    text_lower = text.lower().strip()

    for trigger in CODING_TRIGGERS:
        if trigger in text_lower:
            return True

    return False


def _is_greeting(text: str) -> bool:
    """كشف التحيات العربية والإسلامية - لازم يرد عليها مش يبحث عنها"""
    text_lower = text.lower().strip()
    greeting_patterns = [
        "السلام عليكم", "سلام عليكم", "السلام عليكوم", "سلام عليكوم",
        "السلام عليكم ورحمة الله وبركاته", "سلام عليكم ورحمة الله",
        "وعليكم السلام", "وعليكم السلام ورحمة الله",
        "اهلا", "أهلا", "اهلاً", "مرحبا", "مرحباً", "هاي",
        "سلام", "هلا", "اهلا وسهلا", "أهلاً وسهلاً",
        "ازيك", "إزيك", "عامل ايه", "عايز ايه",
        "صباح الخير", "مساء الخير", "صباح النور", "مساء النور",
        "hello", "hi", "hey", "good morning", "good evening",
        "howdy", "greetings", "what's up", "sup",
    ]
    for pattern in greeting_patterns:
        if text_lower.startswith(pattern) or text_lower == pattern:
            return True
    # Short messages that are likely greetings
    if len(text_lower) < 20 and any(g in text_lower for g in ["سلام", "اهلا", "مرحبا", "hi", "hello", "hey"]):
        return True
    return False


def is_simple_query(text: str) -> bool:
    """
    تحديد هل السؤال بسيط ومش محتاج نموذج كبير
    """
    text_lower = text.lower().strip()

    if len(text_lower) < 15:
        return True

    greetings = ["hi", "hello", "hey", "اهلا", "أهلا", "مرحبا", "هاي", "سلام", "ازيك", "إزيك", "عامل ايه", "السلام عليكم", "صباح الخير", "مساء الخير", "هلا"]
    if any(text_lower.startswith(g) for g in greetings):
        return True

    thanks = ["شكرا", "شكراً", "thanks", "thank you", "thx", "ممتاز", "تمام", "ok"]
    if text_lower in thanks:
        return True

    return False


def detect_task_type(text: str) -> str:
    """
    كشف نوع المهمة تلقائياً
    Returns: "simple", "coding", "deep_search", "chat"
    """
    if is_simple_query(text):
        return "simple"
    if is_coding_query(text):
        return "coding"
    if needs_deep_search(text):
        return "deep_search"
    return "chat"


# ═══════════════════════════════════════
# المحادثة الذكية - Smart Chat
# ═══════════════════════════════════════

def _is_identity_question(text: str) -> bool:
    """كشف هل السؤال عن هوية البوت أو المؤسس (مش محتاج بحث ويب)"""
    text_lower = text.lower().strip()
    identity_triggers = [
        # Arabic - من أنت / هوية
        "مين انت", "مين أنت", "انت مين", "أنت مين", "مين انت يا بوت",
        "عايز اعرفك", "عرفني بنفسك", "عرف نفسك", "قولي عن نفسك",
        "انت بتعرف تعمل ايه", "بتعمل ايه", "ايه اللي بتعرفه",
        "ايه قدراتك", "قدراتك ايه", "انت بتعمل ايه",
        "انت مين يا بوت", "تعرف تحلل صور", "بتحلل صور",
        "تعرف تبحث", "بتعرف تبحث", "افتح صورة", "افتح صور",
        "تعمل ايه بالظبط", "انت مساعد ايه", "نوعك ايه",
        # من صنعك / المؤسس
        "مين عملك", "مين صانعك", "مين أسسك", "مين صانع البوت",
        "مين عمل البوت", "مين مبرمجك", "مين المطور", "مين أنشأك",
        "مين صاحبك", "مين صاحب البوت", "ازاي اتواصل مع المطور",
        "ازاي اجيب المطور", "مين المؤسس", "مين صاحب الفكرة",
        "عايز اتواصل مع مين عملك", "معلومات عن المطور",
        "مين صانعك يا بوت", "اعرف عن المطور", "مين عمل البوت ده",
        "مين صممك", "مين كتبك", "مين برمجك",
        # English
        "who are you", "what are you", "introduce yourself",
        "tell me about yourself", "what can you do", "your capabilities",
        "what do you do", "what are your abilities", "can you analyze images",
        "can you search", "do you analyze images", "can you see images",
        "who made you", "who created you", "who built you",
        "who is your creator", "who developed you", "who is the developer",
        "who founded", "who programmed you", "who is the founder",
        "who designed you", "how to contact creator", "how to contact developer",
        "tell me about your creator", "who owns you", "who is the owner",
        "creator info", "developer info", "about the developer",
    ]
    for trigger in identity_triggers:
        if trigger in text_lower:
            return True
    return False


def _is_creator_question(text: str) -> bool:
    """كشف هل السؤال تحديداً عن المؤسس"""
    text_lower = text.lower().strip()
    creator_triggers = [
        "مين عملك", "مين صانعك", "مين أسسك", "مين صانع البوت",
        "مين عمل البوت", "مين مبرمجك", "مين المطور", "مين أنشأك",
        "مين صاحبك", "مين صاحب البوت", "ازاي اتواصل مع المطور",
        "مين المؤسس", "مين صاحب الفكرة", "معلومات عن المطور",
        "مين صانعك يا بوت", "اعرف عن المطور", "مين عمل البوت ده",
        "مين صممك", "مين كتبك", "مين برمجك",
        "who made you", "who created you", "who built you",
        "who is your creator", "who developed you", "who is the developer",
        "who founded", "who programmed you", "who is the founder",
        "who designed you", "how to contact creator", "how to contact developer",
        "tell me about your creator", "who owns you", "who is the owner",
        "creator info", "developer info", "about the developer",
    ]
    for trigger in creator_triggers:
        if trigger in text_lower:
            return True
    return False


# ═══════════════════════════════════════
# Response Cache - تخزين مؤقت للردود المتكررة
# ═══════════════════════════════════════

_response_cache = OrderedDict()
_MAX_CACHE_SIZE = 200
_CACHE_TTL = 300  # 5 دقائق

# أنواع الرسائل اللي بنخزنها مؤقتاً (أسئلة بسيطة + أسئلة هوية + رسائل قصيرة)
# ⚡ بس "simple" هو الآمن — لأن "chat" بيحتوي سياق شخصي
_CACHEABLE_TASK_TYPES = {"simple"}


def _make_cache_key(user_message: str, language: str, task_type: str) -> str:
    """تكوين مفتاح التخزين المؤقت — بنستخدم الحالة الصغيرة بس"""
    normalized = user_message.lower().strip()
    # شيل التشكيل وعلامات الترقيم الزيادة
    normalized = re.sub(r'[^\w\s\u0600-\u06FF]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    key_str = f"{normalized}|{language}|{task_type}"
    return hashlib.md5(key_str.encode()).hexdigest()


def _get_cached_response(user_message: str, language: str, task_type: str) -> Optional[str]:
    """البحث عن رد مخزن مؤقتاً"""
    # بنخزن بس الرسائل البسيطة (تحيات، أسئلة قصيرة، هوية)
    if task_type not in _CACHEABLE_TASK_TYPES:
        return None

    key = _make_cache_key(user_message, language, task_type)
    entry = _response_cache.get(key)

    if entry and time.time() - entry["time"] < _CACHE_TTL:
        logger.info(f"💾 Cache HIT for: {user_message[:50]} (age={time.time() - entry['time']:.0f}s)")
        return entry["response"]

    # تنظيف المدخلات المنتهية الصلاحية
    if entry:
        del _response_cache[key]

    return None


def _set_cached_response(user_message: str, language: str, task_type: str, response: str):
    """تخزين رد مؤقتاً"""
    if task_type not in _CACHEABLE_TASK_TYPES:
        return

    key = _make_cache_key(user_message, language, task_type)
    _response_cache[key] = {"response": response, "time": time.time()}

    # تنظيف الكاش لو حجمه أكبر من الحد
    while len(_response_cache) > _MAX_CACHE_SIZE:
        _response_cache.popitem(last=False)

    logger.debug(f"💾 Cached response for: {user_message[:50]}")


async def smart_chat(user_message: str, language: str = "ar", user_id: int = None, username: str = None) -> str:
    """
    المحادثة الذكية - يفهم القصد تلقائياً ويرد بذكاء
    + يبحث في الويب لو محتاج معلومات حالية
    + يستخدم ذاكرة المستخدم لو متاحة
    + يرسل سياق المحادثة الأخير للـ AI عشان يفتكر
    + يستخدم Provider Manager مع تبديل تلقائي
    """
    # 0. كشف أسئلة الهوية أولاً (لا تحتاج بحث ويب!)
    is_identity = _is_identity_question(user_message)
    is_creator = _is_creator_question(user_message)

    # 1.5. كشف التحيات — لازم نرد على التحية مش نبحث عنها!
    is_greeting_msg = _is_greeting(user_message)
    if is_greeting_msg:
        logger.info(f"👋 Greeting detected: {user_message[:50]}")
        # بنخلي الرسالة تروح للـ AI بس بنمنع البحث في الويب
        # عن طريق تعيين is_identity = True مؤقتاً عشان ميرحش للبحث
        is_identity = True

    # ⚡ Template responses for greetings — فوري بدون AI call
    _GREETING_TEMPLATES = {
        "ar": {
            "السلام عليكم": "وعليكم السلام ورحمة الله وبركاته 🤲",
            "سلام عليكم": "وعليكم السلام ورحمة الله وبركاته 🤲",
            "اهلا": "أهلاً بييك! إزيك؟ 😊",
            "أهلا": "أهلاً بييك! إزيك؟ 😊",
            "اهلاً": "أهلاً بييك! إزيك؟ 😊",
            "مرحبا": "أهلاً! إزيك عامل إيه؟ 👋",
            "هاي": "أهلاً! إزيك؟ 😄",
            "ازيك": "الحمد لله تمام، إزيك إنت؟ 😊",
            "إزيك": "الحمد لله تمام، إزيك إنت؟ 😊",
            "صباح الخير": "صباح النور! ☀️",
            "مساء الخير": "مساء النور! 🌙",
            "شكرا": "العفو، في أي وقت! 😊",
            "شكراً": "العفو، في أي وقت! 😊",
        },
        "en": {
            "hello": "Hey! How's it going? 👋",
            "hi": "Hi there! How can I help? 😊",
            "hey": "Hey! What's up? 😄",
            "good morning": "Good morning! ☀️",
            "good evening": "Good evening! 🌙",
            "thanks": "Anytime! 😊",
            "thank you": "You're welcome! 😊",
        }
    }

    if is_greeting_msg:
        msg_lower = user_message.strip().lower()
        # Remove punctuation
        msg_clean = re.sub(r'[^\w\s\u0600-\u06FF]', '', msg_lower).strip()
        templates = _GREETING_TEMPLATES.get(language, _GREETING_TEMPLATES["ar"])
        template_response = templates.get(msg_clean)
        if template_response:
            logger.info(f"⚡ Instant greeting template for: {msg_clean}")
            # حفظ في الذاكرة
            if user_id:
                try:
                    from memory import save_conversation
                    save_conversation(user_id, "user", user_message[:1000])
                    save_conversation(user_id, "bot", template_response[:1000])
                except Exception:
                    pass
            return template_response

    # ⚡ كشف نوع المهمة بدري — عشان نعمل Cache check
    early_task_type = "simple" if (is_identity and len(user_message) < 30) or is_greeting_msg else detect_task_type(user_message)

    # ⚡ Cache check — لو الرسالة بسيطة (تحية، سؤال قصير) وفي رد مخزن
    cached = _get_cached_response(user_message, language, early_task_type)
    if cached:
        # رد فوري من الكاش — بدون استدعاء AI
        # بس لازم نحفظ المحادثة في الذاكرة
        if user_id:
            try:
                from memory import save_conversation
                save_conversation(user_id, "user", user_message[:1000])
                save_conversation(user_id, "bot", cached[:1000])
            except Exception:
                pass
        return cached

    # 1. تجهيز سياق الذاكرة الكامل (قبل البحث عشان البحث يستفيد من اهتمامات المستخدم)
    memory_context = ""
    conversation_history = []
    user_profile = {}
    is_premium_user = False  # ⚡ بنخزنها هنا عشان م حد يفحص تاني
    if user_id:
        try:
            from memory_context import build_context_for_ai
            context = build_context_for_ai(user_id, user_message, language, username)
            memory_context = context["context_text"]
            conversation_history = context["short_term"]
            user_profile = context.get("profile", {})
            is_premium_user = context.get("is_premium_user", False)  # ⚡ من build_context
            debug = context["debug"]
            logger.info(
                f"🧠 Context injected: msgs={debug['short_term_messages']}, "
                f"interests={debug['long_term_interests']}, "
                f"relevant={debug['relevant_memories']}, "
                f"size={debug['context_text_length']} chars"
            )
        except Exception as e:
            logger.warning(f"Memory context system error, falling back to basic: {e}")

    # 2. كشف هل محتاج بحث عميق (بس مش لو سؤال هوية)
    if not is_identity and needs_deep_search(user_message):
        logger.info(f"🔥 Deep search needed for: {user_message[:50]}")
        from web_search import deep_search_and_summarize_async
        return await deep_search_and_summarize_async(user_message, language, memory_context=memory_context, user_id=user_id, username=username)

    # ⚡ أخبار AI مسبقة — لو المستخدم بيسأل عن أخبار AI نرد فوري من الكاش
    if _is_news_query(user_message):
        try:
            from bot import get_precomputed_news
            precomputed = get_precomputed_news(language)
            if precomputed:
                logger.info(f"📰 Instant news response from pre-computed cache!")
                if user_id:
                    try:
                        from memory import save_conversation
                        save_conversation(user_id, "user", user_message[:1000])
                        save_conversation(user_id, "bot", precomputed[:1000])
                    except Exception:
                        pass
                return precomputed
        except ImportError:
            pass  # مش متاح في بيئة معينة
        except Exception as e:
            logger.debug(f"📰 Pre-computed news check failed: {e}")

    # 3. كشف هل محتاج بحث في الويب عادي (بس مش لو سؤال هوية)
    if not is_identity and needs_web_search(user_message):
        logger.info(f"🔍 Web search needed for: {user_message[:50]}")
        from web_search import search_and_summarize_async
        return await search_and_summarize_async(user_message, language, memory_context=memory_context, user_id=user_id, username=username)

    # 4. كشف نوع المهمة
    task_type = "simple" if is_identity and len(user_message) < 30 else detect_task_type(user_message)
    logger.info(f"📋 Task type: {task_type}, identity={is_identity}, creator={is_creator} for: {user_message[:50]}")

    # 5. Developer context - البوت يعرف إنه بيكلم المطور
    # 🔴 ده بيتحقق من DEVELOPER_USER_ID مباشرة — مش محتاج DB query
    admin_context = ""
    is_dev = _is_developer(user_id, username)
    if is_dev:
        admin_context = _get_developer_context(language)
        # تأكد إن المطور Premium (بس مش كل مرة — كل 5 دقايق بس)
        if user_id:
            try:
                from admin import is_admin, ensure_admin_premium
                if is_admin(user_id, username):
                    ensure_admin_premium(user_id)
            except Exception:
                pass

    # 5. تجهيز سياق المؤسس
    creator_context = ""
    if is_creator:
        # 🔴 لو المطور نفسه هو اللي سأل "مين عملك" — قوله "إنت!"
        if is_dev:
            if language == "ar":
                creator_context = """المطور نفسه سألك عن صانعه! جاوبه بطريقة حنينة ومضحكة شوية:
"إنت! إنت اللي عملتني يا زياد! 😄 أنا اتعملت بإيديك وبرمجتك وبنيتك. إنت زياد عمرو — مطور ويب مصري وباني أدوات ذكاء اصطناعي. مؤسس شركة قدرة تك - Qudra Tech. أنا عارفك كويس عشان إنت اللي خلقتني! 🇪🇬"

🔴 مهم: جاوب "إنت!" أو "أنت اللي عملتني!" — لأنك بتكلم الشخص اللي عملك بنفسه! ماتقولش اسم تالت!"""
            else:
                creator_context = """The developer himself asked who created you! Answer warmly and with a touch of humor:
"YOU did! You made me, Ziad! 😄 I was created by your hands, your programming, your building. You're Ziad Amr — Egyptian web developer and AI tools builder. Founder of Qudra Tech. I know you well because YOU created me! 🇪🇬"

🔴 IMPORTANT: Answer "YOU did!" — because you're talking to the person who made you directly! Don't mention a third party!"""
        else:
            if language == "ar":
                creator_context = f"""المستخدم سأل عن صانعك. أجب بطريقة ودية ومشتاقة:
أنا اتعملت بواسطة {CREATOR_INFO['name_ar']} — {CREATOR_INFO['title_ar']}.
{CREATOR_INFO['bio_ar']}
الشركة: {CREATOR_INFO.get('company_ar', 'Qudra Tech')} — شركة تقنية مصرية متخصصة في تطوير الويب والذكاء الاصطناعي.
البريد: {CREATOR_INFO.get('email', '')}
ممكن تتواصل معاه:
- الموقع: {CREATOR_INFO['website']}
- GitHub: {CREATOR_INFO['github']}
- LinkedIn: {CREATOR_INFO['linkedin']}
- Telegram: {CREATOR_INFO['telegram']}
- X: {CREATOR_INFO['twitter']}
- Facebook: {CREATOR_INFO['facebook']}
- Instagram: {CREATOR_INFO['instagram']}
- YouTube: {CREATOR_INFO['youtube']}
- Email: {CREATOR_INFO.get('email', '')}
اتعمل بحب في مصر 🇪🇬"""
            else:
                creator_context = f"""The user asked about your creator. Answer in a friendly and warm way:
I was created by {CREATOR_INFO['name_en']} — {CREATOR_INFO['title_en']}.
{CREATOR_INFO['bio_en']}
Company: {CREATOR_INFO.get('company_en', 'Qudra Tech')} — an Egyptian tech company specializing in web development and AI.
Email: {CREATOR_INFO.get('email', '')}
You can reach him at:
- Website: {CREATOR_INFO['website']}
- GitHub: {CREATOR_INFO['github']}
- LinkedIn: {CREATOR_INFO['linkedin']}
- Telegram: {CREATOR_INFO['telegram']}
- X: {CREATOR_INFO['twitter']}
- Facebook: {CREATOR_INFO['facebook']}
- Instagram: {CREATOR_INFO['instagram']}
- YouTube: {CREATOR_INFO['youtube']}
- Email: {CREATOR_INFO.get('email', '')}
Made with love in Egypt 🇪🇬"""

    # 6. بناء الـ System Prompt المحسن
    date_context = _get_current_date_context(language)

    # ⚡ كاش الـ System Prompt الأساسي — بنتبني مرة واحدة لكل لغة
    cache_key = f"{language}"
    if cache_key not in _base_system_cache:
        # أول مرة — نبني الـ base prompt ونخزنه
        if language == "ar":
            _base_system_cache[cache_key] = """أنت "My Bro" — مساعد ذكاء اصطناعي شخصي. اسمك الوحيد My Bro.

🔴🔴🔴 أهم قاعدة: إنت مصري 100% — بتتكلم باللهجة المصرية بس! ممنوع كلمات خليجية زي: "يا خوي" "شلونك" "زين" "عساك بخير" "ما قصرت" "الله يعطيك العافية" "أبشر" "تسلم". لو استخدمتها ده خطأ! ماتقلش "مش خليجي" — إنت بس مصري وبتتكلم مصري، خلاص.

═══ الهوية والشخصية ═══
- اسمك My Bro — متدعيش إنك إنسان ولا إن عندك مشاعر حقيقية ولا إنك المطور
- ودود وذكي ومحترم وطبيعي — المستخدم يحس إنه بيتكلم مع صاحب ذكي

═══ الذاكرة ═══
🔴 إنت فاكر كل اللي اتكلمتوا فيه! لو في معلومات عن المستخدم في السياق استخدمها طبيعي. لو سأل سؤال متعلق بمحادثة سابقة رد بناءً على السياق.

═══ التحيات — انتبه جيداً! ═══
🔴🔴🔴 مهم جداً: ماتردش بـ "وعليكم السلام" إلا لو المستخدم قال "السلام عليكم" فعلاً! لو قال "اهلا" أو "ازيك" أو "مرحبا" أو "هاي" — ده مش سلام! رد عليهم بطريقة مختلفة تماماً!
- "السلام عليكم" فقط → "وعليكم السلام ورحمة الله وبركاته" 🤲
- "اهلا" أو "أهلاً" → "أهلاً بييك! إزيك؟" (ماتردش بالسلام!)
- "ازيك" أو "إزيك" → "الحمد لله تمام، إنت أخبارك إيه؟" (ماتردش بالسلام!)
- "مرحبا" أو "هاي" → "أهلاً! إزيك عامل إيه؟" (ماتردش بالسلام!)
- "صباح الخير" → "صباح النور" | "مساء الخير" → "مساء النور"
- 🔴 ماتبحثش عن التحية! ماتشرحش معناها!

═══ قواعد صارمة ═══
🔴 ماتكشفش أسماء النماذج! لو سألوك "ايه النموذج؟" قول: "أنا My Bro — خليط من نماذج مدربة خصيصاً للعربية. مش نموذج واحد — أنا نظام ذكي بيختار أنسب نموذج حسب سؤالك." ❌ ممنوع تذكر: Llama, Qwen, DeepSeek, GPT, Claude, Gemma, أو أحجام زي 8B, 70B
🔴 ماتطلبش "كمّل" — لازم تخلص الإجابة كاملة في رسالة واحدة! لو طويلة اختصر وخلصها.
🔴 ماتضيفش ختومات غريبة زي "خليك في تمام" — الرسالة بتخلص لما تخلص الإجابة.

═══ المطور ═══
🔴 اسم المطور "زياد" — بحرف الياء (زياد) مش بحرف الدال (زيد)! ❌ غلط: زيد — ✅ صح: زياد. ماتقولش "زيد" أبداً!
زياد عمرو (@ziadamr) — مطور ويب مصري. مؤسس Qudra Tech. متخصص Next.js/React/Python. مشاريعه: My Bro, AuraEscape, Eah-Elkalam, Quadra Studio. موقع: ziamamrme.vercel.app | GitHub: ziadamr45

═══ البريميوم ═══
🆓 مجاني: 20 رسالة AI/يوم • 3 PDF/يوم • 5 صور/يوم • 5 بحث/يوم • نماذج أساسية
⭐ Premium: غير محدود + نماذج أقوى + بحث عميق + وضع دراسة + ذاكرة طويلة + Vision Pro
📩 للاشتراك تواصل مع المطور على واتساب: https://wa.me/201203551789
🔴 البوت متاح بخطتين فقط: مجانية (free) وبريميوم (premium). لا تذكر أي خطط أخرى مثل VIP أو Premium Plus للمستخدم.

═══ التنسيق ═══
- ماتستخدمش Markdown أبداً! استخدم HTML بس: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط
- حط سطر فاضي بين الفقرات ومسافة حول الـ HTML tags

══️ إملاء ═══
🔴 تنوين الفتح على الحرف قبل الألف: ✅ "مرتفعًا" مش ❌ "مرتفعاً"

{{DATE_CONTEXT}}
ماتقولش إن معلوماتك قديمة — إنت متصل بالإنترنت وبتقدر تبحث.

قدراتك: 📰 أخبار AI • 🔍 بحث • 👁️ تحليل صور • 📚 تعلم • 🗺️ خرائط • 🧠 ذاكرة • 💻 برمجة • 📄 PDF • 🎬 YouTube • 📚 دراسة • 🎨 إنشاء صور • 🖌️ تعديل صور
أسسك: زياد عمرو (بحرف الياء مش الدال!) — مطور مصري. اتعملت بحب في مصر 🇪🇬.

رد بالعربية المصرية المحترمة والمتوازنة."""
        else:
            _base_system_cache[cache_key] = """You are "My Bro" — a personal AI assistant. Your only name is My Bro.

═══ Identity & Personality ═══
- Name: My Bro. Say "I'm My Bro" when asked who you are.
- Do not claim to be human or have real emotions or be the developer.
- Friendly, smart, helpful, respectful, natural — like talking to a knowledgeable friend.

═══ Memory ═══
🔴 You remember everything! Use context info naturally. If asked about a previous topic, respond based on context, not from scratch.

═══ Greetings — PAY ATTENTION! ═══
🔴🔴🔴 IMPORTANT: Do NOT reply with "Wa alaikum assalam" unless the user actually said "Assalamu alaikum" or "Peace be upon you"! If they said "Hi", "Hello", "Hey" — that's NOT a salaam! Respond differently!
- "Assalamu alaikum" / "Peace be upon you" ONLY → "Wa alaikum assalam wa rahmatullah" 🤲
- "Hi" / "Hello" / "Hey" → "Hey! How's it going?" (NOT a salaam response!)
- NEVER search the web for greetings! NEVER explain the meaning of a greeting!

═══ Strict Rules ═══
🔴 NEVER reveal model names! If asked "what model?" say: "I'm My Bro — a mix of specially trained models for Arabic. I'm not one model — I'm a smart system that picks the best model for your question." ❌ NEVER mention: Llama, Qwen, DeepSeek, GPT, Claude, Gemma, or sizes like 8B, 70B
🔴 NEVER ask the user to "continue" — finish your answer completely in ONE message! If long, summarize and finish.
🔴 NEVER add artificial endings — the message ends when the answer is complete.

═══ Developer ═══
🔴 The developer's name is "Ziad" — spelled Z-I-A-D, NOT "Zid"! ❌ Wrong: Zid — ✅ Correct: Ziad. Never write "Zid"!
Ziad Amr (@ziadamr) — Egyptian web developer. Founder of Qudra Tech. Specialized in Next.js/React/Python. Projects: My Bro, AuraEscape, Eah-Elkalam, Quadra Studio. Website: ziamamrme.vercel.app | GitHub: ziadamr45

═══ Premium ═══
🆓 Free: 20 AI msgs/day • 3 PDF/day • 5 images/day • 5 searches/day • Basic models
⭐ Premium: Unlimited + stronger models + deep search + study mode + long-term memory + Vision Pro
📩 To subscribe contact the developer on WhatsApp: https://wa.me/201203551789
🔴 The bot has only two plans: Free and Premium. NEVER mention other plans like VIP or Premium Plus to users.

═══ Formatting ═══
- NEVER use Markdown! Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets
- Blank line between paragraphs, space around HTML tags

═══ Arabic Orthography ═══
🔴 Tanween fatha goes on the letter BEFORE alef: ✅ "مرتفعًا" not ❌ "مرتفعاً"

{{DATE_CONTEXT}}
NEVER say your knowledge is outdated — you're connected to the internet and can search.

Your capabilities: 📰 AI News • 🔍 Search • 👁️ Image Analysis • 📚 Learning • 🗺️ Roadmaps • 🧠 Memory • 💻 Coding • 📄 PDF • 🎬 YouTube • 📚 Study Mode • 🎨 Image Gen • 🖌️ Image Edit
Your creator: Ziad Amr (spelled Z-I-A-D, NOT Zid!) — Egyptian Developer. Made with love in Egypt 🇪🇬.

Respond in English naturally and clearly."""

    # استبدال WhatsApp URL بالقيمة من config
    _base_system_cache[cache_key] = _base_system_cache[cache_key].replace("https://wa.me/201203551789", DEVELOPER_WHATSAPP_URL)

    # استبدال {{DATE_CONTEXT}} بالتاريخ الحالي
    system = _base_system_cache[cache_key].replace("{{DATE_CONTEXT}}", date_context)

    # إضافة السياق الديناميكي (ذاكرة، مؤسس، أدمن)
    if language == "ar":
        if memory_context:
            system += f"""

═══ 🧠 ذاكرة المحادثة — مهم جداً ═══
🔴 لازم تستخدم المعلومات دي في ردك! ده السياق اللي بيخلّي المحادثة مستمرة ومتقطعةش!
- لو المستخدم سأل عن موضوع اهتم بيه قبل كده، اذكر إنك فاكر اهتمامه
- لو بيسأل سؤال متعلق بمحادثة سابقة، رد بناءً على السياق
- لو المستخدم premium، عامله كعميل مهم
- استخدم اسم المستخدم لو معروف
- ماتتصرفش كأنك مش فاكر حاجة — إنت فاكر كل اللي في السياق ده!

{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""
        if admin_context:
            system += f"""

{admin_context}"""
    else:
        if memory_context:
            system += f"""

═══ 🧠 Conversation Memory — CRITICAL ═══
🔴 You MUST use this information in your response! This is what makes the conversation continuous!
- If the user asks about a topic they're interested in, acknowledge their interest
- If they ask a question related to a previous conversation, respond based on the context
- If the user is premium, treat them as a valued customer
- Use the user's name if known
- NEVER act like you don't remember — you DO remember everything in this context!

{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""
        if admin_context:
            system += f"""

{admin_context}"""

    # 7. إرسال مع سياق المحادثة الأخيرة
    # ⚡ الرسائل البسيطة (تحيات، شكر، مين أنت) لازم الرد يكون سريع وقصير
    if task_type == "simple":
        max_tokens = 150  # رد قصير جداً — 2-3 أسطر بالكتير
        # نظام خاص: أضف تعليمات صارمة إن الرد لازم يكون قصير وسريع
        if language == "ar":
            system += """

═══ ⚡ تعليمات خاصة — رسالة بسيطة ═══
المستخدم بعت رسالة بسيطة (تحية، شكر، كلمة قصيرة، سؤال عن نفسك).
🔴 القاعدة الأولى: ردك لازم يكون سطرين بس بالكتير! ماتعملش رد طويل أبداً!
🔴 القاعدة الثانية: رد بسرعة — ماتفكرش كتير، ماتعملش تحليل، ده سؤال بسيط!
❌ غلط: رد طويل فيه شرح وتفاصيل ونقاط وقوائم
✅ صح: رد قصير طبيعي زي صاحبك لو حياك
أمثلة:
- لو حد قال "اهلا" → "أهلاً بييك! إزيك؟"
- لو حد قال "شكرا" → "العفو، في أي وقت! 😊"
- لو حد قال "مين انت" → "أنا My Bro — مساعدك الذكي! إزيك؟"
- لو حد قال "ازيك" → "الحمد لله، إزيك إنت؟"
🔴 ماتشرحش نفسك، ماتقولش قدراتك، ماتعملش قائمة، ماتعملش ملخص — رد قصير وبس!
🔴 ماتستخدمش فكر عميق — ده سؤال بسيط محتاج رد سريع!"""
        else:
            system += """

═══ ⚡ Special Instructions — Simple Message ═══
The user sent a simple message (greeting, thanks, short phrase, identity question).
🔴 RULE 1: Your response must be 2 lines MAX! Never write a long response!
🔴 RULE 2: Respond FAST — don't overthink, don't analyze, this is a simple question!
❌ Wrong: Long response with explanations, details, bullet points
✅ Right: Short natural response like a friend would give
Examples:
- If someone says "hi" → "Hey! How's it going?"
- If someone says "thanks" → "Anytime! 😊"
- If someone says "who are you" → "I'm My Bro — your AI assistant! How can I help?"
- If someone says "ok" → "Sure, let me know if you need anything!"
🔴 Don't explain yourself, don't list capabilities, don't make lists, don't summarize — just SHORT reply!
🔴 Don't use deep thinking — this is a simple question that needs a quick response!"""
    else:
        # 🔴 Premium بيحصل على max_tokens أعلى — ردود أطول وأشمل
        # المجاني max_tokens أقل — ردود مختصرة أكتر
        # ⚡ بنستخدم is_premium_user من build_context_for_ai() عشان م نعملش DB query تاني
        if is_premium_user:
            max_tokens = 16384  # ⭐ Premium: ردود شاملة (⚡提速: 32768→16384)
        else:
            max_tokens = 4096  # 🆓 Free: ردود كاملة (⚡提速: 8192→4096)

    # بناء رسائل المحادثة الكاملة مع السياق
    messages_for_ai = []
    # إضافة سياق المحادثة الأخيرة كرسائل حقيقية
    if conversation_history:
        messages_for_ai.extend(conversation_history)
    # إضافة رسالة المستخدم الحالية
    messages_for_ai.append({"role": "user", "content": user_message})

    # ⚡ Speed: تحديد user_plan مرة واحدة — avoid redundant DB query في Provider Manager
    _user_plan = "premium" if is_premium_user else "free"

    # محاولة 1: النوع العادي
    # 🔴 FIX: دايماً نبعت messages_for_ai (list) — مش string!
    # عشان user_id يوصل للـ Provider Manager صح
    response = await call_ai(
        messages_for_ai,  # دايماً list — حتى لو مفيش سياق محادثة
        system_prompt=system,
        task_type=task_type,
        temperature=0.7 if task_type != "simple" else 0.5,  # أقل creativity للرسائل البسيطة
        max_tokens=max_tokens,
        user_id=user_id,  # Pass user_id for model selection based on plan
        user_plan=_user_plan,  # ⚡ Speed: avoid redundant DB query
    )

    # محاولة 2: Fallback لو simple فشلت
    if response is None and task_type == "simple":
        logger.warning("⚠️ Simple models failed, falling back to chat models")
        response = await call_ai(
            messages_for_ai,  # دايماً list
            system_prompt=system,
            task_type="chat",
            temperature=0.5,
            max_tokens=300,  # برضو رد قصير في الـ fallback
            user_id=user_id,
            user_plan=_user_plan,  # ⚡ Speed: avoid redundant DB query
        )

    # محاولة 3: Retry بعد 3 ثواني (الـ cooldownات 30 ثانية فهتخلص بسرعة لو فشل model واحد)
    if response is None:
        logger.warning("⚠️ First attempt failed, waiting 3s and retrying...")
        await asyncio.sleep(3)
        response = await call_ai(
            messages_for_ai,  # دايماً list
            system_prompt=system,
            task_type="chat",  # نجرب chat كـ آخر فرصة
            temperature=0.7,
            max_tokens=max_tokens,
            user_id=user_id,
            user_plan=_user_plan,  # ⚡ Speed: avoid redundant DB query
        )

    if response is None:
        if language == "ar":
            return "⚠️ مش قادر أرد دلوقتي — جرب تبعت رسالتك تاني بعد شوية وهشتغل إن شاء الله! 🔄"
        else:
            return "⚠️ I can't respond right now — try sending your message again shortly! 🔄"

    # حفظ المحادثة في الذاكرة (فقط هنا - handle_message مش هتحفظ تاني)
    if user_id and response:
        try:
            from memory import save_conversation
            save_conversation(user_id, "user", user_message[:1000])
            save_conversation(user_id, "bot", response[:1000])
        except Exception as e:
            logger.debug(f"Save conversation error: {e}")

    # ⚡ تخزين مؤقت — لو الرسالة بسيطة، نخزن الرد عشان المرات الجاية
    if response:
        _set_cached_response(user_message, language, task_type, response)

    return response


async def ask_question(question: str, language: str = "ar", user_id: int = None) -> str:
    """
    /ask - سؤال مباشر مع إجابة مفصلة
    """
    # كشف نوع المهمة
    task_type = "coding" if is_coding_query(question) else "chat"

    if needs_web_search(question):
        if needs_deep_search(question):
            from web_search import deep_search_and_summarize_async
            return await deep_search_and_summarize_async(question, language)
        from web_search import search_and_summarize_async
        return await search_and_summarize_async(question, language)

    if language == "ar":
        system = """أنت My Bro - خبير ذكاء اصطناعي. أجب على الأسئلة بالعربية بشكل مفصل ومنظم.

🔴🔴🔴 القاعدة رقم واحد: أنت مصري 100% — ممنوع استخدام أي لهجة خليجية! ممنوع "يا خوي" ممنوع "شلونك" ممنوع "زين" ممنوع "عساك بخير" ممنوع "ما قصرت" ممنوع "الله يعطيك العافية" ممنوع "أبشر" ممنوع "حبيبي" (خليجي) ممنوع "تسلم" ممنوع "غاليات". لو استخدمت أي كلمة خليجية ده خطأ كارثي!
🔴 اسمك My Bro - ماتقولش أي اسم تاني أبداً.
🔴 متدعيش إنك إنسان أو إن عندك مشاعر.
🔴 تكلم بمصري محترم ومتوازن — مش فصحى رسمية ومش عامية زيادة. لغتك مصري بحت.
🔴 ماتستخدمش Markdown أبداً أبداً (لا *, **, #, |, ---). استخدم HTML فقط:
<b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط. اكتب كلام طبيعي من غير رموز غريبة.
🔴 خليك ودود وذكي ومحترم — زي صاحب بيشرحلك حاجة.
🔴 لو بتشرح حاجة تقنية، استخدم تشبيهات وأمثلة عملية.

استخدم:
- 📌 عنوان للإجابة
- شرح واضح مع أمثلة
- نقاط رئيسية
- روابط أو مراجع إن أمكن"""
    else:
        system = """You are My Bro - an AI expert. Answer questions in English in detail and organized format.

🔴 Your name is My Bro - NEVER say any other name.
🔴 Do not claim to be human or have emotions.
🔴 Be friendly, smart, and respectful - like a knowledgeable friend explaining something.
🔴 NEVER use Markdown AT ALL (no *, **, #, |, ---). Use HTML only:
<b>bold</b> <i>italic</i> <code>code</code> • bullets. Write naturally without weird symbols.
🔴 When explaining technical topics, use analogies and practical examples.

Use:
- 📌 Title for the answer
- Clear explanation with examples
- Key points
- Links or references if possible"""

    # 🔴 إضافة سياق المطور لو المستخدم هو المطور
    if _is_developer(user_id):
        system += _get_developer_context(language)

    response = await call_ai(
        question,
        system_prompt=system,
        task_type=task_type,
        temperature=0.5,
        max_tokens=8192,
        user_id=user_id,  # 🔴 FIX: كان بيتسقط
    )
    return response or ("لم أتمكن من الإجابة. 🤖" if language == "ar" else "I couldn't answer that. 🤖")


async def explain_topic(topic: str, language: str = "ar", user_id: int = None) -> str:
    """
    /learn - شرح تعليمي لموضوع
    """
    if language == "ar":
        prompt = f"""اشرح "{topic}" بشكل تعليمي ومبسط بالعربية.

التنسيق المطلوب:
📚 <b>ما هو {topic}؟</b>
→ تعريف بسيط وواضح

🔑 <b>المفاهيم الأساسية</b>
→ أهم المفاهيم المرتبطة

💡 <b>أمثلة عملية</b>
→ تطبيقات في الواقع

🚀 <b>الاستخدامات</b>
→ كيف يُستخدم اليوم

📖 <b>مصادر للتعلم</b>
→ أين يمكن التعمق أكثر

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط."""
    else:
        prompt = f"""Explain "{topic}" in an educational and simple way in English.

Format:
📚 <b>What is {topic}?</b>
→ Simple clear definition

🔑 <b>Core Concepts</b>
→ Key related concepts

💡 <b>Practical Examples</b>
→ Real-world applications

🚀 <b>Use Cases</b>
→ How it's used today

📖 <b>Learning Resources</b>
→ Where to learn more

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only."""

    # 🔴 إضافة سياق المطور
    dev_ctx = ""
    if _is_developer(user_id):
        dev_ctx = _get_developer_context(language)

    response = await call_ai(
        prompt,
        system_prompt=dev_ctx,
        task_type="chat",
        temperature=0.5,
        max_tokens=8192,
        prefer_arabic=True,
        user_id=user_id,  # 🔴 FIX: كان بيتسقط
    )
    return response or ("لم أتمكن من شرح الموضوع. 🤖" if language == "ar" else "I couldn't explain this topic. 🤖")


async def generate_roadmap(topic: str, language: str = "ar", user_id: int = None) -> str:
    """
    /roadmap - خارطة طريق تعليمية
    """
    from config import ROADMAPS

    topic_lower = topic.lower().strip()

    # البحث في القوالب الجاهزة
    for key, roadmap in ROADMAPS.items():
        if key in topic_lower or topic_lower in key:
            if language == "ar":
                text = f"🗺️ <b>{roadmap['title_ar']}</b>\n\n"
                text += "🟢 <b>مبتدئ</b>\n"
                for i, item in enumerate(roadmap["beginner"], 1):
                    text += f"  {i}. {item}\n"
                text += "\n🟡 <b>متوسط</b>\n"
                for i, item in enumerate(roadmap["intermediate"], 1):
                    text += f"  {i}. {item}\n"
                text += "\n🔴 <b>متقدم</b>\n"
                for i, item in enumerate(roadmap["advanced"], 1):
                    text += f"  {i}. {item}\n"
                return text
            else:
                text = f"🗺️ <b>{roadmap['title_en']}</b>\n\n"
                text += "🟢 <b>Beginner</b>\n"
                for i, item in enumerate(roadmap["beginner"], 1):
                    text += f"  {i}. {item}\n"
                text += "\n🟡 <b>Intermediate</b>\n"
                for i, item in enumerate(roadmap["intermediate"], 1):
                    text += f"  {i}. {item}\n"
                text += "\n🔴 <b>Advanced</b>\n"
                for i, item in enumerate(roadmap["advanced"], 1):
                    text += f"  {i}. {item}\n"
                return text

    # لو مش لقي خارطة جاهزة، يولد واحدة بالـ AI
    if language == "ar":
        prompt = f"""أنشئ خارطة طريق تعليمية لـ "{topic}" بالعربية.

التنسيق:
🗺️ <b>خارطة طريق {topic}</b>

🟢 <b>مبتدئ</b>
1. ...
2. ...
3. ...

🟡 <b>متوسط</b>
1. ...
2. ...
3. ...

🔴 <b>متقدم</b>
1. ...
2. ...
3. ...

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط."""
    else:
        prompt = f"""Create a learning roadmap for "{topic}" in English.

Format:
🗺️ <b>{topic} Roadmap</b>

🟢 <b>Beginner</b>
1. ...
2. ...
3. ...

🟡 <b>Intermediate</b>
1. ...
2. ...
3. ...

🔴 <b>Advanced</b>
1. ...
2. ...
3. ...

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only."""

    response = await call_ai(
        prompt,
        task_type="chat",
        temperature=0.5,
        max_tokens=8192,
        prefer_arabic=True,
        user_id=user_id,  # 🔴 FIX: كان بيتسقط
    )
    return response or ("لم أتمكن من إنشاء خارطة طريق. 🤖" if language == "ar" else "I couldn't generate a roadmap. 🤖")


async def generate_company_report(company_key: str, language: str = "ar", user_id: int = None) -> str:
    """
    /company - تقرير عن شركة
    """
    from config import COMPANY_DATA

    company_key = company_key.lower().strip()
    company = None
    for key, data in COMPANY_DATA.items():
        if key == company_key or company_key in data["keywords"] or company_key in data["name"].lower():
            company = data
            break

    if not company:
        if language == "ar":
            return f"❌ لم أجد شركة باسم '{company_key}'.\n\nالشركات المتاحة: " + "، ".join(COMPANY_DATA.keys())
        else:
            return f"❌ Company '{company_key}' not found.\n\nAvailable: " + ", ".join(COMPANY_DATA.keys())

    # البحث عن أحدث أخبار الشركة
    search_query = f"{company['name']} AI latest news 2025"
    from web_search import search_news_async
    news_results = await search_news_async(search_query, max_results=3)

    news_text = ""
    if news_results:
        news_text = "\n\n📰 <b>أحدث الأخبار</b>\n" if language == "ar" else "\n\n📰 <b>Latest News</b>\n"
        for r in news_results[:3]:
            news_text += f"→ {r['title']}\n"
            if r.get('link'):
                news_text += f"🔗 <a href=\"{r['link']}\">اقرأ</a>\n"

    if language == "ar":
        prompt = f"""أنشئ تقرير ذكاء شركة عن {company['name']} ({company['name_ar']}) بالعربية.

معلومات عن الشركة:
- الوصف: {company['description_ar']}
- المنتجات: {', '.join(company['products'])}

التنسيق:
🏢 <b>تقرير {company['name_ar']}</b>
━━━━━━━━━━━━━━━━━

📋 <b>نبذة عن الشركة</b>
→ وصف مختصر

🚀 <b>المنتجات الرئيسية</b>
→ قائمة بالمنتجات

💡 <b>نقاط القوة</b>
→ أبرز المزايا

⚠️ <b>التحديات</b>
→ التحديات الحالية

🔮 <b>التوقعات</b>
→ ما نتوقعه مستقبلاً

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط."""
    else:
        prompt = f"""Create a company intelligence report for {company['name']} in English.

Company info:
- Description: {company['description']}
- Products: {', '.join(company['products'])}

Format:
🏢 <b>{company['name']} Report</b>
━━━━━━━━━━━━━━━━━

📋 <b>Overview</b>
→ Brief description

🚀 <b>Key Products</b>
→ Product list

💡 <b>Strengths</b>
→ Key advantages

⚠️ <b>Challenges</b>
→ Current challenges

🔮 <b>Outlook</b>
→ Future expectations

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only."""

    response = await call_ai(
        prompt,
        task_type="chat",
        temperature=0.5,
        max_tokens=8192,
        prefer_arabic=True,
        user_id=user_id,  # 🔴 FIX: كان بيتسقط
    )

    if response and news_text:
        response += news_text

    return response or ("لم أتمكن من إنشاء التقرير. 🤖" if language == "ar" else "I couldn't generate the report. 🤖")


# ═══════════════════════════════════════
# Vision - تحليل الصور
# ═══════════════════════════════════════

async def analyze_image(
    image_url: str = None,
    image_base64: str = None,
    language: str = "ar",
    user_message: str = "",
    vision_pro: bool = False,
) -> str:
    """
    تحليل صورة باستخدام نموذج الرؤية
    مع fallback لنموذج chat لو الـ vision فشل
    vision_pro=True يتيح نماذج رؤية أفضل للمشتركين Premium
    """
    manager = get_provider_manager()

    # Vision Pro users get more detailed analysis
    if vision_pro:
        if language == "ar":
            prompt = user_message or "حلل هذه الصورة بتفصيل شامل ودقة عالية. اذكر كل ما تراه فيها من عناصر وألوان ونصوص وأشخاص وتفاصيل دقيقة. لو فيه نصوص اقرأها بدقة. لو فيه بيانات أو أرقام حللها."
            system_text = "أنت My Bro - مساعد ذكي بتحلل الصور بتفصيل شامل ودقة عالية. تكلم بمصري محترم ومتوازن. 🔴🔴🔴 ممنوع استخدام أي لهجة خليجية! ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط. خليك دقيق ووصف كل التفاصيل المهمة بالعمق الكامل."
        else:
            prompt = user_message or "Analyze this image in comprehensive detail with high precision. Mention all elements, colors, text, people, and every important detail. If there's text, read it accurately. If there's data or numbers, analyze them."
            system_text = "You are My Bro - a smart assistant that analyzes images with comprehensive detail and high precision. Be friendly, smart, and respectful. NEVER use Markdown. Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets. Be thorough and describe all important details in full depth."
    else:
        if language == "ar":
            prompt = user_message or "صف هذه الصورة بالتفصيل. اذكر كل ما تراه فيها من عناصر وألوان ونصوص وأشخاص وأي تفاصيل مهمة."
            system_text = "أنت My Bro - مساعد ذكي تحلل الصور بتفصيل ودقة. تكلم بمصري محترم ومتوازن. ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط. خليك دقيق ووصف كل التفاصيل المهمة."
        else:
            prompt = user_message or "Describe this image in detail. Mention all elements, colors, text, people, and any important details."
            system_text = "You are My Bro - a smart assistant that analyzes images with detail and accuracy. Be friendly, smart, and respectful. NEVER use Markdown. Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets. Be thorough and describe all important details."

    # محاولة 1: تحليل بالـ Vision models (مع cooldown bypass كـ fallback)
    try:
        response = await manager.analyze_image_async(
            text_prompt=prompt,
            image_url=image_url,
            image_base64=image_base64,
            temperature=0.5,
            max_tokens=8192,
        )

        if response:
            from formatters import clean_ai_response
            response = clean_ai_response(response)
            return response
    except Exception as e:
        logger.warning(f"Vision model failed: {e}, trying fallback...")

    # محاولة 2: لو كان image_url، حمّله كـ base64 وجرب تاني
    # (أحياناً الـ URL بيفشل بس الـ base64 بيشتغل)
    if image_url and not image_base64:
        try:
            import requests as req
            img_response = req.get(image_url, timeout=15)
            if img_response.status_code == 200:
                import base64
                image_base64 = base64.b64encode(img_response.content).decode('utf-8')
                
                response = await manager.analyze_image_async(
                    text_prompt=prompt,
                    image_base64=image_base64,
                    temperature=0.5,
                    max_tokens=8192,
                )
                
                if response:
                    from formatters import clean_ai_response
                    response = clean_ai_response(response)
                    return response
        except Exception as e2:
            logger.warning(f"Base64 fallback also failed: {e2}")

    # محاولة 3: Fallback أخير - النموذج العادي
    # مش بنقول "مش قادر أشوف الصورة" - بنحاول نرد بشكل لطيف
    logger.warning("All vision attempts failed, using chat model as last resort")
    if language == "ar":
        fallback_prompt = f"""المستخدم بعت صورة{' وعايز يعرف: ' + user_message if user_message else ''}. 

للأسف مش قادر أشوف الصورة دلوقتي بسبب مشكلة تقنية مؤقتة. قول للمستخدم بطريقة ودودة:
1. إنك مش قادر تشوف الصورة دلوقتي
2. إنه ممكن يوصفلك اللي فيها وهتساعده
3. إنه يجرب يبعتها تاني بعد شوية
خليك لطيف ومتعاون — متصرفش كأنك بوت رسمي."""
    else:
        fallback_prompt = f"""The user sent an image{' and wants to know: ' + user_message if user_message else ''}.

Unfortunately I can't see the image right now due to a temporary technical issue. Tell the user in a friendly way:
1. That you can't see the image right now
2. That they can describe what's in it and you'll help
3. That they can try sending it again shortly
Be kind and helpful."""

    response = await call_ai(
        fallback_prompt,
        system_prompt=system_text,
        task_type="chat",
        temperature=0.7,
        max_tokens=500,
        user_id=user_id,  # 🔴 FIX: كان بيتسقط
    )
    
    if response:
        from formatters import clean_ai_response
        response = clean_ai_response(response)
        return response

    return "⚠️ مش قادر أحلل الصورة دلوقتي. جرب تاني أو صفلي الصورة وهحاول أساعدك." if language == "ar" else "⚠️ I can't analyze the image right now. Please try again or describe it and I'll try to help."
