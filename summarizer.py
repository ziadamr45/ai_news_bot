"""
تلخيص الأخبار - News Summarizer Module
يستخدم Provider Manager لتلخيص الأخبار بالعربية
+ دعم المكالمات غير المتزامنة
+ تبديل تلقائي بين المزودين
"""

import asyncio
import logging
import time as time_module
from typing import List, Dict, Optional

from provider_manager import get_provider_manager
from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


def create_summary_prompt(articles: List[Dict]) -> str:
    """إنشاء prompt تلخيص الأخبار مع سياق التاريخ"""
    from datetime import datetime
    now = datetime.now()
    today_str = f"{now.year}-{now.month:02d}-{now.day:02d}"
    today_ar = f"{now.day}/{now.month}/{now.year}"

    articles_text = ""
    for i, article in enumerate(articles, 1):
        articles_text += f"\n--- الخبر {i} ---\n"
        articles_text += f"العنوان: {article.get('title', '')}\n"
        articles_text += f"الوصف: {article.get('description', '')}\n"
        articles_text += f"المصدر: {article.get('source', '')}\n"
        articles_text += f"الرابط: {article.get('link', '')}\n"
        # أضف تاريخ الخبر لو موجود
        published = article.get('published')
        if published:
            try:
                if hasattr(published, 'strftime'):
                    articles_text += f"تاريخ النشر: {published.strftime('%Y-%m-%d')}\n"
            except Exception:
                pass

    prompt = f"""أنت خبير في أخبار الذكاء الاصطناعي. قم بتلخيص الأخبار التالية باللغة العربية.

🔴 مهم جدًا: تاريخ اليوم هو {today_ar} ({today_str}).
- ماتضيفش أي تاريخ مش موجود في الخبر الأصلي
- ماتقولش "يونيو 2026" أو أي سنة/شهر مش موجود في الخبر
- لو الخبر مفيهوش تاريخ، ماتخترعش واحد
- لو الخبر قديم، تلخصه عادي بس ماتقولش إنه جديد أو حديث

المطلوب:
1. تلخيص كل خبر في 2-3 جمل بالعربية الفصحى
2. التركيز على الجوهر والأهمية
3. استخدام لغة واضحة ومباشرة
4. ذكر اسم الشركة أو المنتج إن وُجد
5. عدم إضافة معلومات غير موجودة في الخبر الأصلي — خصوصًا التواريخ!
6. التلخيص يجب أن يكون مفيد للقارئ العربي المهتم بالذكاء الاصطناعي
7. التلخيص يجب أن يكون بالعربية فقط
8. 🔴 مهم: لكل خبر، اكتب عنوان عربي مختصر وواضح

الأخبار:{articles_text}

قم بإرجاع التلخيصات في الصيغة التالية لكل خبر:
TITLE_START
[العنوان العربي المختصر]
TITLE_END
SUMMARY_START
[التلخيص بالعربية]
SUMMARY_END"""

    return prompt


def parse_summaries(response_text: str, num_articles: int) -> tuple:
    """Parse AI response to extract Arabic titles and summaries.
    Returns: (titles_list, summaries_list)
    """
    titles = []
    summaries = []

    # محاولة 1: استخراج بالتنسيق الجديد (TITLE_START/TITLE_END + SUMMARY_START/SUMMARY_END)
    title_parts = response_text.split("TITLE_START")
    for part in title_parts[1:]:
        end_idx = part.find("TITLE_END")
        if end_idx != -1:
            title = part[:end_idx].strip()
            if title:
                titles.append(title)

    summary_parts = response_text.split("SUMMARY_START")
    for part in summary_parts[1:]:
        end_idx = part.find("SUMMARY_END")
        if end_idx != -1:
            summary = part[:end_idx].strip()
            if summary:
                summaries.append(summary)

    # لو مفيش عناوين بالتنسيق الجديد، نرجع للتنسيق القديم
    if not summaries:
        summaries = []
        lines = response_text.strip().split("\n")
        current_summary = []

        for line in lines:
            line = line.strip()
            if not line:
                if current_summary:
                    summary_text = " ".join(current_summary).strip()
                    if summary_text and len(summary_text) > 10:
                        summaries.append(summary_text)
                    current_summary = []
                continue
            current_summary.append(line)

        if current_summary:
            summary_text = " ".join(current_summary).strip()
            if summary_text and len(summary_text) > 10:
                summaries.append(summary_text)

    # لو مفيش عناوين كفاية، نكمل بعناوين فارغة
    if len(titles) < num_articles:
        while len(titles) < num_articles:
            titles.append("")

    # لو مفيش ملاخصات كفاية، نكمل
    if len(summaries) < num_articles:
        while len(summaries) < num_articles:
            summaries.append("تفاصيل الخبر متاحة عبر الرابط المرفق.")

    titles = titles[:num_articles]
    summaries = summaries[:num_articles]

    return (titles, summaries)


def _summarize_articles_sync(articles: List[Dict]) -> List[Dict]:
    """تلخيص الأخبار (متزامن - باستخدام Provider Manager)
    
    ⚠️ BUG FIX: Added structured logging for provider failures and a retry
    mechanism. Previously, when all summary providers failed, the function
    silently replaced article summaries with truncated English descriptions.
    Now it logs which providers failed and why, and attempts one retry with
    extended timeout before falling back to raw descriptions.
    """
    if not articles:
        return articles

    manager = get_provider_manager()

    # فحص هل في مزودين متاحين
    routes = manager.get_model_routes("summary")
    if not routes:
        logger.warning("⚠️ No summary providers available — checking cooldown status...")
        # Log each provider's status for diagnostics
        for pname, pconf in manager.providers.items():
            if pconf.cooldown_until > time_module.time():
                remaining = int(pconf.cooldown_until - time_module.time())
                logger.warning(f"  Provider '{pname}' on cooldown: {remaining}s remaining (last error: {pconf.last_error})")
            else:
                logger.warning(f"  Provider '{pname}' unavailable: no API key or not configured for summary")
        
        # Try with cooldown ignored as last resort
        routes = manager.get_model_routes("summary", ignore_cooldown=True)
        if not routes:
            logger.error("❌ All summary providers failed — using original descriptions as fallback")
            for article in articles:
                desc = article.get("description", "")
                article["arabic_summary"] = desc[:200] if desc else "تفاصيل الخبر متاحة عبر الرابط المرفق."
            return articles

    logger.info(f"Summarizing {len(articles)} articles using {len(routes)} available route(s)...")

    prompt = create_summary_prompt(articles)
    from datetime import datetime
    now = datetime.now()
    today_str = f"{now.year}-{now.month:02d}-{now.day:02d}"
    system_prompt = f"أنت مساعد عربي متخصص في أخبار الذكاء الاصطناعي. تجيب دائمًا بالعربية الفصحى فقط. تاريخ اليوم: {today_str}. ماتخترعش تواريخ مش موجودة في الأخبار الأصلية."

    # محاولة 1: استدعاء عادي
    response = manager.call_with_system_prompt_sync(
        prompt=prompt,
        system_prompt=system_prompt,
        task_type="summary",
        temperature=0.3,
        max_tokens=8192,
    )

    # محاولة 2: Retry مع timeout أطول
    if not response:
        logger.warning("⚠️ First summarization attempt failed — retrying with extended timeout (90s)...")
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        
        response = manager.call_with_system_prompt_sync(
            prompt=prompt,
            system_prompt=system_prompt,
            task_type="summary",
            temperature=0.3,
            max_tokens=8192,
            timeout=90,
        )
        
        if response:
            logger.info("✅ Summary retry succeeded with extended timeout")
        else:
            logger.error("❌ Summary retry also failed — falling back to original descriptions")

    if response:
        titles, summaries = parse_summaries(response, len(articles))
        for i, article in enumerate(articles):
            if i < len(summaries):
                article["arabic_summary"] = summaries[i]
            else:
                desc = article.get("description", "")
                article["arabic_summary"] = desc[:200] if desc else "تفاصيل الخبر متاحة عبر الرابط المرفق."
            # 🔴 FIX: نضيف العنوان العربي لو موجود
            if i < len(titles) and titles[i]:
                article["arabic_title"] = titles[i]
            else:
                article["arabic_title"] = ""
        logger.info(f"✅ Successfully summarized {len(summaries)} articles (with {len([t for t in titles if t])} Arabic titles)")
        return articles

    logger.error("❌ All summarization attempts failed — using original descriptions as fallback")
    for article in articles:
        desc = article.get("description", "")
        article["arabic_summary"] = desc[:200] if desc else "تفاصيل الخبر متاحة عبر الرابط المرفق."

    return articles


async def summarize_articles(articles: List[Dict]) -> List[Dict]:
    """تلخيص الأخبار (غير متزامن)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _summarize_articles_sync(articles)
    )
