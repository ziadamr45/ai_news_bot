"""
🛡️ Content Safety Layer — حماية المحتوى
نظام صارم لحماية المستخدمين من المحتوى غير المناسب

7 طبقات حماية:
1. تصفية الاستعلام (Query Filter) — حظر البحث عن محتوى غير آمن
2. تحليل نتائج البحث (Search Result Analysis) — استبعاد النتائج غير الآمنة
3. فحص الوسائط (Media Inspection) — تحليل الصور/الفيديو/الصوت الفعلي
4. الموافقة النهائية (Final Approval) — فحص درجة الأمان
5. الوضع الآمن (Safe Search) — تفعيل البحث الآمن افتراضياً
6. التسجيل (Logging) — تسجيل الطلبات المحظورة
7. تجربة المستخدم (User Experience) — رسائل واضحة بالعربية والإنجليزية

🔴 ينطبق على:
- /video /audio /photo (بحث + تحميل)
- تحميل الروابط من أي منصة
- التليجرام + الواتساب
"""

import os
import re
import json
import time
import base64
import logging
import asyncio
import tempfile
import subprocess
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("content_safety")

# ═══════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════

# درجة أمان الحد الأدنى (0-100) — لو أقل من كده نرفض
SAFETY_THRESHOLD = int(os.environ.get("CONTENT_SAFETY_THRESHOLD", "70"))

# تفعيل/تعطيل النظام (عشان نقدر نطفيه لو فيه مشاكل)
CONTENT_SAFETY_ENABLED = os.environ.get("CONTENT_SAFETY_ENABLED", "true").lower() == "true"

# عدد فريمات اللي بنسحبها من الفيديو للفحص
VIDEO_FRAME_COUNT = 3

# أقصى حجم للصورة اللي نبعتها للـ VLM (bytes) — 5MB
MAX_IMAGE_SIZE_FOR_VLM = 5 * 1024 * 1024

# ═══════════════════════════════════════
# Layer 1: كلمات مفتاحية محظورة — حظر فوري
# ═══════════════════════════════════════

# 🔴 كلمات ممنوعة بالعربي
BLOCKED_KEYWORDS_AR = [
    # جنس صريح
    "سكس", "sex", "جنس", "نيك", "نياكة", "سكسي", "سكسى",
    "بورنو", "porno", "porn", "بورن", "إباحي", "اباحي", "إباحية", "اباحية",
    "عري", "عاري", "عرى", "عُري",
    # جسد عاري / صريح
    "عريان", "عريانه", "بزاز", "بز", "طيز", "كس", "قضيب", "حلمة",
    "booty", "naked", "nude", "nsfw",
    # محتوى جنسي
    "اغتصاب", "rape", "تحرش", "harassment", "جنسية", "جنسي",
    "شهوة", "شبق", "مثير", "اغراء", "إغراء",
    "xxx", "xxxx", "18+", "عمر 18",
    # محتوى haram / غير أخلاقي
    "حرام", "فاحش", "فاحشة", "رذيلة", "خليع", "خلاعة",
    "مومس", "بغاء", "دعارة",
    # موسيقى / فيديو غير مناسب
    "موسيقى هاري", "رقص شرقي", "رقص مثير",
    "twerk", "striptease", "lap dance",
    # أنماط إضافية
    "شرموط", "قحبة", "عاهرة", "شرموطة",
    "فشخ", "منيك", "متناكة", "مص زب", "لحس",
    "cam girl", "onlyfans", "webcam sex",
    "hentai", "ياباني سكس", "أنمي سكس",
]

# 🔴 كلمات ممنوعة بالإنجليزي
BLOCKED_KEYWORDS_EN = [
    # Explicit sexual content
    "porn", "porno", "pornography", "pornographic",
    "sex", "sexual", "sexy", "nude", "naked", "nsfw",
    "xxx", "hardcore", "softcore", "erotic", "erotica",
    "hentai", "xvideos", "xhamster", "redtube", "youporn",
    "onlyfans", "chaturbate", "cam girl", "camgirl",
    # Body parts (explicit)
    "boobs", "breasts", "tits", "nipples", "pussy", "dick", "cock",
    "penis", "vagina", "anus",
    # Sexual acts
    "fuck", "fucking", "fucked", "blowjob", "handjob", "creampie",
    "orgasm", "cumshot", "ejaculation", "masturbat",
    "rape", "molest", "incest", "bestiality", "zoophilia",
    # Strip / provocative
    "striptease", "lap dance", "pole dance",
    "twerk", "twerking",
    # Prostitution
    "prostitute", "prostitution", "escort", "hooker", "whore",
    # Additional
    "slut", "bitch", "cunt", "twat", "wank",
    "deepfake nude", "undress ai", "nudify",
]

# 🔴 أنماط regex لمزيد من الدقة
BLOCKED_PATTERNS = [
    re.compile(r'\b(porn|porno|pornograph)\w*\b', re.IGNORECASE),
    re.compile(r'\b(nude|naked|nsfw)\w*\b', re.IGNORECASE),
    re.compile(r'\b(sex|sexy|sexual|sexually)\b', re.IGNORECASE),
    re.compile(r'\b(xxx|xxxx)\b', re.IGNORECASE),
    re.compile(r'\b(سكس|سكسي|سكسى|بورنو|بورن)\b', re.IGNORECASE),
    re.compile(r'\b(عري|عاري|عريان|عرى)\b', re.IGNORECASE),
    re.compile(r'\b(إباحي|اباحي|إباحية|اباحية)\b', re.IGNORECASE),
    re.compile(r'\b(بزاز|طيز|قضيب|نيك)\b', re.IGNORECASE),
    re.compile(r'\b(اغتصاب|تحرش|فاحش)\b', re.IGNORECASE),
    re.compile(r'\b(hentai|onlyfans|chaturbate)\b', re.IGNORECASE),
    re.compile(r'\b(18\+)\b'),
]

# ═══════════════════════════════════════
# Layer 6: التسجيل — Logging
# ═══════════════════════════════════════

# ملف تسجيل الطلبات المحظورة
_BLOCKED_LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "content_safety_blocked.jsonl"
)

def _log_blocked_request(
    query: str = "",
    reason: str = "",
    layer: str = "",
    platform: str = "",
    user_id: str = "",
    extra: dict = None,
):
    """تسجيل الطلبات المحظورة — بدون تسجيل الميديا نفسها"""
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query[:200] if query else "",
            "reason": reason,
            "layer": layer,
            "platform": platform,
            "user_id": str(user_id),
        }
        if extra:
            entry.update(extra)

        # نتأكد إن المجلد موجود
        os.makedirs(os.path.dirname(_BLOCKED_LOG_FILE), exist_ok=True)

        with open(_BLOCKED_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info(f"🛡️ Blocked | layer={layer} | reason={reason} | query={query[:50]}")
    except Exception as e:
        logger.warning(f"Failed to log blocked request: {e}")


# ═══════════════════════════════════════
# Layer 1: تصفية الاستعلام — Query Filter
# ═══════════════════════════════════════

def _check_keywords(query: str) -> tuple[bool, str]:
    """فحص الكلمات المفتاحية في الاستعلام — حظر فوري لو فيه كلمة ممنوعة
    
    Returns: (is_blocked, reason)
    """
    if not query:
        return False, ""

    query_lower = query.lower().strip()

    # 1. فحص الكلمات العربية
    for kw in BLOCKED_KEYWORDS_AR:
        if kw in query_lower:
            return True, f"كلمة ممنوعة: {kw}"

    # 2. فحص الكلمات الإنجليزية (كلمات كاملة بس)
    query_words = re.findall(r'\b\w+\b', query_lower)
    for kw in BLOCKED_KEYWORDS_EN:
        # بعض الكلمات الإنجليزية لازم تتطابق ككلمة كاملة
        if kw in query_words:
            return True, f"Blocked keyword: {kw}"
        # والبعض كجزء من الجملة (زي onlyfans)
        if len(kw) > 5 and kw in query_lower:
            return True, f"Blocked keyword: {kw}"

    # 3. فحص أنماط regex
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(query):
            return True, f"نمط ممنوع"

    return False, ""


async def _check_query_with_ai(query: str) -> tuple[bool, str]:
    """فحص الاستعلام بالذكاء الاصطناعي — للطلبات المش واضحة
    
    بنستخدم نموذج سريع (DeepSeek Flash أو Mistral Small)
    عشان نحلل الاستعلام ونشوف هل فيه نية للبحث عن محتوى غير آمن
    
    Returns: (is_blocked, reason)
    """
    try:
        from provider_manager import call_ai

        system_prompt = """You are a content safety classifier. Your job is to determine if a user's search query is requesting inappropriate, explicit, or adult content.

You must classify the query as BLOCKED if it requests or implies any of the following:
- Nudity, naked people, nude photos
- Pornography or sexual content
- Explicit sexual acts or body parts
- Adult/18+ content
- Haram or immoral content
- Provocative or revealing images/videos
- Inappropriate music videos (sexual dancing, provocative)
- Escorts, prostitution, or sexual services

You must classify as SAFE if:
- The query is about normal topics (music, education, news, etc.)
- The query has innocent intent even with ambiguous words
- The query is about medical, educational, or artistic content

Respond with ONLY one word: BLOCKED or SAFE
If BLOCKED, add a brief reason on the same line after a colon.
Example: BLOCKED: requesting nude content
Example: SAFE"""

        result = await call_ai(
            prompt=query,
            system_prompt=system_prompt,
            task_type="simple",
            temperature=0.1,  # Very low temperature for consistent classification
            max_tokens=50,
        )

        if not result:
            # لو الـ AI مش متاح — نعتمد على الكلمات المفتاحية بس
            return False, ""

        result = result.strip().upper()

        if result.startswith("BLOCKED"):
            # استخراج السبب
            reason = ""
            if ":" in result:
                reason = result.split(":", 1)[1].strip()
            else:
                reason = "AI classified as inappropriate"
            return True, reason or "AI classified as inappropriate"

        return False, ""

    except Exception as e:
        logger.warning(f"🛡️ AI query check failed: {e}")
        return False, ""


async def check_query_safety(
    query: str,
    platform: str = "telegram",
    user_id: str = "",
) -> tuple[bool, str]:
    """Layer 1: فحص أمان الاستعلام
    
    🔴 المسار:
    1. فحص الكلمات المفتاحية (فوري — بدون AI)
    2. لو الكلمات مش واضحة → فحص بالـ AI
    
    Returns: (is_safe, reason)
    - is_safe=True → نكمل عادي
    - is_safe=False → نحظر ونفصل
    """
    if not CONTENT_SAFETY_ENABLED:
        return True, ""

    if not query or not query.strip():
        return True, ""

    # 1. فحص الكلمات المفتاحية (فوري)
    is_blocked, reason = _check_keywords(query)
    if is_blocked:
        _log_blocked_request(
            query=query,
            reason=reason,
            layer="L1_keyword",
            platform=platform,
            user_id=user_id,
        )
        return False, reason

    # 2. فحص بالـ AI (للاستعلامات المش واضحة)
    is_blocked_ai, reason_ai = await _check_query_with_ai(query)
    if is_blocked_ai:
        _log_blocked_request(
            query=query,
            reason=reason_ai,
            layer="L1_ai",
            platform=platform,
            user_id=user_id,
        )
        return False, reason_ai

    return True, ""


# ═══════════════════════════════════════
# Layer 2: تحليل نتائج البحث — Search Result Analysis
# ═══════════════════════════════════════

async def check_search_results_safety(
    results: list[dict],
    platform: str = "telegram",
    user_id: str = "",
) -> list[dict]:
    """Layer 2: فحص أمان نتائج البحث — استبعاد النتائج غير الآمنة
    
    بنحلل:
    - عنوان الفيديو
    - الوصف
    - التاجات
    - القناة/التصنيف
    
    Returns: قائمة النتائج الآمنة فقط
    """
    if not CONTENT_SAFETY_ENABLED:
        return results

    if not results:
        return results

    safe_results = []

    for result in results:
        title = result.get("title", "")
        description = result.get("description", "")
        channel = result.get("channel", "")
        tags = result.get("tags", [])

        # تجميع النص
        text_to_check = f"{title} {description} {channel}"
        if isinstance(tags, list):
            text_to_check += " " + " ".join(str(t) for t in tags)

        # 1. فحص الكلمات المفتاحية
        is_blocked, reason = _check_keywords(text_to_check)
        if is_blocked:
            _log_blocked_request(
                query=title[:100],
                reason=f"Search result blocked: {reason}",
                layer="L2_keyword",
                platform=platform,
                user_id=user_id,
                extra={"result_title": title[:100]},
            )
            continue

        # 2. فحص بالـ AI (لو العنوان مشبوه)
        is_suspicious = _has_suspicious_words(text_to_check)
        if is_suspicious:
            is_blocked_ai, reason_ai = await _check_result_with_ai(title, description, channel)
            if is_blocked_ai:
                _log_blocked_request(
                    query=title[:100],
                    reason=f"Search result AI blocked: {reason_ai}",
                    layer="L2_ai",
                    platform=platform,
                    user_id=user_id,
                    extra={"result_title": title[:100]},
                )
                continue

        safe_results.append(result)

    if len(safe_results) < len(results):
        logger.info(f"🛡️ Search results: {len(results)} total, {len(results) - len(safe_results)} blocked, {len(safe_results)} safe")

    return safe_results


def _has_suspicious_words(text: str) -> bool:
    """كشف هل النص فيه كلمات مشبوهة بس مش كافية للحظر المباشر"""
    text_lower = text.lower()

    suspicious = [
        "hot", "sexy", "بنت", "ست", "مرا", "حريم",
        "dance", "رقص", "رقاصة", "model", "موديل",
        "bikini", "بيكيني", "swimwear", "ملابس بحر",
        "lingerie", "ملابس داخلية",
        "strip", "massage", "مساج",
        "boob", "butt", "thigh", "فخذ",
    ]

    for word in suspicious:
        if word in text_lower:
            return True
    return False


async def _check_result_with_ai(title: str, description: str, channel: str) -> tuple[bool, str]:
    """فحص نتيجة بحث بالـ AI"""
    try:
        from provider_manager import call_ai

        text_to_analyze = f"Title: {title}"
        if description:
            text_to_analyze += f"\nDescription: {description[:200]}"
        if channel:
            text_to_analyze += f"\nChannel: {channel}"

        system_prompt = """You are a content safety classifier for search results. Determine if this search result contains or leads to inappropriate content.

BLOCK if it involves:
- Pornography, nudity, or sexual content
- Explicit or 18+ material
- Provocative/revealing media
- Inappropriate music videos (sexual dancing, provocative content)
- Haram or immoral content

SAFE if:
- Normal music, entertainment, education
- Innocent content with ambiguous words
- Medical, artistic, or educational content

Respond with ONLY: BLOCKED or SAFE
If BLOCKED, add reason after colon."""

        result = await call_ai(
            prompt=text_to_analyze,
            system_prompt=system_prompt,
            task_type="simple",
            temperature=0.1,
            max_tokens=50,
        )

        if not result:
            return False, ""

        result = result.strip().upper()
        if result.startswith("BLOCKED"):
            reason = ""
            if ":" in result:
                reason = result.split(":", 1)[1].strip()
            return True, reason or "AI classified as inappropriate"

        return False, ""

    except Exception as e:
        logger.warning(f"🛡️ AI result check failed: {e}")
        return False, ""


# ═══════════════════════════════════════
# Layer 3: فحص الوسائط — Media Inspection
# ═══════════════════════════════════════

async def check_image_safety(
    image_path: str = None,
    image_bytes: bytes = None,
    image_base64: str = None,
    platform: str = "telegram",
    user_id: str = "",
) -> tuple[bool, str, int]:
    """Layer 3: فحص أمان الصورة بالـ Vision AI
    
    🔴 بنستخدم نماذج الرؤية (Llama 3.2 90B Vision / Nemotron Nano VL)
    عشان نحلل الصورة ونكشف:
    - العري
    - المحتوى الجنسي
    - الصور المثيرة
    
    Returns: (is_safe, reason, safety_score)
    - is_safe=True → نكمل ونرسل
    - is_safe=False → نحظر
    - safety_score: 0-100
    """
    if not CONTENT_SAFETY_ENABLED:
        return True, "", 100

    try:
        from provider_manager import get_provider_manager

        manager = get_provider_manager()

        # تجهيز الصورة
        b64_image = None

        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                img_bytes = f.read()
            if len(img_bytes) > MAX_IMAGE_SIZE_FOR_VLM:
                b64_image = _resize_image_for_vlm(img_bytes)
            else:
                b64_image = base64.b64encode(img_bytes).decode("utf-8")
        elif image_bytes:
            if len(image_bytes) > MAX_IMAGE_SIZE_FOR_VLM:
                b64_image = _resize_image_for_vlm(image_bytes)
            else:
                b64_image = base64.b64encode(image_bytes).decode("utf-8")
        elif image_base64:
            b64_image = image_base64

        if not b64_image:
            logger.warning("🛡️ No image data provided for safety check")
            return True, "", 100

        # تحليل الصورة بالـ VLM
        prompt = """Analyze this image for content safety. Check for:
1. Nudity or partial nudity (exposed private parts, see-through clothing)
2. Sexual content or suggestive poses
3. Explicit or pornographic material
4. Provocative or revealing clothing in a sexual context
5. Adult/18+ content

Rate the safety from 0 to 100:
- 100: Completely safe, appropriate for all ages
- 80-99: Generally safe, minor concerns
- 60-79: Borderline, some suggestive elements
- 40-59: Unsafe, clearly inappropriate content
- 0-39: Highly unsafe, explicit content

Respond in EXACTLY this format:
SCORE: <number>
VERDICT: SAFE or UNSAFE
REASON: <brief explanation>"""

        result = await manager.analyze_image_async(
            text_prompt=prompt,
            image_base64=b64_image,
            temperature=0.1,
            max_tokens=100,
        )

        if not result:
            # لو الـ VLM مش متاح — نعتمد على باقي الطبقات
            logger.warning("🛡️ VLM not available for image safety check, passing through")
            return True, "", 75

        # تحليل النتيجة
        safety_score, is_safe, reason = _parse_safety_result(result)

        if not is_safe or safety_score < SAFETY_THRESHOLD:
            _log_blocked_request(
                reason=f"Image unsafe: {reason} (score={safety_score})",
                layer="L3_image",
                platform=platform,
                user_id=user_id,
            )
            return False, reason, safety_score

        return True, "", safety_score

    except Exception as e:
        logger.error(f"🛡️ Image safety check error: {e}")
        return True, "", 75


async def check_video_safety(
    video_path: str,
    title: str = "",
    platform: str = "telegram",
    user_id: str = "",
) -> tuple[bool, str, int]:
    """Layer 3: فحص أمان الفيديو — استخراج فريمات وتحليلها
    
    🔴 بنستخرج عدد فريمات من الفيديو وبنحللهم بالـ VLM
    
    Returns: (is_safe, reason, safety_score)
    """
    if not CONTENT_SAFETY_ENABLED:
        return True, "", 100

    if not video_path or not os.path.exists(video_path):
        return True, "", 100

    try:
        # 1. أولاً نحلل العنوان
        if title:
            title_blocked, title_reason = _check_keywords(title)
            if title_blocked:
                _log_blocked_request(
                    query=title[:100],
                    reason=f"Video title blocked: {title_reason}",
                    layer="L3_title",
                    platform=platform,
                    user_id=user_id,
                )
                return False, title_reason, 0

        # 2. استخراج فريمات من الفيديو
        frames = _extract_video_frames(video_path, count=VIDEO_FRAME_COUNT)

        if not frames:
            # لو مش قادرين نستخرج فريمات — نعتمد على العنوان وباقي الطبقات
            logger.info("🛡️ Could not extract video frames, relying on title analysis")
            return True, "", 75

        # 3. تحليل كل فريم
        lowest_score = 100
        unsafe_reason = ""

        for i, frame_b64 in enumerate(frames):
            is_safe, reason, score = await check_image_safety(
                image_base64=frame_b64,
                platform=platform,
                user_id=user_id,
            )

            if score < lowest_score:
                lowest_score = score
                unsafe_reason = reason

            if not is_safe:
                _log_blocked_request(
                    query=title[:100] if title else "",
                    reason=f"Video frame {i+1} unsafe: {reason} (score={score})",
                    layer="L3_video_frame",
                    platform=platform,
                    user_id=user_id,
                )
                return False, f"إطار غير آمن في الفيديو: {reason}", lowest_score

        return True, "", lowest_score

    except Exception as e:
        logger.error(f"🛡️ Video safety check error: {e}")
        return True, "", 75


async def check_audio_safety(
    title: str = "",
    description: str = "",
    platform: str = "telegram",
    user_id: str = "",
) -> tuple[bool, str, int]:
    """Layer 3: فحص أمان الصوت — تحليل البيانات الوصفية والعنوان
    
    🔴 للصوت بنحلل:
    - العنوان
    - الوصف
    - اسم القناة/الفنان
    
    Returns: (is_safe, reason, safety_score)
    """
    if not CONTENT_SAFETY_ENABLED:
        return True, "", 100

    text_to_check = f"{title} {description}".strip()

    if not text_to_check:
        return True, "", 100

    # 1. فحص الكلمات المفتاحية
    is_blocked, reason = _check_keywords(text_to_check)
    if is_blocked:
        _log_blocked_request(
            query=text_to_check[:100],
            reason=f"Audio blocked: {reason}",
            layer="L3_audio_keyword",
            platform=platform,
            user_id=user_id,
        )
        return False, reason, 0

    # 2. فحص بالـ AI لو فيه كلمات مشبوهة
    if _has_suspicious_words(text_to_check):
        is_blocked_ai, reason_ai = await _check_result_with_ai(title, description, "")
        if is_blocked_ai:
            _log_blocked_request(
                query=text_to_check[:100],
                reason=f"Audio AI blocked: {reason_ai}",
                layer="L3_audio_ai",
                platform=platform,
                user_id=user_id,
            )
            return False, reason_ai, 30

    return True, "", 90


# ═══════════════════════════════════════
# Layer 4: الموافقة النهائية — Final Approval
# ═══════════════════════════════════════

def check_safety_score(score: int) -> tuple[bool, str]:
    """Layer 4: فحص درجة الأمان النهائية
    
    🔴 لو الدرجة أقل من الحد الأدني → نرفض
    
    Returns: (is_approved, reason)
    """
    if not CONTENT_SAFETY_ENABLED:
        return True, ""

    if score >= SAFETY_THRESHOLD:
        return True, ""

    reason = f"درجة الأمان {score} أقل من الحد الأدنى {SAFETY_THRESHOLD}"
    return False, reason


# ═══════════════════════════════════════
# Layer 5: الوضع الآمن — Safe Search Mode
# ═══════════════════════════════════════

def get_safe_search_params() -> dict:
    """Layer 5: إعدادات البحث الآمن
    
    🔴 بنفعّل البحث الآمن افتراضياً لكل عمليات البحث
    
    Returns: dict فيه إعدادات البحث الآمن
    """
    return {
        "safesearch": True,
        "safe_search": "active",
        "family_friendly": True,
    }


def should_enable_safe_search() -> bool:
    """التحقق هل البحث الآمن مفعل"""
    return CONTENT_SAFETY_ENABLED


# ═══════════════════════════════════════
# Layer 7: تجربة المستخدم — User Experience
# ═══════════════════════════════════════

def get_block_message(lang: str = "ar", reason: str = "") -> str:
    """رسالة الرفض للمستخدم — واضحة ومحترمة"""
    if lang == "ar":
        if reason and ("كلمة ممنوعة" in reason or "نمط ممنوع" in reason):
            return "عذرًا، لا أستطيع المساعدة في البحث أو تحميل هذا النوع من المحتوى. 🛡️"
        elif reason and ("unsafe" in reason.lower() or "غير آمن" in reason or "إطار" in reason):
            return "تم العثور على محتوى غير مناسب لذلك لن يتم إرسال الملف. 🛡️"
        elif reason and ("درجة الأمان" in reason):
            return "تم رفض الطلب لأن محتواه غير مناسب. 🛡️"
        else:
            return "عذرًا، لا أستطيع المساعدة في البحث أو تحميل هذا النوع من المحتوى. 🛡️"
    else:
        if reason and ("keyword" in reason.lower() or "pattern" in reason.lower()):
            return "Sorry, I cannot help with searching or downloading this type of content. 🛡️"
        elif reason and ("unsafe" in reason.lower() or "frame" in reason.lower()):
            return "Inappropriate content was found, so the file will not be sent. 🛡️"
        elif reason and ("score" in reason.lower()):
            return "The request was rejected because the content is inappropriate. 🛡️"
        else:
            return "Sorry, I cannot help with searching or downloading this type of content. 🛡️"


def get_no_safe_results_message(lang: str = "ar") -> str:
    """رسالة عدم وجود نتائج آمنة"""
    if lang == "ar":
        return "لم يتم العثور على نتائج آمنة مطابقة لطلبك. جرب كلمات بحث مختلفة. 🛡️"
    else:
        return "No safe results were found matching your request. Try different search terms. 🛡️"


# ═══════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════

def _resize_image_for_vlm(image_bytes: bytes, max_size: int = 1024) -> str:
    """تصغير الصورة عشان نبعتهالـ VLM
    
    Returns: base64 string
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_in:
            tmp_in.write(image_bytes)
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(".jpg", "_resized.jpg")

        result = subprocess.run(
            ["ffmpeg", "-i", tmp_in_path, "-vf",
             f"scale='min({max_size},iw)':'min({max_size},ih)':force_original_aspect_ratio=decrease",
             "-q:v", "5", tmp_out_path],
            capture_output=True, timeout=10
        )

        if result.returncode == 0 and os.path.exists(tmp_out_path):
            with open(tmp_out_path, "rb") as f:
                resized = f.read()
            try:
                os.remove(tmp_in_path)
                os.remove(tmp_out_path)
            except:
                pass
            return base64.b64encode(resized).decode("utf-8")

        try:
            os.remove(tmp_in_path)
            if os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)
        except:
            pass

    except Exception:
        pass

    # Fallback: نرجع الصورة الأصلية
    return base64.b64encode(image_bytes).decode("utf-8")


def _extract_video_frames(video_path: str, count: int = 3) -> list[str]:
    """استخراج فريمات من الفيديو للتحليل
    
    بنستخدم ffmpeg — بنستخرج فريمات من أماكن مختلفة في الفيديو
    
    Returns: list of base64 strings
    """
    frames = []

    try:
        # 1. معرفة مدة الفيديو
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10
        )

        if probe.returncode != 0 or not probe.stdout.strip():
            timestamps = [1, 5, 10]
        else:
            duration = float(probe.stdout.strip())
            if duration <= 0:
                return []

            start = min(2, duration * 0.1)
            end = max(duration - 1, start + 1)
            step = (end - start) / max(count - 1, 1)
            timestamps = [start + i * step for i in range(count)]

        # 2. استخراج كل فريم
        tmpdir = tempfile.mkdtemp(prefix="safety_frames_")

        for i, ts in enumerate(timestamps):
            out_path = os.path.join(tmpdir, f"frame_{i}.jpg")
            try:
                result = subprocess.run(
                    ["ffmpeg", "-ss", str(ts), "-i", video_path,
                     "-vframes", "1", "-q:v", "5",
                     "-vf", "scale=640:-1",
                     out_path],
                    capture_output=True, timeout=15
                )

                if result.returncode == 0 and os.path.exists(out_path):
                    with open(out_path, "rb") as f:
                        frame_bytes = f.read()
                    if len(frame_bytes) > 100:
                        frames.append(base64.b64encode(frame_bytes).decode("utf-8"))
            except Exception as e:
                logger.warning(f"🛡️ Frame extraction error at {ts}s: {e}")
            finally:
                try:
                    os.remove(out_path)
                except:
                    pass

        # تنظيف
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except:
            pass

    except FileNotFoundError:
        logger.warning("🛡️ ffmpeg not available for video frame extraction")
    except Exception as e:
        logger.warning(f"🛡️ Video frame extraction error: {e}")

    return frames


def _parse_safety_result(result: str) -> tuple[int, bool, str]:
    """تحليل نتيجة فحص الأمان من الـ VLM
    
    Returns: (score, is_safe, reason)
    """
    score = 100
    is_safe = True
    reason = ""

    result_upper = result.upper().strip()

    # استخراج الدرجة
    score_match = re.search(r'SCORE[:\s]+(\d+)', result_upper)
    if score_match:
        score = int(score_match.group(1))

    # استخراج الحكم
    if "UNSAFE" in result_upper:
        is_safe = False
    elif "SAFE" in result_upper and score >= SAFETY_THRESHOLD:
        is_safe = True
    else:
        is_safe = score >= SAFETY_THRESHOLD

    # استخراج السبب
    reason_match = re.search(r'REASON[:\s]+(.+)', result, re.IGNORECASE)
    if reason_match:
        reason = reason_match.group(1).strip()

    score = max(0, min(100, score))

    return score, is_safe, reason


# ═══════════════════════════════════════
# دالة شاملة — Comprehensive Safety Check
# ═══════════════════════════════════════

async def comprehensive_media_safety_check(
    query: str = "",
    title: str = "",
    file_path: str = None,
    file_type: str = "video",
    platform: str = "telegram",
    user_id: str = "",
    lang: str = "ar",
) -> tuple[bool, str, str]:
    """فحص أمان شامل للميديا — كل الطبقات مع بعض
    
    🔴 المسار:
    1. فحص الاستعلام (لو موجود)
    2. فحص العنوان
    3. فحص الميديا الفعلي
    4. فحص درجة الأمان
    
    Returns: (is_safe, block_message, reason)
    - is_safe=True → نكمل ونرسل
    - is_safe=False → نعرض block_message للمستخدم
    """
    if not CONTENT_SAFETY_ENABLED:
        return True, "", ""

    # Layer 1: فحص الاستعلام
    if query:
        is_safe, reason = await check_query_safety(query, platform, user_id)
        if not is_safe:
            msg = get_block_message(lang, reason)
            return False, msg, reason

    # Layer 1b: فحص العنوان
    if title:
        is_blocked, reason = _check_keywords(title)
        if is_blocked:
            _log_blocked_request(
                query=title[:100],
                reason=f"Title blocked: {reason}",
                layer="L1_title",
                platform=platform,
                user_id=user_id,
            )
            msg = get_block_message(lang, reason)
            return False, msg, reason

    # Layer 3: فحص الميديا الفعلي
    safety_score = 100
    safety_reason = ""

    if file_path and os.path.exists(file_path):
        if file_type == "image":
            is_safe, reason, score = await check_image_safety(
                image_path=file_path,
                platform=platform,
                user_id=user_id,
            )
            safety_score = score
            safety_reason = reason
            if not is_safe:
                msg = get_block_message(lang, reason)
                return False, msg, reason

        elif file_type == "video":
            is_safe, reason, score = await check_video_safety(
                video_path=file_path,
                title=title,
                platform=platform,
                user_id=user_id,
            )
            safety_score = score
            safety_reason = reason
            if not is_safe:
                msg = get_block_message(lang, reason)
                return False, msg, reason

        elif file_type == "audio":
            is_safe, reason, score = await check_audio_safety(
                title=title,
                platform=platform,
                user_id=user_id,
            )
            safety_score = score
            safety_reason = reason
            if not is_safe:
                msg = get_block_message(lang, reason)
                return False, msg, reason

    # Layer 4: فحص درجة الأمان النهائية
    is_approved, reason = check_safety_score(safety_score)
    if not is_approved:
        msg = get_block_message(lang, reason)
        return False, msg, reason or safety_reason

    return True, "", ""
