"""
نظام التحرير الصحفي - Professional News Editorial System
يحول البوت من مجرد جامع أخبار لمحرر صحفي محترف

يشمل:
- جدول sent_articles لمنع تكرار الأخبار عبر الأيام
- كشف مكررات ذكي (fuzzy matching + semantic similarity)
- تصنيف الأخبار حسب الفئات (نماذج، أبحاث، تنظيم، تمويل، شركات كبرى...)
- وزن الشركات (OpenAI, Google, Anthropic... لهم أولوية أعلى)
- التحقق من تعدد المصادر (خبر مذكور في 5 مصادر = خبر مهم)
- ضمان تفرد النشرة اليومية
- حد أدنى للجودة (لا نرسل أخبار ضعيفة لمجرد ملء المساحة)
- اختيار الخبر الأهم كـ "خبر اليوم"
- مراجعة تحريرية نهائية قبل الإرسال
"""

import re
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from collections import Counter
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

CAIRO_TZ = timezone(timedelta(hours=2))


# ═══════════════════════════════════════
# 1. جدول sent_articles - Persistent Dedup Table
# ═══════════════════════════════════════

def init_sent_articles_table():
    """إنشاء جدول sent_articles في قاعدة البيانات"""
    from memory import _execute, _is_postgres

    try:
        if _is_postgres():
            _execute("""
                CREATE TABLE IF NOT EXISTS sent_articles (
                    id SERIAL PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_hash TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    published_date TEXT DEFAULT NULL,
                    sent_date TEXT NOT NULL,
                    score REAL DEFAULT 0,
                    is_top_story INTEGER DEFAULT 0,
                    UNIQUE(url, sent_date)
                );
            """)
            _execute("CREATE INDEX IF NOT EXISTS idx_sent_url ON sent_articles(url);")
            _execute("CREATE INDEX IF NOT EXISTS idx_sent_title_hash ON sent_articles(title_hash);")
            _execute("CREATE INDEX IF NOT EXISTS idx_sent_date ON sent_articles(sent_date);")
        else:
            _execute("""
                CREATE TABLE IF NOT EXISTS sent_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_hash TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    published_date TEXT DEFAULT NULL,
                    sent_date TEXT NOT NULL,
                    score REAL DEFAULT 0,
                    is_top_story INTEGER DEFAULT 0,
                    UNIQUE(url, sent_date)
                );
            """)
            _execute("CREATE INDEX IF NOT EXISTS idx_sent_url ON sent_articles(url);")
            _execute("CREATE INDEX IF NOT EXISTS idx_sent_title_hash ON sent_articles(title_hash);")
            _execute("CREATE INDEX IF NOT EXISTS idx_sent_date ON sent_articles(sent_date);")

        logger.info("✅ sent_articles table initialized")
    except Exception as e:
        logger.warning(f"sent_articles table init error: {e}")


def _generate_title_hash(title: str) -> str:
    """توليد hash من العنوان بعد تنظيفه"""
    # تحويل لـ lowercase وإزالة الرموز والمسافات الزيادة
    cleaned = re.sub(r'[^\w\s]', '', title.lower().strip())
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return hashlib.md5(cleaned.encode('utf-8')).hexdigest()


def record_sent_article(article: Dict):
    """تسجيل خبر كمرسل في قاعدة البيانات"""
    from memory import _execute, _is_postgres

    url = article.get("link", "")
    title = article.get("title", "")
    title_hash = _generate_title_hash(title)
    source = article.get("source", "")
    category = article.get("category", "general")
    published_date = ""
    if article.get("published"):
        try:
            published_date = article["published"].isoformat() if hasattr(article["published"], "isoformat") else str(article["published"])
        except Exception:
            pass
    sent_date = datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")
    score = article.get("scores", {}).get("total", 0)
    is_top = 1 if article.get("is_top") else 0

    ph = "%s" if _is_postgres() else "?"
    try:
        _execute(
            f"""INSERT INTO sent_articles (url, title, title_hash, source, category, published_date, sent_date, score, is_top_story)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            ON CONFLICT DO NOTHING""",
            (url, title, title_hash, source, category, published_date, sent_date, score, is_top)
        )
    except Exception as e:
        logger.debug(f"Error recording sent article: {e}")


def get_recently_sent_urls(days: int = 7) -> set:
    """الحصول على URLs الأخبار المرسلة في آخر N يوم"""
    from memory import _execute, _is_postgres

    cutoff = (datetime.now(CAIRO_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")

    ph = "%s" if _is_postgres() else "?"
    rows = _execute(
        f"SELECT url FROM sent_articles WHERE sent_date >= {ph}",
        (cutoff,),
        fetch=True
    )
    if rows:
        return set(r[0] for r in rows)
    return set()


def get_recently_sent_hashes(days: int = 7) -> set:
    """الحصول على title hashes الأخبار المرسلة في آخر N يوم"""
    from memory import _execute, _is_postgres

    cutoff = (datetime.now(CAIRO_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")

    ph = "%s" if _is_postgres() else "?"
    rows = _execute(
        f"SELECT title_hash FROM sent_articles WHERE sent_date >= {ph}",
        (cutoff,),
        fetch=True
    )
    if rows:
        return set(r[0] for r in rows)
    return set()


def get_recently_sent_titles(days: int = 7) -> List[str]:
    """الحصول على عناوين الأخبار المرسلة في آخر N يوم"""
    from memory import _execute, _is_postgres

    cutoff = (datetime.now(CAIRO_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")

    ph = "%s" if _is_postgres() else "?"
    rows = _execute(
        f"SELECT title FROM sent_articles WHERE sent_date >= {ph}",
        (cutoff,),
        fetch=True
    )
    if rows:
        return [r[0] for r in rows]
    return []


def get_yesterday_articles() -> List[Dict]:
    """الحصول على أخبار أمس للمقارنة"""
    from memory import _execute, _is_postgres

    yesterday = (datetime.now(CAIRO_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    ph = "%s" if _is_postgres() else "?"
    rows = _execute(
        f"SELECT url, title, title_hash, category, score FROM sent_articles WHERE sent_date = {ph}",
        (yesterday,),
        fetch=True
    )
    if rows:
        return [{"url": r[0], "title": r[1], "title_hash": r[2], "category": r[3], "score": r[4]} for r in rows]
    return []


def cleanup_old_sent_articles(days: int = 30):
    """حذف الأخبار القديمة من جدول sent_articles (أكتر من 30 يوم)"""
    from memory import _execute, _is_postgres

    cutoff = (datetime.now(CAIRO_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")

    ph = "%s" if _is_postgres() else "?"
    _execute(f"DELETE FROM sent_articles WHERE sent_date < {ph}", (cutoff,))
    logger.info(f"Cleaned up sent_articles older than {cutoff}")


# ═══════════════════════════════════════
# 2. كشف المكررات الذكي - Smart Duplicate Detection
# ═══════════════════════════════════════

# Stop words للإنجليزية (كلمات شائعة لا تفيد في المقارنة)
STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by",
    "from", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "not", "but", "and", "or", "if", "then", "than",
    "that", "this", "these", "those", "it", "its", "new", "says", "said",
    "just", "about", "also", "now", "how", "what", "which", "who", "when",
    "where", "why", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "only", "same", "so", "very", "up",
    "out", "over", "after", "before", "into", "through", "during",
}


def _tokenize_title(title: str) -> set:
    """تقسيم العنوان لكلمات مفيدة (بدون stop words)"""
    # تحويل لـ lowercase وإزالة الرموز
    cleaned = re.sub(r'[^\w\s]', ' ', title.lower())
    words = set(cleaned.split())
    # إزالة stop words والكلمات القصيرة جداً
    meaningful = {w for w in words if w not in STOP_WORDS and len(w) > 2}
    return meaningful


def _jaccard_similarity(set1: set, set2: set) -> float:
    """حساب Jaccard similarity بين مجموعتين"""
    if not set1 or not set2:
        return 0.0
    intersection = set1 & set2
    union = set1 | set2
    return len(intersection) / len(union)


def fuzzy_title_similarity(title1: str, title2: str) -> float:
    """
    حساب نسبة التشابه بين عنوانين باستخدام fuzzy matching
    يجمع بين Jaccard similarity و containment ratio
    """
    tokens1 = _tokenize_title(title1)
    tokens2 = _tokenize_title(title2)

    if not tokens1 or not tokens2:
        return 0.0

    # Jaccard similarity
    jaccard = _jaccard_similarity(tokens1, tokens2)

    # Containment ratio (هل العنوان القصير محتوى في الطويل؟)
    shorter = tokens1 if len(tokens1) <= len(tokens2) else tokens2
    longer = tokens2 if len(tokens1) <= len(tokens2) else tokens1
    containment = len(shorter & longer) / len(shorter) if shorter else 0

    # Combination: نعطي وزن أعلى لـ containment لأنه أهم
    similarity = 0.4 * jaccard + 0.6 * containment

    return similarity


def is_similar_to_sent(title: str, sent_titles: List[str], threshold: float = 0.55) -> Tuple[bool, float]:
    """
    فحص هل العنوان مشابه لعنوان تم إرساله مؤخراً
    Returns: (is_similar, max_similarity)
    """
    if not sent_titles:
        return False, 0.0

    max_sim = 0.0
    for sent_title in sent_titles:
        sim = fuzzy_title_similarity(title, sent_title)
        max_sim = max(max_sim, sim)
        if sim >= threshold:
            return True, sim

    return False, max_sim


def is_url_recently_sent(url: str, sent_urls: set) -> bool:
    """فحص هل الـ URL تم إرساله مؤخراً"""
    return url in sent_urls


def is_hash_recently_sent(title: str, sent_hashes: set) -> bool:
    """فحص هل عنوان مشابه تم إرساله مؤخراً (hash-based)"""
    title_hash = _generate_title_hash(title)
    return title_hash in sent_hashes


# ═══════════════════════════════════════
# 3. تصنيف الأخبار - News Categories
# ═══════════════════════════════════════

NEWS_CATEGORIES = {
    "models": {
        "name_ar": "نماذج AI",
        "name_en": "AI Models",
        "emoji": "🤖",
        "keywords": [
            "model", "gpt", "llm", "language model", "foundation model",
            "diffusion", "transformer", "neural network", "open source model",
            "o1", "o3", "o4", "gemini", "claude", "llama", "grok", "mistral",
            "phi", "sora", "dall-e", "midjourney", "stable diffusion",
            "qwen", "deepseek", "copilot",
        ]
    },
    "research": {
        "name_ar": "أبحاث",
        "name_en": "Research",
        "emoji": "🔬",
        "keywords": [
            "research", "paper", "arxiv", "study", "breakthrough",
            "discovery", "benchmark", "evaluation", "method", "algorithm",
            "technique", "approach", "novel", "architecture",
        ]
    },
    "regulation": {
        "name_ar": "تنظيم وسياسات",
        "name_en": "Regulation",
        "emoji": "⚖️",
        "keywords": [
            "regulation", "regulate", "law", "legislation", "policy",
            "governance", "compliance", "eu ai act", "executive order",
            "ban", "restrict", "safety", "alignment", "ethics", "audit",
            "congress", "senate", "parliament", "ftc", "fcc",
        ]
    },
    "funding": {
        "name_ar": "تمويل واستثمار",
        "name_en": "Funding",
        "emoji": "💰",
        "keywords": [
            "funding", "funded", "investment", "invested", "raised",
            "series a", "series b", "series c", "valuation", "billion",
            "million", "acquisition", "acquire", "ipo", "startup funding",
            "venture capital", "seed round",
        ]
    },
    "startups": {
        "name_ar": "شركات ناشئة",
        "name_en": "Startups",
        "emoji": "🚀",
        "keywords": [
            "startup", "launch", "founded", "announced", "new company",
            "new platform", "new service", "new product", "emerging",
            "unicorn", "scale",
        ]
    },
    "big_tech": {
        "name_ar": "شركات كبرى",
        "name_en": "Big Tech",
        "emoji": "🏢",
        "keywords": [
            "openai", "google", "anthropic", "microsoft", "meta",
            "nvidia", "apple", "amazon", "xai", "deepmind", "tesla",
            "ibm", "intel", "amd", "oracle", "salesforce", "adobe",
        ]
    },
    "security": {
        "name_ar": "أمن وسلامة",
        "name_en": "Security",
        "emoji": "🛡️",
        "keywords": [
            "security", "vulnerability", "attack", "breach", "hack",
            "malicious", "threat", "risk", "danger", "exploit",
            "jailbreak", "prompt injection", "deepfake", "misinformation",
            "bias", "hallucination", "safety concern",
        ]
    },
    "healthcare": {
        "name_ar": "صحة وطب",
        "name_en": "Healthcare",
        "emoji": "🏥",
        "keywords": [
            "health", "medical", "drug", "clinical", "diagnosis",
            "alphafold", "protein", "hospital", "patient", "disease",
            "therapy", "pharmaceutical", "fda", "biotech",
        ]
    },
    "robotics": {
        "name_ar": "روبوتات",
        "name_en": "Robotics",
        "emoji": "🤖",
        "keywords": [
            "robot", "robotics", "humanoid", "autonomous", "embodied",
            "self-driving", "autonomous vehicle", "drone", "automation",
            "manufacturing", "warehouse robot",
        ]
    },
}


def classify_article(title: str, description: str = "") -> str:
    """
    تصنيف الخبر في فئة مناسبة
    Returns: category key (e.g. "models", "research", etc.)
    """
    text = f"{title} {description}".lower()

    category_scores = {}
    for cat_key, cat_data in NEWS_CATEGORIES.items():
        score = 0
        for keyword in cat_data["keywords"]:
            if keyword in text:
                # كلمات أطول = أهمية أعلى
                score += len(keyword)
        category_scores[cat_key] = score

    if not category_scores or max(category_scores.values()) == 0:
        return "general"

    best_category = max(category_scores, key=category_scores.get)
    return best_category


def get_category_display(category_key: str, lang: str = "ar") -> str:
    """الحصول على عرض الفئة"""
    cat = NEWS_CATEGORIES.get(category_key, None)
    if not cat:
        return "📌" if lang == "ar" else "📌"
    return f"{cat['emoji']} {cat['name_ar']}" if lang == "ar" else f"{cat['emoji']} {cat['name_en']}"


# ═══════════════════════════════════════
# 4. وزن الشركات - Company Weighting
# ═══════════════════════════════════════

COMPANY_WEIGHTS = {
    "openai": 3.0,
    "chatgpt": 3.0,
    "gpt-4": 2.5,
    "gpt-5": 3.0,
    "google": 2.5,
    "deepmind": 2.5,
    "gemini": 2.5,
    "anthropic": 2.5,
    "claude": 2.5,
    "microsoft": 2.0,
    "copilot": 2.0,
    "meta": 2.0,
    "llama": 2.0,
    "nvidia": 2.0,
    "xai": 2.0,
    "grok": 2.0,
    "apple": 1.8,
    "amazon": 1.5,
    "tesla": 1.5,
}


def calculate_company_boost(title: str, description: str = "") -> float:
    """
    حساب زيادة النتيجة بناءً على الشركات المذكورة
    الشركات الكبرى تحصل على boost أعلى
    """
    text = f"{title} {description}".lower()

    total_boost = 0.0
    companies_mentioned = set()

    for company_keyword, weight in COMPANY_WEIGHTS.items():
        if company_keyword in text:
            total_boost += weight
            companies_mentioned.add(company_keyword)

    # لو شركات كتير مذكورة = خبر مهم
    if len(companies_mentioned) >= 3:
        total_boost += 2.0
    elif len(companies_mentioned) >= 2:
        total_boost += 1.0

    return total_boost


# ═══════════════════════════════════════
# 5. التحقق من تعدد المصادر - Multi-Source Validation
# ═══════════════════════════════════════

def detect_multi_source(articles: List[Dict]) -> Dict[str, int]:
    """
    كشف الأخبار المذكورة في مصادر متعددة
    Returns: {article_index: source_count}
    """
    source_groups = {}

    for i, article in enumerate(articles):
        title = article.get("title", "")
        tokens = _tokenize_title(title)

        # تجميع حسب الكلمات المفتاحية الرئيسية (أول 3 كلمات مهمة)
        key_tokens = sorted(tokens, key=len, reverse=True)[:3]
        group_key = " ".join(sorted(key_tokens))

        if group_key not in source_groups:
            source_groups[group_key] = {"indices": [], "sources": set()}

        source_groups[group_key]["indices"].append(i)

        source = article.get("source", "")
        if source:
            source_groups[group_key]["sources"].add(source)

    # بناء النتيجة: لكل مقال، كم مصدر مختلف بيتكلم عن نفس الموضوع
    multi_source_map = {}
    for group_key, group_data in source_groups.items():
        source_count = len(group_data["sources"])
        for idx in group_data["indices"]:
            multi_source_map[idx] = max(multi_source_map.get(idx, 0), source_count)

    return multi_source_map


def calculate_multi_source_boost(source_count: int) -> float:
    """حساب زيادة النتيجة بناءً على عدد المصادر"""
    if source_count >= 5:
        return 4.0
    elif source_count >= 4:
        return 3.0
    elif source_count >= 3:
        return 2.0
    elif source_count >= 2:
        return 1.0
    return 0.0


# ═══════════════════════════════════════
# 6. ضمان تفرد النشرة اليومية - Daily Uniqueness
# ═══════════════════════════════════════

def calculate_yesterday_similarity(title: str, yesterday_articles: List[Dict]) -> float:
    """حساب التشابه مع أخبار أمس"""
    if not yesterday_articles:
        return 0.0

    max_sim = 0.0
    for yesterday_article in yesterday_articles:
        sim = fuzzy_title_similarity(title, yesterday_article["title"])
        max_sim = max(max_sim, sim)

    return max_sim


def apply_daily_uniqueness_penalty(article: Dict, yesterday_articles: List[Dict]) -> float:
    """
    تطبيق عقوبة على الأخبار المشابهة لأمس
    كلما زاد التشابه، زادت العقوبة
    """
    title = article.get("title", "")
    similarity = calculate_yesterday_similarity(title, yesterday_articles)

    if similarity >= 0.7:
        return -3.0  # عقوبة شديدة
    elif similarity >= 0.5:
        return -2.0  # عقوبة متوسطة
    elif similarity >= 0.35:
        return -1.0  # عقوبة خفيفة

    return 0.0


# ═══════════════════════════════════════
# 7. حد أدنى للجودة - Minimum Quality Threshold
# ═══════════════════════════════════════

MIN_QUALITY_SCORE = 3.5  # الحد الأدنى لإرسال خبر
MIN_ARTICLES_TO_SEND = 2  # أقل عدد أخبار نرسله (لو أقل من كده مش نرسل حاجة ضعيفة)


def meets_quality_threshold(article: Dict) -> bool:
    """فحص هل الخبر بيوافق الحد الأدنى للجودة"""
    score = article.get("scores", {}).get("total", 0)
    return score >= MIN_QUALITY_SCORE


# ═══════════════════════════════════════
# 8. اختيار خبر اليوم - Top Story Selection
# ═══════════════════════════════════════

def select_top_story(articles: List[Dict]) -> Optional[Dict]:
    """
    اختيار خبر اليوم - أهم خبر AI في اليوم
    المعايير:
    1. أعلى نتيجة
    2. مذكور في أكبر عدد من المصادر
    3. يتعلق بشركة كبرى
    4. ليس مشابهاً لأمس
    """
    if not articles:
        return None

    # ترتيب حسب النتيجة الإجمالية
    sorted_articles = sorted(articles, key=lambda x: x.get("final_score", x.get("scores", {}).get("total", 0)), reverse=True)

    return sorted_articles[0] if sorted_articles else None


# ═══════════════════════════════════════
# 9. المراجعة التحريرية النهائية - Final Editorial Review
# ═══════════════════════════════════════

def editorial_review(article: Dict, sent_urls: set, sent_hashes: set,
                     sent_titles: List[str], yesterday_articles: List[Dict]) -> Dict:
    """
    مراجعة تحريرية نهائية لكل خبر قبل الإرسال
    Returns: {
        "approved": bool,
        "reason": str,
        "penalty": float,
        "warnings": List[str]
    }
    """
    title = article.get("title", "")
    url = article.get("link", "")
    warnings = []
    total_penalty = 0.0

    # 1. هل تم إرسال نفس الـ URL من قبل؟
    if is_url_recently_sent(url, sent_urls):
        return {"approved": False, "reason": "URL_already_sent", "penalty": -100, "warnings": ["تم إرسال هذا الرابط من قبل"]}

    # 2. هل تم إرسال عنوان مشابه (hash) من قبل؟
    if is_hash_recently_sent(title, sent_hashes):
        return {"approved": False, "reason": "title_hash_sent", "penalty": -100, "warnings": ["تم إرسال خبر مشابه جداً من قبل"]}

    # 3. هل العنوان مشابه fuzzy لعنوان مرسل؟
    is_similar, similarity = is_similar_to_sent(title, sent_titles, threshold=0.55)
    if is_similar:
        return {"approved": False, "reason": "fuzzy_duplicate", "penalty": -100, "warnings": [f"خبر مشابه تم إرساله (تشابه: {similarity:.0%})"]}

    # 4. هل مشابه لأخبار أمس؟
    yesterday_sim = calculate_yesterday_similarity(title, yesterday_articles)
    if yesterday_sim >= 0.5:
        penalty = apply_daily_uniqueness_penalty(article, yesterday_articles)
        total_penalty += penalty
        warnings.append(f"مشابه لأمس ({yesterday_sim:.0%})")

    # 5. هل النتيجة أعلى من الحد الأدنى؟
    base_score = article.get("scores", {}).get("total", 0)
    if base_score + total_penalty < MIN_QUALITY_SCORE:
        return {"approved": False, "reason": "below_quality", "penalty": total_penalty, "warnings": warnings + [f"نتيجة ضعيفة ({base_score:.1f})"]}

    # 6. هل المقال فعلاً مهم؟ (فحص محتوى)
    importance = article.get("scores", {}).get("importance", 0)
    if importance < 1.5 and base_score < 5.0:
        warnings.append("أهمية منخفضة")

    return {
        "approved": True,
        "reason": "approved",
        "penalty": total_penalty,
        "warnings": warnings,
    }


# ═══════════════════════════════════════
# 10. الخط الرئيسي - Main Editorial Pipeline
# ═══════════════════════════════════════

def run_editorial_pipeline(articles: List[Dict], max_articles: int = 10) -> List[Dict]:
    """
    الخط الرئيسي لنظام التحرير الصحفي
    يمر كل خبر بمراحل المراجعة والتحسين

    المراحل:
    1. تصنيف الأخبار
    2. حساب وزن الشركات
    3. كشف تعدد المصادر
    4. حساب النتيجة المحسنة
    5. المراجعة التحريرية (إزالة المكررات)
    6. ضمان تفرد النشرة اليومية
    7. تطبيق حد الجودة الأدنى
    8. اختيار خبر اليوم
    9. موازنة الفئات
    10. تسجيل الأخبار المرسلة
    """
    logger.info("═══ Running Editorial Pipeline ═══")

    # ─── تهيئة ───
    init_sent_articles_table()

    # جلب بيانات المكررات من قاعدة البيانات
    sent_urls = get_recently_sent_urls(days=7)
    sent_hashes = get_recently_sent_hashes(days=7)
    sent_titles = get_recently_sent_titles(days=7)
    yesterday_articles = get_yesterday_articles()

    logger.info(f"  Sent history: {len(sent_urls)} URLs, {len(sent_hashes)} hashes, {len(sent_titles)} titles, {len(yesterday_articles)} yesterday articles")

    # ─── المرحلة 1: تصنيف الأخبار ───
    logger.info("  Stage 1: Classifying articles...")
    for article in articles:
        article["category"] = classify_article(
            article.get("title", ""),
            article.get("description", "")
        )

    # ─── المرحلة 2: وزن الشركات ───
    logger.info("  Stage 2: Applying company weighting...")
    for article in articles:
        company_boost = calculate_company_boost(
            article.get("title", ""),
            article.get("description", "")
        )
        article["company_boost"] = company_boost

    # ─── المرحلة 3: كشف تعدد المصادر ───
    logger.info("  Stage 3: Detecting multi-source coverage...")
    multi_source_map = detect_multi_source(articles)
    for i, article in enumerate(articles):
        source_count = multi_source_map.get(i, 1)
        article["source_count"] = source_count
        article["multi_source_boost"] = calculate_multi_source_boost(source_count)

    # ─── المرحلة 4: حساب النتيجة المحسنة ───
    logger.info("  Stage 4: Calculating enhanced scores...")
    for article in articles:
        base_score = article.get("scores", {}).get("total", 0)

        enhanced_score = base_score
        enhanced_score += article.get("company_boost", 0)
        enhanced_score += article.get("multi_source_boost", 0)

        # عقوبة التشابه مع أمس
        uniqueness_penalty = apply_daily_uniqueness_penalty(article, yesterday_articles)
        enhanced_score += uniqueness_penalty

        article["final_score"] = round(enhanced_score, 2)

    # ─── المرحلة 5: المراجعة التحريرية ───
    logger.info("  Stage 5: Running editorial review...")
    approved_articles = []
    for article in articles:
        review = editorial_review(
            article, sent_urls, sent_hashes, sent_titles, yesterday_articles
        )
        article["review"] = review

        if review["approved"]:
            # تطبيق العقوبات
            article["final_score"] = article.get("final_score", 0) + review["penalty"]
            approved_articles.append(article)
        else:
            logger.info(f"    REJECTED: {article.get('title', '')[:60]} — {review['reason']}")

    logger.info(f"  Editorial review: {len(articles)} → {len(approved_articles)} approved")

    # ─── المرحلة 6: ترتيب حسب النتيجة النهائية ───
    logger.info("  Stage 6: Ranking by final score...")
    approved_articles.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    # ─── المرحلة 7: حد الجودة الأدنى ───
    logger.info("  Stage 7: Applying quality threshold...")
    quality_articles = [a for a in approved_articles if a.get("final_score", 0) >= MIN_QUALITY_SCORE]

    if len(quality_articles) < MIN_ARTICLES_TO_SEND:
        logger.info(f"  Only {len(quality_articles)} articles meet quality threshold (min: {MIN_ARTICLES_TO_SEND})")
        # لو أقل من الحد الأدنى، نرسل اللي عندنا (حتى لو 1)
        if quality_articles:
            logger.info(f"  Sending {len(quality_articles)} articles (below minimum but quality > empty)")
        else:
            logger.info("  No quality articles found — sending nothing")
            return []
    else:
        logger.info(f"  {len(quality_articles)} articles meet quality threshold")

    # ─── المرحلة 8: موازنة الفئات ───
    logger.info("  Stage 8: Balancing categories...")
    balanced_articles = _balance_categories(quality_articles, max_articles)

    # ─── المرحلة 9: اختيار خبر اليوم ───
    logger.info("  Stage 9: Selecting top story...")
    top_story = select_top_story(balanced_articles)
    for article in balanced_articles:
        article["is_top"] = (article is top_story)

    if top_story:
        logger.info(f"  Top story: {top_story.get('title', '')[:60]}")

    # ─── المرحلة 10: تسجيل الأخبار المرسلة ───
    logger.info("  Stage 10: Recording sent articles...")
    for article in balanced_articles:
        record_sent_article(article)

    # تنظيف البيانات القديمة
    try:
        cleanup_old_sent_articles(days=30)
    except Exception:
        pass

    logger.info(f"═══ Editorial Pipeline Complete: {len(balanced_articles)} articles selected ═══")
    return balanced_articles


def _balance_categories(articles: List[Dict], max_articles: int) -> List[Dict]:
    """
    موازنة الفئات في النشرة
    يضمن تنوع المواضيع بدل ما كل الأخبار من فئة واحدة
    """
    if len(articles) <= max_articles:
        return articles

    # تجميع حسب الفئة
    category_groups = {}
    for article in articles:
        cat = article.get("category", "general")
        if cat not in category_groups:
            category_groups[cat] = []
        category_groups[cat].append(article)

    # ترتيب كل فئة حسب النتيجة
    for cat in category_groups:
        category_groups[cat].sort(key=lambda x: x.get("final_score", 0), reverse=True)

    # الحد الأقصى لكل فئة
    num_categories = len(category_groups)
    max_per_category = max(2, max_articles // max(num_categories, 1))

    # اختيار أفضل مقال من كل فئة أولاً (round-robin)
    selected = []
    remaining_slots = max_articles

    # المرور الأول: أفضل مقال من كل فئة
    for cat in sorted(category_groups.keys(), key=lambda c: category_groups[c][0].get("final_score", 0), reverse=True):
        if remaining_slots <= 0:
            break
        if category_groups[cat]:
            selected.append(category_groups[cat].pop(0))
            remaining_slots -= 1

    # المرور الثاني: أفضل مقال متبقي (حتى الحد الأقصى لكل فئة)
    round = 1
    while remaining_slots > 0 and any(category_groups.values()):
        for cat in sorted(category_groups.keys(), key=lambda c: category_groups[c][0].get("final_score", 0) if category_groups[c] else 0, reverse=True):
            if remaining_slots <= 0:
                break
            if category_groups[cat] and round < max_per_category:
                selected.append(category_groups[cat].pop(0))
                remaining_slots -= 1
        round += 1
        if round > max_per_category:
            break

    # إعادة ترتيب حسب النتيجة
    selected.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    return selected[:max_articles]


# ═══════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════

def get_category_distribution(articles: List[Dict]) -> Dict[str, int]:
    """الحصول على توزيع الفئات"""
    dist = Counter()
    for article in articles:
        cat = article.get("category", "general")
        dist[cat] += 1
    return dict(dist)


def format_editorial_summary(articles: List[Dict], lang: str = "ar") -> str:
    """تنسيق ملخص تحريري للـ logs"""
    if not articles:
        return "No articles selected"

    distribution = get_category_distribution(articles)
    top = articles[0] if articles else None

    if lang == "ar":
        summary = f"📰 النشرة اليومية: {len(articles)} أخبار\n"
        summary += f"🔥 خبر اليوم: {top.get('title', '')[:50] if top else 'لا يوجد'}\n"
        summary += f"📊 الفئات: "
        summary += ", ".join(f"{NEWS_CATEGORIES.get(c, {}).get('name_ar', c)}: {n}" for c, n in distribution.items())
    else:
        summary = f"📰 Daily Newsletter: {len(articles)} articles\n"
        summary += f"🔥 Top Story: {top.get('title', '')[:50] if top else 'None'}\n"
        summary += f"📊 Categories: "
        summary += ", ".join(f"{NEWS_CATEGORIES.get(c, {}).get('name_en', c)}: {n}" for c, n in distribution.items())

    return summary
