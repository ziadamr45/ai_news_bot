"""
تقييم الأخبار - News Scoring Module
يقوم بتقييم كل خبر بناءً على عدة معايير لاختيار الأهم
+ دعم وزن الشركات وتعدد المصادر
"""

import re
import logging
from typing import List, Dict
from urllib.parse import urlparse

from config import SCORE_WEIGHTS, SOURCE_CREDIBILITY, AI_KEYWORDS

logger = logging.getLogger(__name__)


def calculate_ai_relevance(title: str, description: str = "") -> float:
    """
    حساب صلة الخبر بالذكاء الاصطناعي (0-10)
    كلما زاد عدد الكلمات المفتاحية الموجودة، زادت النتيجة
    """
    text = f"{title} {description}".lower()
    match_count = 0
    total_keywords = len(AI_KEYWORDS)

    high_value_keywords = [
        "openai", "chatgpt", "gpt-4", "gpt-5", "o1", "o3", "o4",
        "gemini", "deepmind", "claude", "anthropic", "grok",
        "agi", "ai agents", "ai agent", "foundation model",
        "large language model", "sora"
    ]

    high_value_matches = 0
    for keyword in AI_KEYWORDS:
        if len(keyword) <= 4:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                match_count += 1
                if keyword in high_value_keywords:
                    high_value_matches += 1
        else:
            if keyword.lower() in text:
                match_count += 1
                if keyword in high_value_keywords:
                    high_value_matches += 1

    # النتيجة الأساسية بناءً على عدد التطابقات
    base_score = min(10, (match_count / 5) * 10)

    # Bonus for high-value keywords
    bonus = min(3, high_value_matches * 1.5)

    score = min(10, base_score + bonus)
    return round(score, 2)


def calculate_importance(title: str, description: str = "") -> float:
    """
    حساب أهمية الخبر (0-10)
    بناءً على كلمات تدل على أهمية كبيرة
    + تم التحسين: إضافة كلمات مفتاحية أكثر دقة
    """
    text = f"{title} {description}".lower()

    importance_keywords = [
        # إطلاق وإعلان
        ("breakthrough", 3.5), ("launched", 2.5), ("announced", 2.5),
        ("released", 2.5), ("unveiled", 2.5), ("introduced", 2),

        # أول مرة / تاريخي
        ("first", 2.5), ("first-ever", 3.5), ("revolutionary", 3.5),
        ("historic", 3.5), ("groundbreaking", 3.5), ("milestone", 3),

        # أهمية كبيرة
        ("major", 2.5), ("significant", 2), ("critical", 2.5),
        ("crucial", 2.5), ("massive", 2.5), ("huge", 2),

        # نماذج ومنتجات جديدة
        ("new model", 3.5), ("new ai", 3), ("next generation", 3),
        ("gpt-5", 4), ("gpt-4", 3), ("o1", 3), ("o3", 3), ("o4", 3),
        ("gemini 2", 3.5), ("claude 4", 3.5), ("llama 4", 3),

        # تحديثات
        ("update", 1.5), ("upgrade", 2), ("improvement", 1.5),

        # أعمال وتمويل
        ("acquisition", 3), ("billion", 2.5), ("funding", 2.5),
        ("investment", 2.5), ("ipo", 2.5),

        # تنظيم وتأثير
        ("banned", 2.5), ("regulation", 2.5), ("law", 2.5),
        ("restrict", 2.5), ("eu ai act", 3),

        # أداء وتفوق
        ("beat", 2.5), ("surpass", 2.5), ("record", 2.5),
        ("state of the art", 3), ("sota", 3),

        # مفتوح المصدر
        ("open source", 3), ("free", 1.5), ("democratize", 2.5),

        # شراكات
        ("partnership", 2), ("collaboration", 1.5), ("deal", 2),
    ]

    score = 0
    for keyword, weight in importance_keywords:
        if keyword in text:
            score += weight

    return min(10, round(score, 2))


def calculate_industry_impact(title: str, description: str = "") -> float:
    """
    حساب تأثير الخبر على الصناعة (0-10)
    بناءً على مدى تأثير الخبر على الصناعة ككل
    + تم التحسين: فئات تأثير أكثر دقة
    """
    text = f"{title} {description}".lower()

    impact_keywords = [
        # تأثير صناعي واسع
        ("industry", 2), ("enterprise", 2), ("business", 1.5),
        ("market", 2), ("competitor", 2.5), ("competition", 2),
        ("disrupt", 2.5), ("transform", 2),

        # تنظيم وسياسات
        ("regulation", 3), ("law", 3), ("ban", 3), ("policy", 2.5),
        ("governance", 2.5), ("compliance", 2),

        # سلامة ومخاطر
        ("safety", 2.5), ("risk", 2), ("danger", 2.5), ("threat", 2.5),
        ("security", 2.5), ("vulnerability", 2.5),

        # تأثير على التوظيف
        ("job", 2.5), ("employment", 2.5), ("workforce", 2.5),
        ("replace", 3), ("automation", 2.5), ("layoff", 2),

        # اقتصاد
        ("billion", 3), ("trillion", 3.5), ("investment", 2.5),
        ("revenue", 2), ("profit", 2),

        # شراكات
        ("partnership", 2), ("collaboration", 1.5), ("merger", 2.5),

        # مفتوح المصدر / ديمقراطية
        ("open source", 3), ("democratize", 2.5), ("free access", 2),

        # قطاعات متأثرة
        ("medical", 2), ("healthcare", 2.5), ("education", 2),
        ("military", 3), ("defense", 2.5), ("finance", 2),
        ("legal", 2), ("creative", 1.5),

        # روبوتات وآلي
        ("robot", 2.5), ("humanoid", 3), ("autonomous", 2.5),
        ("self-driving", 2.5), ("embodied ai", 2.5),
    ]

    score = 0
    for keyword, weight in impact_keywords:
        if keyword in text:
            score += weight

    return min(10, round(score, 2))


def get_source_credibility(url: str) -> float:
    """
    حساب مصداقية المصدر (0-10)
    بناءً على جدول المصادر الموثوقة
    """
    try:
        domain = urlparse(url).netloc.lower()
        # إزالة www. لو موجود
        domain = domain.replace("www.", "")

        # البحث المباشر
        if domain in SOURCE_CREDIBILITY:
            return SOURCE_CREDIBILITY[domain]

        # البحث الجزئي
        for source_domain, score in SOURCE_CREDIBILITY.items():
            if source_domain in domain or domain in source_domain:
                return score

    except Exception as e:
        logger.warning(f"Error parsing URL for credibility: {e}")

    # قيمة افتراضية للمصادر غير المعروفة
    return 5.0


def calculate_article_score(article: Dict) -> float:
    """
    حساب النتيجة الإجمالية للخبر
    + دعم وزن إضافي للشركات وتعدد المصادر
    """
    title = article.get("title", "")
    description = article.get("description", "")
    url = article.get("link", "")

    ai_relevance = calculate_ai_relevance(title, description)
    importance = calculate_importance(title, description)
    industry_impact = calculate_industry_impact(title, description)
    source_credibility = get_source_credibility(url)

    # حساب النتيجة المرجحة
    total_score = (
        ai_relevance * SCORE_WEIGHTS["ai_relevance"] +
        importance * SCORE_WEIGHTS["importance"] +
        industry_impact * SCORE_WEIGHTS["industry_impact"] +
        source_credibility * SCORE_WEIGHTS["source_credibility"]
    )

    article["scores"] = {
        "ai_relevance": ai_relevance,
        "importance": importance,
        "industry_impact": industry_impact,
        "source_credibility": source_credibility,
        "total": round(total_score, 2)
    }

    logger.info(f"Score for '{title[:50]}': {total_score:.2f} "
                f"(AI:{ai_relevance} Imp:{importance} Impact:{industry_impact} Src:{source_credibility})")

    return total_score


def rank_articles(articles: List[Dict], max_count: int = 50, min_count: int = 0) -> List[Dict]:
    """
    ترتيب الأخبار حسب النتيجة
    + إذا كان news_editor متاح، يتم استخدام الخط التحريري
    """
    if not articles:
        return articles

    # حساب النتيجة لكل خبر
    for article in articles:
        calculate_article_score(article)

    # محاولة استخدام الخط التحريري المتقدم
    try:
        from news_editor import run_editorial_pipeline
        # تحديد عدد الأخبار المناسب
        editorial_max = min(max_count, 10)  # النشرة اليومية عادة 10 أخبار
        selected = run_editorial_pipeline(articles, max_articles=editorial_max)
        if selected:
            return selected
    except ImportError:
        logger.info("news_editor not available, using basic ranking")
    except Exception as e:
        logger.warning(f"Editorial pipeline error, falling back to basic ranking: {e}")

    # Fallback: الترتيب الأساسي
    sorted_articles = sorted(articles, key=lambda x: x["scores"]["total"], reverse=True)

    count = min(max_count, len(sorted_articles))
    selected = sorted_articles[:count]

    # تحديد أهم خبر
    if selected:
        selected[0]["is_top"] = True
        for article in selected[1:]:
            article["is_top"] = False

    logger.info(f"Selected {len(selected)} articles out of {len(articles)}")
    for i, article in enumerate(selected):
        logger.info(f"  #{i+1}: {article['title'][:60]} (Score: {article['scores']['total']})")

    return selected
