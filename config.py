"""
إعدادات البوت - Bot Configuration
يتم قراءة جميع البيانات الحساسة من متغيرات البيئة (GitHub Secrets)
"""

import os

# Telegram Settings
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# OpenRouter API Settings
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENROUTER_FALLBACK_MODELS = [
    "openrouter/owl-alpha",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "poolside/laguna-m.1:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]

# News Settings
MAX_NEWS_COUNT = 5
MIN_NEWS_COUNT = 3
NEWS_FETCH_HOURS = 24  # جلب أخبار آخر 24 ساعة

# Scoring Weights
SCORE_WEIGHTS = {
    "ai_relevance": 0.35,      # صلة بالذكاء الاصطناعي
    "importance": 0.25,        # أهمية الخبر
    "industry_impact": 0.25,   # تأثير على الصناعة
    "source_credibility": 0.15 # مصداقية المصدر
}

# Source Credibility Scores (0-10)
SOURCE_CREDIBILITY = {
    "openai.com": 10,
    "deepmind.google": 10,
    "anthropic.com": 10,
    "blog.google": 9,
    "reuters.com": 9,
    "techcrunch.com": 8,
    "theverge.com": 8,
    "arstechnica.com": 7,
    "venturebeat.com": 7,
    "wired.com": 7,
    "arxiv.org": 8,
    "huggingface.co": 8,
    "ai.google": 9,
    "mistral.ai": 8,
    "x.ai": 8,
    "meta.ai": 9,
    "nvidia.com": 8,
}

# AI Keywords for filtering (English)
AI_KEYWORDS = [
    "openai", "chatgpt", "gpt-4", "gpt-5", "o1", "o3", "o4",
    "gemini", "deepmind", "google ai",
    "claude", "anthropic",
    "grok", "x.ai", "xAI",
    "ai agents", "ai agent", "autonomous ai",
    "foundation model", "foundation models", "large language model", "llm",
    "artificial intelligence", "machine learning", "deep learning",
    "generative ai", "genai",
    "diffusion model", "text-to-image", "text-to-video",
    "sora", "dall-e", "midjourney", "stable diffusion",
    "copilot", "ai assistant",
    "mistral", "llama", "phi",
    "neural network", "transformer",
    "agi", "artificial general intelligence",
    "reinforcement learning", "rlhf",
    "multimodal ai", "vision language model",
    "ai regulation", "ai safety", "ai alignment",
    "robot", "humanoid", "autonomous",
    "nvidia ai", "gpu ai", "ai chip",
    "ai startup", "ai funding", "ai acquisition",
]

# Exclusion Keywords - topics to filter OUT
EXCLUSION_KEYWORDS = [
    "smartphone", "iphone", "android phone", "samsung galaxy",
    "crypto", "bitcoin", "ethereum", "nft", "blockchain",
    "game release", "esports",
    "social media drama",
    "electric vehicle", "ev car",
    "weather", "celebrity",
]

# RSS Feed URLs
RSS_FEEDS = [
    "https://openai.com/blog/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://www.anthropic.com/feed.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.reuters.com/technology/artificial-intelligence/rss.xml",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://arstechnica.com/tag/ai/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
]

# Retry Settings
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds

# Request Timeout
REQUEST_TIMEOUT = 30  # seconds

# No News Message
NO_NEWS_MESSAGE = "لا توجد اليوم أخبار كبيرة في مجال الذكاء الاصطناعي تستحق التنبيه. 🤖"

# Message Template
MESSAGE_TEMPLATE = """📰 <b>أخبار الذكاء الاصطناعي اليوم</b>
📅 {date}

━━━━━━━━━━━━━━━━━

{news_items}

━━━━━━━━━━━━━━━━━
🤖 <i>بوت أخبار AI — يتم التشغيل تلقائياً كل يوم الساعة 9 صباحاً بتوقيت القاهرة</i>"""

NEWS_ITEM_TEMPLATE = """{badge} <b>{title}</b>

{summary}

🔗 <a href="{url}">اقرأ المزيد</a>"""

TOP_NEWS_BADGE = "🔴"
REGULAR_NEWS_BADGE = "⚪️"
