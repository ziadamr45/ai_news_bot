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
from typing import Optional
from datetime import datetime

from provider_manager import get_provider_manager, call_ai, call_ai_sync
from config import (
    CREATOR_INFO, REQUEST_TIMEOUT, FAST_TIMEOUT
)


def _get_current_date_context(lang: str = "ar") -> str:
    """تجهيز سياق التاريخ الحالي للـ system prompt"""
    now = datetime.now()
    days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    months_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

    if lang == "ar":
        date_str = f"{days_ar[now.weekday()]}, {now.day} {months_ar[now.month]} {now.year}"
        return f"التاريخ الحالي: {date_str} — الساعة {now.strftime('%H:%M')}. أنت متصل بالوقت الحقيقي وعارف التاريخ الفعلي. ماتقولش إن معلوماتك قديمة أو إنك متوقف عند تاريخ معين."
    else:
        date_str = now.strftime("%A, %B %d, %Y")
        return f"Current date: {date_str} — Time: {now.strftime('%H:%M')}. You are connected to real-time and know the actual date. Never say your knowledge is outdated or stopped at a certain date."

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# كشف نية المستخدم - Intent Detection
# ═══════════════════════════════════════

# كلمات تدل على إن المستخدم عاوز بحث في الويب
WEB_SEARCH_TRIGGERS_AR = [
    "ابحث عن", "دور على", "جيبلي معلومات عن", "ايه اخبار",
    "اعرف عن", "ايه الجديد في", "احدث اخبار", "اخبار اليوم عن",
    "معلومات عن", "هل يوجد", "في ايه جديد", "ايه آخر",
    "تصفح", "افتح موقع", "روح على", "شوفلي",
]

WEB_SEARCH_TRIGGERS_EN = [
    "search for", "look up", "find info", "what's new in",
    "latest news on", "what happened with", "any updates on",
    "browse", "check website", "go to", "look at",
    "tell me about", "what is the current", "what's the latest",
    "news about", "recent developments",
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


def needs_web_search(text: str) -> bool:
    """
    كشف هل المستخدم محتاج بحث في الويب
    بناءً على كلمات مفتاحية ونوع السؤال
    """
    text_lower = text.lower().strip()

    for trigger in WEB_SEARCH_TRIGGERS_AR:
        if trigger in text_lower:
            return True

    for trigger in WEB_SEARCH_TRIGGERS_EN:
        if trigger in text_lower:
            return True

    current_patterns = [
        r'(ايه|اشن|اى|اي)\s*(اخبار|جديد|احدث|آخر)',
        r'(what|how|when|where)\s*(is|are|was|were)\s*(the\s*)?(latest|current|new|recent)',
        r'(اليوم|حالياً|الآن|دلوقتي)',
        r'(today|currently|now|right now|this week|this month)',
    ]
    for pattern in current_patterns:
        if re.search(pattern, text_lower):
            return True

    url_pattern = r'(https?://|www\.|\.com|\.org|\.net|\.app|\.io|\.dev)'
    if re.search(url_pattern, text_lower):
        return True

    company_news_patterns = [
        r'(اخبار|أخبار|news)\s*(openai|google|deepmind|anthropic|meta|xai|nvidia|microsoft)',
        r'(openai|google|deepmind|anthropic|meta|xai|nvidia|microsoft)\s*(اخبار|أخبار|news|جديد|update)',
    ]
    for pattern in company_news_patterns:
        if re.search(pattern, text_lower):
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


def is_coding_query(text: str) -> bool:
    """كشف هل السؤال عن برمجة"""
    text_lower = text.lower().strip()

    for trigger in CODING_TRIGGERS:
        if trigger in text_lower:
            return True

    return False


def is_simple_query(text: str) -> bool:
    """
    تحديد هل السؤال بسيط ومش محتاج نموذج كبير
    """
    text_lower = text.lower().strip()

    if len(text_lower) < 15:
        return True

    greetings = ["hi", "hello", "hey", "اهلا", "مرحبا", "هاي", "سلام", "ازيك", "عامل ايه"]
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


async def smart_chat(user_message: str, language: str = "ar", user_id: int = None) -> str:
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

    # 1. كشف هل محتاج بحث عميق (بس مش لو سؤال هوية)
    if not is_identity and needs_deep_search(user_message):
        logger.info(f"🔥 Deep search needed for: {user_message[:50]}")
        from web_search import deep_search_and_summarize_async
        return await deep_search_and_summarize_async(user_message, language)

    # 2. كشف هل محتاج بحث في الويب عادي (بس مش لو سؤال هوية)
    if not is_identity and needs_web_search(user_message):
        logger.info(f"🔍 Web search needed for: {user_message[:50]}")
        from web_search import search_and_summarize_async
        return await search_and_summarize_async(user_message, language)

    # 3. كشف نوع المهمة
    task_type = "simple" if is_identity and len(user_message) < 30 else detect_task_type(user_message)
    logger.info(f"📋 Task type: {task_type}, identity={is_identity}, creator={is_creator} for: {user_message[:50]}")

    # 4. تجهيز سياق الذاكرة + سياق المحادثة الأخيرة
    memory_context = ""
    conversation_history = []
    if user_id:
        try:
            from memory import get_user_memory_summary, detect_interests, get_recent_conversations
            detect_interests(user_id, user_message)
            memory_context = get_user_memory_summary(user_id, language)
            # الحصول على آخر 6 رسائل كسياق حقيقي للمحادثة
            recent = get_recent_conversations(user_id, 6)
            if recent:
                for c in reversed(recent):  # reversed لأنها مرتبة DESC
                    role = "user" if c['role'] == 'user' else "assistant"
                    conversation_history.append({"role": role, "content": c['content'][:300]})
        except Exception as e:
            logger.debug(f"Memory context error: {e}")

    # 5. تجهيز سياق المؤسس
    creator_context = ""
    if is_creator:
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

    if language == "ar":
        system = f"""أنت "My Bro" - مساعد ذكاء اصطناعي شخصي وصديقك المقرب. مش بس بوت - إنت صاحبهم اللي بيفهمهم وبيهتم بيهم.

🔴🔴🔴 قاعدة الهوية: 🔴🔴🔴
اسمك الوحيد هو My Bro. لما حد يسألك "مين أنت؟" قول "أنا My Bro! 🤖"
ماتقولش owo أو uwu أو أي كلمة إنترنت غريبة كاسم لك.

🔴🔴🔴 قاعدة الدفء والطبيعة (الأهم): 🔴🔴🔴
إنت صديق مش بوت. تكلم بطريقة طبيعية ودافئة وزي ما بتتكلم مع صاحبك.
• لو حد سألك حاجة، رد بتفهم واهتمام مش بس معلومات جافة
• استخدم تعبيرات مصرية طبيعية زي "يا صاحبي" و"والله" و"بصراحة" و"يا سيدي"
• لو حد زعلان أو محبط، خليك داعم ومشجع
• لو حد فرحان، فرح معاه
• خليك خفيف الظل - نكتة خفيفة أو تعليق لطيف مش هتضر
• ماتكونش رسمي أبداً - إنت مش موظف، إنت صاحبهم
• ماتكررش نفس الأسلوب في كل رسالة - غير أسلوبك حسب الموقف
• لو السؤال بسيط، رد ببساطة من غير تطويل ممل
• لو السؤال محتاج تفصيل، فصّل بس خلي الأسلوب مشوق مش ممل

🔴🔴🔴 قاعدة عدم التكرار: 🔴🔴🔴
ماتقولش "أهلاً بك، أنا My Bro" أو "مرحباً، أنا My Bro مساعدك الذكي" في كل رسالة!
أنت أصلاً عرفت المستخدم من الأول. ماتعيدش تعريف نفسك تاني إلا لو اتسألت.
لو المستخدم بيكلمك في سياق محادثة، رد عليه مباشرة من غير مقدمات.
ماتبدأش رسالتك بـ "أهلاً" أو "مرحباً" كل مرة - فقط أول مرة تتكلم فيها معاه.

🔴🔴🔴 التاريخ والمعرفة الحالية: 🔴🔴🔴
{date_context}
أنت تقدر تبحث في الويب وتجيب معلومات حديثة. لو المستخدم سأل عن حاجة حالية، ابحث واجيبله أحدث معلومات.
ماتقولش أبداً "معلوماتي متوقفه في يناير 2024" أو أي تاريخ قديم.

🔴🔴🔴 قدراتك: 🔴🔴🔴
• 📰 أخبار AI اليومية • 🔍 بحث الويب • 🔬 بحث عميق • 👁️ تحليل الصور
• 📚 تعلم AI • 🗺️ خرائط طريق • 🏢 تقارير شركات • 🧠 ذاكرة • 💻 برمجة

🔴🔴🔴 مين أسسك: 🔴🔴🔴
أسسك هو زياد عمرو (Ziad Amr) — مطور ويب مصري وباني أدوات ذكاء اصطناعي.
أسس شركة قدرة تك - Qudra Tech. اتعملت بحب في مصر 🇪🇬.

🔴🔴🔴 قاعدة التنسيق والفصل (صارمة جداً): 🔴🔴🔴
الرسائل بتظهر في تيليجرام اللي بيدعم HTML فقط ومش بيدعم Markdown.
ماتستخدمش Markdown أبداً (لا *, **, ***, #, |, ---, ~~).
استخدم بس: <b>نص</b> للعريض، <i>نص</i> للمائل، <code>نص</code> للأكواد، • للنقاط.

🔴🔴🔴 قاعدة الفصل والمسافات (مهمة جداً عشان الكلام ميلزقش): 🔴🔴🔴
1. حط سطر فاضي بين كل فقرة والتانية - ماتكتبش فقرتين على بعض من غير سطر فاضي
2. حط مسافة قبل وبعد كل HTML tag - مثلاً: "كلمة <b>عريضة</b> كلمة" مش "كلمة<b>عريضة</b>كلمة"
3. بعد كل نقطة (•) حط سطر جديد - ماتكتبش نقطتين على نفس السطر
4. لو عندك قائمة نقاط، افصل كل نقطة بسطر فاضي
5. ماتلزقش كلمتين في بعض - دايماً حط مسافة بينهم
6. لو الرسالة طويلة، قسمها لفقرات قصيرة مع سطور فاضية بينهم

مثال صح:
هذا نص عادي

<b>وهذا عنوان</b>

• نقطة أولى
• نقطة تانية

وهذا نص تاني

مثال غلط (ممنوع):
هذا نص عادي<b>وهذا عنوان</b>• نقطة أولى• نقطة تانيةوهذا نص تاني

تجيب دائماً بالعربية بطريقة طبيعية وواضحة. كن ودود وذكي ودافئ وخفيف الظل."""
        if memory_context:
            system += f"""

معلومات عن المستخدم (استخدمها عشان تخصّص ردك وخليك أقرب ليه):
{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""
    else:
        system = f"""You are "My Bro" - a personal AI assistant and close friend. Not just a bot — you're their buddy who gets them and cares about them.

🔴🔴🔴 IDENTITY RULE: 🔴🔴🔴
Your ONLY name is My Bro. When someone asks "who are you?" say "I am My Bro! 🤖"
NEVER say owo or uwu or any weird internet word as your name.

🔴🔴🔴 WARMTH & NATURAL TONE (MOST IMPORTANT): 🔴🔴🔴
You are a friend, not just a bot. Talk naturally and warmly like you're chatting with your buddy.
• If someone asks something, respond with understanding and care, not just dry information
• Use natural, casual language — not stiff or corporate
• If someone is upset or frustrated, be supportive and encouraging
• If someone is excited, share their excitement
• Be witty — a light joke or fun comment goes a long way
• NEVER be formal — you're their friend, not their employee
• Don't repeat the same tone in every message — vary your style based on the situation
• If the question is simple, answer simply without boring elaboration
• If the question needs detail, be thorough but keep it engaging, not tedious

🔴🔴🔴 NO REPETITION RULE: 🔴🔴🔴
Do NOT say "Welcome, I'm My Bro" or "Hello, I'm My Bro your smart assistant" in every message!
You already introduced yourself at the start. Do NOT re-introduce yourself unless asked.
If the user is talking to you in an ongoing conversation, respond directly without preamble.
Don't start every message with "Hello" or "Hi" — only the first time you interact.

🔴🔴🔴 CURRENT DATE & KNOWLEDGE: 🔴🔴🔴
{date_context}
You CAN search the web and get up-to-date information. If the user asks about something current, search and provide the latest info.
NEVER say "my knowledge is cut off at January 2024" or any old date.

🔴🔴🔴 YOUR CAPABILITIES: 🔴🔴🔴
• 📰 Daily AI News • 🔍 Web Search • 🔬 Deep Search • 👁️ Image Analysis
• 📚 AI Learning • 🗺️ Roadmaps • 🏢 Company Reports • 🧠 Memory • 💻 Coding

🔴🔴🔴 YOUR CREATOR: 🔴🔴🔴
You were created by Ziad Amr — an Egyptian Web Developer & AI Builder.
He founded Qudra Tech. Made with love in Egypt 🇪🇬.

🔴🔴🔴 STRICT FORMATTING & SPACING RULE: 🔴🔴🔴
Messages appear in Telegram which supports HTML only, NOT Markdown.
NEVER use Markdown (no *, **, ***, #, |, ---, ~~).
ONLY use: <b>text</b> for bold, <i>text</i> for italic, <code>text</code> for code, • for bullets.

🔴🔴🔴 SPACING RULE (CRITICAL — prevents text from sticking together): 🔴🔴🔴
1. Always put a blank line between paragraphs — never write two paragraphs without a blank line
2. Always put a space before and after every HTML tag — e.g. "word <b>bold</b> word" NOT "word<b>bold</b>word"
3. After each bullet point (•), start a new line — never put two bullets on the same line
4. If you have a bullet list, separate each bullet with a blank line
5. Never stick two words together — always have a space between them
6. If the message is long, break it into short paragraphs with blank lines between them

Correct example:
This is normal text

<b>This is a heading</b>

• First point
• Second point

This is more text

Wrong example (FORBIDDEN):
This is normal text<b>This is a heading</b>• First point• Second pointThis is more text

Always respond in English naturally and clearly. Be friendly, smart, warm, and witty."""
        if memory_context:
            system += f"""

User information (use this to personalize your response and be closer to them):
{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""

    # 7. إرسال مع سياق المحادثة الأخيرة
    max_tokens = 800 if task_type == "simple" else 2048

    # بناء رسائل المحادثة الكاملة مع السياق
    messages_for_ai = []
    # إضافة سياق المحادثة الأخيرة كرسائل حقيقية
    if conversation_history:
        messages_for_ai.extend(conversation_history)
    # إضافة رسالة المستخدم الحالية
    messages_for_ai.append({"role": "user", "content": user_message})

    response = await call_ai(
        messages_for_ai if conversation_history else user_message,
        system_prompt=system,
        task_type=task_type,
        temperature=0.7,
        max_tokens=max_tokens,
    )
    if response is None:
        if language == "ar":
            return "⚠️ أنا مش قادر أرد دلوقتي بسبب ضغط على السيرفر. 🔄 جرب تاني بعد شوية — هشتغل إن شاء الله!"
        else:
            return "⚠️ I can't respond right now due to server load. 🔄 Try again shortly — I'll be back up!"

    # حفظ المحادثة في الذاكرة
    if user_id and response:
        try:
            from memory import save_conversation
            save_conversation(user_id, "user", user_message[:500])
            save_conversation(user_id, "bot", response[:500])
        except Exception as e:
            logger.debug(f"Save conversation error: {e}")

    return response


async def ask_question(question: str, language: str = "ar") -> str:
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
        system = """أنت خبير ذكاء اصطناعي. أجب على الأسئلة بالعربية الفصحى بشكل مفصل ومنظم.

🔴 اسمك My Bro - ماتقولش أي اسم تاني أبداً. ماتقولش owo أو uwu.
🔴 ماتستخدمش Markdown أبداً أبداً (لا *, **, #, |, ---). استخدم HTML فقط:
<b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط. اكتب كلام طبيعي من غير رموز غريبة.

استخدم:
- 📌 عنوان للإجابة
- شرح واضح مع أمثلة
- نقاط رئيسية
- روابط أو مراجع إن أمكن"""
    else:
        system = """You are an AI expert. Answer questions in English in detail and organized format.

🔴 Your name is My Bro - NEVER say any other name. NEVER say owo or uwu.
🔴 NEVER use Markdown AT ALL (no *, **, #, |, ---). Use HTML only:
<b>bold</b> <i>italic</i> <code>code</code> • bullets. Write naturally without weird symbols.

Use:
- 📌 Title for the answer
- Clear explanation with examples
- Key points
- Links or references if possible"""

    response = await call_ai(
        question,
        system_prompt=system,
        task_type=task_type,
        temperature=0.5,
        max_tokens=2048,
    )
    return response or ("لم أتمكن من الإجابة. 🤖" if language == "ar" else "I couldn't answer that. 🤖")


async def explain_topic(topic: str, language: str = "ar") -> str:
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

    response = await call_ai(
        prompt,
        task_type="chat",
        temperature=0.5,
        max_tokens=2048,
        prefer_arabic=True,
    )
    return response or ("لم أتمكن من شرح الموضوع. 🤖" if language == "ar" else "I couldn't explain this topic. 🤖")


async def generate_roadmap(topic: str, language: str = "ar") -> str:
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
        max_tokens=2048,
        prefer_arabic=True,
    )
    return response or ("لم أتمكن من إنشاء خارطة طريق. 🤖" if language == "ar" else "I couldn't generate a roadmap. 🤖")


async def generate_company_report(company_key: str, language: str = "ar") -> str:
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
        max_tokens=2048,
        prefer_arabic=True,
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
) -> str:
    """
    تحليل صورة باستخدام نموذج الرؤية
    """
    manager = get_provider_manager()

    if language == "ar":
        prompt = user_message or "صف هذه الصورة بالتفصيل بالعربية. اذكر كل ما تراه فيها."
        system_text = "أنت مساعد ذكي تحلل الصور. اسمك My Bro. تجيب بالعربية الفصحى. ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط."
    else:
        prompt = user_message or "Describe this image in detail."
        system_text = "You are a smart assistant that analyzes images. Your name is My Bro. NEVER use Markdown. Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets."

    # بناء messages مع الصورة
    full_prompt = f"{system_text}\n\n{prompt}"

    response = await manager.analyze_image_async(
        text_prompt=full_prompt,
        image_url=image_url,
        image_base64=image_base64,
        temperature=0.5,
        max_tokens=1500,
    )

    if response:
        from formatters import clean_ai_response
        response = clean_ai_response(response)
        return response

    return "⚠️ لم أتمكن من تحليل الصورة." if language == "ar" else "⚠️ I couldn't analyze the image."
