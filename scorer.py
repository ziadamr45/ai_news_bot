"""
تقييم الأخبار - News Scoring Module
يقوم بتقييم كل خبر بناءً على عدة معايير لاختيار الأهم
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
    """
    text = f"{title} {description}".lower()

    importance_keywords = [
        ("breakthrough", 3), ("announced", 2), ("launched", 2), ("released", 2),
        ("first", 2), ("revolutionary", 3), ("historic", 3), ("major", 2),
        ("groundbreaking", 3), ("new model", 3), ("new ai", 2.5),
        ("update", 1.5), ("upgrade", 1.5), ("unveiled", 2),
        ("acquisition", 2.5), ("billion", 2), ("funding", 2),
        ("banned", 2), ("regulation", 2), ("law", 2),
        ("beat", 2), ("surpass", 2), ("record", 2),
        ("open source", 2.5), ("free", 1.5),
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
    """
    text = f"{title} {description}".lower()

    impact_keywords = [
        ("industry", 2), ("enterprise", 2), ("business", 1.5),
        ("market", 2), ("competitor", 2), ("competition", 2),
        ("regulation", 3), ("law", 3), ("ban", 3), ("policy", 2.5),
        ("safety", 2), ("risk", 2), ("danger", 2), ("threat", 2),
        ("job", 2), ("employment", 2), ("workforce", 2), ("replace", 2.5),
        ("billion", 3), ("trillion", 3), ("investment", 2.5),
        ("partnership", 2), ("collaboration", 1.5),
        ("open source", 3), ("democratize", 2.5),
        ("medical", 2), ("healthcare", 2), ("education", 2),
        ("military", 3), ("defense", 2.5),
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


def rank_articles(articles: List[Dict], max_count: int = 5, min_count: int = 3) -> List[Dict]:
    """
    ترتيب الأخبار حسب النتيجة واختيار الأهم
    """
    # حساب النتيجة لكل خبر
    for article in articles:
        calculate_article_score(article)

    # ترتيب تنازلي
    sorted_articles = sorted(articles, key=lambda x: x["scores"]["total"], reverse=True)

    # تحديد عدد الأخبار
    count = min(max_count, len(sorted_articles))

    # لو أقل من الحد الأدنى، نرجع اللي عندنا
    if len(sorted_articles) < min_count:
        # بس لازم تكون أخبار مهمة (نتيجة > 3)
        significant = [a for a in sorted_articles if a["scores"]["total"] > 3]
        if len(significant) < min_count:
            logger.info(f"Not enough significant articles ({len(significant)} < {min_count})")
            return significant

    selected = sorted_articles[:count]

    # تحديد أهم خبر
    if selected:
        selected[0]["is_top"] = True
        for article in selected[1:]:
            article["is_top"] = False

    logger.info(f"Selected top {len(selected)} articles out of {len(articles)}")
    for i, article in enumerate(selected):
        logger.info(f"  #{i+1}: {article['title'][:60]} (Score: {article['scores']['total']})")

    return selected
