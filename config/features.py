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
# Tier 1: مصادر شركة AI مباشرة (أعلى مصداقية)
SOURCE_CREDIBILITY = {
    "openai.com": 10,
    "deepmind.google": 10,
    "anthropic.com": 10,
    "blog.google": 9,
    "ai.google": 9,
    "microsoft.com": 9,
    "meta.ai": 9,
    "about.fb.com": 9,
    "nvidia.com": 8,
    "huggingface.co": 8,
    "mistral.ai": 8,
    "x.ai": 8,
    "arxiv.org": 8,
    "deepseek.com": 8,
    "minimaxi.com": 7,

    # Tier 2: وسائل إعلام تقنية رائدة
    "reuters.com": 9,
    "technologyreview.com": 9,  # MIT Tech Review
    "bbc.co.uk": 8,
    "theguardian.com": 8,
    "nytimes.com": 8,
    "cnbc.com": 8,
    "techcrunch.com": 8,
    "theverge.com": 8,
    "spectrum.ieee.org": 8,  # IEEE Spectrum
    "arstechnica.com": 7,
    "venturebeat.com": 7,
    "wired.com": 7,
    "zdnet.com": 7,
    "404media.co": 7,
    "theregister.com": 7,  # The Register
    "syncedreview.com": 7,  # Synced AI Review
    "aitrends.com": 7,  # AI Trends

    # Tier 3: Apple Intelligence
    "9to5mac.com": 7,
    "appleinsider.com": 7,
    "macrumors.com": 7,
    "apple.com": 9,

    # Tier 4: مصادر عامة/مجمّعة
    "news.google.com": 6,  # aggregator — trust depends on original source
    "sciencedaily.com": 7,
    
    # شركات AI صينية
    "zhipuai.com": 7,
    "baidu.com": 8,
    "alibaba.com": 8,
    "tencent.com": 8,
    
    # هاردوير إضافي
    "amd.com": 8,
}

# AI Keywords for filtering (English)
AI_KEYWORDS = [
    # ── شركات ومنتجات AI ──
    "openai", "chatgpt", "gpt-4", "gpt-5", "o1", "o3", "o4",
    "gemini", "deepmind", "google ai",
    "claude", "anthropic",
    "grok", "x.ai", "xAI",
    "mistral", "llama", "phi",
    "copilot", "ai assistant",
    "sora", "dall-e", "midjourney", "stable diffusion",
    "deepseek", "qwen", "codestral",
    "minimax", "minimaxi",
    "perplexity", "cohere",

    # ── Apple Intelligence + Siri ──
    "apple intelligence", "siri ai", "apple ai",
    "on-device ai", "private cloud compute",

    # ── أنواع نماذج ──
    "ai agents", "ai agent", "autonomous ai",
    "foundation model", "foundation models", "large language model", "llm",
    "generative ai", "genai",
    "diffusion model", "text-to-image", "text-to-video",
    "neural network", "transformer",
    "multimodal ai", "vision language model",
    "reinforcement learning", "rlhf",
    "reasoning model", "chain of thought",
    "mixture of experts", "moe",
    "rag", "retrieval augmented",

    # ── مصطلحات عامة ──
    "artificial intelligence", "machine learning", "deep learning",
    "agi", "artificial general intelligence",

    # ─ـ تنظيم وسياسات ──
    "ai regulation", "ai safety", "ai alignment",
    "ai governance", "ai ethics", "ai risk",

    # ── روبوتات وأتمتة ──
    "robot", "humanoid", "autonomous",
    "ai robotics", "embodied ai",

    # ── هاردوير وشركات ──
    "nvidia ai", "gpu ai", "ai chip",
    "ai startup", "ai funding", "ai acquisition",

    # ── تطبيقات ومجالات ──
    "ai model", "ai research", "ai tool",
    "ai-powered", "ai-driven", "ai-based",
    "computer vision", "natural language processing",
    "ai automation", "intelligent automation",

    # ── شركات AI صينية ──
    "chatglm", "glm-4", "glm-5", "zhipu",
    "ernie", "ernie bot", "wenxin",
    "tongyi qianwen", "hunyuan",
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
# ═══════════════════════════════════════════════════════════════
# المصادر مقسمة لـ 4 طبقات:
#   Tier 1 = مصادر شركة AI مباشرة (أعلى مصداقية)
#   Tier 2 = وسائل إعلام تقنية رائدة (مصداقية عالية + تغطية واسعة)
#   Tier 3 = Apple Intelligence + مصادر Apple المخصصة
#   Tier 4 = مصادر عامة/مجمّعة + بدائل Reuters/Anthropic
# ═══════════════════════════════════════════════════════════════
RSS_FEEDS = [
    # ── Tier 1: مصادر شركة AI مباشرة (أعلى مصداقية) ──
    "https://openai.com/blog/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/feed/",  # DeepMind Blog (Google)
    "https://blogs.nvidia.com/feed/",
    "https://huggingface.co/blog/feed.xml",
    "https://www.microsoft.com/en-us/ai/blog/rss/",
    "https://about.fb.com/news/feed/",  # Meta/Facebook AI news

    # ── Tier 2: وسائل إعلام تقنية رائدة ──
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://arstechnica.com/tag/ai/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://www.technologyreview.com/feed/",  # MIT Tech Review
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC Tech
    "https://spectrum.ieee.org/rss/fulltext",  # IEEE Spectrum
    "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",  # ZDNet AI
    "https://www.404media.co/rss/",  # 404 Media (tech investigations)
    "https://www.theguardian.com/technology/artificialintelligenceai/rss",  # The Guardian AI
    "https://feeds.bbci.co.uk/news/technology/rss.xml",  # BBC Tech
    "https://www.theregister.com/headlines.atom",  # The Register (UK tech)
    "https://syncedreview.com/feed/",  # Synced AI Research Review
    "https://www.aitrends.com/feed/",  # AI Trends

    # ── Tier 3: Apple Intelligence + مصادر Apple ──
    "https://9to5mac.com/feed/",  # 9to5Mac — Apple Intelligence + Siri news
    "https://appleinsider.com/rss/news/",  # AppleInsider
    "https://news.google.com/rss/search?q=apple+intelligence+siri+AI&hl=en-US&gl=US&ceid=US:en",  # Google News: Apple Intelligence

    # ── Tier 4: مصادر عامة/مجمّعة + بدائل للشركات اللي معندهاش RSS ──
    # بدائل Reuters (401) و Anthropic (404)
    "https://news.google.com/rss/search?q=reuters+artificial+intelligence&hl=en-US&gl=US&ceid=US:en",  # Google News: Reuters AI
    "https://news.google.com/rss/search?q=anthropic+claude+AI&hl=en-US&gl=US&ceid=US:en",  # Google News: Anthropic/Claude
    # بدائل xAI/Grok و DeepSeek و MiniMax و Mistral (شركات معندهاش RSS خاص)
    "https://news.google.com/rss/search?q=xAI+grok+elon+musk+AI&hl=en-US&gl=US&ceid=US:en",  # Google News: xAI/Grok
    "https://news.google.com/rss/search?q=deepseek+AI+model&hl=en-US&gl=US&ceid=US:en",  # Google News: DeepSeek
    "https://news.google.com/rss/search?q=minimax+AI+model&hl=en-US&gl=US&ceid=US:en",  # Google News: MiniMax
    "https://news.google.com/rss/search?q=mistral+AI+model&hl=en-US&gl=US&ceid=US:en",  # Google News: Mistral
    # شركات AI صينية وأسيوية (GLM/Zhipu, Baidu/ERNIE, Alibaba/Qwen, Tencent/Hunyuan)
    "https://news.google.com/rss/search?q=zhipu+AI+GLM+model&hl=en-US&gl=US&ceid=US:en",  # Google News: Zhipu/GLM
    "https://news.google.com/rss/search?q=baidu+ernie+AI+model&hl=en-US&gl=US&ceid=US:en",  # Google News: Baidu/ERNIE
    "https://news.google.com/rss/search?q=alibaba+qwen+AI+model&hl=en-US&gl=US&ceid=US:en",  # Google News: Alibaba/Qwen
    "https://news.google.com/rss/search?q=tencent+hunyuan+AI+model&hl=en-US&gl=US&ceid=US:en",  # Google News: Tencent/Hunyuan
    # AI هاردوير (AMD, Intel)
    "https://news.google.com/rss/search?q=AMD+MI300+AI+chip&hl=en-US&gl=US&ceid=US:en",  # Google News: AMD AI
    "https://news.google.com/rss/search?q=intel+AI+chip+Gaudi&hl=en-US&gl=US&ceid=US:en",  # Google News: Intel AI
    # روبوتات AI (Figure AI, Tesla Optimus, Boston Dynamics)
    "https://news.google.com/rss/search?q=figure+AI+humanoid+robot&hl=en-US&gl=US&ceid=US:en",  # Google News: Figure AI
    "https://news.google.com/rss/search?q=tesla+optimus+robot+AI&hl=en-US&gl=US&ceid=US:en",  # Google News: Tesla Optimus
    # AI Agents و Automation
    "https://news.google.com/rss/search?q=AI+agents+autonomous+2024&hl=en-US&gl=US&ceid=US:en",  # Google News: AI Agents
    # AI Safety و Regulation
    "https://news.google.com/rss/search?q=AI+safety+regulation+policy+2024&hl=en-US&gl=US&ceid=US:en",  # Google News: AI Safety
    # تغطية عامة شاملة
    "https://news.google.com/rss/search?q=artificial+intelligence+when:1d&hl=en-US&gl=US&ceid=US:en",  # Google News: AI general
    "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",  # ScienceDaily AI
    "https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/technology/rss.xml",  # NYTimes Tech
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
    "apple": {
        "name": "Apple AI",
        "name_ar": "آبل إيه آي",
        "keywords": ["apple intelligence", "apple ai", "siri ai", "siri", "private cloud compute", "on-device ai", "apple ml"],
        "products": ["Apple Intelligence", "Siri AI", "Private Cloud Compute", "On-Device AI"],
        "description": "Tech giant bringing AI to consumer devices",
        "description_ar": "شركة تقنية عملاقة تجلب الذكاء الاصطناعي لأجهزة المستهلكين",
        "rss_keywords": ["apple intelligence", "siri", "apple ai"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "name_ar": "ديب سيك",
        "keywords": ["deepseek", "deepseek-v", "deepseek-r1", "deepseek coder"],
        "products": ["DeepSeek-V", "DeepSeek-R1", "DeepSeek Coder"],
        "description": "Chinese AI lab producing competitive open-source models",
        "description_ar": "مختبر ذكاء اصطناعي صيني ينتج نماذج مفتوحة المصدر تنافسية",
        "rss_keywords": ["deepseek"],
    },
    "minimax": {
        "name": "MiniMax",
        "name_ar": "ميني ماكس",
        "keywords": ["minimax", "minimaxi", "minimax ai"],
        "products": ["MiniMax-01", "MiniMax-Text", "MiniMax-Voice"],
        "description": "Chinese AI company specializing in multimodal models",
        "description_ar": "شركة ذكاء اصطناعي صينية متخصصة في النماذج متعددة الوسائط",
        "rss_keywords": ["minimax", "minimaxi"],
    },
    "mistral": {
        "name": "Mistral AI",
        "name_ar": "ميسترال إيه آي",
        "keywords": ["mistral", "mistral ai", "codestral", "mistral large", "mistral medium", "pixtral"],
        "products": ["Mistral Large", "Mistral Medium", "Codestral", "Pixtral", "Le Chat"],
        "description": "French AI company building efficient open and commercial models",
        "description_ar": "شركة ذكاء اصطناعي فرنسية تبني نماذج مفتوحة وتجارية فعالة",
        "rss_keywords": ["mistral", "codestral"],
    },
    "perplexity": {
        "name": "Perplexity AI",
        "name_ar": "بيربلكسيتي إيه آي",
        "keywords": ["perplexity", "perplexity ai", "perplexity pro"],
        "products": ["Perplexity Pro", "Perplexity Search", "Perplexity API"],
        "description": "AI-powered search engine and answer engine",
        "description_ar": "محرك بحث وإجابات يعمل بالذكاء الاصطناعي",
        "rss_keywords": ["perplexity"],
    },
    "zhipu": {
        "name": "Zhipu AI / GLM",
        "name_ar": "زيپو إيه آي / GLM",
        "keywords": ["zhipu", "chatglm", "glm-4", "glm-5", "chatglm-4", "zhipu ai"],
        "products": ["ChatGLM", "GLM-4", "GLM-5", "CogVideoX"],
        "description": "Leading Chinese AI lab behind the GLM model family",
        "description_ar": "مختبر ذكاء اصطناعي صيني رائد وراء عائلة نماذج GLM",
        "rss_keywords": ["zhipu", "chatglm", "glm"],
    },
    "baidu": {
        "name": "Baidu AI / ERNIE",
        "name_ar": "بايدو إيه آي / إرني",
        "keywords": ["baidu ai", "ernie", "ernie bot", "wenxin", "baidu"],
        "products": ["ERNIE Bot", "ERNIE 4.0", "ERNIE 5.0", "Wenxin"],
        "description": "Chinese tech giant with ERNIE AI chatbot and search",
        "description_ar": "شركة تقنية صينية عملاقة صانعة روبوت ERNIE ومحرك البحث",
        "rss_keywords": ["baidu", "ernie", "wenxin"],
    },
    "alibaba": {
        "name": "Alibaba AI / Qwen",
        "name_ar": "علي بابا إيه آي / كوين",
        "keywords": ["alibaba ai", "qwen", "tongyi qianwen", "alibaba qwen"],
        "products": ["Qwen", "Qwen 2.5", "Tongyi Qianwen", "Qwen-VL"],
        "description": "Chinese e-commerce giant with open-source Qwen AI models",
        "description_ar": "شركة تجارة إلكترونية صينية عملاقة صانعة نماذج Qwen مفتوحة المصدر",
        "rss_keywords": ["alibaba", "qwen", "tongyi"],
    },
    "tencent": {
        "name": "Tencent AI / Hunyuan",
        "name_ar": "تنسنت إيه آي / هونيوان",
        "keywords": ["tencent ai", "hunyuan", "tencent hunyuan", "tencent"],
        "products": ["Hunyuan", "Hunyuan-Large", "Hunyuan 3D"],
        "description": "Chinese tech giant with Hunyuan foundation model",
        "description_ar": "شركة تقنية صينية عملاقة صانعة نموذج هونيوان الأساسي",
        "rss_keywords": ["tencent", "hunyuan"],
    },
    "amd": {
        "name": "AMD AI",
        "name_ar": "إيه إم دي إيه آي",
        "keywords": ["amd", "mi300", "mi350", "amd ai", "amd gpu", "instinct"],
        "products": ["MI300X", "MI350", "Instinct", "ROCm"],
        "description": "Semiconductor company competing with NVIDIA in AI chips",
        "description_ar": "شركة أشباه موصلات تنافس إنفيديا في رقائق الذكاء الاصطناعي",
        "rss_keywords": ["amd", "mi300", "instinct"],
    },
    "figure_ai": {
        "name": "Figure AI",
        "name_ar": "فيجر إيه آي",
        "keywords": ["figure ai", "figure humanoid", "figure robot", "figure 02"],
        "products": ["Figure 01", "Figure 02", "Figure Humanoid"],
        "description": "AI humanoid robotics company backed by OpenAI and NVIDIA",
        "description_ar": "شركة روبوتات هيكلية بشرية مدعومة من OpenAI و NVIDIA",
        "rss_keywords": ["figure ai", "figure humanoid"],
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
