"""
تلخيص الأخبار - News Summarizer Module
يستخدم OpenRouter API (متوافق مع OpenAI) لتلخيص الأخبار بالعربية
"""

import logging
from typing import List, Dict, Optional

import requests

from config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    OPENROUTER_FALLBACK_MODELS, FAST_MODEL, MAX_RETRIES, RETRY_DELAY,
    REQUEST_TIMEOUT, FAST_TIMEOUT
)

logger = logging.getLogger(__name__)


def create_summary_prompt(articles: List[Dict]) -> str:
    """
    إنشاء الـ prompt لإرساله للنموذج
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
7. التلخيص يجب أن يكون بالعربية فقط

الأخبار:{articles_text}

قم بإرجاع التلخيصات في الصيغة التالية لكل خبر:
SUMMARY_START
[التلخيص بالعربية]
SUMMARY_END"""

    return prompt


def parse_summaries(response_text: str, num_articles: int) -> List[str]:
    """
    استخراج التلخيصات من رد النموذج
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

    # لو الصيغة المحددة ماشتغلتش، بنقسم بالفقرات
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


def _call_openrouter(prompt: str, model: str) -> Optional[str]:
    """
    استدعاء OpenRouter API (متوافق مع OpenAI)
    """
    url = f"{OPENROUTER_BASE_URL}/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ziadamr45/ai-news-bot",
        "X-Title": "AI News Telegram Bot",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "أنت مساعد عربي متخصص في أخبار الذكاء الاصطناعي. تجيب دائماً بالعربية الفصحى فقط."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()

        data = response.json()

        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0].get("message", {}).get("content", "")
            if content:
                return content

        # التحقق من وجود خطأ في الرد
        if "error" in data:
            logger.warning(f"OpenRouter API error for {model}: {data['error']}")

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout calling OpenRouter with model {model}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Request error for model {model}: {str(e)[:150]}")
    except Exception as e:
        logger.warning(f"Unexpected error for model {model}: {str(e)[:150]}")

    return None


def summarize_articles(articles: List[Dict]) -> List[Dict]:
    """
    تلخيص قائمة الأخبار باستخدام OpenRouter API
    يجرب الموديل الرئيسي ثم الموديلات البديلة
    """
    if not articles:
        logger.warning("No articles to summarize")
        return articles

    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set. Using descriptions as summaries.")
        for article in articles:
            article["arabic_summary"] = article.get("description", "")[:200]
        return articles

    logger.info(f"Summarizing {len(articles)} articles using OpenRouter API...")

    prompt = create_summary_prompt(articles)

    # قائمة الموديلات للتجربة (السريع أولاً + الرئيسي + البدائل)
    if FAST_MODEL:
        models_to_try = [FAST_MODEL, OPENROUTER_MODEL] + OPENROUTER_FALLBACK_MODELS
    else:
        models_to_try = [OPENROUTER_MODEL] + OPENROUTER_FALLBACK_MODELS

    for attempt in range(MAX_RETRIES):
        for model in models_to_try:
            logger.info(f"Trying model: {model} (attempt {attempt + 1})")
            result = _call_openrouter(prompt, model)

            if result:
                summaries = parse_summaries(result, len(articles))

                for i, article in enumerate(articles):
                    if i < len(summaries):
                        article["arabic_summary"] = summaries[i]
                    else:
                        article["arabic_summary"] = article.get("description", "")[:200]

                logger.info(f"Successfully summarized {len(summaries)} articles using {model}")
                return articles

        # انتظار قبل إعادة المحاولة
        if attempt < MAX_RETRIES - 1:
            import time
            logger.info(f"Waiting {RETRY_DELAY}s before retry...")
            time.sleep(RETRY_DELAY)

    # في حالة فشل كل المحاولات، نستخدم الوصف الأصلي
    logger.warning("All OpenRouter attempts failed. Using original descriptions.")
    for article in articles:
        desc = article.get("description", "")
        article["arabic_summary"] = desc[:200] if desc else "تفاصيل الخبر متاحة عبر الرابط المرفق."

    return articles
