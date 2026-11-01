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
# ✅ محدثة 2026-11-02 — النماذج القديمة اتسحبت من NVIDIA (410 Gone) والجديدة مختبرة لايف من السيرفر
# الحية: nemotron-3.5-lightning (0.5s) → nemotron-3.5-super-vl (0.6s) → mistral-large-4 (7-27s)
FREE_CHAT_MODELS = [
    # ⭐ NVIDIA Nemotron 3.5 Lightning — أسرع نموذج حي (0.5 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — قوي وسريع (0.6 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ Mistral Small — fallback (لو الـ429 خلص)
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ NVIDIA Mistral Large 4 — fallback قوي (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_GLM_51_KEY},
]

PREMIUM_CHAT_MODELS = [
    # ⭐ NVIDIA Nemotron 3.5 Lightning — أساسي (0.5 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — موازي سريع (0.6 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Mistral Large 4 — قوي للردود العميقة (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ Mistral Large — fallback (لو الـ429 خلص)
    {"provider": "mistral", "model": "mistral-large-latest"},
]

# Default (backward compatibility)
CHAT_MODELS = PREMIUM_CHAT_MODELS

# ⚡ Simple - الرسائل البسيطة (تحيات، أسئلة قصيرة، أسئلة هوية)
# ✅ محدثة 2026-11-02 — أول مسارين بيشتغلوا parallel والاتنين مختبرين ✅
FREE_SIMPLE_MODELS = [
    # ⚡ NVIDIA Nemotron 3.5 Lightning — أسرع رد فوري (0.5 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⚡ NVIDIA Nemotron 3.5 Super VL — موازي (0.6 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⚡ Mistral Small — fallback
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⚡ SambaNova fallback (المفتاح الحالي مرفوض — لو اتجدد هيرجع يشتغل)
    {"provider": "sambanova", "model": "Meta-Llama-3.3-70B-Instruct"},
]

PREMIUM_SIMPLE_MODELS = [
    # ⚡ NVIDIA Nemotron 3.5 Lightning — أساسي (0.5 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⚡ NVIDIA Nemotron 3.5 Super VL — موازي سريع (0.6 ثانية، مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⚡ NVIDIA Mistral Large 4 — fallback قوي (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_GLM_51_KEY},
    # ⚡ Mistral Medium — fallback أخير
    {"provider": "mistral", "model": "mistral-medium-latest"},
]

# Default
SIMPLE_MODELS = PREMIUM_SIMPLE_MODELS

# 🔥 Deep Search - البحث العميق
# ✅ محدثة 2026-11-02 — Mistral Large 4 هو الأقوى المتاح للمهام العميقة (مختبر ✅)
FREE_DEEP_SEARCH_MODELS = [
    # 🔴 NVIDIA Mistral Large 4 — الأقوى المتاح (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_GLM_51_KEY},
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    {"provider": "mistral", "model": "mistral-small-latest"},
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_DEEP_SEARCH_MODELS = [
    # ⭐ NVIDIA Mistral Large 4 — أساسي للبحث العميق (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — تحليل سريع (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Lightning — سريع (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ Mistral Large — fallback
    {"provider": "mistral", "model": "mistral-large-latest"},
]

# Default
DEEP_SEARCH_MODELS = PREMIUM_DEEP_SEARCH_MODELS

# 👨‍💻 Coding - البرمجة
# ✅ محدثة 2026-11-02 — Mistral Large 4 + Nemotron Super VL (مختبرين ✅)
FREE_CODING_MODELS = [
    # ⭐ NVIDIA Mistral Large 4 — قوي في الكود (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_STEP_37_FLASH_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — سريع (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ Mistral Codestral — متخصص برمجة (لو الـ429 خلص)
    {"provider": "mistral", "model": "codestral-latest"},
    # ⭐ Mistral Small — fallback
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_CODING_MODELS = [
    # ⭐ NVIDIA Mistral Large 4 — أساسي للبرمجة (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — موازي (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Lightning — سريع (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ Mistral Codestral — متخصص برمجة
    {"provider": "mistral", "model": "codestral-latest"},
    # ⭐ Mistral Large — fallback
    {"provider": "mistral", "model": "mistral-large-latest"},
]

# Default
CODING_MODELS = PREMIUM_CODING_MODELS

# 📄 Summary - التلخيص
# ✅ محدثة 2026-11-02 — Nemotron Lightning سريع جدًا في التلخيص (مختبر ✅)
FREE_SUMMARY_MODELS = [
    # ⭐ NVIDIA Nemotron 3.5 Lightning — سريع في التلخيص (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — موازي (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ Mistral Small — fallback
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_SUMMARY_MODELS = [
    # ⭐ NVIDIA Mistral Large 4 — تلخيص عميق (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Lightning — سريع (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — موازي (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ Mistral Large — fallback
    {"provider": "mistral", "model": "mistral-large-latest"},
    # ⭐ Mistral Medium — fallback أخير
    {"provider": "mistral", "model": "mistral-medium-latest"},
]

# Default
SUMMARY_MODELS = PREMIUM_SUMMARY_MODELS

# 👁️ Vision - تحليل الصور
# ✅ محدثة 2026-11-02 — Nemotron 3.5 Super VL هو البديل الحي الأسرع (0.6s، مختبر ✅)
FREE_VISION_MODELS = [
    # ⭐ NVIDIA Nemotron 3.5 Super VL — أساسي للرؤية (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Llama 3.2 90B Vision — fallback (بطيء أحيانًا)
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_NEMOTRON_NANO_VL_KEY},
    # ⭐ Mistral Pixtral — fallback
    {"provider": "mistral", "model": "pixtral-large-latest"},
]

PREMIUM_VISION_MODELS = [
    # ⭐ NVIDIA Nemotron 3.5 Super VL — أساسي للرؤية (مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Llama 3.2 90B Vision — fallback (بطيء أحيانًا)
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_NEMOTRON_NANO_VL_KEY},
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
