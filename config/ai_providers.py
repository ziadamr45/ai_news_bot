"""
إعدادات مزودين AI - AI Providers & Model Routes
═══════════════════════════════════════════════════
الخطه الجديدة 2026-11-02 (نماذج NVIDIA الجديدة — كل نموذج له مفتاح خاص):
- 7 نماذج شات + رؤية + توليد صور + تحليل ملفات + Embeddings + Reranking
- FREE = نماذج سريعة أساسية | PRO = أقوى نماذج
NVIDIA keys, Mistral, SambaNova, Groq, OpenAI, OpenRouter,
Model routes (Free/Premium), Timeout & Retry settings
"""

import os

# ═══════════════════════════════════════
# مزودين AI - AI Providers
# ═══════════════════════════════════════

# NVIDIA NIM — كل نموذج له مفتاح API خاص!
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# NVIDIA Visual GenAI + Retrieval endpoints (نماذج الصور وتحليل الملفات)
NVIDIA_GENAI_BASE_URL = "https://ai.api.nvidia.com/v1/genai"
NVIDIA_RETRIEVAL_BASE_URL = "https://ai.api.nvidia.com/v1/retrieval"

# ── 🔴 المفاتيح الجديدة (زياد بعتها 2026-11-02 — كل مفتاح لحساب NVIDIA منفصل) ──
NVIDIA_MINIMAX_M31_FLASH_KEY = os.environ.get("NVIDIA_MINIMAX_M31_FLASH_KEY", "")
NVIDIA_DEEPSEEK_V41_FLASH_KEY = os.environ.get("NVIDIA_DEEPSEEK_V41_FLASH_KEY", "")
NVIDIA_GLM_53_FLASH_KEY = os.environ.get("NVIDIA_GLM_53_FLASH_KEY", "")
NVIDIA_MISTRAL_LARGE_4_KEY = os.environ.get("NVIDIA_MISTRAL_LARGE_4_KEY", "")
NVIDIA_NEMOTRON_PARSE_KEY = os.environ.get("NVIDIA_NEMOTRON_PARSE_KEY", "")
NVIDIA_NEMOTRON_BOLT_KEY = os.environ.get("NVIDIA_NEMOTRON_BOLT_KEY", "")
NVIDIA_NEMOTRON_RERANK_KEY = os.environ.get("NVIDIA_NEMOTRON_RERANK_KEY", "")
NVIDIA_NEMOTRON_EMBED_KEY = os.environ.get("NVIDIA_NEMOTRON_EMBED_KEY", "")
NVIDIA_NEMOTRON_SUPER_VL_KEY = os.environ.get("NVIDIA_NEMOTRON_SUPER_VL_KEY", "")
NVIDIA_STEP_5_KEY = os.environ.get("NVIDIA_STEP_5_KEY", "")
NVIDIA_FLUX3_KLEIN_KEY = os.environ.get("NVIDIA_FLUX3_KLEIN_KEY", "")
NVIDIA_QWEN_IMAGE_2512_KEY = os.environ.get("NVIDIA_QWEN_IMAGE_2512_KEY", "")
NVIDIA_QWEN_IMAGE_EDIT_2511_KEY = os.environ.get("NVIDIA_QWEN_IMAGE_EDIT_2511_KEY", "")
NVIDIA_WHISPER_V3_KEY = os.environ.get("NVIDIA_WHISPER_V3_KEY", "")
NVIDIA_PARAKEET_ASR_KEY = os.environ.get("NVIDIA_PARAKEET_ASR_KEY", "")
NVIDIA_GEMMA_4_31B_KEY = os.environ.get("NVIDIA_GEMMA_4_31B_KEY", "")

# ── مفاتيح قديمة (لسه شغالة — بنستخدمها كـ fallback: llama-3.2-90b-vision لسه حي) ──
NVIDIA_LLAMA_32_90B_VISION_KEY = os.environ.get("NVIDIA_LLAMA_32_90B_VISION_KEY", "")
NVIDIA_DEEPSEEK_V4_PRO_KEY = os.environ.get("NVIDIA_DEEPSEEK_V4_PRO_KEY", "")
NVIDIA_DEEPSEEK_V4_FLASH_KEY = os.environ.get("NVIDIA_DEEPSEEK_V4_FLASH_KEY", "")
NVIDIA_KIMI_K26_KEY = os.environ.get("NVIDIA_KIMI_K26_KEY", "")
NVIDIA_GLM_51_KEY = os.environ.get("NVIDIA_GLM_51_KEY", "")
NVIDIA_MINIMAX_M27_KEY = os.environ.get("NVIDIA_MINIMAX_M27_KEY", "")
NVIDIA_LLAMA_33_70B_KEY = os.environ.get("NVIDIA_LLAMA_33_70B_KEY", "")
NVIDIA_STEP_37_FLASH_KEY = os.environ.get("NVIDIA_STEP_37_FLASH_KEY", "")
NVIDIA_NEMOTRON_NANO_VL_KEY = os.environ.get("NVIDIA_NEMOTRON_NANO_VL_KEY", "")
NVIDIA_QWEN_IMAGE_KEY = os.environ.get("NVIDIA_QWEN_IMAGE_KEY", "")
NVIDIA_QWEN_IMAGE_EDIT_KEY = os.environ.get("NVIDIA_QWEN_IMAGE_EDIT_KEY", "")
NVIDIA_SD35_LARGE_KEY = os.environ.get("NVIDIA_SD35_LARGE_KEY", "")
NVIDIA_FLUX_KONTEXT_KEY = os.environ.get("NVIDIA_FLUX_KONTEXT_KEY", "")

# NVIDIA API Keys — centralized dictionary
NVIDIA_KEYS = {
    # الجديدة (مختبرة لايف 2026-11-02)
    "minimax_m31_flash": NVIDIA_MINIMAX_M31_FLASH_KEY,
    "deepseek_v41_flash": NVIDIA_DEEPSEEK_V41_FLASH_KEY,
    "glm_53_flash": NVIDIA_GLM_53_FLASH_KEY,
    "mistral_large_4": NVIDIA_MISTRAL_LARGE_4_KEY,
    "nemotron_parse": NVIDIA_NEMOTRON_PARSE_KEY,
    "nemotron_bolt": NVIDIA_NEMOTRON_BOLT_KEY,
    "nemotron_rerank": NVIDIA_NEMOTRON_RERANK_KEY,
    "nemotron_embed": NVIDIA_NEMOTRON_EMBED_KEY,
    "nemotron_super_vl": NVIDIA_NEMOTRON_SUPER_VL_KEY,
    "step_5_preview": NVIDIA_STEP_5_KEY,
    "flux3_klein": NVIDIA_FLUX3_KLEIN_KEY,
    "qwen_image_2512": NVIDIA_QWEN_IMAGE_2512_KEY,
    "qwen_image_edit_2511": NVIDIA_QWEN_IMAGE_EDIT_2511_KEY,
    "whisper_v3": NVIDIA_WHISPER_V3_KEY,
    "parakeet_asr": NVIDIA_PARAKEET_ASR_KEY,
    "gemma_4_31b": NVIDIA_GEMMA_4_31B_KEY,
    # القديمة (fallback)
    "llama_32_90b_vision": NVIDIA_LLAMA_32_90B_VISION_KEY,
    "deepseek_v4_pro": NVIDIA_DEEPSEEK_V4_PRO_KEY,
    "deepseek_v4_flash": NVIDIA_DEEPSEEK_V4_FLASH_KEY,
    "kimi_k26": NVIDIA_KIMI_K26_KEY,
    "glm_51": NVIDIA_GLM_51_KEY,
    "minimax_m27": NVIDIA_MINIMAX_M27_KEY,
    "llama_33_70b": NVIDIA_LLAMA_33_70B_KEY,
    "step_37_flash": NVIDIA_STEP_37_FLASH_KEY,
    "nemotron_nano_vl": NVIDIA_NEMOTRON_NANO_VL_KEY,
    "qwen_image": NVIDIA_QWEN_IMAGE_KEY,
    "qwen_image_edit": NVIDIA_QWEN_IMAGE_EDIT_KEY,
    "sd35_large": NVIDIA_SD35_LARGE_KEY,
    "flux_kontext": NVIDIA_FLUX_KONTEXT_KEY,
}


def get_nvidia_key(model_name: str) -> str:
    """Get NVIDIA API key by model name — single point of access"""
    return NVIDIA_KEYS.get(model_name, "")


# Mistral AI (fallback — مفتاح واحد لكل النماذج)
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

# SambaNova (fallback أخير للمجاني)
SAMBANOVA_API_KEY = os.environ.get("SAMBANOVA_API_KEY", "")
SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"

# Groq (ASR - تحويل الصوت لنص عبر Whisper)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# OpenAI (ASR fallback)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# OpenRouter (ASR fallback layer 3)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# ═══════════════════════════════════════════════════════════
# الخطه الاحترافية v2 — Model Routes (2026-11-03 — بعد بحث كامل في قدرات كل نموذج)
#
# 🔴 قواعد زياد:
#   1) FREE = نماذج ضعيفة/أساسية بس | PRO = أقوى نماذج
#   2) المهام السريعة (شات/تحيات) = نماذج سريعة | المهام الثقيلة (بحث عميق/تلخيص/كود) = نماذج ضخمة
#   3) كل ميزة تستخدم عائلتها: صور→vision, توليد صور→image, صوت→STT, ملفات→parse
#
# 🔴 جدول القدرات (من البحث):
#   Bolt E4B:         8B/4B فعّالة — ضعيف وسريع جدًا (0.4s لايف) → المجاني
#   Gemma 4 31B:      30.7B dense, 256K ctx, متعدد الوسائط (نص+صورة+فيديو) → متوسط (فري/فولباك برو)
#   GLM 5.3 Flash:    320B-A18B, 1M ctx, قوي جدًا وسريع → البرو (شات تفاعلي)
#   DeepSeek V4.1:    763B MoE, 1M ctx, elite coding/agents, 190 tok/s → البرو
#   MiniMax M3.1:     428B-A23B, 1M ctx, thinking دايمًا شغال (بطيء البداية) → برو fallback
#   Mistral Large 4:  1T-A52B, 1M ctx, flagship — بطيء نسبيًا → مهام برو الثقيلة فقط (timeout أطول)
#   Step 5 Preview:   reasoning ضخم — أبطأ واحد → آخر حل للتحليل العميق فقط
#   Super VL 120B:    120B-A12B رؤية (صور+فيديو) → تحليل الصور برو
# 🔴 SambaNova (401) و Mistral-large API (403) اتشالوا — كانوا بيضيّعوا وقت في كل فشل
# ═══════════════════════════════════════════════════════════

# 🧠 Chat - المحادثة الذكية
# FREE:  Bolt → Gemma 31B → Mistral Small (ضعيفين كلهم — زياد أمر)
# PRO:   GLM Flash + DeepSeek V4.1 (توازي، سريعين وقويين) → MiniMax → Mistral Large 4 (مهلة أطول) → Gemma
FREE_CHAT_MODELS = [
    # ⚡ NVIDIA Nemotron 3.5 Bolt E4B (8B/4B) — ضعيف وسريع جدًا — أساسي المجاني
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
    # 📊 Gemma 4 31B — متوسط، fallback للمجاني
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 45},
    # 🛡️ Mistral Small — آخر حل (مجاني)
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_CHAT_MODELS = [
    # ⚡ NVIDIA GLM 5.3 Flash (320B-A18B) — قوي وسريع — أولوية برو للشات التفاعلي
    {"provider": "nvidia", "model": "z-ai/glm-5.3-flash", "api_key": NVIDIA_GLM_53_FLASH_KEY},
    # ⚡ NVIDIA DeepSeek V4.1 Flash (763B) — قوي وسريع — توازي مع GLM
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 🔥 MiniMax M3.1 Flash (428B) — قوي لكن thinking دايمًا شغال → تالت
    {"provider": "nvidia", "model": "minimaxai/minimax-m3.1-flash", "api_key": NVIDIA_MINIMAX_M31_FLASH_KEY, "timeout": 45},
    # 🛡️ Mistral Small API — دايمًا حي (ينقذ وقت ازدحام NVIDIA الذروة)
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 🔥 NVIDIA Mistral Large 4 (1T-A52B) — أقوى عام لكن بطيء → مهلة 60s
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_MISTRAL_LARGE_4_KEY, "timeout": 60},
    # 📊 Gemma 4 31B — fallback
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 40},
]

# Default (backward compatibility)
CHAT_MODELS = PREMIUM_CHAT_MODELS

# ⚡ Simple - الرسائل البسيطة (تحيات، أسئلة قصيرة، أسئلة هوية) — السرعة أهم حاجة
# FREE: Bolt → Gemma
# PRO:  Bolt (0.4s لايف!) → GLM Flash → DeepSeek Flash
FREE_SIMPLE_MODELS = [
    # ⚡ Bolt — أسرع نموذج (لايف: رد في 0.4 ثانية)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
    # 📊 Gemma 4 31B — fallback
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 30},
    # 🛡️ Mistral Small — آخر حل
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_SIMPLE_MODELS = [
    # ⚡ Bolt — أسرع رد للتحيات/البسيط (حتى للبرو — السرعة هي الميزة هنا)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
    # ⚡ GLM 5.3 Flash — قوي وسريع
    {"provider": "nvidia", "model": "z-ai/glm-5.3-flash", "api_key": NVIDIA_GLM_53_FLASH_KEY},
    # ⚡ DeepSeek V4.1 Flash
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 📊 Gemma 4 31B — fallback
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 30},
]

# Default
SIMPLE_MODELS = PREMIUM_SIMPLE_MODELS

# 🔥 Deep Search - البحث العميق (مهمة ثقيلة → نماذج قوية)
# FREE:  Gemma 31B (متوسط) → Bolt → Mistral Small
# PRO:   DeepSeek V4.1 + Mistral Large 4 (توازي) → Step 5 (تحليل أعمق، مهلة 90s) → GLM Flash
FREE_DEEP_SEARCH_MODELS = [
    # 📊 Gemma 4 31B — أفضل متاح للمجاني في التحليل
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 60},
    # ⚡ Bolt — fallback سريع
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
    # 🛡️ Mistral Small — آخر حل
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_DEEP_SEARCH_MODELS = [
    # ⚡ DeepSeek V4.1 Flash — قوي وسريع (الملخص لازم يخلص في الميزانية)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 🛡️ Mistral Small API — دايمًا حي (ينقذ وقت ازدحام NVIDIA)
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 🔥 Mistral Large 4 — تركيب أقوى (مهلة 60s)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_MISTRAL_LARGE_4_KEY, "timeout": 60},
    # 🔥 Step 5 Preview — أعمق تحليل (مهلة 75s — للمهام الثقيلة)
    {"provider": "nvidia", "model": "stepfun-ai/step-5-preview", "api_key": NVIDIA_STEP_5_KEY, "timeout": 75},
    # ⚡ GLM 5.3 Flash — fallback سريع
    {"provider": "nvidia", "model": "z-ai/glm-5.3-flash", "api_key": NVIDIA_GLM_53_FLASH_KEY},
]

# Default
DEEP_SEARCH_MODELS = PREMIUM_DEEP_SEARCH_MODELS

# 👨‍💻 Coding - البرمجة (مهمة ثقيلة)
# FREE:  Gemma 31B → Bolt → Mistral Small
# PRO:   DeepSeek V4.1 (elite coding) + Mistral Large 4 (توازي) → Step 5 (معقد) → GLM Flash
FREE_CODING_MODELS = [
    # 📊 Gemma 4 31B — كود متوسط للمجاني
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 60},
    # ⚡ Bolt — fallback
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
    # 🛡️ Mistral Small — آخر حل
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_CODING_MODELS = [
    # 💻 DeepSeek V4.1 Flash — elite في الكود والـ agents (763B, 190 tok/s)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 🛡️ Mistral Small API — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 💻 Mistral Large 4 — cybersecurity/coding flagship (مهلة 60s)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_MISTRAL_LARGE_4_KEY, "timeout": 60},
    # 💻 Step 5 Preview — مسائل البرمجة المعقدة (مهلة 75s)
    {"provider": "nvidia", "model": "stepfun-ai/step-5-preview", "api_key": NVIDIA_STEP_5_KEY, "timeout": 75},
    # 💻 GLM 5.3 Flash — #5 Code Arena fallback
    {"provider": "nvidia", "model": "z-ai/glm-5.3-flash", "api_key": NVIDIA_GLM_53_FLASH_KEY},
]

# Default
CODING_MODELS = PREMIUM_CODING_MODELS

# 📄 Summary - التلخيص
# FREE:  Bolt → Gemma → Mistral Small
# PRO:   DeepSeek V4.1 + Mistral Large 4 (توازي) → GLM Flash → MiniMax
FREE_SUMMARY_MODELS = [
    # 📄 Bolt — تلخيص سريع للمجاني
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
    # 📄 Gemma 4 31B — fallback
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 45},
    # 🛡️ Mistral Small — آخر حل
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_SUMMARY_MODELS = [
    # 📄 DeepSeek V4.1 Flash — سريع وقوي
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 🛡️ Mistral Small API — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 📄 Mistral Large 4 — تلخيص احترافي (مهلة 60s)
    {"provider": "nvidia", "model": "mistralai/mistral-large-4-1t-a52b", "api_key": NVIDIA_MISTRAL_LARGE_4_KEY, "timeout": 60},
    # 📄 GLM 5.3 Flash — fallback سريع
    {"provider": "nvidia", "model": "z-ai/glm-5.3-flash", "api_key": NVIDIA_GLM_53_FLASH_KEY},
    # 📄 MiniMax M3.1 Flash — آخر NVIDIA حل
    {"provider": "nvidia", "model": "minimaxai/minimax-m3.1-flash", "api_key": NVIDIA_MINIMAX_M31_FLASH_KEY, "timeout": 45},
]

# Default
SUMMARY_MODELS = PREMIUM_SUMMARY_MODELS

# 👁️ Vision - تحليل الصور (عائلة الرؤية بس — زياد أمر)
# FREE:  Gemma 4 31B (vision متوسط) → Llama 3.2 90B (قديم) → Pixtral
# PRO:   Super VL 120B (أقوى رؤية) → Gemma 31B → Llama 90B → Pixtral
FREE_VISION_MODELS = [
    # 📊 Gemma 4 31B IT — vision متعدد الوسائط (نص+صورة+فيديو) — مناسب للمجاني
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 60},
    # 🛡️ NVIDIA Llama 3.2 90B Vision — fallback (لسه شغال بمفتاحه القديم)
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY, "timeout": 60},
    # 🛡️ Mistral Pixtral — fallback أخير
    {"provider": "mistral", "model": "pixtral-large-latest"},
]

PREMIUM_VISION_MODELS = [
    # 🔥 NVIDIA Nemotron 3.5 Super VL 120B — أقوى نموذج رؤية (مختبر 200 OK ✅)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_NEMOTRON_SUPER_VL_KEY, "timeout": 60},
    # 📊 Gemma 4 31B IT — vision fallback
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 60},
    # 🛡️ NVIDIA Llama 3.2 90B Vision — fallback
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_LLAMA_32_90B_VISION_KEY, "timeout": 60},
    # 🛡️ Mistral Pixtral — fallback أخير
    {"provider": "mistral", "model": "pixtral-large-latest"},
]

# Default
VISION_MODELS = PREMIUM_VISION_MODELS

# 🎨 Image Generation - إنشاء الصور
# 🔴 مختبر لايف 2026-11-02: flux-3-image-klein شغال عبر GenAI API بـ mode=t2i ✅
# (Qwen-Image-2512 مش متاح hosted على NVIDIA — Downloadable بس)
PREMIUM_IMAGE_GEN_MODELS = [
    # 🎨 NVIDIA Flux 3 Image Klein — أحدث نموذج توليد صور (توليد + تحرير)
    {"provider": "nvidia_genai", "model": "black-forest-labs/flux-3-image-klein", "api_key": NVIDIA_FLUX3_KLEIN_KEY},
    # 🎨 NVIDIA Qwen-Image-2512 — لو NVIDIA فعّلته hosted هيشتغل تلقائياً
    {"provider": "nvidia_genai", "model": "Qwen/Qwen-Image-2512", "api_key": NVIDIA_QWEN_IMAGE_2512_KEY},
]

# 🖌️ Image Edit - تعديل الصور
# 🔴 Qwen-Image-Edit-2511 مفتاحه ساري بس NVIDIA مش مستضيفه لسه (404) — أول ما يتفعل هيشتغل
PREMIUM_IMAGE_EDIT_MODELS = [
    # 🖌️ NVIDIA Qwen-Image-Edit-2511 — تعديل الصور
    {"provider": "nvidia_genai", "model": "Qwen/Qwen-Image-Edit-2511", "api_key": NVIDIA_QWEN_IMAGE_EDIT_2511_KEY},
    # 🖌️ Flux 3 Klein (i2i) — fallback لو NVIDIA فتح i2i للـ base64
    {"provider": "nvidia_genai", "model": "black-forest-labs/flux-3-image-klein", "api_key": NVIDIA_FLUX3_KLEIN_KEY},
]

# 📄 File Analysis - تحليل الملفات والمستندات (جديد!)
# Nemotron 3.5 Parse: بيستخرج النص والجداول من صور صفحات المستندات
# مختبر لايف ✅ — multipart/form-data field "document"
# Endpoint: https://ai.api.nvidia.com/v1/retrieval/nvidia/nemotron-3.5-parse/parse
FILE_PARSE_MODELS = [
    {"provider": "nvidia_parse", "model": "nvidia/nemotron-3.5-parse/parse", "api_key": NVIDIA_NEMOTRON_PARSE_KEY},
]

# 🔍 Search Quality - جودة البحث (جديد!)
# Embeddings + Reranking لترتيب نتائج البحث الأذكى (الأكثر صلة أولاً)
# مختبر لايف ✅:
#   embed:  POST https://integrate.api.nvidia.com/v1/embeddings (dim=4096)
#   rerank: POST https://ai.api.nvidia.com/v1/retrieval/nvidia/nemotron-3.5-rerank-8b/reranking
#           payload: {"model": "nvidia/nemotron-3.5-rerank-8b", "query": {"text": "..."}, "passages": [{"text": ...}]}
EMBED_TEXT_MODELS = [
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-embed-8b", "api_key": NVIDIA_NEMOTRON_EMBED_KEY},
]
RERANK_MODELS = [
    {"provider": "nvidia_rerank", "model": "nvidia/nemotron-3.5-rerank-8b", "api_key": NVIDIA_NEMOTRON_RERANK_KEY},
]

# 🎙️ Audio STT - تحويل الصوت لنص (مفاتيح NVIDIA — gRPC Riva فقط)
# 🔴 ملاحظة مهمة: whisper-large-v3 + parakeet على NVIDIA hosted بيتنادى عبر gRPC
#   (grpc.nvcf.nvidia.com) — مش REST. المفاتيح محفوظة هنا والدمج في ASR chain
#   هيعتمد على Groq أولاً لحد ما ندعم gRPC.
NVIDIA_WHISPER_MODEL = "whisper-large-v3"
NVIDIA_PARAKEET_MODEL = "nvidia/parakeet-1.1b-rnnt-multilingual-asr"

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
