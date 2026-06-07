"""
بحث الويب - Web Search Module
يستخدم DuckDuckGo (ddgs) للبحث مع تلخيص النتائج بالذكاء الاصطناعي
+ دعم المكالمات غير المتزامنة
"""

import asyncio
import logging
from typing import List, Dict, Optional

from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


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
    """البحث في الويب (متزامن)"""
    DDGS = _get_ddgs()
    if DDGS is None:
        return []

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

        logger.info(f"DuckDuckGo search for '{query}': found {len(results)} results")
        return results

    except Exception as e:
        logger.error(f"DuckDuckGo search error: {e}")
        return []


async def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """البحث في الويب (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _search_web_sync(query, max_results)
    )


def _search_news_sync(query: str, max_results: int = 5) -> List[Dict]:
    """البحث عن أخبار (متزامن)"""
    DDGS = _get_ddgs()
    if DDGS is None:
        return []

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

        logger.info(f"DuckDuckGo news search for '{query}': found {len(results)} results")
        return results

    except Exception as e:
        logger.error(f"DuckDuckGo news search error: {e}")
        return []


async def search_news_async(query: str, max_results: int = 5) -> List[Dict]:
    """البحث عن أخبار (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _search_news_sync(query, max_results)
    )


# Keep sync version for backward compatibility (main.py uses it)
def search_news(query: str, max_results: int = 5) -> List[Dict]:
    """البحث عن أخبار محددة في الويب (متزامن)"""
    return _search_news_sync(query, max_results)


def _search_and_summarize_sync(query: str, language: str = "ar") -> str:
    """البحث والتلخيص (متزامن)"""
    from ai_engine import _call_ai_sync

    results = _search_web_sync(query, max_results=5)

    if not results:
        if language == "ar":
            prompt = f"""أجب على السؤال التالي بأفضل ما تعرفه. إذا لم تكن متأكداً، اذكر ذلك.

السؤال: {query}

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code>"""
            system = "أنت مساعد ذكي تجيب بالعربية الفصحى. كن دقيقاً واستخدم إيموجي مناسبة. ماتستخدمش Markdown أبداً."
        else:
            prompt = f"""Answer the following question to the best of your knowledge. If unsure, say so.

Question: {query}

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code>"""
            system = "You are a smart assistant. Be accurate and use appropriate emojis. NEVER use Markdown."

        response = _call_ai_sync(prompt, system_prompt=system, temperature=0.5, max_tokens=1500)
        from formatters import clean_ai_response
        if response:
            response = clean_ai_response(response)
        return response or ("لم أتمكن من العثور على معلومات. 🤖" if language == "ar" else "I couldn't find information. 🤖")

    # تجميع نتائج البحث
    search_text = ""
    for i, r in enumerate(results, 1):
        search_text += f"\n--- نتيجة {i} ---\n"
        search_text += f"العنوان: {r['title']}\n"
        search_text += f"المقتطف: {r['snippet']}\n"
        search_text += f"الرابط: {r['link']}\n"

    if language == "ar":
        prompt = f"""بناءً على نتائج البحث التالية، أجب على سؤال المستخدم بالعربية الفصحى.
أضف الروابط المفيدة في إجابتك باستخدام تنسيق HTML.

سؤال المستخدم: {query}

نتائج البحث:{search_text}

التنسيق المطلوب:
- إجابة واضحة ومفيدة
- استخدم إيموجي مناسبة
- أضف الروابط المفيدة: 🔗 <a href="الرابط">عنوان الرابط</a>
- كن مختصراً لكن شاملاً

⚠️ ماتستخدمش Markdown أبداً (لا *, **, #, |, ---). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط"""
        system = "أنت مساعد ذكي يجيب بالعربية الفصحى بناءً على نتائج بحث حقيقية. استخدم إيموجي وتنسيق HTML جميل. ماتستخدمش Markdown أبداً."
    else:
        prompt = f"""Based on the following search results, answer the user's question in English.
Include useful links in your answer using HTML format.

User's question: {query}

Search results:{search_text}

Format requirements:
- Clear and helpful answer
- Use appropriate emojis
- Include useful links: 🔗 <a href="link">Link title</a>
- Be concise but comprehensive

⚠️ NEVER use Markdown (no *, **, #, |, ---). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets"""
        system = "You are a smart assistant answering based on real search results. Use emojis and nice HTML formatting. NEVER use Markdown."

    response = _call_ai_sync(prompt, system_prompt=system, temperature=0.5, max_tokens=1500)
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
