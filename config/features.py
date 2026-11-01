"""
إعدادات الميزات والمحتوى - Feature Limits & Content Data
═══════════════════════════════════════════════════════════
News settings, Premium limits, Voice/PDF/YouTube settings,
Download services, Creator info, Storage paths, Supabase
"""

import os

# ═══════════════════════════════════════
# News Settings
# ═══════════════════════════════════════

MAX_NEWS_COUNT = 50
MIN_NEWS_COUNT = 0
NEWS_FETCH_HOURS = 24
WEEKLY_FETCH_HOURS = 168

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

# Exclusion Keywords
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
# Premium Limits (⚠️仅供参考 — the actual limits are in PLAN_LIMITS in premium.py)
# ═══════════════════════════════════════

FREE_AI_MESSAGES_PER_DAY = 20
FREE_PDF_PER_DAY = 3
FREE_IMAGES_PER_DAY = 5
FREE_YOUTUBE_PER_DAY = 3
FREE_SEARCHES_PER_DAY = 5
FREE_PHOTO_SEARCHES_PER_DAY = 3

# ═══════════════════════════════════════
# إعدادات الصوت - Voice Settings
# ═══════════════════════════════════════

WHISPER_MODEL = "whisper-large-v3"  # Groq Whisper model
VOICE_MAX_DURATION = 300  # Max voice duration in seconds (5 min)

# ═══════════════════════════════════════
# إعدادات PDF - PDF Settings
# ═══════════════════════════════════════

PDF_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
PDF_MAX_CHARS = 50000  # Max chars to send to AI (increased from 30000 → 50000 for better PDF analysis)
PDF_SUMMARY_TIMEOUT = 180  # 3 minutes for PDF summarization (increased from default)

# ═══════════════════════════════════════
# إعدادات YouTube - YouTube Settings
# ═══════════════════════════════════════

YOUTUBE_MAX_TRANSCRIPT_CHARS = 12000
CLOUDFLARE_WORKER_URL = os.environ.get("CLOUDFLARE_WORKER_URL", "https://holy-forest-335e.ziadamreltourcke7.workers.dev")

# 🔴 سيرفر التحميل الخاص — VPS بـ IP نظيف بيحل مشكلة حظر YouTube
# ده أفضل طريقة — البوت يبعت الرابط للسيرفر، السيرفر يحمل ويرفع على Supabase
# لو مش متوفر، البوت يكمل بالطرق العادية (yt-dlp على Railway)
DOWNLOAD_SERVICE_URL = os.environ.get("DOWNLOAD_SERVICE_URL", "")  # مثال: http://1.2.3.4:8080
DOWNLOAD_SERVICE_KEY = os.environ.get("DOWNLOAD_SERVICE_KEY", "")   # API Key للسيرفر

# Cobalt Self-Hosted — أقوى بديل لتحميل الفيديوهات (أول طبقة في fallback chain)
# بنشغله على Railway سيرفر منفصل ونربطه بالبوت
COBALT_API_URL = os.environ.get("COBALT_API_URL", "")  # مثال: https://cobalt.up.railway.app
COBALT_API_KEY = os.environ.get("COBALT_API_KEY", "")   # API Key من keys.json

# RapidAPI — fallback لتحميل Threads وخدمات تانية
# اشترك في: https://rapidapi.com/snapvidsnet/api/threads-downloader
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

# Cobalt JWT — آخر fallback لليوتيوب (من cobalt.tools بعد Turnstile verification)
# 🔴 مفيش logo/api/key — ده JWT شخصي بيتجدد من cobalt.tools
# بنستخدمه كـ آخر محاولة لو كل الطرق التانية فشلت
COBALT_JWT = os.environ.get("COBALT_JWT", "")

# Apify — fallback رابع لتحميل فيديوهات اليوتيوب
# 🔵 Apify هو منصة scraping قوية — بنستخدم actor لتحميل الفيديوهات
# لما yt-dlp و Cobalt يفشلوا، Apify بيكون الحل الأضمن
# 🔴 ميزة: مش بيتأثر بـ YouTube bot detection خالص — سيرفرات مختلفة تمامًا
APIFY_API_KEY = os.environ.get("APIFY_API_KEY", "")  # apify_api_...

# Invidious API — واجهة بديلة لليوتيوب (fallback بين RapidAPI و yt-dlp)
# 🟣 الميزة: مجاني ومفتوح — مش بيتأثر بـ YouTube bot detection خالص
# الطلبات بتروح لسيرفرات Invidious مش من الـ IP بتاعك
# لو عندك سيرفر Invidious خاص (أضمن وأسرع) — ضع الرابط هنا
INVIDIOUS_INSTANCE = os.environ.get("INVIDIOUS_INSTANCE", "")  # مثال: https://inv.nadeko.net

# ═══════════════════════════════════════
# معلومات المؤسس - Creator Info
# ═══════════════════════════════════════

CREATOR_INFO = {
    "name_en": "Ziad Amr",
    "name_ar": "زياد عمرو",
    "title_en": "Egyptian Web Developer & AI Builder",
    "title_ar": "مطوّر ويب مصري وباني أدوات ذكاء اصطناعي",
    "bio_en": "Full-stack web developer specializing in Next.js, React, TypeScript, and modern web technologies. Building AI-powered tools and bots that make artificial intelligence accessible to everyone, especially Arabic speakers. Founder and CEO of Qudra Tech — an Egyptian tech startup focused on innovative web solutions and AI applications. Passionate about bridging the gap between cutting-edge AI technology and the Arabic-speaking world.",
    "bio_ar": "مطوّر ويب متكامل متخصص في Next.js و React و TypeScript وتقنيات الويب الحديثة. بيبني أدوات وبوتات بتقنية الذكاء الاصطناعي بتخلي التكنولوجيا متاحة للجميع، خصوصًا الناطقين بالعربية. مؤسس ومدير تنفيذي لشركة Qudra Tech — شركة تقنية مصرية ناشئة متخصصة في حلول الويب المبتكرة وتطبيقات الذكاء الاصطناعي. شغوف إنه يعمل كوبري بين أحدث تقنيات الذكاء الاصطناعي والعالم العربي.",
    "company_en": "Qudra Tech",
    "company_ar": "Qudra Tech — قدرة تك",
    "company_desc_en": "An Egyptian tech startup specializing in web development, AI applications, and innovative digital solutions. Building tools that make AI accessible to Arabic speakers worldwide.",
    "company_desc_ar": "شركة تقنية مصرية ناشئة متخصصة في تطوير الويب وتطبيقات الذكاء الاصطناعي والحلول الرقمية المبتكرة. بتبني أدوات بتخلي الذكاء الاصطناعي متاح للناطقين بالعربية في كل مكان.",
    "email": "ziad90216@gmail.com",
    "website": "https://ziadamrme.vercel.app",
    "github": "https://github.com/ziadamr45",
    "linkedin": "https://www.linkedin.com/in/ziad-amr-44633a411",
    "twitter": "https://x.com/ziad90216",
    "facebook": "https://www.facebook.com/ziad7mr",
    "instagram": "https://www.instagram.com/ziadamr455/",
    "telegram": "https://t.me/ziadamr",
    "youtube": "https://youtube.com/@alhayat_ala_eltareq",
    "threads": "https://www.threads.com/@ziadamr455",
    "devto": "https://dev.to/ziad_amr_0e76916f10a8563f",
    "tech_stack": ["Next.js", "React", "TypeScript", "Tailwind CSS", "PostgreSQL", "Prisma", "Node.js", "Python", "Docker", "AI/ML"],
    "projects": [
        {"name": "My Bro", "desc": "AI News Telegram Bot with multi-provider AI engine, memory system, and deep search"},
        {"name": "AuraEscape", "desc": "Endless Runner Game"},
        {"name": "Eah-Elkalam", "desc": "Egyptian Trend Radar"},
        {"name": "Quadra Studio", "desc": "Quranic Video Maker"},
        {"name": "Bawabet-elhadas", "desc": "Smart News Portal"},
    ],
}

# Memory / Storage
RAILWAY_VOLUME_PATH = os.environ.get("RAILWAY_VOLUME_PATH", "")
if RAILWAY_VOLUME_PATH and os.path.isdir(RAILWAY_VOLUME_PATH):
    DATA_DIR = RAILWAY_VOLUME_PATH
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DATABASE_PATH = os.path.join(DATA_DIR, "memory.db")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")

# ═══════════════════════════════════════
# Supabase Storage — رفع الملفات الكبيرة
# ═══════════════════════════════════════
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "Downloads")
