"""
تلخيص الأخبار - News Summarizer Module
يستخدم Gemini API لتلخيص الأخبار بالعربية
"""

import logging
from typing import List, Dict, Optional

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)

# تعيين الـ API Key
genai.configure(api_key=GEMINI_API_KEY)


def create_summary_prompt(articles: List[Dict]) -> str:
    """
    إنشاء الـ prompt لإرساله لـ Gemini
    """
    articles_text = ""
    for i, article in enumerate(articles, 1):
        articles_text += f"\n--- الخبر {i} ---\n"
        articles_text += f"العنوان: {article.get('title', '')}\n"
        articles_text += f"الوصف: {article.get('description', '')}\n"
        articles_text += f"المصدر: {article.get('source', '')}\n"
        articles_text += f"الرابط: {article.get('link', '')}\n"

    prompt = f"""أنت خبير في أخبار الذكاء الاصطناعي. قم بتلخيص الأخبار التالية باللغة العربية.

المطلوب:
1. تلخيص كل خبر في 2-3 جمل بالعربية الفصحى
2. التركيز على الجوهر والأهمية
3. استخدام لغة واضحة ومباشرة
4. ذكر اسم الشركة أو المنتج إن وُجد
5. عدم إضافة معلومات غير موجودة في الخبر الأصلي
6. التلخيص يجب أن يكون مفيد للقارئ العربي المهتم بالذكاء الاصطناعي

الأخبار:{articles_text}

قم بإرجاع التلخيصات في الصيغة التالية لكل خبر:
SUMMARY_START
[التلخيص بالعربية]
SUMMARY_END"""

    return prompt


def parse_summaries(response_text: str, num_articles: int) -> List[str]:
    """
    استخراج التلخيصات من رد Gemini
    """
    summaries = []

    # محاولة استخراج بالصيغة المحددة
    parts = response_text.split("SUMMARY_START")
    for part in parts[1:]:  # تجاهل الجزء الأول قبل أول SUMMARY_START
        end_idx = part.find("SUMMARY_END")
        if end_idx != -1:
            summary = part[:end_idx].strip()
            if summary:
                summaries.append(summary)

    # لو الصيغة المحددة ماشتغلتش، بنقسم بالأرقام
    if len(summaries) != num_articles:
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

    # التأكد من عدد التلخيصات
    if len(summaries) < num_articles:
        # إضافة تلخيصات فارغة لو ناقصة
        while len(summaries) < num_articles:
            summaries.append("تفاصيل الخبر متاحة عبر الرابط المرفق.")

    # اقتطاع لو زائدة
    summaries = summaries[:num_articles]

    return summaries


def summarize_articles(articles: List[Dict]) -> List[Dict]:
    """
    تلخيص قائمة الأخبار باستخدام Gemini API
    """
    if not articles:
        logger.warning("No articles to summarize")
        return articles

    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not set. Using descriptions as summaries.")
        for article in articles:
            article["arabic_summary"] = article.get("description", "")[:200]
        return articles

    logger.info(f"Summarizing {len(articles)} articles using Gemini API...")

    prompt = create_summary_prompt(articles)

    for attempt in range(MAX_RETRIES):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=2048,
                )
            )

            if response and response.text:
                summaries = parse_summaries(response.text, len(articles))

                for i, article in enumerate(articles):
                    if i < len(summaries):
                        article["arabic_summary"] = summaries[i]
                    else:
                        article["arabic_summary"] = article.get("description", "")[:200]

                logger.info(f"Successfully summarized {len(summaries)} articles")
                return articles
            else:
                logger.warning(f"Gemini returned empty response (attempt {attempt + 1})")

        except Exception as e:
            logger.error(f"Gemini API error (attempt {attempt + 1}): {e}")

        if attempt < MAX_RETRIES - 1:
            import time
            time.sleep(RETRY_DELAY)

    # في حالة فشل كل المحاولات، نستخدم الوصف الأصلي
    logger.warning("All Gemini attempts failed. Using original descriptions.")
    for article in articles:
        desc = article.get("description", "")
        article["arabic_summary"] = desc[:200] if desc else "تفاصيل الخبر متاحة عبر الرابط المرفق."

    return articles
