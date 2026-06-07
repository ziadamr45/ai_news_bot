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

# النموذج الرئيسي - سريع وكفؤ
OPENROUTER_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

# النموذج السريع - للأسئلة البسيطة والتحيات
FAST_MODEL = "moonshotai/kimi-vl-a3b-thinking:free"

# النماذج البديلة - مرتبة حسب السرعة
OPENROUTER_FALLBACK_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "qwen/qwen3-235b-a22b:free",
    "openrouter/owl-alpha",
    "nvidia/nemotron-3-super-120b-a12b:free",
]

# News Settings
MAX_NEWS_COUNT = 50
MIN_NEWS_COUNT = 0
NEWS_FETCH_HOURS = 24  # جلب أخبار آخر 24 ساعة
WEEKLY_FETCH_HOURS = 168  # جلب أخبار آخر أسبوع

# Scoring Weights
SCORE_WEIGHTS = {
    "ai_relevance": 0.35,
    "importance": 0.25,
    "industry_impact": 0.25,
    "source_credibility": 0.15
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
    "microsoft.com": 9,
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

# Company Data for Reports
COMPANY_DATA = {
    "openai": {
        "name": "OpenAI",
        "name_ar": "أوبن إيه آي",
        "keywords": ["openai", "chatgpt", "gpt-4", "gpt-5", "o1", "o3", "o4", "dall-e", "sora", "codex"],
        "products": ["ChatGPT", "GPT-4", "GPT-5", "DALL-E", "Sora", "Codex", "API"],
        "description": "Leading AI research lab focused on AGI",
        "description_ar": "مختبر أبحاث رائد في مجال الذكاء الاصطناعي العام",
        "rss_keywords": ["openai"],
    },
    "google": {
        "name": "Google / DeepMind",
        "name_ar": "جوجل / ديب مايند",
        "keywords": ["google ai", "gemini", "deepmind", "bard", "google", "alphafold"],
        "products": ["Gemini", "Gemini Pro", "Gemini Ultra", "AlphaFold", "Google AI"],
        "description": "Tech giant with world-class AI research division",
        "description_ar": "شركة تقنية عملاقة بقسم أبحاث ذكاء اصطناعي عالمي",
        "rss_keywords": ["google", "gemini", "deepmind"],
    },
    "anthropic": {
        "name": "Anthropic",
        "name_ar": "أنثروبيك",
        "keywords": ["anthropic", "claude", "constitutional ai"],
        "products": ["Claude", "Claude Pro", "Claude API"],
        "description": "AI safety company building reliable AI systems",
        "description_ar": "شركة سلامة الذكاء الاصطناعي تبني أنظمة موثوقة",
        "rss_keywords": ["anthropic", "claude"],
    },
    "microsoft": {
        "name": "Microsoft",
        "name_ar": "مايكروسوفت",
        "keywords": ["microsoft", "copilot", "azure ai", "bing ai"],
        "products": ["Copilot", "Azure AI", "Azure OpenAI", "Bing AI"],
        "description": "Tech giant integrating AI across products",
        "description_ar": "شركة تقنية عملاقة تدمج الذكاء الاصطناعي في منتجاتها",
        "rss_keywords": ["microsoft", "copilot"],
    },
    "meta": {
        "name": "Meta AI",
        "name_ar": "ميتا إيه آي",
        "keywords": ["meta ai", "llama", "meta", "facebook ai", "segment anything"],
        "products": ["Llama", "Llama 2", "Llama 3", "Segment Anything", "Meta AI"],
        "description": "Social media giant with open-source AI focus",
        "description_ar": "شركة وسائل تواصل اجتماعي تركز على الذكاء الاصطناعي مفتوح المصدر",
        "rss_keywords": ["meta", "llama", "facebook ai"],
    },
    "xai": {
        "name": "xAI",
        "name_ar": "إكس إيه آي",
        "keywords": ["xai", "grok", "elon musk ai"],
        "products": ["Grok", "Grok-2"],
        "description": "Elon Musk's AI company",
        "description_ar": "شركة الذكاء الاصطناعي لإيلون ماسك",
        "rss_keywords": ["xai", "grok"],
    },
    "nvidia": {
        "name": "NVIDIA",
        "name_ar": "إنفيديا",
        "keywords": ["nvidia", "gpu", "ai chip", "cuda", "h100", "blackwell"],
        "products": ["H100", "H200", "Blackwell", "CUDA", "DGX"],
        "description": "AI hardware leader powering the AI revolution",
        "description_ar": "رائد أجهزة الذكاء الاصطناعي الذي يشغل ثورة الذكاء الاصطناعي",
        "rss_keywords": ["nvidia", "gpu", "ai chip"],
    },
    "deepmind": {
        "name": "DeepMind",
        "name_ar": "ديب مايند",
        "keywords": ["deepmind", "alphafold", "alphago", "gemini"],
        "products": ["AlphaFold", "AlphaGo", "Gemini"],
        "description": "World-leading AI research lab (Google)",
        "description_ar": "مختبر أبحاث ذكاء اصطناعي عالمي (جوجل)",
        "rss_keywords": ["deepmind", "alphafold"],
    },
}

# Learning Roadmaps
ROADMAPS = {
    "ai": {
        "title_ar": "خارطة طريق الذكاء الاصطناعي",
        "title_en": "AI Learning Roadmap",
        "beginner": ["Python basics", "Math for ML (Linear Algebra, Stats)", "Intro to ML", "Pandas & NumPy", "Basic ML with Scikit-learn"],
        "intermediate": ["Deep Learning fundamentals", "Neural Networks", "CNNs for Computer Vision", "RNNs & LSTMs", "NLP basics", "PyTorch / TensorFlow"],
        "advanced": ["Transformers & Attention", "LLMs & Fine-tuning", "RLHF", "RAG systems", "AI Agents", "Multimodal AI", "Deployment & MLOps"],
    },
    "machine learning": {
        "title_ar": "خارطة طريق تعلم الآلة",
        "title_en": "Machine Learning Roadmap",
        "beginner": ["Python", "Statistics & Probability", "Data preprocessing", "Linear & Logistic Regression", "Decision Trees"],
        "intermediate": ["Ensemble methods", "SVMs", "Unsupervised Learning", "Feature Engineering", "Cross-validation"],
        "advanced": ["AutoML", "Time Series", "Anomaly Detection", "Model optimization", "Production ML"],
    },
    "deep learning": {
        "title_ar": "خارطة طريق التعلم العميق",
        "title_en": "Deep Learning Roadmap",
        "beginner": ["Neural Network basics", "Backpropagation", "Activation functions", "Gradient Descent", "PyTorch basics"],
        "intermediate": ["CNNs", "RNNs/LSTMs", "Transfer Learning", "GANs", "Sequence models"],
        "advanced": ["Transformers", "Diffusion models", "Self-supervised learning", "Neural Architecture Search", "Model distillation"],
    },
    "nlp": {
        "title_ar": "خارطة طريق معالجة اللغة الطبيعية",
        "title_en": "NLP Roadmap",
        "beginner": ["Text preprocessing", "Tokenization", "Word embeddings", "Text classification", "Sentiment analysis"],
        "intermediate": ["Sequence models", "Attention mechanism", "Named Entity Recognition", "Machine Translation", "Text generation"],
        "advanced": ["Transformers (BERT, GPT)", "Fine-tuning LLMs", "RAG", "Prompt Engineering", "AI Agents"],
    },
    "llm": {
        "title_ar": "خارطة طريق النماذج اللغوية الكبيرة",
        "title_en": "LLM Roadmap",
        "beginner": ["What are LLMs", "Prompt Engineering basics", "API usage (OpenAI, etc.)", "Understanding context windows", "Chat vs Completion"],
        "intermediate": ["Fine-tuning (LoRA, QLoRA)", "RAG systems", "Vector databases", "LangChain / LlamaIndex", "Evaluation metrics"],
        "advanced": ["Training from scratch", "RLHF & Alignment", "Multimodal LLMs", "AI Agents frameworks", "MLOps for LLMs"],
    },
}

# ═══════════════════════════════════════
# إعدادات السرعة - Speed Settings
# ═══════════════════════════════════════

# مهلة الطلب العادية (ثانية) - تم تقليلها لتسريع الاستجابة
REQUEST_TIMEOUT = 20  # كان 30، دلوقتي 20

# مهلة الطلب السريع (ثانية) - للأسئلة البسيطة
FAST_TIMEOUT = 12

# عدد محاولات إعادة المحاولة
MAX_RETRIES = 2  # كان 3، دلوقتي 2

# تأخير بين المحاولات (ثانية)
RETRY_DELAY = 5  # كان 10، دلوقتي 5

# ═══════════════════════════════════════
# إعدادات البوت - Bot Settings
# ═══════════════════════════════════════

BOT_NAME = "My Bro"
BOT_VERSION = "2.1"

# Memory / Storage
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")

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
