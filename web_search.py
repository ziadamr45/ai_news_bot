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

from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# Tavily API (بحث حقيقي بأفضل جودة)
# ═══════════════════════════════════════

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")


def _search_tavily_sync(query: str, max_results: int = 5, search_depth: str = "basic") -> List[Dict]:
    """بحث عبر Tavily API (أفضل جودة - بحث حقيقي)"""
    if not TAVILY_API_KEY:
        logger.warning("⚠️ TAVILY_API_KEY not set! Set it as environment variable.")
        return []

    # محاولة 1: استخدام tavily-python SDK
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        
        if search_depth == "advanced":
            response = client.search(query, max_results=max_results, search_depth="advanced", include_answer=True)
        else:
            response = client.search(query, max_results=max_results, search_depth="basic", include_answer=True)
        
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

        response = requests.post(url, json=payload, timeout=20)
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


def _search_web_sync(query: str, max_results: int = 5) -> List[Dict]:
    """البحث في الويب (متزامن) - Tavily أولاً ثم DuckDuckGo"""
    # محاولة Tavily أولاً (أفضل جودة - بحث حقيقي)
    if TAVILY_API_KEY:
        tavily_results = _search_tavily_sync(query, max_results)
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
                search_results = list(ddgs.text(query, max_results=max_results))

                for r in search_results:
                    results.append({
                        "title": r.get("title", ""),
                        "link": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })

            logger.info(f"✅ DuckDuckGo search for '{query}': found {len(results)} results")

            # لو النتائج قليلة، نجرب بحث أوسع
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
                    results = unique_results[:max_results]

            return results

        except Exception as e:
            logger.error(f"DuckDuckGo search error (attempt {attempt+1}): {e}")
            if attempt == 0:
                import time
                time.sleep(1)
                continue

    return []


async def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """البحث في الويب (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _search_web_sync(query, max_results)
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
            response = requests.post(url, json=payload, timeout=15)
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

def _search_and_summarize_sync(query: str, language: str = "ar") -> str:
    """البحث والتلخيص (متزامن) - بحث حقيقي في الويب"""
    from provider_manager import call_ai_sync

    logger.info(f"🔍 Starting web search for: {query}")
    results = _search_web_sync(query, max_results=5)

    if not results:
        logger.warning(f"⚠️ No search results found for: {query}")
        if language == "ar":
            prompt = f"""أنا بحثت في الويب عن سؤالك بس ملقيتش نتائج كافية. هجاوبك بأفضل اللي أعرفه، بس ممكن المعلومات تكون مش دقيقة لأنها من ذاكرتي مش من نتائج بحث حقيقية.

السؤال: {query}

⚠️ مهم: قول للمستخدم إنك بحثت وملقيتش نتائج كافية، وإن المعلومات دي من معرفتك الشخصية وممكن تكون مش محدثة. لو السؤال عن أحداث حديثة، نصحه يبحث بنفسه.

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code>"""
            system = "أنت مساعد ذكي تجيب بالعربية الفصحى. كن دقيقاً واستخدم إيموجي مناسبة. ماتستخدمش Markdown أبداً. لو مش متأكد من معلومة، قول صراحة."
        else:
            prompt = f"""I searched the web for your question but couldn't find sufficient results. I'll answer from my knowledge, but this may not be up-to-date.

Question: {query}

⚠️ Important: Tell the user you searched but found limited results, and that this info is from your training data and may not be current. If asking about recent events, suggest they verify.

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code>"""
            system = "You are a smart assistant. Be honest about limitations. NEVER use Markdown."

        response = call_ai_sync(prompt, system_prompt=system, task_type="chat", temperature=0.5, max_tokens=1500)
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

    if language == "ar":
        prompt = f"""🔬 بحثت في الويب وجبت لك نتائج حقيقية! بناءً على نتائج البحث التالية، أجب على سؤال المستخدم بالعربية بطريقة مفيدة وشاملة.

⚠️ مهم جداً: المعلومات دي من بحث حقيقي في الويب - استخدمها كلها واختار الأهم. ماتخترعش معلومات مش في النتائج.

سؤال المستخدم: {query}

نتائج البحث الحقيقية:{search_text}

المطلوب:
- إجابة واضحة ومفيدة وشاملة بناءً على نتائج البحث
- تنظيم المعلومات بوضوح
- ذكر المصادر والروابط
- استخدم إيموجي مناسبة
- الروابط: 🔗 <a href="الرابط">عنوان الرابط</a>
- كن مفصلاً ومفيداً

⚠️ ماتستخدمش Markdown أبداً (لا *, **, #, |, ---). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
        system = "أنت مساعد ذكي يجيب بناءً على نتائج بحث حقيقية من الويب. ماتخترعش معلومات مش في النتائج. استخدم إيموجي وتنسيق HTML جميل. كن مفصلاً ومفيداً. ماتستخدمش Markdown أبداً."
    else:
        prompt = f"""🔬 I searched the web and found real results! Based on the following search results, answer the user's question comprehensively.

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

    response = call_ai_sync(prompt, system_prompt=system, task_type="chat", temperature=0.5, max_tokens=2000)
    from formatters import clean_ai_response
    if response:
        response = clean_ai_response(response)
    return response or ("لم أتمكن من معالجة نتائج البحث. 🤖" if language == "ar" else "I couldn't process search results. 🤖")


async def search_and_summarize_async(query: str, language: str = "ar") -> str:
    """البحث والتلخيص (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _search_and_summarize_sync(query, language)
    )


# Keep sync version for backward compatibility
def search_and_summarize(query: str, language: str = "ar") -> str:
    """البحث والتلخيص (متزامن - للتوافق مع الكود القديم)"""
    return _search_and_summarize_sync(query, language)


# ═══════════════════════════════════════
# البحث العميق - Deep Search
# ═══════════════════════════════════════

def _deep_search_and_summarize_sync(query: str, language: str = "ar") -> str:
    """
    البحث العميق - يستخدم Tavily Advanced + DuckDuckGo + بحث أخبار
    ثم يلخص بنموذج Deep Search مخصص
    """
    from provider_manager import call_ai_sync

    logger.info(f"🔬 Starting DEEP search for: {query}")

    # 1. بحث متعدد المصادر
    web_results = _search_web_sync(query, max_results=8)
    news_results = _search_news_sync(query, max_results=5)

    # Tavily بحث عميق
    tavily_deep_results = []
    if TAVILY_API_KEY:
        tavily_deep_results = _search_tavily_sync(query, max_results=5, search_depth="advanced")

    all_results_count = len(web_results) + len(news_results) + len(tavily_deep_results)
    logger.info(f"🔬 Deep search found {all_results_count} total results (web={len(web_results)}, news={len(news_results)}, tavily_adv={len(tavily_deep_results)})")

    if all_results_count == 0:
        # لو مفيش نتائج، نحاول بالإجابة المباشرة مع تحذير
        if language == "ar":
            prompt = f"""بحثت بعمق في الويب عن سؤالك بس ملقيتش نتائج كافية. هجاوبك بأفضل اللي أعرفه، بس خلي بالك إن المعلومات دي ممكن تكون مش محدثة لأنها من ذاكرتي.

السؤال: {query}

⚠️ مهم: قول صراحة إنك بحثت وملقيتش نتائج، وإن إجابتك ممكن تكون مش دقيقة لأنها من بياناتك القديمة.

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
            system = "أنت باحث متخصص. تجيب بالعربية بشكل شامل. لو مش متأكد، قول صراحة. ماتستخدمش Markdown أبداً."
        else:
            prompt = f"""I did a deep search but couldn't find sufficient results. I'll answer from my knowledge, but this may not be up-to-date.

Question: {query}

⚠️ Important: Be honest that you searched but found limited results, and your answer may not be current.

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets"""
            system = "You are a researcher. Be honest about limitations. NEVER use Markdown."

        response = call_ai_sync(prompt, system_prompt=system, task_type="deep_search", temperature=0.4, max_tokens=3000)
        from formatters import clean_ai_response
        if response:
            response = clean_ai_response(response)
        return response or ("لم أتمكن من العثور على معلومات كافية. 🤖" if language == "ar" else "I couldn't find enough information. 🤖")

    # 2. تجميع كل النتائج
    search_text = ""

    # دمج Tavily deep results
    if tavily_deep_results:
        search_text += "\n🔬 نتائج Tavily المتقدمة:\n" if language == "ar" else "\n🔬 Tavily Advanced Results:\n"
        for i, r in enumerate(tavily_deep_results, 1):
            search_text += f"\n--- نتيجة متقدمة {i} ---\n"
            search_text += f"العنوان: {r['title']}\n"
            search_text += f"المحتوى: {r['snippet']}\n"
            if r.get('link'):
                search_text += f"الرابط: {r['link']}\n"
            if r.get('source'):
                search_text += f"المصدر: {r['source']}\n"

    if web_results:
        search_text += "\n🌐 نتائج بحث الويب:\n" if language == "ar" else "\n🌐 Web Search Results:\n"
        for i, r in enumerate(web_results, 1):
            search_text += f"\n--- نتيجة ويب {i} ---\n"
            search_text += f"العنوان: {r['title']}\n"
            search_text += f"المقتطف: {r['snippet']}\n"
            search_text += f"الرابط: {r['link']}\n"

    if news_results:
        search_text += "\n📰 نتائج أخبار:\n" if language == "ar" else "\n📰 News Results:\n"
        for i, r in enumerate(news_results, 1):
            search_text += f"\n--- خبر {i} ---\n"
            search_text += f"العنوان: {r['title']}\n"
            search_text += f"المقتطف: {r['snippet']}\n"
            search_text += f"الرابط: {r['link']}\n"
            if r.get('source'):
                search_text += f"المصدر: {r['source']}\n"
            if r.get('date'):
                search_text += f"التاريخ: {r['date']}\n"

    # 3. تلخيص شامل
    if language == "ar":
        prompt = f"""🔬 <b>بحث عميق</b>

بحثت بعمق في الويب وجبت لك نتائج حقيقية من مصادر متعددة! بناءً على النتائج دي، قدّم إجابة مفصلة ومنظمة.

⚠️ مهم جداً: المعلومات دي من بحث حقيقي — استخدمها كلها واختار الأهم. ماتخترعش أي معلومة مش موجودة في النتائج.

سؤال المستخدم: {query}

نتائج البحث الشاملة:{search_text}

المطلوب:
- إجابة شاملة ومفصلة جداً
- تنظيم المعلومات بوضوح في أقسام
- ذكر المصادر والروابط الحقيقية
- مقارنة بين الآراء إن وُجدت
- استنتاجات وتوقعات إن أمكن
- الروابط: 🔗 <a href="الرابط">عنوان الرابط</a>

⚠️ ماتستخدمش Markdown أبداً (لا *, **, #, |, ---). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
        system = """أنت باحث متخصص في البحث العميق. تجيب بالعربية بشكل شامل ومفصل.
تنظم المعلومات بشكل واضح مع ذكر المصادر.
ماتستخدمش Markdown أبداً. استخدم HTML فقط.
ماتخترعش معلومات مش في نتائج البحث - لو مش متأكد، قول صراحة."""
    else:
        prompt = f"""🔬 <b>Deep Search</b>

I did a deep web search and found real results from multiple sources! Based on these results, provide a detailed and organized answer.

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

    response = call_ai_sync(prompt, system_prompt=system, task_type="deep_search", temperature=0.4, max_tokens=4000)
    from formatters import clean_ai_response
    if response:
        response = clean_ai_response(response)
    return response or ("لم أتمكن من معالجة نتائج البحث العميق. 🤖" if language == "ar" else "I couldn't process deep search results. 🤖")


async def deep_search_and_summarize_async(query: str, language: str = "ar") -> str:
    """البحث العميق والتلخيص (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _deep_search_and_summarize_sync(query, language)
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
