"""
محرك الذكاء الاصطناعي - AI Engine
يتعامل مع OpenRouter API لجميع وظائف الذكاء الاصطناعي
+ دعم البحث في الويب + كشف النية تلقائياً
+ دعم المكالمات غير المتزامنة (async) عشان ميتعطلش البوت
"""

import asyncio
import logging
import re
from typing import Optional

import requests

from config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    OPENROUTER_FALLBACK_MODELS, FAST_MODEL, MAX_RETRIES, RETRY_DELAY,
    REQUEST_TIMEOUT, FAST_TIMEOUT
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


# ═══════════════════════════════════════
# استدعاء AI - AI API Calls
# ═══════════════════════════════════════

def _call_ai_sync(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    prefer_arabic: bool = False,
    fast: bool = False,
) -> Optional[str]:
    """
    استدعاء OpenRouter API (متزامن - يتم تشغيله في thread منفصل)
    """
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set")
        return None

    if prefer_arabic and not system_prompt:
        system_prompt = "أنت مساعد ذكي تجيب بالعربية الفصحى دائماً. استخدم تنسيق جميل مع إيموجي."

    url = f"{OPENROUTER_BASE_URL}/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ziadamr45/ai-news-bot",
        "X-Title": "My Bro AI Bot",
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # اختيار الموديلات حسب السرعة
    if fast and FAST_MODEL:
        models_to_try = [FAST_MODEL] + [OPENROUTER_MODEL] + OPENROUTER_FALLBACK_MODELS
    else:
        models_to_try = [OPENROUTER_MODEL] + OPENROUTER_FALLBACK_MODELS

    timeout = FAST_TIMEOUT if fast else REQUEST_TIMEOUT
    max_retries = 1 if fast else MAX_RETRIES

    payload = {
        "model": models_to_try[0],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    for attempt in range(max_retries):
        for model in models_to_try:
            payload["model"] = model
            try:
                logger.info(f"Calling AI: model={model}, fast={fast}, attempt={attempt+1}")
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                response.raise_for_status()

                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0].get("message", {}).get("content", "")
                    if content:
                        logger.info(f"AI response from {model} (attempt {attempt+1}, {len(content)} chars)")
                        return content

                if "error" in data:
                    error_msg = data.get("error", {})
                    if isinstance(error_msg, dict):
                        error_msg = error_msg.get("message", str(error_msg))
                    logger.warning(f"API error for {model}: {error_msg}")
                    continue

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout ({timeout}s) for model {model}")
            except requests.exceptions.RequestException as e:
                if "403" in str(e) or "401" in str(e):
                    logger.warning(f"Auth/region error for {model}, trying next")
                    continue
                logger.warning(f"Request error for {model}: {str(e)[:100]}")
            except Exception as e:
                logger.warning(f"Error for {model}: {str(e)[:100]}")

        if attempt < max_retries - 1:
            import time
            time.sleep(RETRY_DELAY)

    logger.error("All AI model attempts failed")
    return None


async def call_ai(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    prefer_arabic: bool = False,
    fast: bool = False,
) -> Optional[str]:
    """
    استدعاء OpenRouter API (غير متزامن - لا يحجب event loop)
    يتم تشغيل الاستدعاء المتزامن في thread منفصل
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _call_ai_sync(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            prefer_arabic=prefer_arabic,
            fast=fast,
        )
    )
    return result


# ═══════════════════════════════════════
# المحادثة الذكية - Smart Chat
# ═══════════════════════════════════════

async def smart_chat(user_message: str, language: str = "ar", user_id: int = None) -> str:
    """
    المحادثة الذكية - يفهم القصد تلقائياً ويرد بذكاء
    + يبحث في الويب لو محتاج معلومات حالية
    + يستخدم ذاكرة المستخدم لو متاحة
    """
    # 1. كشف هل محتاج بحث في الويب
    if needs_web_search(user_message):
        logger.info(f"Web search needed for: {user_message[:50]}")
        from web_search import search_and_summarize_async
        return await search_and_summarize_async(user_message, language)

    # 2. كشف هل سؤال بسيط
    fast = is_simple_query(user_message)

    # 3. تجهيز سياق الذاكرة
    memory_context = ""
    if user_id:
        try:
            from memory import get_user_memory_summary, detect_interests
            detect_interests(user_id, user_message)
            memory_context = get_user_memory_summary(user_id, language)
        except Exception as e:
            logger.debug(f"Memory context error: {e}")

    # 4. كشف أسئلة عن المؤسس
    creator_context = ""
    from config import CREATOR_INFO
    user_lower = user_message.lower()
    creator_triggers_ar = ["مين عملك", "مين صانعك", "مين أسسك", "مين صانع البوت", "مين عمل البوت", "مين مبرمجك", "مين المطور", "مين أنشأك", "مين صاحبك"]
    creator_triggers_en = ["who made you", "who created you", "who built you", "who is your creator", "who developed you", "who is the developer", "who founded", "who programmed you"]
    for trigger in creator_triggers_ar + creator_triggers_en:
        if trigger in user_lower:
            if language == "ar":
                creator_context = f"""المستخدم سأل عن صانعك. أجب بالتالي:
أنا اتعملت بواسطة {CREATOR_INFO['name_ar']} — {CREATOR_INFO['title_ar']}.
{CREATOR_INFO['bio_ar']}
ممكن تتواصل معاه:
- الموقع: {CREATOR_INFO['website']}
- GitHub: {CREATOR_INFO['github']}
- LinkedIn: {CREATOR_INFO['linkedin']}
- Telegram: {CREATOR_INFO['telegram']}
- X: {CREATOR_INFO['twitter']}
اتعمل بحب في مصر 🇪🇬"""
            else:
                creator_context = f"""The user asked about your creator. Answer with:
I was created by {CREATOR_INFO['name_en']} — {CREATOR_INFO['title_en']}.
{CREATOR_INFO['bio_en']}
You can reach him at:
- Website: {CREATOR_INFO['website']}
- GitHub: {CREATOR_INFO['github']}
- LinkedIn: {CREATOR_INFO['linkedin']}
- Telegram: {CREATOR_INFO['telegram']}
- X: {CREATOR_INFO['twitter']}
Made with love in Egypt 🇪🇬"""
            break

    if language == "ar":
        system = """أنت "My Bro" - مساعد ذكاء اصطناعي شخصي. تجيب دائماً بالعربية الفصحى.

قواعد:
- فهم قصد المستخدم تلقائياً
- أجب بذكاء ووضوح
- استخدم إيموجي مناسبة
- استخدم تنسيق جميل (عناوين، نقاط، فواصل)
- إذا سأل عن أخبار AI، اذكر أحدث ما تعرفه
- إذا سأل سؤال تقني، اشرح ببساطة
- كن ودود ومفيد
- لا تقل "لا أستطيع تصفح المواقع" - أنت تملك القدرة على البحث الآن!"""
        if memory_context:
            system += f"""

معلومات عن المستخدم (استخدمها عشان تخصّص ردك):
{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""
    else:
        system = """You are "My Bro" - a personal AI assistant. Always respond in English.

Rules:
- Understand user intent automatically
- Answer intelligently and clearly
- Use appropriate emojis
- Use beautiful formatting (headings, bullets, separators)
- If asked about AI news, share what you know
- If asked technical questions, explain simply
- Be friendly and helpful
- Never say "I can't browse websites" - you now have web search capability!"""
        if memory_context:
            system += f"""

User information (use this to personalize your response):
{memory_context}"""
        if creator_context:
            system += f"""

{creator_context}"""

    max_tokens = 800 if fast else 2048
    response = await call_ai(user_message, system_prompt=system, temperature=0.7, max_tokens=max_tokens, fast=fast)
    return response or ("عذراً، لم أتمكن من معالجة طلبك. حاول مرة أخرى. 🤖" if language == "ar" else "Sorry, I couldn't process your request. Please try again. 🤖")


async def ask_question(question: str, language: str = "ar") -> str:
    """
    /ask - سؤال مباشر مع إجابة مفصلة
    """
    if needs_web_search(question):
        from web_search import search_and_summarize_async
        return await search_and_summarize_async(question, language)

    if language == "ar":
        system = """أنت خبير ذكاء اصطناعي. أجب على الأسئلة بالعربية الفصحى بشكل مفصل ومنظم.
استخدم:
- 📌 عنوان للإجابة
- شرح واضح مع أمثلة
- نقاط رئيسية
- روابط أو مراجع إن أمكن"""
    else:
        system = """You are an AI expert. Answer questions in English in detail and organized format.
Use:
- 📌 Title for the answer
- Clear explanation with examples
- Key points
- Links or references if possible"""

    response = await call_ai(question, system_prompt=system, temperature=0.5, max_tokens=2048)
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
→ أين يمكن التعمق أكثر"""
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
→ Where to learn more"""

    response = await call_ai(prompt, temperature=0.5, max_tokens=2048, prefer_arabic=True)
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
3. ..."""
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
3. ..."""

    response = await call_ai(prompt, temperature=0.5, max_tokens=2048, prefer_arabic=True)
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

    # البحث عن أحدث أخبار الشركة (بشكل غير متزامن)
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
→ ما نتوقعه مستقبلاً"""
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
→ Future expectations"""

    response = await call_ai(prompt, temperature=0.5, max_tokens=2048, prefer_arabic=True)

    if response and news_text:
        response += news_text

    return response or ("لم أتمكن من إنشاء التقرير. 🤖" if language == "ar" else "I couldn't generate the report. 🤖")
