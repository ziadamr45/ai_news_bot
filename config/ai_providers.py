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
# ✅ خطة زياد الأصلية مترمّرة 2026-11-02: كل موديل اتسحب من NVIDIA (410/404) اتحطّ مكانه البديل الحي
# — كل البدائل مختبرة لايف من السيرفر بنفس اليوم:
#   mistral-small (API) ✅ | open-mistral-nemo (1.2s) ✅ | nemotron-3.5-super-vl (0.5s) ✅
#   nemotron-3-ultra-550b (reasoning حقيقي 🧠 think ON/OFF اتنين شغالين) ✅ | mistral-large-4 على NVIDIA ✅
#   step-5-preview (28s) ✅ | meta/llama-3.2-90b-vision (43s) ✅
# الماتة المؤكدة (410/404/hang): llama-3.3-70b, deepseek-v4-flash/pro, kimi-k2.6, minimax-m2.7,
#   thudm/glm-5.1, z-ai/glm-5.3-flash, deepseek-v4.1-flash, gemma-4-31b, gpt-oss-20b, pixtral
# و mistral-large على Mistral API بقّت 403 (مش متاحة في الاشتراك) → بديلها mistral-large-4 على NVIDIA
FREE_CHAT_MODELS = [
    # ⭐ Mistral Small — أساسي للمجاني (سريع ومجاني) — خطة زياد الأصلية
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ Mistral Nemo — fallback سريع (حي ومختبر ✅ 1.2s)
    {"provider": "mistral", "model": "open-mistral-nemo"},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — بدل Llama 3.3 70B المسحوب (0.5s مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Nemotron 3 Ultra 550B — بدل DeepSeek V4 Flash للحواج الثقيلة (reasoning مفعّل 🧠)
    {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b", "api_key": NVIDIA_DEEPSEEK_V4_FLASH_KEY},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_CHAT_MODELS = [
    # ⭐ NVIDIA Mistral Large 4 — بدل Mistral Large API (بقّت 403) — مختبر ✅
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ Mistral Medium — fallback (429 مؤقت — بيرجع لما الـ rate limit يفضى)
    {"provider": "mistral", "model": "mistral-medium-latest"},
    # ⭐ NVIDIA Nemotron 3 Ultra 550B — بدل Kimi K2.6 (ذكي جدًا + reasoning 🧠 — ميزة البريميوم!)
    {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b", "api_key": NVIDIA_KIMI_K26_KEY},
    # ⭐ NVIDIA Step 5 Preview — بدل MiniMax M2.7 (مختبر ✅ 28s)
    {"provider": "nvidia", "model": "stepfun-ai/step-5-preview", "api_key": NVIDIA_STEP_37_FLASH_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — بدل GLM 5.1 (0.5s مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ NVIDIA Nemotron 3.5 Lightning — بدل DeepSeek V4 Pro (سريع 0.5s ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ Mistral Small — ضمان الرد النهائي (لو كله فشل)
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default (backward compatibility)
CHAT_MODELS = PREMIUM_CHAT_MODELS

# ⚡ Simple - الرسائل البسيطة (تحيات، أسئلة قصيرة، أسئلة هوية)
# ✅ خطة زياد الأصلية — البدائل الحية المختبرة
FREE_SIMPLE_MODELS = [
    # ⚡ Mistral Small — أسرع رد فوري — خطة زياد الأصلية
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⚡ Mistral Nemo — fallback سريع (حي ✅ 1.2s)
    {"provider": "mistral", "model": "open-mistral-nemo"},
    # ⚡ NVIDIA Nemotron 3.5 Lightning — بدل Step 3.7 Flash المسحوب (0.5s مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⚡ SambaNova fallback (المفتاح الحالي مرفوض — لو اتجدد هيرجع يشتغل)
    {"provider": "sambanova", "model": "Meta-Llama-3.3-70B-Instruct"},
]

PREMIUM_SIMPLE_MODELS = [
    # ⚡ NVIDIA Mistral Large 4 — بدل Mistral Large API (بقّت 403) — مختبر ✅
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_GLM_51_KEY},
    # ⚡ NVIDIA Nemotron 3.5 Lightning — بدل Step 3.7 Flash (0.5s ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⚡ Mistral Medium — fallback أخير
    {"provider": "mistral", "model": "mistral-medium-latest"},
]

# Default
SIMPLE_MODELS = PREMIUM_SIMPLE_MODELS

# 🔥 Deep Search - البحث العميق
# ✅ خطة زياد الأصلية — Nemotron 3 Ultra هو بديل DeepSeek (reasoning حقيقي للبحث العميق)
FREE_DEEP_SEARCH_MODELS = [
    # 🔴 NVIDIA Nemotron 3 Ultra 550B — بدل DeepSeek V4 Flash (reasoning مفعّل 🧠 — بحث عميق حقيقي)
    {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b", "api_key": NVIDIA_DEEPSEEK_V4_FLASH_KEY},
    # 🔴 Mistral Small — خطة زياد الأصلية
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 🔴 SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_DEEP_SEARCH_MODELS = [
    # ⭐ NVIDIA Nemotron 3 Ultra 550B — بدل DeepSeek V4 Pro أساسي للبحث العميق (reasoning 🧠 مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA Mistral Large 4 — بدل Kimi K2.6 في البحث (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_KIMI_K26_KEY},
    # ⭐ NVIDIA Step 5 Preview — بدل MiniMax M2.7 تحليل متقدم (مختبر ✅)
    {"provider": "nvidia", "model": "stepfun-ai/step-5-preview", "api_key": NVIDIA_MINIMAX_M27_KEY},
    # ⭐ Mistral Small — ضمان الرد (بدل Mistral Large API — بقّت 403)
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default
DEEP_SEARCH_MODELS = PREMIUM_DEEP_SEARCH_MODELS

# 👨‍💻 Coding - البرمجة
# ✅ خطة زياد الأصلية — Codestral حي (0.6s) والـ Ultra للبرمجة العميقة بالبريميوم
FREE_CODING_MODELS = [
    # ⭐ Mistral Codestral — بدل Step 3.7 Flash متخصص برمجة (حي ✅ 0.6s)
    {"provider": "mistral", "model": "codestral-latest"},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — سريع (0.5s ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ Mistral Small
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_CODING_MODELS = [
    # ⭐ NVIDIA Nemotron 3 Ultra 550B — بدل GLM 5.1 أساسي للبرمجة في البريميوم (reasoning 🧠 مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b", "api_key": NVIDIA_GLM_51_KEY},
    # ⭐ NVIDIA Mistral Large 4 — بدل DeepSeek V4 Pro قوي في البرمجة (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ Mistral Codestral — بدل Kimi K2.6 متخصص برمجة (حي ✅)
    {"provider": "mistral", "model": "codestral-latest"},
    # ⭐ NVIDIA Nemotron 3.5 Super VL — موازي سريع (0.5s ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ Mistral Small — ضمان الرد
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default
CODING_MODELS = PREMIUM_CODING_MODELS

# 📄 Summary - التلخيص
# ✅ خطة زياد الأصلية — Mistral الأول عشان العربي المضمون في الأخبار
FREE_SUMMARY_MODELS = [
    # ⭐ Mistral Small — عربي مضمون في الأخبار (بدل DeepSeek V4 Flash المسحوب) — خطة زياد
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ Mistral Nemo — fallback (حي ✅)
    {"provider": "mistral", "model": "open-mistral-nemo"},
    # ⭐ NVIDIA Nemotron 3.5 Lightning — سريع في التلخيص (0.5s ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
    # ⭐ SambaNova fallback
    {"provider": "sambanova", "model": "DeepSeek-V3.1"},
]

PREMIUM_SUMMARY_MODELS = [
    # ⭐ NVIDIA Mistral Large 4 — بدل DeepSeek V4 Pro أساسي للتلخيص (مختبر ✅)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_DEEPSEEK_V4_PRO_KEY},
    # ⭐ NVIDIA Nemotron 3 Ultra 550B — بدل MiniMax M2.7 تلخيص متقدم (reasoning 🧠)
    {"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b", "api_key": NVIDIA_MINIMAX_M27_KEY},
    # ⭐ Mistral Small — عربي مضمون
    {"provider": "mistral", "model": "mistral-small-latest"},
    # ⭐ NVIDIA Nemotron 3.5 Lightning — سريع (0.5s ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LLAMA_33_70B_KEY},
]

# Default
SUMMARY_MODELS = PREMIUM_SUMMARY_MODELS

# 👁️ Vision - تحليل الصور
# ✅ محدثة 2026-11-02 — Nemotron 3.5 Super VL هو البديل الحي الأسرع (0.6s، مختبر ✅)
FREE_VISION_MODELS = [
    # ⭐ NVIDIA Nemotron 3.5 Super VL — أسرع نموذج رؤية حي (0.5s مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Llama 3.2 90B Vision — أساسية الخطة الأصلية (حية لكن بطيئة 43s — مختبر)
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_NEMOTRON_NANO_VL_KEY},
]

PREMIUM_VISION_MODELS = [
    # ⭐ NVIDIA Nemotron 3.5 Super VL — أسرع نموذج رؤية حي (0.5s مختبر ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY},
    # ⭐ NVIDIA Llama 3.2 90B Vision — أساسية الخطة الأصلية (حية لكن بطيئة 43s — مختبر)
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_NEMOTRON_NANO_VL_KEY},
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
