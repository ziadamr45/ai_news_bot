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

# ── 🌟 Google Gemini (أساسي جديد — أمر زياد 2026-11-04: نماذج جوجل أول حاجة في الفري والبرو) ──
# OpenAI-compatible endpoint — مختبر لايف من serv00 2026-11-04:
#   gemini-3.5-flash-lite: 0.8s ✅ (أسرع نموذج في البوت كله) | gemini-3.6-flash: 1.9s ✅
#   gemini-3.8-flash: 503 ازدحام متكرر في الاختبار → اتشال من الأساسي (قاعدة زياد: ممنوع ما يعطل)
# ملاحظة: نفس المفتاح بيشغل STT (gemini-3.5-transcribe مجاني) وتعديل الصور (nano-banana — مدفوع)
GOOGLE_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# 🖌️ مفتاح الصور من جوجل (Nano Banana 2.1 / Pro — توليد + تعديل) — لما زياد يبعته
# يتحط هنا في .env والدمج بيبقى من غير ما نلمس مفاتيح الشات (قاعدة: كل وظيفة ليها مفتاح)
GOOGLE_IMAGE_KEY = os.environ.get("GOOGLE_IMAGE_KEY", "")

# 🎙️ مفتاح STT (gemini-3.5-transcribe) — أمر زياد 2026-11-04:
# مفتاح منفصل لكل الخدمات غير الشاتية (transcribe + embedding + grounding)
# والشات بيفضل على GEMINI_API_KEY لوحده (قاعدة: كل وظيفة ليها مفتاح)
GOOGLE_TRANSCRIBE_KEY = os.environ.get("GOOGLE_TRANSCRIBE_KEY", "")

# 🔴 NVIDIA self-heal — بروكسي اختياري (أمر زياد 2026-11-04: "شوف حل لنماذج نيفيديا"):
# لو NVIDIA اتحجب شبكياً من serv00 تاني (زي حادثة 3 نوفمبر)، بيتحط رابط worker proxy
# عام هنا والبوت بيتحول عليه تلقائياً لمدة 10 دقايق عند أول فشل اتصال. فاضي = مباشر دايماً.
NVIDIA_PROXY_URL = os.environ.get("NVIDIA_PROXY_URL", "")

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
# الخطه v3 — Model Routes (2026-11-03 — بعد بحث كامل + اختبار لايف لكل نموذج)
#
# 🔴 قواعد زياد (أمر مباشر):
#   1) أساسي البرو = DeepSeek V4.1 — أقوى وأسرع واحد، وبياخد أي رسالة عادية
#   2) GLM 5.3 = المهام التقيلة والبرمجة (الريزونينج شغال عنده دايمًا — مختبر)
#   3) المجاني = سريع ومتوسط (نفس خطته المعتمدة)
#   4) أي حاجة بتعطّل الموديل = تتشال (بلاش ما يعطل)
#   5) الريزونينج يتفعل للمهام الثقيلة والبرمجة (لو الموديل فيه كده)
#
# 🔴 جدول القدرات — مختبر لايف 2026-11-03 (model_research_nov3.json):
#   DeepSeek V4.1:    763B MoE — رد عادي 1.8-3.1s ✅ (thinking بياكل الميزانية — مقفول للسرعة)
#   GLM 5.3 Flash:    320B-A18B — الريزونينج دايمًا شغال (حتى مع thinking:false — مختبر)
#                     reasoning_content 1100+ حرف، رد كامل في 8-11s → موديل المهام الثقيلة والبرمجة
#   Omni 30B:         nemotron-3-nano-omni-30b-a3b — عربي ممتاز في 0.9s ✅ + بياخد صوت عبر REST ✅
#   Lightning 30B:    nemotron-3.5-lightning-30b-a3b — متوسط + تفكير، 3.7s ✅
#   Bolt E4B:         أسرع في الهدوء (0.4s) لكن بيترصّ صف في الذروة (40s+ مختبر) → منقذ آخر
#   Gemma 4 31B:      🏆 أفضل OCR عربي في الرؤية — قرأ النص العربي في الصورة 100% صح (53s)
#                     بس شات النص بيقفل صف (timeout 3 مرات) → fallback بمهلة قصيرة بس
#   Super VL 120B:    بيرجع محتوى فاضي مع النص العربي في الصور (مختبر) — إنجليزي بس
#   MiniMax M3.1:     thinking دايمًا + بداية بطيئة (cold start) → fallback متأخر
#   Mistral Small:    API دايمًا حي — منقذ ازدحام NVIDIA في كل السلاسل
#   Llama 3.2 90B:    مفتاحه القديم بقى 403 → اتشال من الراوتس نهائيًا
#   Step 5 Preview:   110s timeout حتى لسؤال بسيط (مختبر) → اتشال (قاعدة زياد: مفيش ما يعطل)
#   Mistral Large 4:  1T بطيء في الذروة → اتشال من الراوتس (المفتاح محفوظ)
#
# 🔴 اكتشاف مهم: مفاتيح NVIDIA عالمية — أي مفتاح بينادي أي نموذج hosted (مختبر 4 حسابات)
# 🔴 SambaNova(401) + OpenRouter(401) + Groq(403) اتشالوا من .env — كلهم ميوت
# ═══════════════════════════════════════════════════════════

# مفتاح Bolt بينادي أي نموذج NVIDIA (المفاتيح عالمية — مختبر) — بنستخدمه للنماذج الجديدة
NVIDIA_LIGHTNING_KEY = os.environ.get("NVIDIA_LIGHTNING_KEY", "") or NVIDIA_NEMOTRON_BOLT_KEY
NVIDIA_OMNI_30B_KEY = os.environ.get("NVIDIA_OMNI_30B_KEY", "") or NVIDIA_NEMOTRON_BOLT_KEY

# 🧠 Chat - المحادثة الذكية
# 🔴 إصلاح أكل الكلمات (2026-11-03): Bolt E4B اتشال من الأساسيات — بيترصّ صف في الذروة
#   (40s+ مختبر) وبيفصل كلمات عربي، وده اللي كان بيخلي رد "My Bro —ك الذكي!"
# FREE:  Omni → Lightning → Mistral Small → Bolt (منقذ أخير)
# PRO:   🔴 DeepSeek أساسي (أمر زياد) → Omni → Lightning → Mistral Small
FREE_CHAT_MODELS = [
    # 🌟 Google 3.5 Flash-Lite — أساسي المجاني (أمر زياد 2026-11-04: جوجل أول حاجة) — 0.8s مختبر
    {"provider": "google", "model": "gemini-3.5-flash-lite", "timeout": 30},
    # ⚡ Omni 30B — عربي ممتاز 0.9s (أساسي المجاني القديم — مختبر)
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 30},
    # 📊 Lightning 30B — متوسط 3.7s
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 40},
    # 🛡️ Mistral Small — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 🚑 Bolt E4B — منقذ أخير بس (ضعيف بالعربي — ممنوع يبقى أساسي)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
]

PREMIUM_CHAT_MODELS = [
    # 🌟 Google 3.6 Flash — أساسي البرو الجديد (أمر زياد 2026-11-04: جوجل أول حاجة) — 1.9s مختبر
    # (3.8-flash أقوى بس 503 ازدحام متكرر في الاختبار — مننقله لما يستقر)
    {"provider": "google", "model": "gemini-3.6-flash", "timeout": 30},
    # 🔴🔴 DeepSeek V4.1 Flash — أساسي البرو القديم (أمر زياد: أقوى وأسرع — 1.8-3.1s مختبر)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # ⚡ Omni 30B — منقذ سريع 0.9s لو DeepSeek في طابور
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 30},
    # 📊 Lightning 30B — متوسط 3.7s
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 40},
    # 🛡️ Mistral Small API — دايمًا حي (ينقذ وقت ازدحام NVIDIA الذروة)
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 🔴 Bolt اتشال من البرو نهائيًا (2026-11-03) — كان بياكل كلمات وبيبطّئ الردود الطويلة
]

# Default (backward compatibility)
CHAT_MODELS = PREMIUM_CHAT_MODELS

# ⚡ Simple - الرسائل البسيطة (تحيات، أسئلة قصيرة، أسئلة هوية) — السرعة أهم حاجة
# 🔴 Bolt اتشال من هنا كمان — التحية الناقصة "My Bro —ك الذكي!" كانت منه
# FREE: Omni → Mistral Small → Bolt (أخير)
# PRO:  DeepSeek (أساسي) → Omni → Mistral Small
FREE_SIMPLE_MODELS = [
    # 🌟 Google 3.5 Flash-Lite — أساسي (أمر زياد 2026-11-04) — أسرع تحية 0.8s
    {"provider": "google", "model": "gemini-3.5-flash-lite", "timeout": 25},
    # ⚡ Omni 30B — 0.9s عربي ممتاز
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 25},
    # 🛡️ Mistral Small — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 🚑 Bolt — منقذ أخير بس
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
]

PREMIUM_SIMPLE_MODELS = [
    # 🌟 Google 3.6 Flash — أساسي البرو (أمر زياد 2026-11-04: جوجل أول حاجة)
    {"provider": "google", "model": "gemini-3.6-flash", "timeout": 25},
    # 🔴 DeepSeek — أساسي البرو القديم (أمر زياد)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # ⚡ Omni 30B — منقذ سريع
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 25},
    # 🛡️ Mistral Small — آخر حل
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default
SIMPLE_MODELS = PREMIUM_SIMPLE_MODELS

# 🔥 Deep Search - البحث العميق (مهمة ثقيلة → نماذج قوية)
# FREE:  Lightning → Omni → Gemma (مهلة قصيرة) → Mistral Small
# PRO:   DeepSeek → GLM (ريزونينج للتحليل العميق — أمر زياد) → Lightning → Mistral Small
FREE_DEEP_SEARCH_MODELS = [
    # 🌟 Google 3.5 Flash-Lite — أساسي (أمر زياد 2026-11-04)
    {"provider": "google", "model": "gemini-3.5-flash-lite", "timeout": 45},
    # 📊 Lightning 30B — متوسط + تفكير 3.7s
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 45},
    # ⚡ Omni 30B — سريع وممتاز عربي
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 35},
    # 📊 Gemma 4 31B — أقوى متاح بس بيترص صف → مهلة قصيرة
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 45},
    # 🛡️ Mistral Small — آخر حل
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_DEEP_SEARCH_MODELS = [
    # 🌟 Google 3.6 Flash — أساسي البرو (أمر زياد 2026-11-04: جوجل أول حاجة)
    {"provider": "google", "model": "gemini-3.6-flash", "timeout": 45},
    # ⚡ DeepSeek V4.1 — قوي وسريع (أساسي قديم)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 🧠 GLM 5.3 Flash — الريزونينج شغال دايمًا (أمر زياد: المهام الثقيلة بـ GLM) — 8-11s
    {"provider": "nvidia", "model": "z-ai/glm-5.3-flash", "api_key": NVIDIA_GLM_53_FLASH_KEY, "timeout": 60},
    # 📊 Lightning 30B — متوسط
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 45},
    # 🛡️ Mistral Small API — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default
DEEP_SEARCH_MODELS = PREMIUM_DEEP_SEARCH_MODELS

# 👨‍💻 Coding - البرمجة (مهمة ثقيلة + ريزونينج — أمر زياد)
# FREE:  Lightning → Omni → Gemma → Mistral Small
# PRO:   🧠 GLM (ريزونينج + برمجة — أمر زياد) → DeepSeek → Lightning → Mistral Small
FREE_CODING_MODELS = [
    # 🌟 Google 3.5 Flash-Lite — أساسي (أمر زياد 2026-11-04)
    {"provider": "google", "model": "gemini-3.5-flash-lite", "timeout": 60},
    # 📊 Lightning 30B — كود متوسط مع تفكير
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 45},
    # ⚡ Omni 30B
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 35},
    # 📊 Gemma 4 31B — مهلة قصيرة
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 45},
    # 🛡️ Mistral Small — آخر حل
    {"provider": "mistral", "model": "mistral-small-latest"},
]

PREMIUM_CODING_MODELS = [
    # 🌟 Google 3.6 Flash — أساسي البرو (أمر زياد 2026-11-04: جوجل أول حاجة)
    {"provider": "google", "model": "gemini-3.6-flash", "timeout": 60},
    # 🧠🔴 GLM 5.3 Flash — أمر زياد: GLM للمهام التقيلة والبرمجة (ريزونينج دايمًا شغال — مختبر)
    {"provider": "nvidia", "model": "z-ai/glm-5.3-flash", "api_key": NVIDIA_GLM_53_FLASH_KEY, "timeout": 75},
    # 💻 DeepSeek V4.1 — elite coding (763B, 190 tok/s)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 📊 Lightning 30B — متوسط
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 45},
    # 🛡️ Mistral Small API — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default
CODING_MODELS = PREMIUM_CODING_MODELS

# 📄 Summary - التلخيص
# FREE:  Omni → Lightning → Mistral Small → Bolt (أخير)
# PRO:   DeepSeek → Lightning → Omni → Mistral Small
FREE_SUMMARY_MODELS = [
    # 🌟 Google 3.5 Flash-Lite — أساسي (أمر زياد 2026-11-04)
    {"provider": "google", "model": "gemini-3.5-flash-lite", "timeout": 35},
    # ⚡ Omni 30B — عربي ممتاز
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 35},
    # 📊 Lightning 30B
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 45},
    # 🛡️ Mistral Small — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
    # 🚑 Bolt — منقذ أخير بس (كان بيقطّع التلخيص الطويل)
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-bolt-e4b", "api_key": NVIDIA_NEMOTRON_BOLT_KEY},
]

PREMIUM_SUMMARY_MODELS = [
    # 🌟 Google 3.6 Flash — أساسي البرو (أمر زياد 2026-11-04: جوجل أول حاجة)
    {"provider": "google", "model": "gemini-3.6-flash", "timeout": 35},
    # 📄 DeepSeek V4.1 — سريع وقوي (أساسي قديم)
    {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash", "api_key": NVIDIA_DEEPSEEK_V41_FLASH_KEY},
    # 📊 Lightning 30B
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "api_key": NVIDIA_LIGHTNING_KEY, "timeout": 45},
    # ⚡ Omni 30B
    {"provider": "nvidia", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "api_key": NVIDIA_OMNI_30B_KEY, "timeout": 35},
    # 🛡️ Mistral Small API — دايمًا حي
    {"provider": "mistral", "model": "mistral-small-latest"},
]

# Default
SUMMARY_MODELS = PREMIUM_SUMMARY_MODELS

# 👁️ Vision - تحليل الصور (عائلة الرؤية بس — زياد أمر)
# 🔴 إصلاح 2026-11-03 (شكوى زياد: الرؤية وحشة بالعربي + نجوم في الرد):
#   - الباك كان فيه BUG: مهلة الرؤية كانت 20s ثابتة (REQUEST_TIMEOUT) ومكانتش بتقرا
#     مهلة النموذج (90s) — فـ Gemma كانت بتتقطع قبل ما تخلّص والسلسلة تقع على SuperVL
#     اللي بيرجع فاضي بالعربي. دلوقتي مهلة كل نموذج بتتبّنّ حقيقي.
#   - System prompt صار بيوصل فعلاً للموديل (كان مش بيتبعت خالص → نجوم Markdown)
# 🔴🔴 مختبر لايف 2026-11-03 صباح (صورة عربية حقيقية: "القاهرة يوم صافي / القط الصغير
#      بيجري في الشارع / My Bro 2026" + دوائر ملونة) — 3 جولات:
#   - Llama 3.2 90B Vision: 🏆 قرأ العربي 5/5 كامل + الألوان + الأشكال (105s)
#     → بقى الأول (مفتاح Bolt العام بيناديه — المفتاح القديم 403)
#   - Gemma 4 31B: timeout مرتين النهارده (ازدحام) — مختبر أمس كان 100% → تاني
#   - Pixtral Large: 💀 "Invalid model: pixtral-large-latest" — الاسم ميت على Mistral
#     (كان بينقص السلسلة لـ SuperVL الفاضي → ده كان سبب التحليل الوحش في الإنتاج)
#     → اتستبدل بـ mistral-medium-latest (من كتالوج Mistral الحالي 55 موديل)
#   - Llama 3.2 11B: 404 مش مستضاف فعلياً — اتشال
#   - Llama بيخرج نجوم Markdown → clean_ai_response بتحولها (إصلاح العريض متعدد الأسطر)
FREE_VISION_MODELS = [
    # 🏆 Llama 3.2 90B Vision — أقوى عربي في المختبر (5/5 OCR + وصف كامل بالعربي)
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_NEMOTRON_BOLT_KEY, "timeout": 120},
    # 🥈 Gemma 4 31B IT — قوي بالعربي (مختبر أمس 100%) بس بيتزاحم وقت الذروة
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 75},
    # 🛡️ Mistral Medium — بديل Pixtral الميت + API مستقر
    {"provider": "mistral", "model": "mistral-medium-latest", "timeout": 60},
    # ⚡ Super VL 120B — سريع للإنجليزي بس (بيرجع فاضي مع العربي — مختبر) — أخير
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_NEMOTRON_SUPER_VL_KEY, "timeout": 45},
]

PREMIUM_VISION_MODELS = [
    # 🏆 Llama 3.2 90B Vision — أقوى عربي (أمر زياد: الرؤية لازم تقرا العربي صح)
    {"provider": "nvidia", "model": "meta/llama-3.2-90b-vision-instruct", "api_key": NVIDIA_NEMOTRON_BOLT_KEY, "timeout": 120},
    # 🥈 Gemma 4 31B IT — احتياطي قوي
    {"provider": "nvidia", "model": "google/gemma-4-31b-it", "api_key": NVIDIA_GEMMA_4_31B_KEY, "timeout": 75},
    # 🛡️ Mistral Medium — بديل Pixtral الميت
    {"provider": "mistral", "model": "mistral-medium-latest", "timeout": 60},
    # ⚡ Super VL 120B — أخير
    {"provider": "nvidia", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "api_key": NVIDIA_NEMOTRON_SUPER_VL_KEY, "timeout": 45},
]

# Default
VISION_MODELS = PREMIUM_VISION_MODELS

# 🎨 Image Generation - إنشاء الصور
# 🔴 مختبر لايف 2026-11-02: flux-3-image-klein شغال عبر GenAI API بـ mode=t2i ✅
# (Qwen-Image-2512 مش متاح hosted على NVIDIA — 404 مختبر 2026-11-03 — اتشال)
PREMIUM_IMAGE_GEN_MODELS = [
    # 🎨 NVIDIA Flux 3 Image Klein — أحدث نموذج توليد صور
    {"provider": "nvidia_genai", "model": "black-forest-labs/flux-3-image-klein", "api_key": NVIDIA_FLUX3_KLEIN_KEY},
]

# 🖌️ Image Edit - تعديل الصور
# 🔴 الحقيقة (مختبر 2026-11-03): Qwen-Image-Edit-2511 لسه 404 (مش مستضاف) و
#    flux i2i بيرفض base64 و URL (بيقبل example_id بس) — NVIDIA مقفلتش التعديل لسه.
#    الإعدادات جاهزة — أول ما NVIDIA تستضيفه هيشتغل من غير تعديل كود.
PREMIUM_IMAGE_EDIT_MODELS = [
    # 🖌️ NVIDIA Qwen-Image-Edit-2511 — تعديل الصور (مفتاح زيد محفوظ وساري)
    {"provider": "nvidia_genai", "model": "Qwen/Qwen-Image-Edit-2511", "api_key": NVIDIA_QWEN_IMAGE_EDIT_2511_KEY},
    # 🖌️ Flux 3 Klein (i2i) — fallback لو NVIDIA فتح i2i
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
