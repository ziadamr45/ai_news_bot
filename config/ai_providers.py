"""
إعدادات مزودين AI - AI Providers & Model Routes
═══════════════════════════════════════════════════
NVIDIA keys, Mistral, SambaNova, Groq, OpenAI, OpenRouter,
Model routes (Free/Premium), Timeout & Retry settings
"""

import os

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

# NVIDIA API Keys — centralized dictionary
NVIDIA_KEYS = {
    "deepseek_v4_pro": NVIDIA_DEEPSEEK_V4_PRO_KEY,
    "deepseek_v4_flash": NVIDIA_DEEPSEEK_V4_FLASH_KEY,
    "kimi_k26": NVIDIA_KIMI_K26_KEY,
    "glm_51": NVIDIA_GLM_51_KEY,
    "minimax_m27": NVIDIA_MINIMAX_M27_KEY,
    "llama_33_70b": NVIDIA_LLAMA_33_70B_KEY,
    "step_37_flash": NVIDIA_STEP_37_FLASH_KEY,
    "llama_32_90b_vision": NVIDIA_LLAMA_32_90B_VISION_KEY,
    "nemotron_nano_vl": NVIDIA_NEMOTRON_NANO_VL_KEY,
    "qwen_image": NVIDIA_QWEN_IMAGE_KEY,
    "qwen_image_edit": NVIDIA_QWEN_IMAGE_EDIT_KEY,
    "sd35_large": NVIDIA_SD35_LARGE_KEY,
    "flux_kontext": NVIDIA_FLUX_KONTEXT_KEY,
}


def get_nvidia_key(model_name: str) -> str:
    """Get NVIDIA API key by model name — single point of access"""
    return NVIDIA_KEYS.get(model_name, "")


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
# FREE: Mistral Small → Mistral Nemo → Llama 3.3 70B → DeepSeek V4 Flash (heavy) → SambaNova
# PREMIUM: Mistral Large → Mistral Medium → Kimi K2.6 → MiniMax M2.7 → GLM 5.1 → DeepSeek V4 Pro (heavy) → SambaNova
FREE_CHAT_MODELS = [
    # ⭐ Mistral Small — أساسي للمجاني (سريع ومجاني دائم)
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ Mistral Nemo — fallback سريع
    {"provider": "mistral", "model": "open-mistral-nemo"},
    # ⭐ NVIDIA Llama 3.3 70B — fallback قوي
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ NVIDIA DeepSeek V4 Flash — للحواج الثقيلة بس (تحليل عميق، محتوى معقد)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-flash", "api_key": NVIDIA_DEEPSEEK_V4_FLASH_KEY},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_CHAT_MODELS = [
    # ⭐ Mistral Large — أساسي للبريميوم (سريع وضمان الرد)
    {"provider": "mistral", "model": "mistral-large-latest"},
    # ⭐ Mistral Medium — fallback سريع
    {"provider": "mistral", "model": "mistral-medium-latest"},
    # ⭐ NVIDIA Kimi K2.6 — نموذج ذكي جداً
    {"provider": "nvidia", "model": "moonshotai/kimi-k2.6", "api_key": NVIDIA_KIMI_K26_KEY},
    # ⭐ NVIDIA MiniMax M2.7 — نموذج متقدم
    {"provider": "nvidia", "model": "minimaxai/minimax-m2.7", "api_key": NVIDIA_MINIMAX_M27_KEY},
    # ⭐ NVIDIA GLM 5.1 — نموذج صيني قوي
    {"provider": "nvidia", "model": "thudm/glm-5.1", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ NVIDIA DeepSeek V4 Pro — للحواج الثقيلة بس (تحليل عميق، محتوى معقد)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-pro", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
]

# Default (backward compatibility)
CHAT_MODELS = PREMIUM_CHAT_MODELS

# ⚡ Simple - الرسائل البسيطة (تحيات، أسئلة قصيرة، أسئلة هوية)
# FREE: Mistral Small → Llama 3.3 70B → Step 3.7 Flash → SambaNova
# PREMIUM: Mistral Large → Step 3.7 Flash → Mistral Medium
FREE_SIMPLE_MODELS = [
    # ⚡ Mistral Small — أسرع رد فوري
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⚡ NVIDIA Llama 3.3 70B
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⚡ NVIDIA Step 3.7 Flash
    {"provider": "nvidia", "model": "stepfun-ai/step-3.7-flash", "api_key": NVIDIA_STEP_37_FLASH_KEY},
    # ⚡ SambaNova fallback
    {"provider": "sambanova", "model": "Meta-Llama-3.3-70B-Instruct"},
]

PREMIUM_SIMPLE_MODELS = [
    # ⚡ Mistral Large — أساسي للبريميوم (حتى الرسائل البسيطة)
    {"provider": "mistral", "model": "mistral-large-latest"},
    # ⚡ NVIDIA Step 3.7 Flash — fallback سريع
    {"provider": "nvidia", "model": "stepfun-ai/step-3.7-flash", "api_key": NVIDIA_STEP_37_FLASH_KEY},
    # ⚡ Mistral Medium — fallback
    {"provider": "mistral", "model": "mistral-medium-latest"},
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

REQUEST_TIMEOUT = 20      # Timeout for regular AI requests (fast fail → next model)
FAST_TIMEOUT = 15         # Timeout for simple/greeting messages
MAX_RETRIES = 2           # Maximum retry attempts
RETRY_DELAY = 1           # Delay between retries in seconds

# Image generation timeout (longer because image generation takes more time)
IMAGE_GEN_TIMEOUT = 180  # 3 minutes for image generation (Flux takes longer)
IMAGE_EDIT_TIMEOUT = 180  # 3 minutes for image editing

# NVIDIA Visual GenAI API (different from chat completions API)
NVIDIA_GENAI_BASE_URL = "https://ai.api.nvidia.com/v1/genai"
