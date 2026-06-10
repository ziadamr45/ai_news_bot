"""
إعدادات البوت - Bot Configuration
يتم قراءة جميع البيانات الحساسة من متغيرات البيئة (GitHub Secrets / Railway Env)
+ مزودين: NVIDIA NIM (كل نموذج له مفتاح خاص) + Mistral + SambaNova
+ الخطه الشامله: Chat, Simple, Deep Search, Coding, Summary, Vision, Image Gen, Image Edit
+ كل نموذج NVIDIA ليه مفتاح API خاص بيه
"""

import os

# ═══════════════════════════════════════
# Telegram Settings
# ═══════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# PostgreSQL (Neon) - قاعدة بيانات دائمة
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ═══════════════════════════════════════
# مزودين AI - AI Providers
# ═══════════════════════════════════════

# NVIDIA NIM — كل نموذج له مفتاح API خاص!
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# NVIDIA model-specific API keys
NVIDIA_DEEPSEEK_V4_PRO_KEY = os.environ.get("NVIDIA_DEEPSEEK_V4_PRO_KEY", "")
NVIDIA_DEEPSEEK_V4_FLASH_KEY = os.environ.get("NVIDIA_DEEPSEEK_V4_FLASH_KEY", "")
NVIDIA_KIMI_K26_KEY = os.environ.get("NVIDIA_KIMI_K26_KEY", "")
NVIDIA_GLM_51_KEY = os.environ.get("NVIDIA_GLM_51_KEY", "")
NVIDIA_MINIMAX_M27_KEY = os.environ.get("NVIDIA_MINIMAX_M27_KEY", "")
NVIDIA_LLAMA_33_70B_KEY = os.environ.get("NVIDIA_LLAMA_33_70B_KEY", "")
NVIDIA_STEP_37_FLASH_KEY = os.environ.get("NVIDIA_STEP_37_FLASH_KEY", "")
NVIDIA_LLAMA_32_90B_VISION_KEY = os.environ.get("NVIDIA_LLAMA_32_90B_VISION_KEY", "")
NVIDIA_NEMOTRON_NANO_VL_KEY = os.environ.get("NVIDIA_NEMOTRON_NANO_VL_KEY", "")
NVIDIA_QWEN_IMAGE_KEY = os.environ.get("NVIDIA_QWEN_IMAGE_KEY", "")
NVIDIA_QWEN_IMAGE_EDIT_KEY = os.environ.get("NVIDIA_QWEN_IMAGE_EDIT_KEY", "")
NVIDIA_SD35_LARGE_KEY = os.environ.get("NVIDIA_SD35_LARGE_KEY", "")
NVIDIA_FLUX_KONTEXT_KEY = os.environ.get("NVIDIA_FLUX_KONTEXT_KEY", "")

# Mistral AI (أساسي للمجاني + fallback للبريميوم — 1B توكن/شهر)
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

# SambaNova (fallback للمجاني — مجاني وسريع، محدود 20 طلب/يوم)
SAMBANOVA_API_KEY = os.environ.get("SAMBANOVA_API_KEY", "")
SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"

# Groq (ASR - تحويل الصوت لنص عبر Whisper، مجاني وسريع)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# OpenAI (ASR fallback - تحويل الصوت لنص)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# OpenRouter (ASR fallback layer 3 - تحويل الصوت لنص)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# ═══════════════════════════════════════
# مسارات النماذج - Model Routes (الخطه الشامله)
# كل نموذج NVIDIA ليه مفتاح api_key خاص
# FREE = أخف/أسرع | PREMIUM = أقوى/أعمق
# ═══════════════════════════════════════

# 🧠 Chat - المحادثة الذكية
# FREE: DeepSeek V4 Flash → Llama 3.3 70B → Mistral Small → Nemo → SambaNova
# PREMIUM: DeepSeek V4 Pro → Kimi K2.6 → GLM 5.1 → MiniMax M2.7 → Mistral Large → Medium
FREE_CHAT_MODELS = [
    # ⭐ NVIDIA DeepSeek V4 Flash — أساسي للمجاني (سريع وقوي)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-flash", "api_key": NVIDIA_DEEPSEEK_V4_FLASH_KEY},
    # ⭐ NVIDIA Llama 3.3 70B — fallback قوي
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ Mistral Small — سريع ومجاني دائم
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ Mistral Nemo — fallback
    {"provider": "mistral", "model": "open-mistral-nemo"},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_CHAT_MODELS = [
    # ⭐ NVIDIA DeepSeek V4 Pro — أقوى نموذج (أساسي للبريميوم)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-pro", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA Kimi K2.6 — نموذج ذكي جداً
    {"provider": "nvidia", "model": "moonshotai/kimi-k2.6", "api_key": NVIDIA_KIMI_K26_KEY},
    # ⭐ NVIDIA GLM 5.1 — نموذج صيني قوي
    {"provider": "nvidia", "model": "thudm/glm-5.1", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ NVIDIA MiniMax M2.7 — نموذج متقدم
    {"provider": "nvidia", "model": "minimaxai/minimax-m2.7", "api_key": NVIDIA_MINIMAX_M27_KEY},
    # ⭐ Mistral Large — fallback قوي
    {"provider": "mistral", "model": "mistral-large-latest"},
    # ⭐ Mistral Medium — fallback أخف
    {"provider": "mistral", "model": "mistral-medium-latest"},
]

# Default (backward compatibility)
CHAT_MODELS = PREMIUM_CHAT_MODELS

# ⚡ Simple - الرسائل البسيطة (تحيات، أسئلة قصيرة، أسئلة هوية)
# FREE: Step 3.7 Flash → Llama 3.3 70B → Mistral Small → SambaNova
# PREMIUM: DeepSeek V4 Pro → Step 3.7 Flash → Mistral Small
FREE_SIMPLE_MODELS = [
    # ⚡ NVIDIA Step 3.7 Flash — أسرع رد
    {"provider": "nvidia", "model": "stepfun-ai/step-3.7-flash", "api_key": NVIDIA_STEP_37_FLASH_KEY},
    # ⚡ NVIDIA Llama 3.3 70B
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⚡ Mistral Small — سريع
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⚡ SambaNova fallback
    {"provider": "sambanova", "model": "Meta-Llama-3.3-70B-Instruct"},
]

PREMIUM_SIMPLE_MODELS = [
    # ⚡ NVIDIA DeepSeek V4 Pro — سريع وقوي
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-pro", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⚡ NVIDIA Step 3.7 Flash — أسرع رد
    {"provider": "nvidia", "model": "stepfun-ai/step-3.7-flash", "api_key": NVIDIA_STEP_37_FLASH_KEY},
    # ⚡ Mistral Small — رد فوري
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default
SIMPLE_MODELS = PREMIUM_SIMPLE_MODELS

# 🔥 Deep Search - البحث العميق
# FREE: DeepSeek V4 Flash → Mistral Small → SambaNova
# PREMIUM: DeepSeek V4 Pro → Kimi K2.6 → MiniMax M2.7 → Mistral Large
FREE_DEEP_SEARCH_MODELS = [
    # 🔴 البحث العميق محدود للمجاني
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-flash", "api_key": NVIDIA_DEEPSEEK_V4_FLASH_KEY},
    {"provider": "mistral", "model": "mistral-small-latest"},
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_DEEP_SEARCH_MODELS = [
    # ⭐ NVIDIA DeepSeek V4 Pro — أساسي للبحث العميق
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-pro", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA Kimi K2.6 — ذكي في البحث
    {"provider": "nvidia", "model": "moonshotai/kimi-k2.6", "api_key": NVIDIA_KIMI_K26_KEY},
    # ⭐ NVIDIA MiniMax M2.7 — تحليل متقدم
    {"provider": "nvidia", "model": "minimaxai/minimax-m2.7", "api_key": NVIDIA_MINIMAX_M27_KEY},
    # ⭐ Mistral Large — fallback
    {"provider": "mistral", "model": "mistral-large-latest"},
]

# Default
DEEP_SEARCH_MODELS = PREMIUM_DEEP_SEARCH_MODELS

# 👨‍💻 Coding - البرمجة
# FREE: Step 3.7 Flash → Codestral → Mistral Small → SambaNova
# PREMIUM: GLM 5.1 → DeepSeek V4 Pro → Kimi K2.6 → Codestral → Mistral Large
FREE_CODING_MODELS = [
    # ⭐ NVIDIA Step 3.7 Flash — سريع في البرمجة
    {"provider": "nvidia", "model": "stepfun-ai/step-3.7-flash", "api_key": NVIDIA_STEP_37_FLASH_KEY},
    # ⭐ Mistral Codestral — متخصص برمجة
    {"provider": "mistral", "model": "codestral-latest"},
    # ⭐ Mistral Small
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_CODING_MODELS = [
    # ⭐ NVIDIA GLM 5.1 — أساسي للبرمجة في البريميوم
    {"provider": "nvidia", "model": "thudm/glm-5.1", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ NVIDIA DeepSeek V4 Pro — قوي في البرمجة
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-pro", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA Kimi K2.6 — كويس في الكود
    {"provider": "nvidia", "model": "moonshotai/kimi-k2.6", "api_key": NVIDIA_KIMI_K26_KEY},
    # ⭐ Mistral Codestral — متخصص برمجة
    {"provider": "mistral", "model": "codestral-latest"},
    # ⭐ Mistral Large — fallback
    {"provider": "mistral", "model": "mistral-large-latest"},
]

# Default
CODING_MODELS = PREMIUM_CODING_MODELS

# 📄 Summary - التلخيص
# FREE: DeepSeek V4 Flash → Mistral Small → Nemo → SambaNova
# PREMIUM: DeepSeek V4 Pro → MiniMax M2.7 → Mistral Large → Medium
FREE_SUMMARY_MODELS = [
    # ⭐ NVIDIA DeepSeek V4 Flash — سريع في التلخيص
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-flash", "api_key": NVIDIA_DEEPSEEK_V4_FLASH_KEY},
    # ⭐ Mistral Small
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ Mistral Nemo
    {"provider": "mistral", "model": "open-mistral-nemo"},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_SUMMARY_MODELS = [
    # ⭐ NVIDIA DeepSeek V4 Pro — أساسي للتلخيص
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-pro", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA MiniMax M2.7 — تلخيص متقدم
    {"provider": "nvidia", "model": "minimaxai/minimax-m2.7", "api_key": NVIDIA_MINIMAX_M27_KEY},
    # ⭐ Mistral Large
    {"provider": "mistral", "model": "mistral-large-latest"},
    # ⭐ Mistral Medium
    {"provider": "mistral", "model": "mistral-medium-latest"},
]

# Default
SUMMARY_MODELS = PREMIUM_SUMMARY_MODELS

# 👁️ Vision - تحليل الصور
# FREE: Llama 3.2 90B Vision → Nemotron Nano VL → Mistral Pixtral
# PREMIUM: Llama 3.2 90B Vision → Nemotron Nano VL → Mistral Pixtral
FREE_VISION_MODELS = [
    # ⭐ NVIDIA Llama 3.2 90B Vision — أساسي للرؤية
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Nemotron Nano VL — fallback خفيف
    {"provider": "nvidia", "model": "nvidia/nemotron-nano-12b-v2-vl", "api_key": NVIDIA_NEMOTRON_NANO_VL_KEY},
    # ⭐ Mistral Pixtral — fallback
    {"provider": "mistral", "model": "pixtral-large-latest"},
]

PREMIUM_VISION_MODELS = [
    # ⭐ NVIDIA Llama 3.2 90B Vision — أساسي للرؤية
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Nemotron Nano VL — fallback خفيف
    {"provider": "nvidia", "model": "nvidia/nemotron-nano-12b-v2-vl", "api_key": NVIDIA_NEMOTRON_NANO_VL_KEY},
    # ⭐ Mistral Pixtral — fallback
    {"provider": "mistral", "model": "pixtral-large-latest"},
]

# Default
VISION_MODELS = PREMIUM_VISION_MODELS

# 🎨 Image Generation - إنشاء الصور (بريميوم بس!)
# بيتستخدم NVIDIA Visual GenAI API: https://ai.api.nvidia.com/v1/genai/{model}
# Payload: {"prompt": "...", "mode": "base", "seed": N, "steps": 30}
# Response: {"artifacts": [{"base64": "...", "finishReason": "...", "seed": N}]}
PREMIUM_IMAGE_GEN_MODELS = [
    # 🎨 NVIDIA Stable Diffusion 3.5 Large — أقوى نموذج لإنشاء الصور (8B params، واقعية عالية)
    {"provider": "nvidia_genai", "model": "stabilityai/stable-diffusion-3.5-large", "api_key": NVIDIA_SD35_LARGE_KEY},
    # 🎨 NVIDIA Flux.1 Kontext Dev — نموذج متقدم من Black Forest Labs
    {"provider": "nvidia_genai", "model": "black-forest-labs/flux.1-kontext-dev", "api_key": NVIDIA_FLUX_KONTEXT_KEY},
    # 🎨 NVIDIA Flux.1 Dev — fallback قوي (النموذج القديم)
    {"provider": "nvidia_genai", "model": "black-forest-labs/flux.1-dev", "api_key": NVIDIA_QWEN_IMAGE_KEY},
]

# 🖌️ Image Edit - تعديل الصور (بريميوم بس!)
# بيتستخدم NVIDIA Visual GenAI API مع canny/depth mode
# Payload: {"prompt": "...", "image": "base64", "mode": "canny", "seed": 0}
# Response: {"artifacts": [{"base64": "..."}]}
PREMIUM_IMAGE_EDIT_MODELS = [
    # 🖌️ NVIDIA Stable Diffusion 3.5 Large (canny/depth mode) — أقوى نموذج لتعديل الصور
    {"provider": "nvidia_genai", "model": "stabilityai/stable-diffusion-3.5-large", "api_key": NVIDIA_SD35_LARGE_KEY},
    # 🖌️ NVIDIA Flux.1 Dev (canny mode) — fallback قوي للتعديل
    {"provider": "nvidia_genai", "model": "black-forest-labs/flux.1-dev", "api_key": NVIDIA_QWEN_IMAGE_EDIT_KEY},
]

# ═══════════════════════════════════════
# إعدادات السرعة - Speed Settings
# ═══════════════════════════════════════

REQUEST_TIMEOUT = 120  # Timeout for regular AI requests (increased from 60 → 120)
FAST_TIMEOUT = 30      # Timeout for simple/greeting messages (increased from 15 → 30)
MAX_RETRIES = 3        # Maximum retry attempts (increased from 2 → 3)
RETRY_DELAY = 2        # Delay between retries in seconds

# Image generation timeout (longer because image generation takes more time)
IMAGE_GEN_TIMEOUT = 180  # 3 minutes for image generation (Flux takes longer)
IMAGE_EDIT_TIMEOUT = 180  # 3 minutes for image editing

# NVIDIA Visual GenAI API (different from chat completions API)
NVIDIA_GENAI_BASE_URL = "https://ai.api.nvidia.com/v1/genai"

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
# إعدادات البوت - Bot Settings
# ═══════════════════════════════════════

BOT_NAME = "My Bro"
BOT_VERSION = "9.15"

# ═══════════════════════════════════════
# معرف المطور - Developer Identity
# ═══════════════════════════════════════

_DEVELOPER_ID_FROM_ENV = int(CHAT_ID) if CHAT_ID else 0
DEVELOPER_USER_ID = _DEVELOPER_ID_FROM_ENV if _DEVELOPER_ID_FROM_ENV else 8674141938
DEVELOPER_USERNAME = "ziadamr"  # @ziadamr

# ═══════════════════════════════════════
# إعدادات Premium - Premium Settings
# ═══════════════════════════════════════

DEVELOPER_TELEGRAM = "@ziadamr"
DEVELOPER_TELEGRAM_URL = "https://t.me/ziadamr"
DEVELOPER_WHATSAPP = "01203551789"
DEVELOPER_WHATSAPP_URL = "https://wa.me/201203551789"

# Premium limits
FREE_AI_MESSAGES_PER_DAY = 20
FREE_PDF_PER_DAY = 2
FREE_IMAGES_PER_DAY = 3
FREE_YOUTUBE_PER_DAY = 2
FREE_SEARCHES_PER_DAY = 5

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

# Cobalt Self-Hosted — أقوى بديل لتحميل الفيديوهات (أول طبقة في fallback chain)
# بنشغله على Railway سيرفر منفصل ونربطه بالبوت
COBALT_API_URL = os.environ.get("COBALT_API_URL", "")  # مثال: https://cobalt.up.railway.app
COBALT_API_KEY = os.environ.get("COBALT_API_KEY", "")   # API Key من keys.json

# RapidAPI — fallback لتحميل Threads وخدمات تانية
# اشترك في: https://rapidapi.com/snapvidsnet/api/threads-downloader
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

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
    "bio_ar": "مطوّر ويب متكامل متخصص في Next.js و React و TypeScript وتقنيات الويب الحديثة. بيبني أدوات وبوتات بتقنية الذكاء الاصطناعي بتخلي التكنولوجيا متاحة للجميع، خصوصاً الناطقين بالعربية. مؤسس ومدير تنفيذي لشركة Qudra Tech — شركة تقنية مصرية ناشئة متخصصة في حلول الويب المبتكرة وتطبيقات الذكاء الاصطناعي. شغوف إنه يعمل كوبري بين أحدث تقنيات الذكاء الاصطناعي والعالم العربي.",
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
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DATABASE_PATH = os.path.join(DATA_DIR, "memory.db")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")

# ═══════════════════════════════════════
# إعدادات الجدولة - Scheduler Settings
# ═══════════════════════════════════════

DAILY_NEWS_HOUR = 9
DAILY_NEWS_MINUTE = 0
DAILY_NEWS_TIMEZONE = "Africa/Cairo"
BROADCAST_DELAY_SECONDS = 0.5

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

TOP_NEWS_BADGE = "🔥"
REGULAR_NEWS_BADGE = "⚪️"
