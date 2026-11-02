"""
سياسة رسائل المستخدم — User-Facing Message Policy
═══════════════════════════════════════════════════
قاعدة زياد (2026-11-02): المستخدم العادي ما لوش دعوة بأي مصطلح تقني —
لا اسم خدمة (Cobalt/Apify/yt-dlp/VPS)، لا خطأ تقني خام، لا تفاصيل داخلية.
المطور بس هو اللي يشوف التفاصيل التقنية الكاملة:
  - تليجرام: CHAT_ID
  - واتساب: ADMIN_WA_ID / DEVELOPER_WHATSAPP
"""

import os
import logging

logger = logging.getLogger("user_facing")


def is_developer(platform: str, user_id) -> bool:
    """هل المستخدم ده هو المطور نفسه؟ (مش أي أدمن — المطور فقط)"""
    try:
        if user_id is None:
            return False
        uid = str(user_id).strip().lstrip("+")
        if not uid:
            return False
        if platform == "whatsapp":
            devs = {os.environ.get("DEVELOPER_WHATSAPP", ""), os.environ.get("ADMIN_WA_ID", "")}
            return uid in {d.strip().lstrip("+") for d in devs if d}
        # telegram (default)
        dev_tg = os.environ.get("CHAT_ID", "").strip()
        return bool(dev_tg) and uid == dev_tg
    except Exception as e:
        logger.debug(f"is_developer error: {e}")
        return False


def dl_progress(platform: str, user_id, lang: str,
                dev_ar: str, dev_en: str,
                plain_ar: str, plain_en: str) -> str:
    """رسالة تقدّم التحميل — اسم الخدمة/المصدر يظهر للمطور فقط."""
    if is_developer(platform, user_id):
        return dev_ar if lang == "ar" else dev_en
    return plain_ar if lang == "ar" else plain_en


def dl_error_hint(platform: str, user_id, lang: str,
                  error_str: str,
                  friendly_ar: str, friendly_en: str) -> str:
    """ملحق رسالة الخطأ — التفاصيل التقنية الخام للمطور فقط."""
    if is_developer(platform, user_id):
        tech = str(error_str)[:150].replace("\n", " ")
        return (f"\n🔧 تفاصيل تقنية (للمطور): {tech}"
                if lang == "ar" else
                f"\n🔧 Technical details (dev): {tech}")
    return friendly_ar if lang == "ar" else friendly_en


async def safe_answer_callback(query, text: str = None, show_alert: bool = False):
    """🔴 إصلاح 'Query is too old and response timeout expired' (Sentry 2026-11-03):
    الضغطة القديمة (بعد معالجة طويلة أو إعادة تشغيل) بترفض لما نجاوب عليها
    وبرفع استثناء بيروح Sentry — ده غلاف آمن: بيجرب يرد ولو الضغطة قديمة
    بيتجاهل الرد بصمت والمعالجة نفسها بتكمل عادي."""
    try:
        if text:
            await query.answer(text=text, show_alert=show_alert)
        else:
            await query.answer()
    except Exception as e:
        logger.debug(f"callback answer skipped (stale/expired): {type(e).__name__}: {str(e)[:80]}")
