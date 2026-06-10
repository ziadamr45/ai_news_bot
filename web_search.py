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
from typing import List, Dict, Optional

from config import REQUEST_TIMEOUT, DEVELOPER_USER_ID, DEVELOPER_USERNAME

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
🔴 ماتنساش أبداً إنه المطور — لو طلب حاجة نفذها فوراً
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
    """البحث في الويب (متزامن) - Tavily أولاً ثم DuckDuckGo"""
    # محاولة Tavily أولاً (أفضل جودة - بحث حقيقي)
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
            if language == "ar" and len(results) < max_results and attempt == 0:
                # ترجمة الاستعلام للإنجليزي عشان نجيب نتائج أكتر
                try:
                    from provider_manager import call_ai_sync
                    en_query = call_ai_sync(
                        f"Translate this Arabic search query to English (just the translation, nothing else): {query}",
                        task_type="simple", max_tokens=100, temperature=0.1
                    )
                    if en_query and en_query.strip():
                        en_query = en_query.strip().strip('"').strip("'")
                        logger.info(f"🔍 Also searching in English: {en_query}")
                        with DDGS() as ddgs:
                            en_results = list(ddgs.text(en_query, max_results=max_results))
                            for r in en_results:
                                results.append({
                                    "title": r.get("title", ""),
                                    "link": r.get("href", ""),
                                    "snippet": r.get("body", ""),
                                })
                except Exception as e:
                    logger.debug(f"English search fallback failed: {e}")

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
    """البحث عن أخبار (متزامن) - Tavily أولاً ثم DuckDuckGo"""
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
    results = _search_web_sync(query, max_results=8, language=language)

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
            system = f"أنت مساعد ذكي تجيب بالعربية الفصحى. كن دقيقاً واستخدم إيموجي مناسبة. ماتستخدمش Markdown أبداً. لو مش متأكد من معلومة، قول صراحة. تاريخ اليوم: {today_str}. ماتخترعش تواريخ."
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

        response = call_ai_sync(prompt, system_prompt=system, task_type="chat", temperature=0.5, max_tokens=8192, user_id=user_id)
        from formatters import clean_ai_response
        if response:
            response = clean_ai_response(response)
        return response or ("لم أتمكن من العثور على معلومات. 🤖" if language == "ar" else "I couldn't find information. 🤖")

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
⚠️ مهم جداً: المعلومات دي من بحث حقيقي في الويب - استخدمها كلها واختار الأهم. ماتخترعش معلومات مش في النتائج.

🔴🔴🔴 مهم جداً - اللغة: لازم تجيب ردك كله بالعربي! لو نتائج البحث بالإنجليزي، ترجمها واعرضها بالعربي. ماتسيبش أي جزء بالإنجليزي غير أسماء العلم والروابط. المستخدم مصري وعربي ومحتاج يفهم كل حاجة بالعربي.

سؤال المستخدم: {query}

نتائج البحث الحقيقية:{search_text}

المطلوب:
- إجابة واضحة ومفيدة وشاملة بناءً على نتائج البحث
- 🔴 كل الرد لازم يكون بالعربي — ترجم أي معلومة إنجليزي للعربي
- تنظيم المعلومات بوضوح
- ذكر المصادر والروابط
- استخدم إيموجي مناسبة
- الروابط: 🔗 <a href="الرابط">عنوان الرابط</a>
- كن مفصلاً ومفيداً

⚠️ ماتستخدمش Markdown أبداً (لا *, **, #, |, ---). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
        system = "أنت مساعد ذكي يجيب بناءً على نتائج بحث حقيقية من الويب. 🔴 مهم: لازم تجيب بالعربي دايماً — ترجم أي محتوى إنجليزي للعربي. ماتخترعش معلومات مش في النتائج. استخدم إيموجي وتنسيق HTML جميل. كن مفصلاً ومفيداً. ماتستخدمش Markdown أبداً."
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

    response = call_ai_sync(prompt, system_prompt=system, task_type="chat", temperature=0.5, max_tokens=8192, user_id=user_id)
    from formatters import clean_ai_response
    if response:
        response = clean_ai_response(response)
    return response or ("لم أتمكن من معالجة نتائج البحث. 🤖" if language == "ar" else "I couldn't process search results. 🤖")


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

    # ═══ المرحلة 0: بحث الويب ═══
    _notify_stage(0)
    # 🔴 FIX: لو اللغة عربي، نخلي الـ deep search يجيب نتائج اكتر
    search_max = 8 if language == "ar" else 5
    web_results = _search_web_sync(query, max_results=search_max, language=language)
    logger.info(f"🔍 Web search: {len(web_results)} results")

    # ═══ المرحلة 1: بحث الأخبار ═══
    _notify_stage(1)
    news_results = _search_news_sync(query, max_results=8 if language == "ar" else 5)
    logger.info(f"📰 News search: {len(news_results)} results")

    # ═══ المرحلة 2: بحث متقدم (Tavily Advanced) ═══
    _notify_stage(2)
    tavily_deep_results = []
    if TAVILY_API_KEY:
        tavily_deep_results = _search_tavily_sync(query, max_results=5, search_depth="advanced")
    logger.info(f"🔬 Tavily advanced: {len(tavily_deep_results)} results")

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
            system = f"أنت باحث متخصص. تجيب بالعربية بشكل شامل. لو مش متأكد، قول صراحة. ماتستخدمش Markdown أبداً. تاريخ اليوم: {today_str}. ماتخترعش تواريخ."
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
        return response or ("لم أتمكن من العثور على معلومات كافية. 🤖" if language == "ar" else "I couldn't find enough information. 🤖")

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
⚠️ مهم جداً: المعلومات دي من بحث حقيقي — استخدمها كلها واختار الأهم. ماتخترعش أي معلومة مش موجودة في النتائج.

🔴🔴🔴 مهم جداً - اللغة: لازم تجيب ردك كله بالعربي! لو نتائج البحث بالإنجليزي، ترجمها واعرضها بالعربي. ماتسيبش أي جزء بالإنجليزي غير أسماء العلم والروابط. المستخدم عربي ومحتاج يفهم كل حاجة بالعربي.

سؤال المستخدم: {query}

نتائج البحث الشاملة:{search_text}

المطلوب:
- إجابة شاملة ومفصلة جداً
- 🔴 كل الرد لازم يكون بالعربي — ترجم أي معلومة إنجليزي للعربي
- تنظيم المعلومات بوضوح في أقسام
- ذكر المصادر والروابط الحقيقية
- مقارنة بين الآراء إن وُجدت
- استنتاجات وتوقعات إن أمكن
- الروابط: 🔗 <a href="الرابط">عنوان الرابط</a>

⚠️ ماتستخدمش Markdown أبداً (لا *, **, #, |, ---). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
        system = """أنت باحث متخصص في البحث العميق. تجيب بالعربية بشكل شامل ومفصل.
🔴 مهم: لازم تجيب بالعربي دايماً — ترجم أي محتوى إنجليزي للعربي.
تنظم المعلومات بشكل واضح مع ذكر المصادر.
ماتستخدمش Markdown أبداً. استخدم HTML فقط.
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

    response = call_ai_sync(prompt, system_prompt=system, task_type="deep_search", temperature=0.4, max_tokens=8192, user_id=user_id)
    from formatters import clean_ai_response
    if response:
        response = clean_ai_response(response)
    return response or ("لم أتمكن من معالجة نتائج البحث العميق. 🤖" if language == "ar" else "I couldn't process deep search results. 🤖")


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
        snippet = r.get("snippet", "")
        link = r.get("link", "")
        source = r.get("source", "")

        if language == "ar":
            message += f"{i}. 📄 <b>{title}</b>\n"
            if snippet:
                message += f"   {snippet[:200]}\n"
            if source:
                message += f"   📡 {source}\n"
            if link:
                message += f'   🔗 <a href="{link}">اقرأ المزيد</a>\n'
        else:
            message += f"{i}. 📄 <b>{title}</b>\n"
            if snippet:
                message += f"   {snippet[:200]}\n"
            if source:
                message += f"   📡 {source}\n"
            if link:
                message += f'   🔗 <a href="{link}">Read more</a>\n'
        message += "\n"

    message += "━━━━━━━━━━━━━━━━━\n🤖 <i>My Bro — بحث الويب</i>"
    return message
