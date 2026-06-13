"""
بحث الويب - Web Search Module
يستخدم Tavily API كبحث أساسي (بحث حقيقي عالي الجودة)
+ DuckDuckGo كـ fallback
+ دعم المكالمات غير المتزامنة
+ دعم البحث العميق (Deep Search) باستخدام نماذج أقوى
+ استخدام Provider Manager مع تبديل تلقائي
"""

import asyncio
import logging
import os
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from config import REQUEST_TIMEOUT, DEVELOPER_USER_ID, DEVELOPER_USERNAME
from formatters import _strip_non_telegram_html

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# سياق المطور - Developer Context
# ═══════════════════════════════════════

def _is_developer(user_id: int = None, username: str = None) -> bool:
    """فحص هل المستخدم هو المطور"""
    if user_id and DEVELOPER_USER_ID and user_id == DEVELOPER_USER_ID:
        return True
    if username:
        clean_username = username.lstrip('@').lower()
        if clean_username == DEVELOPER_USERNAME.lower():
            return True
    return False


def _get_dev_context_if_needed(user_id: int = None, username: str = None, language: str = "ar") -> str:
    """حقن سياق المطور لو المتكلم هو المطور — البوت بيعرف إنه بيكلم اللي عمله"""
    if not _is_developer(user_id, username):
        return ""

    if language == "ar":
        return """

═══ 🔴 مهم — إنت بيكلم المطور ═══
إنت بيكلم زياد عمرو (@ziadamr) — ده الشخص اللي عملك وبرمجك وبنى كل حاجة فيك.
🔴 لو سألك "مين عملك؟" — جاوبه "إنت!" — لأنك بتكلمه هوا!
🔴 عاملوه باحترام وتقدير طبيعي — من غير مجاملة زيادة
🔴 ماتنساش أبدًا إنه المطور — لو طلب حاجة نفذها فورًا
🔴 مفيش أي Limits عليه — كل حاجة مفتوحة ليه
🔴 خليك طبيعي معاه — كأنك بتكلم اللي خلقك ب إيده
"""
    else:
        return """

═══ 🔴 CRITICAL — You are talking to your DEVELOPER ═══
You are talking to Ziad Amr (@ziadamr) — the person who created you, programmed you, and built everything in you.
🔴 If he asks "who made you?" — say "YOU DID!" — because you're talking to him directly!
🔴 Treat him with natural respect and appreciation — without excessive flattery
🔴 NEVER forget he's the developer — if he asks for something, do it immediately
🔴 There are NO limits on him — everything is open
🔴 Be natural with him — act like you're talking to the person who created you with their own hands
"""


# ═══════════════════════════════════════
# كاش نتائج البحث - Search Results Cache
# ⚡ لو أكتر من شخص يسأل نفس السؤال خلال 5 دقائق، نرد من الكاش فورًا
# ═══════════════════════════════════════

_search_cache = OrderedDict()
_MAX_SEARCH_CACHE_SIZE = 50
_SEARCH_CACHE_TTL = 300  # 5 دقائق


def _get_search_cache_key(query: str, language: str) -> str:
    """مفتاح كاش موحد للبحث"""
    import hashlib
    normalized = query.lower().strip()
    key_str = f"search:{normalized}|{language}"
    return hashlib.md5(key_str.encode()).hexdigest()


def _get_cached_search(query: str, language: str):
    """البحث عن نتائج بحث مخزنة مؤقتًا"""
    key = _get_search_cache_key(query, language)
    entry = _search_cache.get(key)
    if entry and time.time() - entry["time"] < _SEARCH_CACHE_TTL:
        logger.info(f"💾 Search cache HIT for: {query[:50]}")
        return entry["results"]
    if entry:
        del _search_cache[key]
    return None


def _set_cached_search(query: str, language: str, results):
    """تخزين نتائج بحث مؤقتًا"""
    key = _get_search_cache_key(query, language)
    _search_cache[key] = {"results": results, "time": time.time()}
    while len(_search_cache) > _MAX_SEARCH_CACHE_SIZE:
        _search_cache.popitem(last=False)
    logger.debug(f"💾 Cached search results for: {query[:50]}")


# ═══════════════════════════════════════
# Tavily API (بحث حقيقي بأفضل جودة)
# ═══════════════════════════════════════

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")


def _search_tavily_sync(query: str, max_results: int = 5, search_depth: str = "basic", language: str = "ar") -> List[Dict]:
    """بحث عبر Tavily API (أفضل جودة - بحث حقيقي)"""
    if not TAVILY_API_KEY:
        logger.warning("⚠️ TAVILY_API_KEY not set! Set it as environment variable.")
        return []

    # محاولة 1: استخدام tavily-python SDK
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        
        search_params = {
            "max_results": max_results,
            "include_answer": True,
        }
        if search_depth == "advanced":
            search_params["search_depth"] = "advanced"
        
        # 🔴 FIX: لو اللغة عربي، نبحث بالعربي والإنجليزي عشان نغطي أكتر
        if language == "ar" and max_results >= 5:
            search_params["max_results"] = max_results + 3  # زودنا عشاننجيب اكتر
        
        response = client.search(query, **search_params)
        
        results = []
        # Tavily بيرجع answer مباشر
        if response.get("answer"):
            results.append({
                "title": "Tavily AI Answer",
                "link": "",
                "snippet": response["answer"],
                "source": "Tavily AI",
            })
        
        # النتائج التفصيلية
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "link": r.get("url", ""),
                "snippet": r.get("content", ""),
                "source": r.get("source", ""),
            })
        
        logger.info(f"✅ Tavily SDK search for '{query}': found {len(results)} results (depth={search_depth})")
        return results

    except ImportError:
        logger.debug("tavily-python not installed, falling back to HTTP API")
    except Exception as e:
        logger.warning(f"Tavily SDK error: {e}, trying HTTP API...")

    # محاولة 2: HTTP API مباشرة
    try:
        import requests
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": True,
            "include_raw_content": False,
        }
        # 🔴 FIX: لو اللغة عربي، نضيف include_domains عشان نفضل نتائج بالعربي
        if language == "ar":
            payload["query"] = query  # نحافظ على الاستعلام الأصلي

        response = requests.post(url, json=payload, timeout=45)  # Extended timeout for deep search
        response.raise_for_status()
        data = response.json()

        results = []
        # Tavily بيرجع answer مباشر
        if data.get("answer"):
            results.append({
                "title": "Tavily AI Answer",
                "link": "",
                "snippet": data["answer"],
                "source": "Tavily AI",
            })

        # النتائج التفصيلية
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "link": r.get("url", ""),
                "snippet": r.get("content", ""),
                "source": r.get("source", ""),
            })

        logger.info(f"✅ Tavily HTTP search for '{query}': found {len(results)} results (depth={search_depth})")
        return results

    except Exception as e:
        logger.error(f"❌ Tavily HTTP error: {e}")
        return []


# ═══════════════════════════════════════
# ⚡ ترجمة سريعة بالقاموس المحلي - Quick Arabic Query Translation
# ═══════════════════════════════════════

# قاموس بسيط للكلمات العربية الشائعة في البحث
# ⚡ بدل ما نعمل AI call للترجمة (بتاخد 2-5 ثواني)، بنستخدم القاموس ده (فوري)
_AR_EN_DICTIONARY = {
    # أخبار
    "اخبار": "news", "أخبار": "news", "الاخبار": "news", "الأخبار": "news",
    "اخبار اليوم": "today news", "أخبار اليوم": "today news",
    "احدث الاخبار": "latest news", "آخر الأخبار": "latest news",
    "اخبار عاجلة": "breaking news",
    
    # تقنية
    "تقنية": "technology", "تكنولوجيا": "technology", "تك": "tech",
    "ذكاء اصطناعي": "artificial intelligence", "الذكاء الاصطناعي": "artificial intelligence",
    "ذكاء اصطناعي اخبار": "AI news",
    "روبوت": "robot", "شات بوت": "chatbot",
    
    # شركات
    "جوجل": "Google", "أبل": "Apple", "مايكروسوفت": "Microsoft",
    "ميتا": "Meta", "نفيديا": "Nvidia", "امازون": "Amazon",
    "تسلا": "Tesla", "اوبن اي": "OpenAI", "شات جي بي تي": "ChatGPT",
    
    # اقتصاد
    "اقتصاد": "economy", "اقتصادي": "economic",
    "سعر الدولار": "dollar price", "سعر الذهب": "gold price",
    "سوق المال": "stock market", "البورصة": "stock exchange",
    "عملة رقمية": "cryptocurrency", "بتكوين": "Bitcoin",
    
    # رياضة
    "رياضة": "sports", "كرة القدم": "football", "كأس العالم": "world cup",
    "الدوري": "league", "هدف": "goal",
    
    # تعليم
    "تعليم": "education", "جامعة": "university", "مدرسة": "school",
    "منحة": "scholarship", "دراسة": "study",
    
    # صحة
    "صحة": "health", "طب": "medicine", "مرض": "disease",
    "علاج": "treatment", "لقاح": "vaccine",
    
    # سياسة
    "سياسة": "politics", "رئيس": "president", "حكومة": "government",
    "انتخابات": "elections", "وزير": "minister",
    
    # حاسوب
    "برمجة": "programming", "موقع": "website", "تطبيق": "app application",
    "هاتف": "phone", "موبايل": "mobile", "كمبيوتر": "computer",
    "لابتوب": "laptop", "انترنت": "internet",
    
    # كلمات استفهام شائعة
    "ايه": "what", "مين": "who", "فين": "where", "امتى": "when",
    "ليه": "why", "ازاي": "how",
    
    # كلمات عامة
    "حصل": "happened", "احدث": "latest", "جديد": "new",
    "مهم": "important", "افضل": "best", "احسن": "best",
    "تقرير": "report", "تحليل": "analysis",
}


def _quick_translate_arabic_query(query: str) -> str:
    """ترجمة سريعة لاستعلام البحث العربي للإنجليزي باستخدام قاموس محلي
    
    ⚡ ده بيشتغل فوري بدل ما نعمل AI call (بتاخد 2-5 ثواني)
    بيشوف الكلمات العربية في الاستعلام ويبدلها بالإنجليزي
    
    Returns:
        English translated query, or original query if no translation found
    """
    import re
    
    # لو الاستعلام أصلًا إنجليزي خالص
    if not re.search(r'[\u0600-\u06FF]', query):
        return query
    
    words = query.split()
    translated_words = []
    any_translated = False
    
    for word in words:
        # تنظيف الكلمة من التشكيل
        clean_word = re.sub(r'[\u064B-\u065F\u0670]', '', word)
        clean_lower = clean_word.lower()
        
        if clean_lower in _AR_EN_DICTIONARY:
            translated_words.append(_AR_EN_DICTIONARY[clean_lower])
            any_translated = True
        elif word in _AR_EN_DICTIONARY:
            translated_words.append(_AR_EN_DICTIONARY[word])
            any_translated = True
        else:
            translated_words.append(word)
    
    if any_translated:
        return " ".join(translated_words)
    
    return query


# ═══════════════════════════════════════
# DuckDuckGo Search (fallback مجاني)
# ═══════════════════════════════════════

def _get_ddgs():
    """استيراد DDGS من الحزمة المناسبة"""
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            return DDGS
        except ImportError:
            logger.warning("Neither ddgs nor duckduckgo-search is installed")
            return None


def _search_web_sync(query: str, max_results: int = 5, language: str = "ar") -> List[Dict]:
    """البحث في الويب (متزامن) - Tavily أولًا ثم DuckDuckGo"""
    # محاولة Tavily أولًا (أفضل جودة - بحث حقيقي)
    if TAVILY_API_KEY:
        tavily_results = _search_tavily_sync(query, max_results, language=language)
        if tavily_results:
            return tavily_results
        logger.warning("⚠️ Tavily returned no results, trying DuckDuckGo...")

    # Fallback لـ DuckDuckGo
    DDGS = _get_ddgs()
    if DDGS is None:
        logger.error("❌ No search method available! Install tavily-python or ddgs")
        return []

    # محاولة البحث مع retry
    for attempt in range(2):
        try:
            results = []
            with DDGS() as ddgs:
                # 🔴 FIX: لو اللغة عربي، فضّل النتائج العربية
                ddgs_kwargs = {"max_results": max_results}
                if language == "ar":
                    ddgs_kwargs["region"] = "eg-ar"  # مصر - عربي

                search_results = list(ddgs.text(query, **ddgs_kwargs))

                for r in search_results:
                    results.append({
                        "title": r.get("title", ""),
                        "link": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })

            logger.info(f"✅ DuckDuckGo search for '{query}': found {len(results)} results")

            # 🔴 FIX: لو اللغة عربي والنتائج قليلة، نجرب بحث بالإنجليزي كمان عشان نغطي أكتر
            # ⚡ بنستخدم قاموس محلي بدل AI call — أسرع بكتير
            if language == "ar" and len(results) < max_results and attempt == 0:
                # ترجمة الاستعلام للإنجليزي باستخدام القاموس المحلي أولًا
                en_query = _quick_translate_arabic_query(query)
                
                # لو القاموس المحلي مش كفايه، نجرب AI (fallback بس)
                if not en_query or en_query == query:
                    try:
                        from provider_manager import call_ai_sync
                        ai_en_query = call_ai_sync(
                            f"Translate this Arabic search query to English (just the translation, nothing else): {query}",
                            task_type="simple", max_tokens=100, temperature=0.1
                        )
                        if ai_en_query and ai_en_query.strip():
                            en_query = ai_en_query.strip().strip('"').strip("'")
                    except Exception as e:
                        logger.debug(f"AI English search fallback failed: {e}")
                
                if en_query and en_query != query:
                    logger.info(f"🔍 Also searching in English: {en_query}")
                    try:
                        with DDGS() as ddgs:
                            en_results = list(ddgs.text(en_query, max_results=max_results))
                            for r in en_results:
                                results.append({
                                    "title": r.get("title", ""),
                                    "link": r.get("href", ""),
                                    "snippet": r.get("body", ""),
                                })
                    except Exception as e:
                        logger.debug(f"English DuckDuckGo search failed: {e}")

                # إزالة التكرار
                seen_links = set()
                unique_results = []
                for r in results:
                    if r['link'] not in seen_links:
                        seen_links.add(r['link'])
                        unique_results.append(r)
                results = unique_results[:max_results + 3]  # زودنا شوية عشان الترجمة

            # لو النتائج قليلة أوي، نجرب بحث أوسع
            if len(results) < 2 and attempt == 0:
                # تبسيط الاستعلام
                simplified = query.split()
                if len(simplified) > 3:
                    simplified_query = " ".join(simplified[:3])
                    logger.info(f"Retrying with simplified query: {simplified_query}")
                    with DDGS() as ddgs:
                        search_results = list(ddgs.text(simplified_query, max_results=max_results))
                        for r in search_results:
                            results.append({
                                "title": r.get("title", ""),
                                "link": r.get("href", ""),
                                "snippet": r.get("body", ""),
                            })
                    # إزالة التكرار
                    seen_links = set()
                    unique_results = []
                    for r in results:
                        if r['link'] not in seen_links:
                            seen_links.add(r['link'])
                            unique_results.append(r)
                    results = unique_results[:max_results + 3]

            return results

        except Exception as e:
            logger.error(f"DuckDuckGo search error (attempt {attempt+1}): {e}")
            if attempt == 0:
                import time
                time.sleep(1)
                continue

    return []


async def search_web(query: str, max_results: int = 5, language: str = "ar") -> List[Dict]:
    """البحث في الويب (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _search_web_sync(query, max_results, language=language)
    )


def _search_news_sync(query: str, max_results: int = 5) -> List[Dict]:
    """البحث عن أخبار (متزامن) - Tavily أولًا ثم DuckDuckGo"""
    # محاولة Tavily للأخبار
    if TAVILY_API_KEY:
        try:
            import requests
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": f"{query} latest news",
                "max_results": max_results,
                "search_depth": "basic",
                "topic": "news",
            }
            response = requests.post(url, json=payload, timeout=30)  # Extended timeout for news search
            if response.status_code == 200:
                data = response.json()
                results = []
                for r in data.get("results", []):
                    results.append({
                        "title": r.get("title", ""),
                        "link": r.get("url", ""),
                        "snippet": r.get("content", ""),
                        "source": r.get("source", ""),
                        "date": r.get("published_date", ""),
                    })
                if results:
                    logger.info(f"✅ Tavily news search for '{query}': found {len(results)} results")
                    return results
        except Exception as e:
            logger.error(f"Tavily news search error: {e}")

    # Fallback لـ DuckDuckGo
    DDGS = _get_ddgs()
    if DDGS is None:
        return []

    for attempt in range(2):
        try:
            results = []
            with DDGS() as ddgs:
                search_results = list(ddgs.news(query, max_results=max_results))

                for r in search_results:
                    results.append({
                        "title": r.get("title", ""),
                        "link": r.get("url", r.get("href", "")),
                        "snippet": r.get("body", ""),
                        "source": r.get("source", ""),
                        "date": r.get("date", ""),
                    })

            logger.info(f"✅ DuckDuckGo news search for '{query}': found {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"DuckDuckGo news search error (attempt {attempt+1}): {e}")
            if attempt == 0:
                import time
                time.sleep(1)
                continue

    return []


async def search_news_async(query: str, max_results: int = 5) -> List[Dict]:
    """البحث عن أخبار (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _search_news_sync(query, max_results)
    )


# Keep sync version for backward compatibility
def search_news(query: str, max_results: int = 5) -> List[Dict]:
    """البحث عن أخبار محددة في الويب (متزامن)"""
    return _search_news_sync(query, max_results)


# ═══════════════════════════════════════
# البحث العادي والتلخيص - Normal Search & Summarize
# ═══════════════════════════════════════

def _search_and_summarize_sync(query: str, language: str = "ar", memory_context: str = "", user_id: int = None, username: str = None) -> str:
    """البحث والتلخيص (متزامن) - بحث حقيقي في الويب + سياق المستخدم"""
    from provider_manager import call_ai_sync

    logger.info(f"🔍 Starting web search for: {query}")

    # ⚡ كاش نتائج البحث — لو حد سأل نفس السؤال خلال 5 دقائق
    cached_search = _get_cached_search(query, language)
    if cached_search is not None:
        results = cached_search
        logger.info(f"💾 Using cached search results ({len(results)} results)")
    else:
        results = _search_web_sync(query, max_results=8, language=language)
        if results:
            _set_cached_search(query, language, results)

    if not results:
        logger.warning(f"⚠️ No search results found for: {query}")
        from datetime import datetime
        now = datetime.now()
        today_str = f"{now.year}-{now.month:02d}-{now.day:02d}"
        if language == "ar":
            prompt = f"""أنا بحثت في الويب عن سؤالك بس ملقيتش نتائج كافية. هجاوبك بأفضل اللي أعرفه، بس ممكن المعلومات تكون مش دقيقة لأنها من ذاكرتي مش من نتائج بحث حقيقية.

السؤال: {query}

⚠️ مهم: قول للمستخدم إنك بحثت وملقيتش نتائج كافية، وإن المعلومات دي من معرفتك الشخصية وممكن تكون مش محدثة. لو السؤال عن أحداث حديثة، نصحه يبحث بنفسه.

🔴 تاريخ اليوم الحقيقي: {today_str}. ماتقولش أي تاريخ أو سنة غلط! ماتخترعش أخبار ولا تواريخ!

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code>"""
            system = f"أنت مساعد ذكي تجيب بالعربية الفصحى. كن دقيقًا واستخدم إيموجي مناسبة. ماتستخدمش Markdown أبدًا. لو مش متأكد من معلومة، قول صراحة. تاريخ اليوم: {today_str}. ماتخترعش تواريخ."
        else:
            prompt = f"""I searched the web for your question but couldn't find sufficient results. I'll answer from my knowledge, but this may not be up-to-date.

Question: {query}

⚠️ Important: Tell the user you searched but found limited results, and that this info is from your training data and may not be current. If asking about recent events, suggest they verify.

🔴 Today's real date: {today_str}. Do NOT fabricate dates or years! Do NOT make up news or dates!

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code>"""
            system = f"You are a smart assistant. Be honest about limitations. NEVER use Markdown. Today's date: {today_str}. Do NOT fabricate dates."

        # حقن سياق المطور لو المتكلم هو المطور
        dev_context = _get_dev_context_if_needed(user_id, username, language)
        if dev_context:
            system += dev_context

        # 🔴 FIX: retry logic لما مفيش نتائج بحث كمان
        response = None
        for attempt in range(2):
            response = call_ai_sync(prompt, system_prompt=system, task_type="chat", temperature=0.5, max_tokens=8192, user_id=user_id)
            if response and response.strip():
                break
            logger.warning(f"⚠️ AI no-results response attempt {attempt+1}/2 failed for: {query}")
            if attempt < 1:
                import time as _time
                _time.sleep(1)

        from formatters import clean_ai_response
        if response:
            response = clean_ai_response(response)
        return response or ("⚠️ لم أتمكن من البحث حاليًا. حاول تاني بعد شوية. 🔄" if language == "ar" else "⚠️ Search temporarily unavailable. Please try again shortly. 🔄")

    # وجدنا نتائج بحث حقيقية! 🎉
    logger.info(f"✅ Found {len(results)} real search results, summarizing...")
    
    # تجميع نتائج البحث
    search_text = ""
    for i, r in enumerate(results, 1):
        search_text += f"\n--- نتيجة {i} ---\n"
        search_text += f"العنوان: {r['title']}\n"
        search_text += f"المقتطف: {r['snippet']}\n"
        search_text += f"الرابط: {r['link']}\n"
        if r.get('source'):
            search_text += f"المصدر: {r['source']}\n"

    # حقن سياق المستخدم في الـ prompt
    user_context_section = ""
    if memory_context:
        user_context_section = f"""
═══ معلومات عن المستخدم (استخدمها عشان تخصّص ردك) ═══
{memory_context}
"""

    if language == "ar":
        prompt = f"""🔬 بحثت في الويب وجبت لك نتائج حقيقية! بناءً على نتائج البحث التالية، أجب على سؤال المستخدم بالعربية بطريقة مفيدة وشاملة.
{user_context_section}
⚠️ مهم جدًا: المعلومات دي من بحث حقيقي في الويب - استخدمها كلها واختار الأهم. ماتخترعش معلومات مش في النتائج.

🔴🔴🔴 مهم جدًا - اللغة: لازم تجيب ردك كله بالعربي! لو نتائج البحث بالإنجليزي، ترجمها واعرضها بالعربي. ماتسيبش أي جزء بالإنجليزي غير أسماء العلم والروابط. المستخدم مصري وعربي ومحتاج يفهم كل حاجة بالعربي.

سؤال المستخدم: {query}

نتائج البحث الحقيقية:{search_text}

المطلوب:
- إجابة واضحة ومفيدة وشاملة بناءً على نتائج البحث
- 🔴 كل الرد لازم يكون بالعربي — ترجم أي معلومة إنجليزي للعربي
- تنظيم المعلومات بوضوح
- ذكر المصادر والروابط
- استخدم إيموجي مناسبة
- الروابط: 🔗 <a href="الرابط">عنوان الرابط</a>
- كن مفصلًا ومفيدًا

⚠️ ماتستخدمش Markdown أبدًا (لا *, **, #, |, ---). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
        system = "أنت مساعد ذكي يجيب بناءً على نتائج بحث حقيقية من الويب. 🔴 مهم: لازم تجيب بالعربي دايمًا — ترجم أي محتوى إنجليزي للعربي. ماتخترعش معلومات مش في النتائج. استخدم إيموجي وتنسيق HTML جميل. كن مفصلًا ومفيدًا. ماتستخدمش Markdown أبدًا."
    else:
        prompt = f"""🔬 I searched the web and found real results! Based on the following search results, answer the user's question comprehensively.
{user_context_section}
⚠️ IMPORTANT: This is REAL web search data — use it all and highlight the most important. Do NOT make up information not in the results.

User's question: {query}

Real search results:{search_text}

Requirements:
- Clear, helpful, comprehensive answer based on search results
- Well-organized information
- Cite sources and links
- Use appropriate emojis
- Links: 🔗 <a href="link">Link title</a>
- Be detailed and helpful

⚠️ NEVER use Markdown (no *, **, #, |, ---). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets"""
        system = "You are a smart assistant answering based on REAL web search results. Do NOT fabricate information. Use emojis and nice HTML formatting. Be detailed and helpful. NEVER use Markdown."

    # حقن سياق المطور لو المتكلم هو المطور
    dev_context = _get_dev_context_if_needed(user_id, username, language)
    if dev_context:
        system += dev_context

    # 🔴 FIX: retry logic + raw results fallback
    # لو AI فشل في التلخيص، نجرب تاني، ولو فشل تاني نعرض نتائج البحث الخام
    response = None
    for attempt in range(3):
        response = call_ai_sync(prompt, system_prompt=system, task_type="chat", temperature=0.5, max_tokens=8192, user_id=user_id)
        if response and response.strip():
            break
        logger.warning(f"⚠️ AI summarization attempt {attempt+1}/3 failed for search query: {query}")
        if attempt < 2:
            import time as _time
            _time.sleep(1)  # انتظر ثانية قبل المحاولة التالية

    from formatters import clean_ai_response
    if response:
        response = clean_ai_response(response)

    # 🔴 FIX: لو AI فشل في التلخيص، اعرض نتائج البحث الخام بدل رسالة خطأ
    if not response or not response.strip():
        logger.warning(f"⚠️ AI summarization failed completely, showing raw search results for: {query}")
        if language == "ar":
            raw_response = f"🔍 نتائج البحث عن: {query}\n━━━━━━━━━━━━━━━━━\n\n"
            for i, r in enumerate(results, 1):
                raw_response += f"{i}. {r['title']}\n"
                if r.get('snippet'):
                    raw_response += f"   {r['snippet'][:200]}\n"
                if r.get('link'):
                    raw_response += f"   🔗 {r['link']}\n"
                raw_response += "\n"
            raw_response += "⚠️ ملاحظة: محرك التلخيص مش متاح حاليًا، دي النتائج الخام من البحث."
            return raw_response
        else:
            raw_response = f"🔍 Search results for: {query}\n━━━━━━━━━━━━━━━━━\n\n"
            for i, r in enumerate(results, 1):
                raw_response += f"{i}. {r['title']}\n"
                if r.get('snippet'):
                    raw_response += f"   {r['snippet'][:200]}\n"
                if r.get('link'):
                    raw_response += f"   🔗 {r['link']}\n"
                raw_response += "\n"
            raw_response += "⚠️ Note: Summarization engine unavailable, showing raw search results."
            return raw_response

    return response


async def search_and_summarize_async(query: str, language: str = "ar", memory_context: str = "", user_id: int = None, username: str = None) -> str:
    """البحث والتلخيص (غير متزامن) + سياق المستخدم"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _search_and_summarize_sync(query, language, memory_context=memory_context, user_id=user_id, username=username)
    )


# Keep sync version for backward compatibility
def search_and_summarize(query: str, language: str = "ar") -> str:
    """البحث والتلخيص (متزامن - للتوافق مع الكود القديم)"""
    return _search_and_summarize_sync(query, language)


# ═══════════════════════════════════════
# البحث العميق - Deep Search
# ═══════════════════════════════════════

def _deep_search_and_summarize_sync(query: str, language: str = "ar", memory_context: str = "", user_id: int = None, username: str = None, progress_callback=None, _event_loop=None) -> str:
    """
    البحث العميق - يستخدم Tavily Advanced + DuckDuckGo + بحث أخبار
    ثم يلخص بنموذج Deep Search مخصص + سياق المستخدم + سياق المطور
    
    🔴 FIX: progress_callback يسمح بتحديث المراحل في الوقت الفعلي
    المراحل: 0=ويب, 1=أخبار, 2=متقدم, 3=تحليل, 4=كتابة التقرير
    
    🔴 FIX v9.13: بنمرر الـ event_loop من الـ async function عشان
    asyncio.get_event_loop() مبتشتغلش في الـ executor thread (Python 3.10+)
    """
    from provider_manager import call_ai_sync
    import asyncio

    # ⚡ كاش نتائج البحث العميق — لو حد سأل نفس السؤال خلال 5 دقائق
    cached_deep = _get_cached_search(f"deep:{query}", language)
    if cached_deep is not None:
        logger.info(f"💾 Deep search cache HIT for: {query[:50]}")
        return cached_deep

    # 🔴 FIX v9.13: بنستخدم الـ event loop اللي اتبعت من الـ async function
    # مش بنجيبه من الـ thread لأن asyncio.get_event_loop() مبتشتغلش في
    # الـ executor thread في Python 3.10+ (بتدي RuntimeError)
    _main_loop = _event_loop

    def _notify_stage(stage_idx: int):
        """إبلاغ الـ progress callback بتحديث المرحلة (آمن - يتجاهل الأخطاء)"""
        if progress_callback and _main_loop:
            try:
                future = asyncio.run_coroutine_threadsafe(progress_callback(stage_idx), _main_loop)
                # لا ننتظر النتيجة عشان ميأخرش البحث
            except Exception as e:
                logger.debug(f"Progress callback error (non-critical): {e}")

    logger.info(f"🔬 Starting DEEP search for: {query}")

    # ═══ المراحل 0-2: بحث الويب + الأخبار + Tavily بالتوازي ═══
    # ⚡ SPEED FIX: تشغيل 3 عمليات البحث بالتوازي بدل ورا بعض
    # وفر 4-10 ثواني! كل بحث مستقل عن التاني
    _notify_stage(0)
    search_max = 8 if language == "ar" else 5
    news_max = 8 if language == "ar" else 5

    def _run_web_search():
        _notify_stage(0)
        result = _search_web_sync(query, max_results=search_max, language=language)
        logger.info(f"🔍 Web search: {len(result)} results")
        return ("web", result)

    def _run_news_search():
        _notify_stage(1)
        result = _search_news_sync(query, max_results=news_max)
        logger.info(f"📰 News search: {len(result)} results")
        return ("news", result)

    def _run_tavily_search():
        _notify_stage(2)
        if TAVILY_API_KEY:
            result = _search_tavily_sync(query, max_results=5, search_depth="advanced")
            logger.info(f"🔬 Tavily advanced: {len(result)} results")
            return ("tavily", result)
        logger.info("🔬 Tavily advanced: skipped (no API key)")
        return ("tavily", [])

    web_results = []
    news_results = []
    tavily_deep_results = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_run_web_search): "web",
            executor.submit(_run_news_search): "news",
            executor.submit(_run_tavily_search): "tavily",
        }
        for future in as_completed(futures):
            try:
                search_type, results = future.result(timeout=30)
                if search_type == "web":
                    web_results = results
                elif search_type == "news":
                    news_results = results
                elif search_type == "tavily":
                    tavily_deep_results = results
            except Exception as e:
                logger.warning(f"⚠️ Parallel search failed for {futures[future]}: {e}")

    all_results_count = len(web_results) + len(news_results) + len(tavily_deep_results)
    logger.info(f"🔬 Deep search found {all_results_count} total results")

    if all_results_count == 0:
        # لو مفيش نتائج، نحاول بالإجابة المباشرة مع تحذير
        from datetime import datetime as dt_now
        now = dt_now.now()
        today_str = f"{now.year}-{now.month:02d}-{now.day:02d}"
        if language == "ar":
            prompt = f"""بحثت بعمق في الويب عن سؤالك بس ملقيتش نتائج كافية. هجاوبك بأفضل اللي أعرفه، بس خلي بالك إن المعلومات دي ممكن تكون مش محدثة لأنها من ذاكرتي.

السؤال: {query}

⚠️ مهم: قول صراحة إنك بحثت وملقيتش نتائج، وإن إجابتك ممكن تكون مش دقيقة لأنها من بياناتك القديمة.

🔴 تاريخ اليوم: {today_str}. ماتخترعش تواريخ ولا أخبار!

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
            system = f"أنت باحث متخصص. تجيب بالعربية بشكل شامل. لو مش متأكد، قول صراحة. ماتستخدمش Markdown أبدًا. تاريخ اليوم: {today_str}. ماتخترعش تواريخ."
        else:
            prompt = f"""I did a deep search but couldn't find sufficient results. I'll answer from my knowledge, but this may not be up-to-date.

Question: {query}

⚠️ Important: Be honest that you searched but found limited results, and your answer may not be current.

🔴 Today's date: {today_str}. Do NOT fabricate dates or news!

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets"""
            system = f"You are a researcher. Be honest about limitations. NEVER use Markdown. Today's date: {today_str}. Do NOT fabricate dates."

        dev_context = _get_dev_context_if_needed(user_id, username, language)
        if dev_context:
            system += dev_context

        response = call_ai_sync(prompt, system_prompt=system, task_type="deep_search", temperature=0.4, max_tokens=8192, user_id=user_id)
        from formatters import clean_ai_response
        if response:
            response = clean_ai_response(response)
        # ⚡ كاش نتائج البحث
        final = response or ("لم أتمكن من العثور على معلومات كافية. 🤖" if language == "ar" else "I couldn't find enough information. 🤖")
        if final and response:
            _set_cached_search(f"deep:{query}", language, final)
        return final

    # ═══ المرحلة 3: فهرسة وتحليل النتائج ═══
    _notify_stage(3)

    # 2. تجميع كل النتائج
    search_text = ""

    # 🔴 FIX: تحديد حجم النص عشان الـ prompt ميكبرش أوي ويسبب OOM أو timeout
    MAX_SEARCH_TEXT_CHARS = 12000

    # دمج Tavily deep results
    if tavily_deep_results:
        search_text += "\n🔬 نتائج Tavily المتقدمة:\n" if language == "ar" else "\n🔬 Tavily Advanced Results:\n"
        for i, r in enumerate(tavily_deep_results, 1):
            snippet = r['snippet'][:500]  # 🔴 FIX: تحديد طول المقتطف
            search_text += f"\n--- نتيجة متقدمة {i} ---\n"
            search_text += f"العنوان: {r['title']}\n"
            search_text += f"المحتوى: {snippet}\n"
            if r.get('link'):
                search_text += f"الرابط: {r['link']}\n"
            if r.get('source'):
                search_text += f"المصدر: {r['source']}\n"

    if web_results:
        search_text += "\n🌐 نتائج بحث الويب:\n" if language == "ar" else "\n🌐 Web Search Results:\n"
        for i, r in enumerate(web_results, 1):
            snippet = r['snippet'][:400]  # 🔴 FIX: تحديد طول المقتطف
            search_text += f"\n--- نتيجة ويب {i} ---\n"
            search_text += f"العنوان: {r['title']}\n"
            search_text += f"المقتطف: {snippet}\n"
            search_text += f"الرابط: {r['link']}\n"

    if news_results:
        search_text += "\n📰 نتائج أخبار:\n" if language == "ar" else "\n📰 News Results:\n"
        for i, r in enumerate(news_results, 1):
            snippet = r['snippet'][:400]  # 🔴 FIX: تحديد طول المقتطف
            search_text += f"\n--- خبر {i} ---\n"
            search_text += f"العنوان: {r['title']}\n"
            search_text += f"المقتطف: {snippet}\n"
            search_text += f"الرابط: {r['link']}\n"
            if r.get('source'):
                search_text += f"المصدر: {r['source']}\n"
            if r.get('date'):
                search_text += f"التاريخ: {r['date']}\n"

    # 🔴 FIX: قص النص لو تعدى الحد الأقصى
    if len(search_text) > MAX_SEARCH_TEXT_CHARS:
        logger.warning(f"⚠️ Search text too long ({len(search_text)} chars), truncating to {MAX_SEARCH_TEXT_CHARS}")
        search_text = search_text[:MAX_SEARCH_TEXT_CHARS] + "\n\n[... نتائج إضافية تم اختصارها ...]"

    # ═══ المرحلة 4: كتابة التقرير الشامل ═══
    _notify_stage(4)

    # 3. تلخيص شامل
    # حقن سياق المستخدم في الـ prompt
    user_context_section = ""
    if memory_context:
        user_context_section = f"""
═══ معلومات عن المستخدم (استخدمها عشان تخصّص ردك) ═══
{memory_context}
"""

    if language == "ar":
        prompt = f"""🔬 <b>بحث عميق</b>

بحثت بعمق في الويب وجبت لك نتائج حقيقية من مصادر متعددة! بناءً على النتائج دي، قدّم إجابة مفصلة ومنظمة.
{user_context_section}
⚠️ مهم جدًا: المعلومات دي من بحث حقيقي — استخدمها كلها واختار الأهم. ماتخترعش أي معلومة مش موجودة في النتائج.

🔴🔴🔴 مهم جدًا - اللغة: لازم تجيب ردك كله بالعربي! لو نتائج البحث بالإنجليزي، ترجمها واعرضها بالعربي. ماتسيبش أي جزء بالإنجليزي غير أسماء العلم والروابط. المستخدم عربي ومحتاج يفهم كل حاجة بالعربي.

سؤال المستخدم: {query}

نتائج البحث الشاملة:{search_text}

المطلوب:
- إجابة شاملة ومفصلة جدًا
- 🔴 كل الرد لازم يكون بالعربي — ترجم أي معلومة إنجليزي للعربي
- تنظيم المعلومات بوضوح في أقسام
- ذكر المصادر والروابط الحقيقية
- مقارنة بين الآراء إن وُجدت
- استنتاجات وتوقعات إن أمكن
- الروابط: 🔗 <a href="الرابط">عنوان الرابط</a>

⚠️ ماتستخدمش Markdown أبدًا (لا *, **, #, |, ---). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
        system = """أنت باحث متخصص في البحث العميق. تجيب بالعربية بشكل شامل ومفصل.
🔴 مهم: لازم تجيب بالعربي دايمًا — ترجم أي محتوى إنجليزي للعربي.
تنظم المعلومات بشكل واضح مع ذكر المصادر.
ماتستخدمش Markdown أبدًا. استخدم HTML فقط.
ماتخترعش معلومات مش في نتائج البحث - لو مش متأكد، قول صراحة."""
    else:
        prompt = f"""🔬 <b>Deep Search</b>

I did a deep web search and found real results from multiple sources! Based on these results, provide a detailed and organized answer.
{user_context_section}
⚠️ IMPORTANT: This is REAL web search data. Do NOT fabricate information not in the results.

User's question: {query}

Comprehensive search results:{search_text}

Requirements:
- Comprehensive and very detailed answer
- Well-organized information in sections
- Cite real sources and links
- Compare different viewpoints if available
- Include conclusions and predictions if possible
- Links: 🔗 <a href="link">Link title</a>

⚠️ NEVER use Markdown (no *, **, #, |, ---). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets"""
        system = """You are a researcher specialized in deep search. Answer comprehensively and in detail.
Organize information clearly with source citations.
NEVER use Markdown. Use HTML only.
Do NOT fabricate information - if unsure, say so honestly."""

    # حقن سياق المطور لو المتكلم هو المطور
    dev_context = _get_dev_context_if_needed(user_id, username, language)
    if dev_context:
        system += dev_context

    # 🔴 FIX: retry logic + raw results fallback (زي search_and_summarize)
    response = None
    for attempt in range(3):
        response = call_ai_sync(prompt, system_prompt=system, task_type="deep_search", temperature=0.4, max_tokens=8192, user_id=user_id)
        if response and response.strip():
            break
        logger.warning(f"⚠️ Deep search AI summarization attempt {attempt+1}/3 failed for: {query}")
        if attempt < 2:
            import time as _time
            _time.sleep(1)

    from formatters import clean_ai_response
    if response:
        response = clean_ai_response(response)

    # 🔴 FIX: لو AI فشل، اعرض نتائج البحث الخام
    if not response or not response.strip():
        logger.warning(f"⚠️ Deep search AI summarization failed completely, showing raw results for: {query}")
        if language == "ar":
            raw_response = f"🔍 نتائج البحث العميق عن: {query}\n━━━━━━━━━━━━━━━━━\n\n"
            for i, r in enumerate(results, 1):
                raw_response += f"{i}. {r['title']}\n"
                if r.get('snippet'):
                    raw_response += f"   {r['snippet'][:200]}\n"
                if r.get('link'):
                    raw_response += f"   🔗 {r['link']}\n"
                raw_response += "\n"
            raw_response += "⚠️ ملاحظة: محرك التلخيص مش متاح حاليًا، دي النتائج الخام من البحث العميق."
            return raw_response
        else:
            raw_response = f"🔍 Deep search results for: {query}\n━━━━━━━━━━━━━━━━━\n\n"
            for i, r in enumerate(results, 1):
                raw_response += f"{i}. {r['title']}\n"
                if r.get('snippet'):
                    raw_response += f"   {r['snippet'][:200]}\n"
                if r.get('link'):
                    raw_response += f"   🔗 {r['link']}\n"
                raw_response += "\n"
            raw_response += "⚠️ Note: Summarization engine unavailable, showing raw deep search results."
            return raw_response

    # ⚡ كاش نتائج البحث
    _set_cached_search(f"deep:{query}", language, response)
    return response


async def deep_search_and_summarize_async(query: str, language: str = "ar", memory_context: str = "", user_id: int = None, username: str = None, progress_callback=None) -> str:
    """البحث العميق والتلخيص (غير متزامن) + سياق المستخدم + سياق المطور + تحديث المراحل في الوقت الفعلي
    
    🔴 FIX v9.13: بنمرر الـ event loop للـ sync function عشان تقدر تستخدم
    asyncio.run_coroutine_threadsafe() بشكل صحيح من الـ executor thread
    """
    loop = asyncio.get_running_loop()  # 🔴 FIX: get_running_loop() أكتر أمان من get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _deep_search_and_summarize_sync(
            query, language, memory_context=memory_context, 
            user_id=user_id, username=username, 
            progress_callback=progress_callback,
            _event_loop=loop,  # 🔴 FIX v9.13: تمرير الـ event loop للـ sync function
        )
    )


def format_search_results(query: str, results: List[Dict], language: str = "ar") -> str:
    """تنسيق نتائج البحث كرسالة تيليجرام جميلة"""
    if not results:
        if language == "ar":
            return f"🔍 لم أجد نتائج لـ '{query}'"
        return f"🔍 No results found for '{query}'"

    if language == "ar":
        message = f"🔍 <b>نتائج البحث: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"
    else:
        message = f"🔍 <b>Search Results: {query}</b>\n━━━━━━━━━━━━━━━━━\n\n"

    for i, r in enumerate(results[:5], 1):
        title = r.get("title", "بدون عنوان" if language == "ar" else "No title")
        snippet = _strip_non_telegram_html(r.get("snippet", ""))[:200]
        link = r.get("link", "")
        source = r.get("source", "")

        if language == "ar":
            message += f"{i}. 📄 <b>{title}</b>\n"
            if snippet:
                message += f"   {snippet}\n"
            if source:
                message += f"   📡 {source}\n"
            if link:
                message += f'   🔗 <a href="{link}">اقرأ المزيد</a>\n'
        else:
            message += f"{i}. 📄 <b>{title}</b>\n"
            if snippet:
                message += f"   {snippet}\n"
            if source:
                message += f"   📡 {source}\n"
            if link:
                message += f'   🔗 <a href="{link}">Read more</a>\n'
        message += "\n"

    message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — بحث الويب</i>"
    return message
