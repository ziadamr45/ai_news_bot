"""
نظام الإدارة - Admin System
الادمن (@ziadamr) ليه صلاحيات كاملة:
- يشوف الإحصائيات والـ Dashboard
- يفعل Premium لأي حد
- يشيل Premium من أي حد
- يبعت رسالة لكل المشتركين (Broadcast)
- يشوف معلومات أي يوزر
- يضيف/يشيل أدمن تانيين
- الأدمن مبيتحكمش فيه أي Limits — كل حاجة مفتوحة
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import DEVELOPER_TELEGRAM, CHAT_ID

logger = logging.getLogger(__name__)

CAIRO_TZ = timezone(timedelta(hours=2))


# ═══════════════════════════════════════
# تحليل المدة - Duration Parser
# ═══════════════════════════════════════

def parse_duration(duration_str: str) -> tuple[int, str]:
    """
    تحليل مدة الـ Premium من نص
    
    الاختصارات:
    - d أو يوم أو day → أيام
    - w أو أسبوع أو week → أسابيع (×7)
    - m أو شهر أو month → أشهر (×30)
    - y أو سنة أو year → سنين (×365)
    - 0 أو دائم أو forever → مدى الحياة
    - رقم لوحده → أيام
    - مركبة: m3 (3 أشهر), w2 (أسبوعين), y2 (سنتين)
    
    Returns: (days, display_text)
    - days = 0 يعني مدى الحياة
    - days = -1 يعني خطأ
    """
    s = duration_str.strip().lower()
    
    # مدى الحياة
    if s in ("0", "دائم", "forever", "lifetime", "life"):
        return (0, "مدى الحياة 🔓")
    
    # سنة — الكلمات العربية الأول (قبل ما نحاول int)
    if s in ("سنة", "سنين", "عام") or s.startswith("y"):
        if s in ("سنة", "سنين", "عام"):
            num = 1
        else:
            num_part = s.lstrip("y").strip()
            num = int(num_part) if num_part else 1
        days = num * 365
        label = f"{num} سنة" if num > 1 else "سنة"
        return (days, f"{label} ({days} يوم) 🔒")
    
    # شهر
    if s in ("شهر", "شهور", "أشهر") or s.startswith("m"):
        if s in ("شهر", "شهور", "أشهر"):
            num = 1
        else:
            num_part = s.lstrip("m").strip()
            num = int(num_part) if num_part else 1
        days = num * 30
        label = f"{num} شهر" if num > 1 else "شهر"
        return (days, f"{label} ({days} يوم) 🔒")
    
    # أسبوع
    if s in ("أسبوع", "اسبوع", "أسبوعين", "week", "weeks") or s.startswith("w"):
        if s in ("أسبوع", "اسبوع", "أسبوعين", "week", "weeks"):
            num = 1
        else:
            num_part = s.lstrip("w").strip()
            num = int(num_part) if num_part else 1
        days = num * 7
        label = f"{num} أسبوع" if num > 1 else "أسبوع"
        return (days, f"{label} ({days} يوم) 🔒")
    
    # يوم
    if s in ("يوم", "ايام", "أيام", "day", "days") or s.startswith("d"):
        if s in ("يوم", "ايام", "أيام", "day", "days"):
            num = 1
        else:
            num_part = s.lstrip("d").strip()
            num = int(num_part) if num_part else 1
        return (num, f"{num} يوم 🔒")
    
    # رقم لوحده = أيام
    try:
        num = int(s)
        if num < 0:
            return (-1, "")
        if num == 0:
            return (0, "مدى الحياة 🔓")
        return (num, f"{num} يوم 🔒")
    except ValueError:
        return (-1, "")

# ═══════════════════════════════════════
# Cache لـ ensure_admin_premium - عشان ميعملش DB query مع كل رسالة
# ═══════════════════════════════════════
_admin_premium_cache = {}  # {user_id: (is_premium, timestamp)}
_ADMIN_PREMIUM_CACHE_TTL = 300  # 5 دقايق

# ═══════════════════════════════════════
# هوية الأدمن - Admin Identity
# ═══════════════════════════════════════

ADMIN_TELEGRAM_USERNAME = "ziadamr"  # @ziadamr — المالك والادمن
ADMIN_USER_IDS = set()  # هيتم تعبئتهم من CHAT_ID + الداتابيز + أي IDs تانية

# إضافة CHAT_ID كأدمن
try:
    if CHAT_ID:
        ADMIN_USER_IDS.add(int(CHAT_ID))
except (ValueError, TypeError):
    pass

# 🔴 FIX: إضافة developer ID كـ fallback عشان لو CHAT_ID مش موجود
# الـ developer لازم يكون أدمن دايماً
try:
    from config import DEVELOPER_USER_ID
    if DEVELOPER_USER_ID:
        ADMIN_USER_IDS.add(DEVELOPER_USER_ID)
except Exception:
    pass


def _load_admin_ids_from_db():
    """تحميل الأدمن IDs من الداتابيز عند التشغيل"""
    try:
        from memory import _execute, _is_postgres
        # إنشاء جدول admin_users لو مش موجود
        if _is_postgres():
            _execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT DEFAULT '',
                    role TEXT DEFAULT 'admin',
                    added_at TEXT DEFAULT (NOW() AT TIME ZONE 'UTC'::text),
                    added_by TEXT DEFAULT 'system'
                )
            """)
        else:
            _execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT DEFAULT '',
                    role TEXT DEFAULT 'admin',
                    added_at TEXT DEFAULT (datetime('now')),
                    added_by TEXT DEFAULT 'system'
                )
            """)
        # تحميل كل الأدمن IDs
        rows = _execute("SELECT user_id FROM admin_users", fetch=True)
        if rows:
            for row in rows:
                ADMIN_USER_IDS.add(row[0])
            logger.info(f"👑 Loaded {len(rows)} admin IDs from database")
    except Exception as e:
        logger.warning(f"Could not load admin IDs from DB: {e}")


# تحميل الأدمن IDs من الداتابيز عند الاستيراد
_load_admin_ids_from_db()


def is_admin(user_id: int, username: str = None) -> bool:
    """
    فحص هل المستخدم ده أدمن (المالك أو أدمن مضاف)
    - لو الـ user_id في ADMIN_USER_IDS
    - أو الـ username هو @ziadamr
    """
    if user_id in ADMIN_USER_IDS:
        return True
    if username:
        # تنظيف الـ @ من بداية الاسم
        clean_username = username.lstrip('@').lower()
        if clean_username == ADMIN_TELEGRAM_USERNAME:
            # حفظ الـ ID عشان المرات الجاية
            ADMIN_USER_IDS.add(user_id)
            # حفظ في الداتابيز كمان
            try:
                _save_admin_to_db(user_id, username, role="owner")
            except Exception:
                pass
            return True
    return False


def _save_admin_to_db(user_id: int, username: str = "", role: str = "admin", added_by: str = "system"):
    """حفظ أدمن جديد في الداتابيز"""
    try:
        from memory import _execute, _is_postgres, _ensure_user_in_db
        _ensure_user_in_db(user_id)
        
        now = datetime.now(CAIRO_TZ).isoformat()
        ph1, ph2, ph3, ph4, ph5 = tuple(["%s"] * 5) if _is_postgres() else tuple(["?"] * 5)
        
        existing = _execute(
            f"SELECT user_id FROM admin_users WHERE user_id = {ph1}",
            (user_id,), fetchone=True
        )
        if not existing:
            _execute(
                f"INSERT INTO admin_users (user_id, username, role, added_at, added_by) VALUES ({ph1}, {ph2}, {ph3}, {ph4}, {ph5})",
                (user_id, username, role, now, added_by)
            )
    except Exception as e:
        logger.warning(f"Could not save admin to DB: {e}")


def _remove_admin_from_db(user_id: int):
    """شيل أدمن من الداتابيز"""
    try:
        from memory import _execute, _is_postgres
        ph = "%s" if _is_postgres() else "?"
        _execute(f"DELETE FROM admin_users WHERE user_id = {ph}", (user_id,))
        ADMIN_USER_IDS.discard(user_id)
    except Exception as e:
        logger.warning(f"Could not remove admin from DB: {e}")


def ensure_admin_premium(user_id: int):
    """
    التأكد إن الأدمن دايماً Premium
    يتضاف تلقائياً لو مش Premium
    
    🔴 محسن: بيستخدم cache عشان ميعملش DB query مع كل رسالة
    الـ cache بيتجدد كل 5 دقايق بس
    """
    import time as _time
    # فحص الـ cache الأول
    now = _time.time()
    if user_id in _admin_premium_cache:
        is_premium, cached_at = _admin_premium_cache[user_id]
        if now - cached_at < _ADMIN_PREMIUM_CACHE_TTL:
            return  # الـ cache لسه صالح — مفيش داعي نعمل query
    
    try:
        from premium import get_user_plan, grant_premium
        plan = get_user_plan(user_id)
        is_premium = (plan == "premium")
        
        if plan != "premium":
            grant_premium(user_id, granted_by="system_admin", expires=None)
            logger.info(f"👑 Auto-granted premium to admin {user_id}")
            is_premium = True
        
        # تحديث الـ cache
        _admin_premium_cache[user_id] = (is_premium, now)
    except Exception as e:
        logger.warning(f"Could not auto-grant premium to admin: {e}")


# ═══════════════════════════════════════
# إرسال إشعارات عبر المنصات - Cross-Platform Notifications
# ═══════════════════════════════════════

async def send_cross_platform_notification(
    target_user_id: int,
    text: str,
    telegram_bot=None,
    html_parse_mode: bool = True
):
    """إرسال إشعار للمستخدم على المنصة الصح (تليجرام أو واتساب)
    
    Args:
        target_user_id: معرف المستخدم (hashed user_id)
        text: نص الرسالة
        telegram_bot: كائن البوت التليجرام (context.bot) — لازم لو اليوزر تليجرام
        html_parse_mode: هل الرسالة بـ HTML formatting
    
    Returns:
        True لو الإشعار وصل، False لو فشل
    """
    try:
        from memory import get_user
        user_data = get_user(target_user_id)
        platform = user_data.get("platform", "telegram")
        wa_phone = user_data.get("wa_phone", "")
        
        if platform == "whatsapp" and wa_phone:
            # يوزر واتساب — ابعت عبر WhatsApp Cloud API
            try:
                from whatsapp_webhook import _send_whatsapp_message, _strip_html_for_whatsapp
                
                # WhatsApp لا يدعم HTML — حوّله لـ WhatsApp formatting
                wa_text = _strip_html_for_whatsapp(text) if html_parse_mode else text
                
                result = await _send_whatsapp_message(wa_phone, wa_text)
                if "error" not in result:
                    logger.info(f"📤 WA notification sent to {wa_phone}")
                    return True
                else:
                    logger.warning(f"⚠️ WA notification failed for {wa_phone}: {result}")
            except ImportError:
                logger.warning("⚠️ whatsapp_webhook not available for notification")
            except Exception as e:
                logger.warning(f"⚠️ WA notification error: {e}")
            
            # Fallback: حاول ابعت على التليجرام كمان
            if telegram_bot:
                try:
                    await telegram_bot.send_message(
                        chat_id=target_user_id,
                        text=text,
                        parse_mode="HTML" if html_parse_mode else None
                    )
                    return True
                except Exception:
                    pass
            
            return False
        
        else:
            # يوزر تليجرام — ابعت عبر Telegram Bot API
            if telegram_bot:
                try:
                    await telegram_bot.send_message(
                        chat_id=target_user_id,
                        text=text,
                        parse_mode="HTML" if html_parse_mode else None
                    )
                    return True
                except Exception as e:
                    logger.info(f"Could not notify Telegram user {target_user_id}: {e}")
                    return False
            
            return False
    
    except Exception as e:
        logger.warning(f"⚠️ Cross-platform notification error: {e}")
        return False


# ═══════════════════════════════════════
# أوامر الأدمن - Admin Commands
# ═══════════════════════════════════════

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /admin — لوحة تحكم الأدمن"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    lang = "ar"  # الأدمن مصري :)

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    # تأكد إن الأدمن Premium
    ensure_admin_premium(user_id)

    from dashboard import format_dashboard, get_total_users, get_total_subscribers, get_total_premium, get_today_stats
    from premium import get_all_premium_users
    from memory import get_all_subscribers

    dashboard = format_dashboard(lang)

    # إضافة معلومات الأدمن
    admin_info = f"""
━━━━━━━━━━━━━━━━━
👑 <b>صلاحياتك كأدمن</b>
→ مفيش أي Limits — كل حاجة مفتوحة
→ تفعيل Premium لأي حد
→ شيل Premium من أي حد
→ بث رسالة لكل المشتركين
→ معلومات أي يوزر
→ لوحة الإحصائيات الكاملة

━━━━━━━━━━━━━━━━━
🔧 <b>أوامر الأدمن</b>
→ <code>/grant [مدة] user_id</code> — تفعيل Premium (m=شهر, w=أسبوع, y=سنة)
→ <code>/revoke user_id</code> — شيل Premium
→ <code>/resetlimit user_id</code> — إعادة تعيين الحدود المجانية
→ <code>/broadcast رسالة</code> — بث لكل المشتركين
→ <code>/userinfo user_id</code> — معلومات يوزر شاملة (بدون بيانات حساسة)
→ <code>/userstats user_id</code> — إحصائيات يوزر مفصلة
→ <code>/admin</code> — اللوحة دي
"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ كل الـ Premium", callback_data="admin_list_premium"),
            InlineKeyboardButton("👥 كل المشتركين", callback_data="admin_list_subscribers"),
        ],
        [
            InlineKeyboardButton("📊 إحصائيات مفصلة", callback_data="admin_detailed_stats"),
            InlineKeyboardButton("🔄 تحديث", callback_data="admin_refresh"),
        ],
    ])

    await update.message.reply_text(
        dashboard + admin_info,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    # 🔴 FIX: إعادة إرسال الواجهة (ReplyKeyboard) للأدمن عشان التليجرام بيخفيها أحياناً
    from handlers.keyboards import get_main_keyboard
    from memory import get_language
    admin_lang = get_language(user_id)
    main_keyboard = get_main_keyboard(admin_lang)
    await update.message.reply_text(
        "⬆️ الأزرار" if admin_lang == "ar" else "⬆️ Menu",
        reply_markup=main_keyboard
    )


async def grant_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر /grant — تفعيل Premium ليوزر
    الاستخدام: /grant [مدة] user_id
    
    المدة:
    - رقم أيام: /grant 30 user_id
    - اختصارات: w (أسبوع), m (شهر), y (سنة), d (يوم)
    - مركبة: w2 (أسبوعين), m3 (3 أشهر)
    - 0 أو دائم: مدى الحياة
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "⭐ <b>تفعيل Premium</b>\n\n"
            "الاستخدام:\n"
            "<code>/grant user_id</code> — تفعيل مدى الحياة\n"
            "<code>/grant 30 user_id</code> — تفعيل 30 يوم\n"
            "<code>/grant m user_id</code> — تفعيل شهر (30 يوم)\n"
            "<code>/grant w user_id</code> — تفعيل أسبوع (7 أيام)\n"
            "<code>/grant y user_id</code> — تفعيل سنة (365 يوم)\n"
            "<code>/grant m3 user_id</code> — تفعيل 3 أشهر\n"
            "<code>/grant 0 user_id</code> — تفعيل مدى الحياة\n\n"
            "🔑 <b>اختصارات المدة:</b>\n"
            "d = يوم | w = أسبوع | m = شهر | y = سنة\n"
            "0 أو دائم = مدى الحياة\n\n"
            "🔄 <b>تجديد Premium:</b>\n"
            "<code>/grant force m user_id</code> — تجديد حتى لو Premium\n\n"
            "مثال: <code>/grant m 123456789</code>\n"
            "مثال: <code>/grant w2 123456789</code>",
            parse_mode="HTML"
        )
        return

    # 🔴 فحص كلمة force — عشان تجديد Premium للمستخدم اللي أصلاً Premium
    force_renew = False
    if args[0].lower() == "force":
        force_renew = True
        args = args[1:]  # شيل كلمة force من المعاملات

    if not args:
        await update.message.reply_text("❌ لازم تحدد user_id بعد force. مثال: /grant force m 123456789")
        return

    # تحليل المعاملات
    if len(args) == 1:
        # /grant user_id → مدى الحياة
        try:
            target_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ user_id لازم يكون رقم. مثال: /grant 123456789")
            return
        days = 0
        expires_display = "مدى الحياة 🔓"
    elif len(args) == 2:
        # /grant [مدة] user_id
        duration_str = args[0]
        try:
            target_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ user_id لازم يكون رقم. مثال: /grant m 123456789")
            return
        
        days, expires_display = parse_duration(duration_str)
        if days == -1:
            await update.message.reply_text(
                "❌ المدة مش صحيحة.\n\n"
                "🔑 الاختصارات:\n"
                "d أو يوم = أيام | w أو أسبوع = أسابيع\n"
                "m أو شهر = أشهر | y أو سنة = سنين\n"
                "0 أو دائم = مدى الحياة\n\n"
                "مثال: <code>/grant m 123456789</code> (شهر)\n"
                "مثال: <code>/grant w2 123456789</code> (أسبوعين)\n"
                "مثال: <code>/grant 30 123456789</code> (30 يوم)",
                parse_mode="HTML"
            )
            return
    else:
        await update.message.reply_text("❌ كترت المعاملات. الاستخدام: /grant [مدة] user_id")
        return

    # حساب تاريخ الانتهاء
    expires = None
    if days > 0:
        expires_date = datetime.now(CAIRO_TZ) + timedelta(days=days)
        expires = expires_date.isoformat()
        expires_display += f" (ينتهي {expires_date.strftime('%Y-%m-%d')})"

    # تفعيل Premium
    try:
        from premium import grant_premium, get_premium_info
        from memory import _ensure_user_in_db

        _ensure_user_in_db(target_id)
        
        # 🔴 فحص هل المستخدم أصلاً Premium
        current_info = get_premium_info(target_id)
        
        # محاولة جلب اسم المستخدم
        try:
            from memory import get_user
            user_data = get_user(target_id)
            target_name = user_data.get("name", "")
        except Exception:
            target_name = ""

        name_display = f" ({target_name})" if target_name else ""

        if current_info["is_premium"] and not force_renew:
            # المستخدم أصلاً Premium — نقول للأدمن ونعرض معلوماته
            current_expires = current_info["expires_display"]
            current_since = current_info["premium_since"][:10] if current_info["premium_since"] else "مش محدد"
            
            # 🔴 هل المدة الجديدة أطول من الحالية؟ لو آه → تجديد
            # لو لأ → نقول للأدمن إنه أصلاً Premium
            await update.message.reply_text(
                f"⚠️ <b>المستخدم ده أصلاً Premium!</b>\n\n"
                f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
                f"⭐ الخطة الحالية: Premium\n"
                f"📅 مفعل من: {current_since}\n"
                f"⏰ المتبقي: {current_expires}\n\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"🔄 <b>عايز تجدده؟</b>\n"
                f"المدة الجديدة: {expires_display}\n\n"
                f"لو عايز تجدده / تطيل مدته، اكتب:\n"
                f"<code>/grant force {' '.join(context.args[1:]) if len(context.args) > 1 else str(target_id)}</code>",
                parse_mode="HTML"
            )
            return

        # تفعيل أو تجديد Premium
        if force_renew and current_info["is_premium"]:
            # تجديد — نقول للأدمن إنه جدّد
            old_expires = current_info["expires_display"]
            grant_premium(target_id, granted_by=f"admin_{user_id}", expires=expires)
            await update.message.reply_text(
                f"🔄 <b>تم تجديد Premium!</b>\n\n"
                f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
                f"⭐ الخطة: Premium\n"
                f"⏰ المدة القديمة: {old_expires}\n"
                f"⏰ المدة الجديدة: {expires_display}\n"
                f"🔑 التجديد بواسطة: @ziadamr",
                parse_mode="HTML"
            )
        else:
            # المستخدم Free → تفعيل عادي
            grant_premium(target_id, granted_by=f"admin_{user_id}", expires=expires)

            await update.message.reply_text(
                f"✅ <b>تم تفعيل Premium!</b>\n\n"
                f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
                f"📊 الخطة السابقة: Free\n"
                f"⭐ الخطة الجديدة: Premium\n"
                f"⏰ المدة: {expires_display}\n"
                f"🔑 التفعيل بواسطة: @ziadamr",
                parse_mode="HTML"
            )

        # محاولة إرسال رسالة للمستخدم (عبر المنصة الصح — تليجرام أو واتساب)
        try:
            await send_cross_platform_notification(
                target_user_id=target_id,
                text=f"⭐ <b>مبروك! تم تفعيل Premium!</b>\n\n"
                     f"أنت دلوقتي مشترك Premium في My Bro!\n"
                     f"استمتع بكل المزايا:\n"
                     f"• رسائل AI غير محدودة 💬\n"
                     f"• تحليل PDF غير محدود 📄\n"
                     f"• تحليل صور غير محدود + Vision Pro 👁️\n"
                     f"• ملخصات YouTube غير محدودة 🎬\n"
                     f"• بحث غير محدود 🔍\n"
                     f"• تحميل وسائط من أي منصة 📥\n"
                     f"  (YouTube, Instagram, TikTok, FB, Twitter...)\n"
                     f"• فيديو بالبحث غير محدود 🎬\n"
                     f"• صوت بالبحث غير محدود 🎵\n"
                     f"• بحث صور غير محدود 🖼️\n"
                     f"• إنشاء صور بالذكاء الاصطناعي 🎨\n"
                     f"• تعديل صور بالذكاء الاصطناعي 🖌️\n"
                     f"• وضع الدراسة 📚\n"
                     f"• ذاكرة طويلة المدى 🧠\n\n"
                     f"⏰ المدة: {expires_display}",
                telegram_bot=context.bot
            )
        except Exception as e:
            logger.info(f"Could not notify user {target_id}: {e}")

    except Exception as e:
        await update.message.reply_text(f"❌ حصل خطأ: {e}")


async def revoke_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر /revoke — شيل Premium من يوزر
    الاستخدام: /revoke 123456789
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "❌ <b>شيل Premium</b>\n\n"
            "الاستخدام: <code>/revoke user_id</code>\n"
            "مثال: <code>/revoke 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return

    # منع شيل Premium من الأدمن نفسه
    if is_admin(target_id):
        await update.message.reply_text("👑 مينفعش تشيل Premium من الأدمن!")
        return

    try:
        from premium import revoke_premium, get_premium_info

        current_info = get_premium_info(target_id)
        
        # 🔴 فحص هل المستخدم أصلاً مش Premium
        if not current_info["is_premium"]:
            # محاولة جلب اسم المستخدم
            try:
                from memory import get_user
                user_data = get_user(target_id)
                target_name = user_data.get("name", "")
            except Exception:
                target_name = ""
            name_display = f" ({target_name})" if target_name else ""
            
            await update.message.reply_text(
                f"⚠️ <b>المستخدم ده أصلاً مش Premium!</b>\n\n"
                f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
                f"📊 الخطة الحالية: Free\n\n"
                f"مفيش حاجة تتشيل — المستخدم على الخطه المجانيه بالفعل.",
                parse_mode="HTML"
            )
            return

        # المستخدم Premium → شيله
        old_expires = current_info["expires_display"]
        old_since = current_info["premium_since"][:10] if current_info["premium_since"] else "مش محدد"
        
        # محاولة جلب اسم المستخدم
        try:
            from memory import get_user
            user_data = get_user(target_id)
            target_name = user_data.get("name", "")
        except Exception:
            target_name = ""
        name_display = f" ({target_name})" if target_name else ""
        
        revoke_premium(target_id)

        await update.message.reply_text(
            f"✅ <b>تم شيل Premium</b>\n\n"
            f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
            f"📊 الخطة القديمة: Premium\n"
            f"📅 كان مفعل من: {old_since}\n"
            f"⏰ كان المتبقي: {old_expires}\n"
            f"📊 الخطة الجديدة: Free",
            parse_mode="HTML"
        )

        # إبلاغ المستخدم (عبر المنصة الصح — تليجرام أو واتساب)
        try:
            await send_cross_platform_notification(
                target_user_id=target_id,
                text="⚠️ <b>تم إلغاء اشتراك Premium</b>\n\n"
                     "اشتراكك Premium اتلغى. لسه تقدر تستخدم الخطة المجانية.\n\n"
                     "📩 لو عايز تجدده تواصل مع @ziadamr",
                telegram_bot=context.bot
            )
        except Exception:
            pass

    except Exception as e:
        await update.message.reply_text(f"❌ حصل خطأ: {e}")


async def resetlimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر /resetlimit — إعادة تعيين حدود الاستخدام المجاني لمستخدم
    الأدمن يقدر يرجع الحد اليومي لمستخدم مجاني خلص كوته
    الاستخدام: /resetlimit 123456789
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "🔄 <b>إعادة تعيين الحدود المجانية</b>\n\n"
            "الاستخدام: <code>/resetlimit user_id</code>\n\n"
            "💡 الأمر ده بيرجع الحد اليومي للمستخدم المجاني\n"
            "يعني لو المستخدم خلص رسائله أو PDF أو بحث — يقدر يكمل تاني\n\n"
            "⚠️ مش بيحول المستخدم Premium — بيبقى مجاني بس الحد بيرجع\n\n"
            "مثال: <code>/resetlimit 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return

    try:
        from premium import reset_user_usage, get_user_plan, get_usage, get_premium_info
        from memory import _ensure_user_in_db

        # التأكد إن المستخدم موجود
        _ensure_user_in_db(target_id)

        # معرفة الخطة الحالية
        current_info = get_premium_info(target_id)
        plan = current_info["plan"]
        
        # 🔴 فحص هل المستخدم Premium — لو آه، الريست مش هيعمل حاجة لأنه unlimited
        if current_info["is_premium"]:
            # محاولة جلب اسم المستخدم
            try:
                from memory import get_user
                user_data = get_user(target_id)
                target_name = user_data.get("name", "")
            except Exception:
                target_name = ""
            name_display = f" ({target_name})" if target_name else ""
            
            await update.message.reply_text(
                f"⚠️ <b>المستخدم ده Premium — مش محتاج ريست!</b>\n\n"
                f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
                f"⭐ الخطة: Premium\n"
                f"⏰ المتبقي: {current_info['expires_display']}\n\n"
                f"المستخدمين Premium استخدامهم غير محدود — مفيش حدود تتأثر بالريست.\n\n"
                f"لو عايز تشيل البريميوم، استخدم: <code>/revoke {target_id}</code>",
                parse_mode="HTML"
            )
            return
        
        # جلب الاستخدام الحالي قبل الريست
        old_usage = get_usage(target_id)

        # إعادة التعيين
        success = reset_user_usage(target_id)

        if success:
            # محاولة جلب اسم المستخدم
            try:
                from memory import get_user
                user_data = get_user(target_id)
                target_name = user_data.get("name", "")
            except Exception:
                target_name = ""

            name_display = f" ({target_name})" if target_name else ""
            plan_display = "⭐ Premium" if plan in ("premium", "premium_plus") else "🆓 مجاني"

            await update.message.reply_text(
                f"✅ <b>تم إعادة تعيين الحدود!</b>\n\n"
                f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
                f"📊 الخطة: {plan_display}\n\n"
                f"📊 <b>الاستخدام قبل الريست:</b>\n"
                f"→ رسائل AI: {old_usage.get('ai_messages', 0)}\n"
                f"→ تحليلات PDF: {old_usage.get('pdf_analyses', 0)}\n"
                f"→ تحليلات صور: {old_usage.get('image_analyses', 0)}\n"
                f"→ ملخصات YouTube: {old_usage.get('youtube_summaries', 0)}\n"
                f"→ عمليات بحث: {old_usage.get('searches', 0)}\n\n"
                f"🔄 كل الحدود بقت صفر — المستخدم يقدر يكمل استخدام عادي!",
                parse_mode="HTML"
            )

            # إبلاغ المستخدم (عبر المنصة الصح — تليجرام أو واتساب)
            try:
                await send_cross_platform_notification(
                    target_user_id=target_id,
                    text="🔄 <b>تم إعادة تعيين حدودك!</b>\n\n"
                         "حدودك اليومية اترجعت تاني — تقدر تكمل استخدام البوت عادي!\n\n"
                         "💬 رسائل AI: 0/20\n"
                         "📄 تحليلات PDF: 0/3\n"
                         "🖼️ تحليلات صور: 0/5\n"
                         "🎬 ملخصات YouTube: 0/3\n"
                         "🔍 عمليات بحث: 0/5",
                    telegram_bot=context.bot
                )
            except Exception as e:
                logger.info(f"Could not notify user {target_id}: {e}")

        else:
            await update.message.reply_text("❌ حصل خطأ في إعادة التعيين. جرب تاني.")

    except Exception as e:
        await update.message.reply_text(f"❌ حصل خطأ: {e}")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر /broadcast — بث رسالة لكل المشتركين
    الاستخدام: /broadcast رسالة هنا
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "📢 <b>بث رسالة</b>\n\n"
            "الاستخدام: <code>/broadcast الرسالة</code>\n"
            "مثال: <code>/broadcast تحديث جديد في البوت!</code>\n\n"
            "⚠️ الرسالة هتتبعت لكل المشتركين في الأخبار",
            parse_mode="HTML"
        )
        return

    message_text = " ".join(args)

    from memory import get_all_subscribers
    subscribers = get_all_subscribers()

    if not subscribers:
        await update.message.reply_text("❌ مفيش مشتركين حالياً.")
        return

    # تأكيد
    confirm_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ إبعت", callback_data=f"admin_broadcast_confirm"),
            InlineKeyboardButton("❌ إلغي", callback_data="admin_broadcast_cancel"),
        ],
    ])

    # حفظ الرسالة في context
    context.user_data["broadcast_message"] = message_text
    context.user_data["broadcast_count"] = len(subscribers)

    await update.message.reply_text(
        f"📢 <b>تأكيد البث</b>\n\n"
        f"👥 عدد المشتركين: {len(subscribers)}\n"
        f"📝 الرسالة:\n{message_text}\n\n"
        f"متأكد تبعته؟",
        parse_mode="HTML",
        reply_markup=confirm_keyboard
    )


async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر /userinfo — معلومات يوزر شاملة (بدون بيانات حساسة)
    
    ⚠️ البيانات الحساسة اللي مش بتتعرض:
    - محتوى المحادثات
    - ذكريات المستخدم (user_memories)
    - المفضلات التفصيلية
    - عناصر Workspace التفصيلية
    
    الاستخدام: /userinfo 123456789
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "👤 <b>معلومات مستخدم شاملة</b>\n\n"
            "الاستخدام: <code>/userinfo user_id</code>\n\n"
            "💡 الأمر ده بيرجع كل المعلومات العامة عن المستخدم:\n"
            "→ الاسم (من البروفايل + الاسم المفضل)\n"
            "→ الخطة والاشتراكات وتاريخها\n"
            "→ كم مدة على البوت وعلى الخطة\n"
            "→ إحصائيات الاستخدام\n\n"
            "🔒 <b>مش بيرجع بيانات حساسة:</b>\n"
            "→ محتوى المحادثات\n"
            "→ ذكريات المستخدم\n\n"
            "مثال: <code>/userinfo 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return

    try:
        from premium import get_user_stats
        
        stats = get_user_stats(target_id)
        
        if not stats.get("found"):
            await update.message.reply_text("❌ المستخدم ده مش موجود في قاعدة البيانات.")
            return
        
        # ═══ الأسماء ═══
        name = stats.get("name", "")
        profile_name = stats.get("profile_name", "")  # 🔴 الاسم الأصلي من البروفايل
        
        # عرض الاسم — لو فيه اسم مفضل مختلف عن اسم البروفايل، نعرض الاتين
        if name and profile_name and name != profile_name:
            name_display = f"{name} (اسم البروفايل: {profile_name})"
        elif name:
            name_display = name
        elif profile_name:
            name_display = profile_name
        else:
            name_display = "مش محدد"
        
        # ═══ معلومات أساسية ═══
        plan_display = "⭐ Premium" if stats.get("is_premium") else "🆓 Free"
        if stats.get("plan") == "premium_plus":
            plan_display = "⭐ Premium+"
        
        platform_display = "📱 تليجرام" if stats.get("platform") == "telegram" else "📱 واتساب"
        lang_display = "🇪🇬 العربية" if stats.get("language") == "ar" else "🇬🇧 English"
        
        # ═══ معلومات Premium ═══
        if stats.get("is_premium"):
            premium_section = f"""
⭐ <b>الخطة الحالية:</b> {plan_display}
📅 <b>مفعل من:</b> {stats.get('premium_since', 'مش محدد')[:10] if stats.get('premium_since') else 'مش محدد'}
⏰ <b>المتبقي:</b> {stats.get('premium_expires_display', '—')}
⏱️ <b>على الخطة دي من:</b> {stats.get('time_on_current_plan', 'مش محدد')}
🔑 <b>بواسطة:</b> {stats.get('premium_granted_by') or 'مش محدد'}"""
        else:
            premium_section = f"""
⭐ <b>الخطة الحالية:</b> {plan_display}"""
        
        # ═══ تاريخ Premium ═══
        grant_count = stats.get("premium_grant_count", 0)
        revoke_count = stats.get("premium_revoke_count", 0)
        history = stats.get("premium_history", [])
        
        premium_history_text = f"\n🔄 <b>عدد مرات الاشتراك:</b> {grant_count}"
        if revoke_count > 0:
            premium_history_text += f"\n❌ <b>عدد مرات الإلغاء:</b> {revoke_count}"
        
        if history:
            premium_history_text += "\n\n📜 <b>آخر أحداث Premium:</b>"
            for h in history[:5]:
                action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                by = h.get("granted_by", "") or ""
                by_text = f" (بواسطة: {by})" if by and by != "None" else ""
                premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"
        
        # ═══ إحصائيات الاستخدام ═══
        total = stats.get("total_usage", {})
        today = stats.get("today_usage", {})
        
        # ═══ حالة الحظر ═══
        if stats.get("banned"):
            ban_section = f"""
🚫 <b>محظور!</b>
📝 السبب: {stats.get('ban_reason', 'مش محدد')}
📅 من: {stats.get('ban_date', '')[:16] if stats.get('ban_date') else 'مش محدد'}
🔑 بواسطة: {stats.get('banned_by', '')}"""
        else:
            ban_section = ""
        
        # ═══ تحذيرات ═══
        warnings = stats.get("warning_count", 0)
        warn_section = f"\n⚠️ <b>تحذيرات:</b> {warnings}/3" if warnings > 0 else ""
        
        # ═══ أدمن ═══
        admin_section = "\n👑 <b>أدمن:</b> نعم" if stats.get("is_admin") else ""
        
        # ═══ بناء الرسالة النهائية ═══
        info = f"""👤 <b>معلومات المستخدم الشاملة</b>
━━━━━━━━━━━━━━━━━
🔒 <i>بدون بيانات حساسة — محادثات وذكريات المستخدم محمية</i>

🆔 <b>ID:</b> <code>{target_id}</code>
📝 <b>الاسم:</b> {name_display}
📱 <b>المنصة:</b> {platform_display}
🌐 <b>اللغة:</b> {lang_display}
⏱️ <b>على البوت من:</b> {stats.get('time_on_bot', 'مش محدد')}
{premium_section}
{premium_history_text}
{ban_section}{warn_section}{admin_section}

📊 <b>استخدام اليوم:</b>
→ رسائل AI: {today.get('ai_messages', 0)}
→ تحليلات PDF: {today.get('pdf_analyses', 0)}
→ تحليلات صور: {today.get('image_analyses', 0)}
→ ملخصات YouTube: {today.get('youtube_summaries', 0)}
→ عمليات بحث: {today.get('searches', 0)}

📈 <b>الإجمالي عبر الوقت:</b>
→ رسائل AI: {total.get('ai_messages', 0)}
→ تحليلات PDF: {total.get('pdf_analyses', 0)}
→ تحليلات صور: {total.get('image_analyses', 0)}
→ ملخصات YouTube: {total.get('youtube_summaries', 0)}
→ عمليات بحث: {total.get('searches', 0)}
→ بحث عميق: {total.get('deep_searches', 0)}
→ إنشاء صور: {total.get('image_generations', 0)}
→ تعديل صور: {total.get('image_edits', 0)}
📅 أيام نشاط: {total.get('active_days', 0)}

💬 <b>محادثات:</b> {stats.get('chat_count', 0)}
⚡ <b>أوامر:</b> {stats.get('commands_used', 0)}
🎯 <b>اهتمامات:</b> {', '.join(stats.get('interests', [])[:8]) if stats.get('interests') else 'لا يوجد'}

📅 <b>تاريخ التسجيل:</b> {stats.get('created_at', 'مش محدد')[:16] if stats.get('created_at') else 'مش محدد'}
📅 <b>آخر تفاعل:</b> {stats.get('last_interaction', 'مش محدد')[:16] if stats.get('last_interaction') else 'مش محدد'}
"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐ فعّل Premium" if not stats.get("is_premium") else "❌ شيل Premium",
                    callback_data=f"admin_toggle_premium_{target_id}"
                ),
            ],
            [
                InlineKeyboardButton("🔄 إعادة تعيين الحدود", callback_data=f"admin_reset_limit_{target_id}"),
            ],
        ])

        await update.message.reply_text(info, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error in userinfo_command: {e}")
        await update.message.reply_text(f"❌ حصل خطأ: {e}")


# ═══════════════════════════════════════
# معالجة أزرار الأدمن - Admin Callbacks
# ═══════════════════════════════════════

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار لوحة تحكم الأدمن"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    username = query.from_user.username or ""

    if not is_admin(user_id, username):
        await query.answer("❌ مش مسموح", show_alert=True)
        return

    data = query.data

    if data == "admin_refresh" or data == "admin_detailed_stats":
        from dashboard import format_dashboard, get_total_users, get_total_subscribers, get_total_premium, get_today_stats
        import json

        dashboard = format_dashboard("ar")

        # إحصائيات مفصلة إضافية
        try:
            stats = get_today_stats()
            total_users = get_total_users()
            total_subs = get_total_subscribers()
            total_prem = get_total_premium()

            # حساب نسب التحويل
            sub_rate = f"{(total_subs/total_users*100):.1f}%" if total_users > 0 else "0%"
            prem_rate = f"{(total_prem/total_users*100):.1f}%" if total_users > 0 else "0%"

            extra = f"""
━━━━━━━━━━━━━━━━━
📊 <b>إحصائيات مفصلة</b>

👥 <b>المستخدمين</b>
→ الإجمالي: {total_users}
→ مشتركين أخبار: {total_subs} ({sub_rate})
→ Premium: {total_prem} ({prem_rate})

📈 <b>نسب التحويل</b>
→ نسبة الاشتراك: {sub_rate}
→ نسبة Premium: {prem_rate}
→ رسائل لكل يوزر: {(stats['total_messages']/max(total_users,1)):.1f}
"""
            dashboard += extra
        except Exception as e:
            dashboard += f"\n\n⚠️ خطأ في الإحصائيات المفصلة: {e}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⭐ كل الـ Premium", callback_data="admin_list_premium"),
                InlineKeyboardButton("👥 كل المشتركين", callback_data="admin_list_subscribers"),
            ],
            [
                InlineKeyboardButton("📊 إحصائيات مفصلة", callback_data="admin_detailed_stats"),
                InlineKeyboardButton("🔄 تحديث", callback_data="admin_refresh"),
            ],
        ])

        try:
            await query.edit_message_text(dashboard, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass

    elif data == "admin_list_premium":
        try:
            from premium import _execute, _is_postgres

            ph = "%s" if _is_postgres() else "?"
            rows = _execute(
                f"SELECT user_id, plan, premium_since, granted_by FROM premium_users WHERE plan = {ph}",
                ("premium",), fetch=True
            )

            if rows:
                text = "⭐ <b>مشتركي Premium</b>\n━━━━━━━━━━━━━━━━━\n\n"
                for row in rows[:30]:  # حد أقصى 30
                    uid = row[0]
                    since = row[2] or "مش محدد"
                    granted = row[3] or "مش محدد"
                    text += f"👤 <code>{uid}</code> — من: {since[:10] if since else 'مش محدد'} — بواسطة: {granted}\n"
                if len(rows) > 30:
                    text += f"\n... و{len(rows) - 30} تانيين"
            else:
                text = "⭐ مفيش مشتركي Premium حالياً"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_refresh")],
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")

    elif data == "admin_list_subscribers":
        try:
            from memory import get_all_subscribers
            subscribers = get_all_subscribers()

            if subscribers:
                text = "👥 <b>مشتركين الأخبار</b>\n━━━━━━━━━━━━━━━━━\n\n"
                for sub in subscribers[:30]:
                    uid = sub.get("user_id", "")
                    name = sub.get("name", "")
                    lang = sub.get("language", "ar")
                    text += f"👤 <code>{uid}</code> — {name} ({lang})\n"
                if len(subscribers) > 30:
                    text += f"\n... و{len(subscribers) - 30} تانيين"
            else:
                text = "👥 مفيش مشتركين حالياً"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_refresh")],
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")

    elif data == "admin_broadcast_confirm":
        message_text = context.user_data.get("broadcast_message", "")
        if not message_text:
            await query.edit_message_text("❌ الرسالة اتلغت أو ضاعت.")
            return

        from memory import get_all_subscribers
        subscribers = get_all_subscribers()

        success = 0
        fail = 0

        status_msg = await query.edit_message_text(
            f"📢 <b>جاري البث...</b>\n\n📤 0/{len(subscribers)}",
            parse_mode="HTML"
        )

        for i, sub in enumerate(subscribers):
            try:
                await send_cross_platform_notification(
                    target_user_id=sub["user_id"],
                    text=f"📢 <b>رسالة من My Bro</b>\n\n{message_text}",
                    telegram_bot=context.bot
                )
                success += 1
            except Exception:
                fail += 1

            # تحديث كل 10 رسائل
            if (i + 1) % 10 == 0:
                try:
                    await status_msg.edit_text(
                        f"📢 <b>جاري البث...</b>\n\n📤 {i+1}/{len(subscribers)} (✅ {success} ❌ {fail})",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        await status_msg.edit_text(
            f"✅ <b>تم البث!</b>\n\n👥 المجموع: {len(subscribers)}\n✅ نجح: {success}\n❌ فشل: {fail}",
            parse_mode="HTML"
        )
        context.user_data.pop("broadcast_message", None)

    elif data == "admin_broadcast_cancel":
        context.user_data.pop("broadcast_message", None)
        await query.edit_message_text("❌ تم إلغاء البث.")

    elif data.startswith("admin_toggle_premium_"):
        target_id_str = data.replace("admin_toggle_premium_", "")
        try:
            target_id = int(target_id_str)
        except ValueError:
            await query.answer("❌ خطأ في ID", show_alert=True)
            return

        from premium import get_premium_info, grant_premium, revoke_premium

        current_info = get_premium_info(target_id)
        if current_info["is_premium"]:
            if is_admin(target_id):
                await query.answer("👑 مينفعش تشيل Premium من الأدمن!", show_alert=True)
                return
            old_expires = current_info["expires_display"]
            revoke_premium(target_id)
            await query.answer(f"❌ تم شيل Premium (كان: {old_expires})", show_alert=True)
        else:
            grant_premium(target_id, granted_by=f"admin_{user_id}", expires=None)
            await query.answer("⭐ تم تفعيل Premium مدى الحياة!", show_alert=True)

        # تحديث الرسالة
        await userinfo_callback_refresh(query, context, target_id)

    elif data.startswith("admin_reset_limit_"):
        target_id_str = data.replace("admin_reset_limit_", "")
        try:
            target_id = int(target_id_str)
        except ValueError:
            await query.answer("❌ خطأ في ID", show_alert=True)
            return

        from premium import reset_user_usage, get_usage, get_user_plan

        # جلب الاستخدام الحالي قبل الريست
        old_usage = get_usage(target_id)
        plan = get_user_plan(target_id)

        # إعادة التعيين
        success = reset_user_usage(target_id)

        if success:
            await query.answer(
                f"✅ تم إعادة تعيين الحدود! (رسائل: {old_usage.get('ai_messages', 0)}→0, PDF: {old_usage.get('pdf_analyses', 0)}→0)",
                show_alert=True
            )
            # تحديث الرسالة
            await userinfo_callback_refresh(query, context, target_id)
        else:
            await query.answer("❌ حصل خطأ في إعادة التعيين", show_alert=True)


async def userinfo_callback_refresh(query, context, target_id):
    """تحديث رسالة معلومات اليوزر بعد تغيير Premium"""
    try:
        from memory import get_user, get_interests, get_favorite_companies, get_learning_progress
        from premium import get_user_plan, get_usage

        user_data = get_user(target_id)
        plan = get_user_plan(target_id)
        usage = get_usage(target_id)
        interests = get_interests(target_id)
        companies = get_favorite_companies(target_id)
        learning = get_learning_progress(target_id)

        info = f"""👤 <b>معلومات المستخدم</b>
━━━━━━━━━━━━━━━━━

🆔 <b>ID:</b> <code>{target_id}</code>
📝 <b>الاسم:</b> {user_data.get('name', 'مش محدد')}
🌐 <b>اللغة:</b> {'العربية' if user_data.get('language') == 'ar' else 'English'}
⭐ <b>الخطة:</b> {plan.upper()}
📬 <b>مشترك أخبار:</b> {'نعم' if user_data.get('subscribed') else 'لا'}
⏰ <b>وقت الأخبار:</b> {user_data.get('news_time', '12:00')}
💬 <b>محادثات:</b> {user_data.get('chat_count', 0)}
⚡ <b>أوامر:</b> {user_data.get('commands_used', 0)}

📊 <b>استخدام اليوم:</b>
→ رسائل AI: {usage.get('ai_messages', 0)}
→ تحليلات PDF: {usage.get('pdf_analyses', 0)}
→ تحليلات صور: {usage.get('image_analyses', 0)}
→ ملخصات YouTube: {usage.get('youtube_summaries', 0)}
→ عمليات بحث: {usage.get('searches', 0)}

🎯 <b>اهتمامات:</b> {', '.join(interests[:10]) if interests else 'لا يوجد'}
🏢 <b>شركات مفضلة:</b> {', '.join(companies[:5]) if companies else 'لا يوجد'}
📚 <b>مواضيع متعلمة:</b> {len(learning)} موضوع

📅 <b>تاريخ التسجيل:</b> {user_data.get('created_at', 'مش محدد')}
📅 <b>آخر تفاعل:</b> {user_data.get('last_interaction', 'مش محدد')}
"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐ فعّل Premium" if plan != "premium" else "❌ شيل Premium",
                    callback_data=f"admin_toggle_premium_{target_id}"
                ),
            ],
            [
                InlineKeyboardButton("🔄 إعادة تعيين الحدود", callback_data=f"admin_reset_limit_{target_id}"),
            ],
        ])

        try:
            await query.edit_message_text(info, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error refreshing userinfo: {e}")


# ═══════════════════════════════════════
# دوال مساعدة للأدمن - Admin Helpers
# ═══════════════════════════════════════

def get_admin_help_text() -> str:
    """نص مساعدة أوامر الأدمن"""
    return """👑 <b>أوامر الأدمن — My Bro</b>
━━━━━━━━━━━━━━━━━

📊 <code>/admin</code> — لوحة الإحصائيات
📊 <code>/botstats</code> — إحصائيات مفصلة
👥 <code>/allusers</code> — قائمة كل المستخدمين
⭐ <code>/grant user_id</code> — تفعيل Premium مدى الحياة
⭐ <code>/grant m user_id</code> — تفعيل شهر | <code>/grant w</code> أسبوع | <code>/grant y</code> سنة
❌ <code>/revoke user_id</code> — شيل Premium
🔄 <code>/resetlimit user_id</code> — إعادة تعيين الحدود المجانية
🚫 <code>/ban user_id [سبب]</code> — حظر مستخدم
✅ <code>/unban user_id</code> — إلغاء حظر
⚠️ <code>/warn user_id [سبب]</code> — تحذير (3 تحذيرات = حظر)
📢 <code>/broadcast رسالة</code> — بث لكل المشتركين
👤 <code>/userinfo user_id</code> — معلومات يوزر شاملة (بدون بيانات حساسة)
📊 <code>/userstats user_id</code> — إحصائيات يوزر مفصلة
👑 <code>/addadmin user_id</code> — إضافة أدمن جديد
👑 <code>/removeadmin user_id</code> — شيل أدمن
👑 <code>/listadmins</code> — قائمة كل الأدمنز

💡 أنت الأدمن — مفيش أي Limits عليك!"""


def check_admin_bypass(user_id: int, username: str = None) -> bool:
    """
    فحص هل المستخدم أدمن — يتجاوز كل Limits
    يُستخدم في premium checks عشان الأدمن ميتحكمش فيه
    """
    return is_admin(user_id, username)


# ═══════════════════════════════════════
# أوامر الحظر والتحذيرات - Ban & Warn Commands
# ═══════════════════════════════════════

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /ban — حظر مستخدم"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "🚫 <b>حظر مستخدم</b>\n\nالاستخدام: <code>/ban user_id [السبب]</code>\nمثال: <code>/ban 123456789 سبام</code>",
            parse_mode="HTML"
        )
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return
    if is_admin(target_id):
        await update.message.reply_text("👑 مينفعش تحظر الأدمن!")
        return
    reason = " ".join(args[1:]) if len(args) > 1 else "حظر من الأدمن"
    from memory import ban_user
    ban_user(target_id, reason=reason, banned_by=f"admin_{user_id}")
    await update.message.reply_text(
        f"🚫 <b>تم حظر المستخدم</b>\n\n👤 ID: <code>{target_id}</code>\n📝 السبب: {reason}",
        parse_mode="HTML"
    )
    
    # 🔴 إرسال إشعار للمستخدم المستهدف
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🚫 <b>تم حظرك من استخدام البوت</b>\n📝 السبب: {reason}\n\nلو تعتقد إن ده غلطة، تواصل مع @ziadamr",
            parse_mode="HTML"
        )
    except Exception:
        pass


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /unban — إلغاء حظر"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("✅ <b>إلغاء حظر</b>\n\nالاستخدام: <code>/unban user_id</code>", parse_mode="HTML")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return
    from memory import unban_user
    unban_user(target_id)
    await update.message.reply_text(f"✅ تم إلغاء حظر المستخدم <code>{target_id}</code>", parse_mode="HTML")
    
    # 🔴 إرسال إشعار للمستخدم المستهدف
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="✅ <b>تم إلغاء الحظر!</b>\n\nتقدر تستخدم البوت تاني عادي.",
            parse_mode="HTML"
        )
    except Exception:
        pass


async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /warn — تحذير مستخدم"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "⚠️ <b>تحذير مستخدم</b>\n\nالاستخدام: <code>/warn user_id [السبب]</code>\nبعد 3 تحذيرات يتم الحظر تلقائياً",
            parse_mode="HTML"
        )
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return
    if is_admin(target_id):
        await update.message.reply_text("👑 مينفعش تحذر الأدمن!")
        return
    reason = " ".join(args[1:]) if len(args) > 1 else "تحذير من الأدمن"
    from memory import add_warning, ban_user
    count = add_warning(target_id, reason=reason, warned_by=f"admin_{user_id}")
    if count >= 3:
        ban_user(target_id, reason="حظر تلقائي بعد 3 تحذيرات", banned_by=f"admin_{user_id}")
        await update.message.reply_text(
            f"🚫 <b>تم الحظر تلقائياً!</b>\n\n👤 ID: <code>{target_id}</code>\n⚠️ وصل 3 تحذيرات\n📝 آخر سبب: {reason}",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            f"⚠️ <b>تحذير {count}/3</b>\n\n👤 ID: <code>{target_id}</code>\n📝 السبب: {reason}\n💡 بعد 3 تحذيرات يتم الحظر تلقائياً",
            parse_mode="HTML"
        )


async def allusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /allusers — قائمة كل المستخدمين"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return
    from memory import _execute
    rows = _execute(
        "SELECT user_id, name, language, subscribed, commands_used, chat_count, created_at, last_interaction FROM user_profiles ORDER BY last_interaction DESC LIMIT 50",
        fetch=True
    )
    if not rows:
        await update.message.reply_text("👥 مفيش مستخدمين حالياً.")
        return
    text = "👥 <b>كل المستخدمين</b>\n━━━━━━━━━━━━━━━━━\n\n"
    for i, r in enumerate(rows, 1):
        uid = r[0]
        name = r[1] or "مش محدد"
        lang = r[2] or "ar"
        sub = "✅" if r[3] else "❌"
        cmds = r[4] or 0
        chats = r[5] or 0
        last = (r[7] or "")[:16]
        text += f"{i}. 👤 <code>{uid}</code> — {name} ({lang}) {sub}\n   💬 {chats} محادثة | ⚡ {cmds} أمر | آخر: {last}\n"
    text += "\n━━━━━━━━━━━━━━━━━\n🤖 My Bro Admin"
    # Split if too long
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def botstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /botstats — إحصائيات البوت التفصيلية"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return
    from dashboard import format_dashboard, get_total_users, get_total_subscribers, get_total_premium, get_today_stats
    from memory import _execute, _is_postgres

    dashboard = format_dashboard("ar")

    # Additional detailed stats
    try:
        total_users = get_total_users()
        total_subs = get_total_subscribers()
        total_prem = get_total_premium()
        today = get_today_stats()

        # Active users (last 24h)
        active_24h = _execute(
            "SELECT COUNT(*) FROM user_profiles WHERE last_interaction > NOW() - INTERVAL '24 hours'" if _is_postgres() else
            "SELECT COUNT(*) FROM user_profiles WHERE last_interaction > datetime('now', '-1 day')",
            fetchone=True
        )
        active_count = active_24h[0] if active_24h else 0

        # Total conversations
        total_convos = _execute("SELECT COUNT(*) FROM conversations", fetchone=True)
        convos_count = total_convos[0] if total_convos else 0

        # Total memories
        total_mems = _execute("SELECT COUNT(*) FROM user_memories", fetchone=True)
        mems_count = total_mems[0] if total_mems else 0

        # Banned users
        banned = _execute("SELECT COUNT(*) FROM banned_users", fetchone=True)
        banned_count = banned[0] if banned else 0

        extra = f"""
━━━━━━━━━━━━━━━━━
📊 <b>إحصائيات مفصلة</b>

👥 <b>المستخدمين</b>
→ الإجمالي: {total_users}
→ مشتركين أخبار: {total_subs}
→ Premium: {total_prem}
→ نشطين آخر 24 ساعة: {active_count}
→ محظورين: {banned_count}

📈 <b>النشاط</b>
→ إجمالي المحادثات: {convos_count}
→ إجمالي الذكريات: {mems_count}

💰 <b>اليوم</b>
→ رسائل: {today['total_messages']}
→ أوامر: {today['total_commands']}
→ طلبات AI: {today['ai_requests']}
→ عمليات بحث: {today['search_requests']}
→ أخطاء: {today['total_errors']}
"""
        dashboard += extra
    except Exception as e:
        dashboard += f"\n\n⚠️ خطأ في الإحصائيات: {e}"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ كل الـ Premium", callback_data="admin_list_premium"),
            InlineKeyboardButton("👥 كل المشتركين", callback_data="admin_list_subscribers"),
        ],
        [InlineKeyboardButton("🔄 تحديث", callback_data="admin_refresh")],
    ])

    await update.message.reply_text(dashboard, parse_mode="HTML", reply_markup=keyboard)


# ═══════════════════════════════════════
# أوامر إدارة الأدمنز - Admin Management Commands
# ═══════════════════════════════════════

async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /addadmin — إضافة أدمن جديد (المالك فقط)"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "👑 <b>إضافة أدمن جديد</b>\n\n"
            "الاستخدام: <code>/addadmin user_id</code>\n"
            "مثال: <code>/addadmin 123456789</code>\n\n"
            "⚠️ الأدمن الجديد هيكون ليه نفس صلاحياتك تقريباً (ما عدا إنه يشيلك)",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return

    # منع إضافة أدمن موجود
    if is_admin(target_id):
        await update.message.reply_text("⚠️ المستخدم ده أدمن فعلاً!")
        return

    # إضافة الأدمن
    _save_admin_to_db(target_id, role="admin", added_by=f"owner_{user_id}")
    ADMIN_USER_IDS.add(target_id)

    # تفعيل Premium للأدمن الجديد
    ensure_admin_premium(target_id)

    # محاولة جلب اسم المستخدم
    try:
        from memory import get_user
        user_data = get_user(target_id)
        target_name = user_data.get("name", "")
    except Exception:
        target_name = ""

    name_display = f" ({target_name})" if target_name else ""

    await update.message.reply_text(
        f"✅ <b>تم إضافة أدمن جديد!</b>\n\n"
        f"👤 المستخدم: <code>{target_id}</code>{name_display}\n"
        f"👑 الدور: Admin\n"
        f"⭐ Premium: مفعّل تلقائياً\n"
        f"🔑 أُضيف بواسطة: @{username or 'owner'}",
        parse_mode="HTML"
    )

    # إبلاغ الأدمن الجديد
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="👑 <b>تم ترقيتك لأدمن!</b>\n\n"
                 "أنت دلوقتي أدمن في My Bro!\n"
                 "ليك صلاحيات كاملة:\n"
                 "• مفيش أي Limits عليك\n"
                 "• تفعيل Premium لأي حد\n"
                 "• حظر وتحذير المستخدمين\n"
                 "• لوحة الإحصائيات\n\n"
                 "اكتب /admin عشان تشوف لوحة التحكم",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.info(f"Could not notify new admin {target_id}: {e}")


async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /removeadmin — شيل أدمن (المالك فقط)"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "👑 <b>شيل أدمن</b>\n\n"
            "الاستخدام: <code>/removeadmin user_id</code>\n"
            "مثال: <code>/removeadmin 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return

    # منع شيل المالك
    clean_username = (username or "").lstrip('@').lower()
    if clean_username == ADMIN_TELEGRAM_USERNAME:
        # المالك يقدر يشيل أي أدمن
        pass
    elif target_id in ADMIN_USER_IDS:
        # أدمن عادي مش يقدر يشيل المالك
        await update.message.reply_text("👑 مينفعش تشيل أدمن تاني! ده المالك بس اللي يقدر.")
        return

    if not is_admin(target_id):
        await update.message.reply_text("⚠️ المستخدم ده مش أدمن أصلاً!")
        return

    # منع شيل نفسك
    if target_id == user_id:
        await update.message.reply_text("⚠️ مينفعش تشيل نفسك من الأدمن!")
        return

    _remove_admin_from_db(target_id)

    await update.message.reply_text(
        f"✅ <b>تم شيل الأدمن</b>\n\n"
        f"👤 المستخدم: <code>{target_id}</code>\n"
        f"👑 الدور الجديد: مستخدم عادي",
        parse_mode="HTML"
    )


async def listadmins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /listadmins — قائمة كل الأدمنز"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    try:
        from memory import _execute
        rows = _execute(
            "SELECT user_id, username, role, added_at, added_by FROM admin_users ORDER BY added_at",
            fetch=True
        )

        if not rows:
            text = "👑 مفيش أدمنز مسجلين في الداتابيز (فقط CHAT_ID وusername)"
        else:
            text = "👑 <b>قائمة الأدمنز</b>\n━━━━━━━━━━━━━━━━━\n\n"
            for i, row in enumerate(rows, 1):
                uid = row[0]
                uname = row[1] or ""
                role = row[2] or "admin"
                added = (row[3] or "")[:10]
                by = row[4] or "system"
                role_display = "🦁 مالك" if role == "owner" else "👑 أدمن"
                text += f"{i}. {role_display} <code>{uid}</code> @{uname}\n"
                text += f"   أُضيف: {added} — بواسطة: {by}\n"

        # إضافة المعلومة عن الـ CHAT_ID
        text += f"\n📍 CHAT_ID في البيئة: <code>{CHAT_ID or 'مش محدد'}</code>"
        text += f"\n📍 الأدمنز في الذاكرة: {len(ADMIN_USER_IDS)}"

        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ حصل خطأ: {e}")


# ═══════════════════════════════════════
# أمر إحصائيات المستخدم الشاملة - User Stats Command
# ═══════════════════════════════════════

async def userstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر /userstats — إحصائيات شاملة عن مستخدم (بدون بيانات حساسة)
    
    ⚠️ البيانات الحساسة اللي مش بتتعرض:
    - محتوى المحادثات
    - ذكريات المستخدم (user_memories)
    - المفضلات التفصيلية
    - عناصر Workspace التفصيلية
    
    الاستخدام: /userstats 123456789
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not is_admin(user_id, username):
        await update.message.reply_text("❌ هذا الأمر للمطور فقط.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "📊 <b>إحصائيات مستخدم شاملة</b>\n\n"
            "الاستخدام: <code>/userstats user_id</code>\n\n"
            "💡 الأمر ده بيرجع كل المعلومات العامة عن المستخدم:\n"
            "→ الخطة والاشتراكات\n"
            "→ تاريخ Premium (كم مرة اشترك)\n"
            "→ إحصائيات الاستخدام الإجمالي\n"
            "→ حالة الحظر والتحذيرات\n\n"
            "🔒 <b>مش بيرجع بيانات حساسة:</b>\n"
            "→ محتوى المحادثات\n"
            "→ ذكريات المستخدم\n"
            "→ المفضلات التفصيلية\n"
            "→ محتوى Workspace\n\n"
            "مثال: <code>/userstats 123456789</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id لازم يكون رقم.")
        return

    try:
        from premium import get_user_stats
        
        stats = get_user_stats(target_id)
        
        if not stats.get("found"):
            await update.message.reply_text("❌ المستخدم ده مش موجود في قاعدة البيانات.")
            return
        
        # ═══ معلومات أساسية ═══
        plan_display = "⭐ Premium" if stats.get("is_premium") else "🆓 Free"
        if stats.get("plan") == "premium_plus":
            plan_display = "⭐ Premium+"
        
        platform_display = "📱 تليجرام" if stats.get("platform") == "telegram" else "📱 واتساب"
        lang_display = "🇪🇬 العربية" if stats.get("language") == "ar" else "🇬🇧 English"
        
        # ═══ معلومات Premium ═══
        if stats.get("is_premium"):
            premium_section = f"""
⭐ <b>الخطة الحالية:</b> {plan_display}
📅 <b>مفعل من:</b> {stats.get('premium_since', 'مش محدد')[:10] if stats.get('premium_since') else 'مش محدد'}
⏰ <b>المتبقي:</b> {stats.get('premium_expires_display', '—')}
⏱️ <b>على الخطة دي من:</b> {stats.get('time_on_current_plan', 'مش محدد')}
🔑 <b>بواسطة:</b> {stats.get('premium_granted_by') or 'مش محدد'}"""
        else:
            premium_section = f"""
⭐ <b>الخطة الحالية:</b> {plan_display}"""

        # ═══ تاريخ Premium ═══
        grant_count = stats.get("premium_grant_count", 0)
        revoke_count = stats.get("premium_revoke_count", 0)
        history = stats.get("premium_history", [])
        
        premium_history_text = f"\n🔄 <b>عدد مرات الاشتراك:</b> {grant_count}"
        if revoke_count > 0:
            premium_history_text += f"\n❌ <b>عدد مرات الإلغاء:</b> {revoke_count}"
        
        if history:
            premium_history_text += "\n\n📜 <b>آخر أحداث Premium:</b>"
            for h in history[:5]:
                action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                by = h.get("granted_by", "") or ""
                by_text = f" (بواسطة: {by})" if by and by != "None" else ""
                premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"

        # ═══ إحصائيات الاستخدام الإجمالي ═══
        total = stats.get("total_usage", {})
        today = stats.get("today_usage", {})
        
        usage_section = f"""
📊 <b>إحصائيات الاستخدام:</b>

📅 <b>اليوم:</b>
→ رسائل AI: {today.get('ai_messages', 0)}
→ تحليلات PDF: {today.get('pdf_analyses', 0)}
→ تحليلات صور: {today.get('image_analyses', 0)}
→ ملخصات YouTube: {today.get('youtube_summaries', 0)}
→ عمليات بحث: {today.get('searches', 0)}

📈 <b>الإجمالي عبر الوقت:</b>
→ رسائل AI: {total.get('ai_messages', 0)}
→ تحليلات PDF: {total.get('pdf_analyses', 0)}
→ تحليلات صور: {total.get('image_analyses', 0)}
→ ملخصات YouTube: {total.get('youtube_summaries', 0)}
→ عمليات بحث: {total.get('searches', 0)}
→ بحث عميق: {total.get('deep_searches', 0)}
→ إنشاء صور: {total.get('image_generations', 0)}
→ تعديل صور: {total.get('image_edits', 0)}
📅 أيام نشاط: {total.get('active_days', 0)}"""

        # ═══ حالة الحظر ═══
        if stats.get("banned"):
            ban_section = f"""
🚫 <b>محظور!</b>
📝 السبب: {stats.get('ban_reason', 'مش محدد')}
📅 من: {stats.get('ban_date', '')[:16] if stats.get('ban_date') else 'مش محدد'}
🔑 بواسطة: {stats.get('banned_by', '')}"""
        else:
            ban_section = ""
        
        # ═══ تحذيرات ═══
        warnings = stats.get("warning_count", 0)
        warn_section = f"\n⚠️ <b>تحذيرات:</b> {warnings}/3" if warnings > 0 else ""

        # ═══ أدمن ═══
        admin_section = "\n👑 <b>أدمن:</b> نعم" if stats.get("is_admin") else ""

        # ═══ معلومات عامة ═══
        interests = stats.get("interests", [])
        companies = stats.get("favorite_companies", [])
        
        general_section = f"""
🎯 <b>اهتمامات:</b> {', '.join(interests[:8]) if interests else 'لا يوجد'}
🏢 <b>شركات مفضلة:</b> {', '.join(companies[:5]) if companies else 'لا يوجد'}
📚 <b>مواضيع متعلمة:</b> {stats.get('learning_topics_count', 0)} موضوع
⭐ <b>مفضلات:</b> {stats.get('favorites_count', 0)} عنصر
🗂️ <b>عناصر Workspace:</b> {stats.get('workspace_count', 0)} عنصر
🔔 <b>تنبيهات ذكية:</b> {stats.get('smart_alerts_count', 0)}"""

        # ═══ بناء الرسالة النهائية ═══
        info = f"""📊 <b>إحصائيات المستخدم الشاملة</b>
━━━━━━━━━━━━━━━━━
🔒 <i>بدون بيانات حساسة — محادثات وذكريات المستخدم محمية</i>

👤 <b>معلومات أساسية:</b>
🆔 <b>ID:</b> <code>{target_id}</code>
📝 <b>الاسم:</b> {stats.get('name') or 'مش محدد'}
{platform_display} | {lang_display}
📅 <b>على البوت من:</b> {stats.get('time_on_bot', 'مش محدد')} ({stats.get('days_on_bot', 0)} يوم)
📅 <b>تاريخ التسجيل:</b> {stats.get('created_at', 'مش محدد')[:16] if stats.get('created_at') else 'مش محدد'}
📅 <b>آخر تفاعل:</b> {stats.get('last_interaction', 'مش محدد')[:16] if stats.get('last_interaction') else 'مش محدد'}

💬 <b>محادثات:</b> {stats.get('chat_count', 0)}
⚡ <b>أوامر:</b> {stats.get('commands_used', 0)}
📬 <b>مشترك أخبار:</b> {'نعم ✅' if stats.get('subscribed') else 'لا ❌'}
{admin_section}
{ban_section}{warn_section}
{premium_section}
{premium_history_text}
{usage_section}
{general_section}

━━━━━━━━━━━━━━━━━
🤖 <i>My Bro — Admin User Stats</i>"""

        # Send the message (split if too long)
        if len(info) > 4000:
            from formatters import smart_split_message
            chunks = smart_split_message(info)
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML")
        else:
            await update.reply_text(info, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in userstats_command: {e}")
        await update.message.reply_text(f"❌ حصل خطأ: {e}")
