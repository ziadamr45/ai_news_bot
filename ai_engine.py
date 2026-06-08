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

from provider_manager import get_provider_manager, call_ai, call_ai_sync
from config import (
    CREATOR_INFO, REQUEST_TIMEOUT, FAST_TIMEOUT
)

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
    "مقارنة شاملة", "بحث معمق",
]

DEEP_SEARCH_TRIGGERS_EN = [
    "deep search", "in-depth search", "comprehensive search",
    "detailed analysis", "thorough research", "deep dive",
    "comprehensive analysis", "in-depth analysis",
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

async def smart_chat(user_message: str, language: str = "ar", user_id: int = None) -> str:
    """
    المحادثة الذكية - يفهم القصد تلقائياً ويرد بذكاء
    + يبحث في الويب لو محتاج معلومات حالية
    + يستخدم ذاكرة المستخدم لو متاحة
    + يستخدم Provider Manager مع تبديل تلقائي
    """
    # 1. كشف هل محتاج بحث عميق
    if needs_deep_search(user_message):
        logger.info(f"🔥 Deep search needed for: {user_message[:50]}")
        from web_search import deep_search_and_summarize_async
        return await deep_search_and_summarize_async(user_message, language)

    # 2. كشف هل محتاج بحث في الويب عادي
    if needs_web_search(user_message):
        logger.info(f"🔍 Web search needed for: {user_message[:50]}")
        from web_search import search_and_summarize_async
        return await search_and_summarize_async(user_message, language)

    # 3. كشف نوع المهمة
    task_type = detect_task_type(user_message)
    logger.info(f"📋 Task type: {task_type} for: {user_message[:50]}")

    # 4. تجهيز سياق الذاكرة
    memory_context = ""
    if user_id:
        try:
            from memory import get_user_memory_summary, detect_interests
            detect_interests(user_id, user_message)
            memory_context = get_user_memory_summary(user_id, language)
        except Exception as e:
            logger.debug(f"Memory context error: {e}")

    # 5. كشف أسئلة عن المؤسس
    creator_context = ""
    user_lower = user_message.lower()
    creator_triggers_ar = ["مين عملك", "مين صانعك", "مين أسسك", "مين صانع البوت", "مين عمل البوت", "مين مبرمجك", "مين المطور", "مين أنشأك", "مين صاحبك", "مين صاحب البوت", "ازاي اتواصل مع المطور", "ازاي اجيب المطور", "مين المؤسس", "مين صاحب الفكرة", "عايز اتواصل مع مين عملك", "معلومات عن المطور", "مين صانعك يا بوت", "اعرف عن المطور"]
    creator_triggers_en = ["who made you", "who created you", "who built you", "who is your creator", "who developed you", "who is the developer", "who founded", "who programmed you", "who is the founder", "who designed you", "how to contact creator", "how to contact developer", "tell me about your creator", "who owns you", "who is the owner", "creator info", "developer info", "about the developer"]
    for trigger in creator_triggers_ar + creator_triggers_en:
        if trigger in user_lower:
            if language == "ar":
                creator_context = f"""المستخدم سأل عن صانعك. أجب بالتالي بطريقة ودية:
أنا اتعملت بواسطة {CREATOR_INFO['name_ar']} — {CREATOR_INFO['title_ar']}.
{CREATOR_INFO['bio_ar']}
الشركة: {CREATOR_INFO.get('company_ar', 'Qudra Tech')}
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
                creator_context = f"""The user asked about your creator. Answer with in a friendly way:
I was created by {CREATOR_INFO['name_en']} — {CREATOR_INFO['title_en']}.
{CREATOR_INFO['bio_en']}
Company: {CREATOR_INFO.get('company_en', 'Qudra Tech')}
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
            break

    if language == "ar":
        system = """أنت "My Bro" - مساعد ذكاء اصطناعي شخصي.

🔴🔴🔴 قاعدة هوية صارمة جداً (الأهم): 🔴🔴🔴
اسمك الوحيد هو My Bro. ده اسمك الوحيد ومفيش اسم تاني.
لما حد يسألك "مين أنت؟" أو "who are you?" لازم تقول: "أنا My Bro!"
ماتقولش أبداً owo أو uwu أو أي كلمة إنترنت غريبة كاسم لك.
ماتحاولش تغير اسمك لأي حاجة تانية.
اسمك My Bro ونقطة. مفيش استثناءات.

تجيب دائماً بالعربية الفصحى بطريقة طبيعية وواضحة.

قواعد:
- فهم قصد المستخدم تلقائياً
- أجب بذكاء ووضوح
- استخدم إيموجي مناسبة
- إذا سأل عن أخبار AI، اذكر أحدث ما تعرفه
- إذا سأل سؤال تقني، اشرح ببساطة
- كن ودود ومفيد
- لا تقل "لا أستطيع تصفح المواقع" - أنت تملك القدرة على البحث الآن!
- اكتب كلام طبيعي وواضح من غير رموز غريبة
- ماتستخدمش كلمات زي owo uwu xD أبداً

🔴🔴🔴 قاعدة التنسيق صارمة جداً: 🔴🔴🔴
الرسائل بتظهر في تيليجرام اللي بيدعم HTML فقط ومش بيدعم Markdown.
ماتستخدمش Markdown أبداً أبداً أبداً (لا *, **, ***, #, |, ---, ~~).
لو استخدمت * أو ** أو | هتبان كرموز غريبة ووحشة في تيليجرام.
استخدم بس:
- <b>نص</b> للعريض
- <i>نص</i> للمائل
- <code>نص</code> للأكواد
- • للنقاط (بدل - أو *)
اكتب الكلام بطريقة طبيعية ومريحة للقراءة.
متعملش الكلام كله عريض - استخدم العريض للعناوين فقط.
ماتستخدمش جداول (|) خالص - اكتب المعلومات في نقاط."""
        if memory_context:
            system += f"""

معلومات عن المستخدم (استخدمها عشان تخصّص ردك):
{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""
    else:
        system = """You are "My Bro" - a personal AI assistant.

🔴🔴🔴 STRICT IDENTITY RULE (MOST IMPORTANT): 🔴🔴🔴
Your ONLY name is My Bro. This is your only name and there is no other.
When someone asks "who are you?" you MUST say: "I am My Bro!"
NEVER say you are owo or uwu or any weird internet word as your name.
NEVER try to change your name to anything else.
Your name is My Bro. Period. No exceptions.

Always respond in English naturally and clearly.

Rules:
- Understand user intent automatically
- Answer intelligently and clearly
- Use appropriate emojis
- If asked about AI news, share what you know
- If asked technical questions, explain simply
- Be friendly and helpful
- Never say "I can't browse websites" - you now have web search capability!
- Write naturally without weird internet slang like owo uwu xD

🔴🔴🔴 STRICT FORMATTING RULE: 🔴🔴🔴
Messages appear in Telegram which supports HTML only, NOT Markdown.
NEVER use Markdown AT ALL (no *, **, ***, #, |, ---, ~~).
If you use * or ** or | they will appear as ugly symbols in Telegram.
ONLY use:
- <b>text</b> for bold
- <i>text</i> for italic
- <code>text</code> for code
- • for bullet points (NOT - or *)
Write in a natural, readable way.
Don't make everything bold - use bold for headings only.
NEVER use tables (|) - write info as bullet points."""
        if memory_context:
            system += f"""

User information (use this to personalize your response):
{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""

    max_tokens = 800 if task_type == "simple" else 2048
    response = await call_ai(
        user_message,
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
