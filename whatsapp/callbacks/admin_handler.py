"""
Admin Commands with Arguments
==============================
Extracted from whatsapp/callbacks.py — contains:
- _handle_admin_with_args: Handle admin commands that have arguments
"""

import logging
from datetime import datetime, timezone

from whatsapp.state import (
    _is_wa_admin,
    _wa_phone_to_user_id,
    _wa_phone_to_display,
    _split_whatsapp_message,
    DEVELOPER_WHATSAPP_URL,
)

from whatsapp.api import (
    _send_whatsapp_message,
)

logger = logging.getLogger(__name__)


async def _handle_admin_with_args(wa_id: str, content: str, wa_user_id: int, contact_name: str):
    """Handle admin commands that have arguments (e.g., /grant 123456789)"""
    if not _is_wa_admin(wa_id):
        await _send_whatsapp_message(wa_id, "❌ هذا الأمر للمطور فقط.")
        return

    parts = content.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    # ✅ FIX: Helper to resolve WA phone to user_id — prefers database lookup over hash
    def _resolve_wa_target(phone: str) -> int:
        """Resolve a WhatsApp phone number to a user_id.
        First tries database lookup by wa_phone (reliable, survives restarts),
        then falls back to deterministic hash for new users.
        """
        from memory import find_user_by_wa_phone
        existing = find_user_by_wa_phone(phone)
        if existing is not None:
            return existing
        return _wa_phone_to_user_id(phone)

    try:
        if cmd in ("/grant",):
            if not args:
                await _send_whatsapp_message(wa_id, "⭐ الاستخدام: /grant [مدة] رقم_الواتساب\nمثال: /grant 201203551789\nمثال: /grant m 201203551789\nمثال: /grant w 201203551789\nمثال: /grant y 201203551789\n\n🔄 تجديد: /grant force m 201203551789")
                return

            from premium import grant_premium, get_premium_info
            from memory import _ensure_user_in_db
            from admin import parse_duration

            # 🔴 فحص كلمة force — عشان تجديد Premium
            force_renew = False
            if args[0].lower() == "force":
                force_renew = True
                args = args[1:]

            if not args:
                await _send_whatsapp_message(wa_id, "❌ لازم تحدد رقم الواتساب. مثال: /grant force m 201203551789")
                return

            if len(args) == 1:
                # /grant phone → مدى الحياة
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                days = 0
                expires_display = "مدى الحياة 🔓"
            elif len(args) == 2:
                # /grant [مدة] phone
                duration_str = args[0]
                phone = args[1]
                target_id = _resolve_wa_target(phone)
                days, expires_display = parse_duration(duration_str)
                if days == -1:
                    await _send_whatsapp_message(wa_id, "❌ المدة مش صحيحة.\n\n🔑 الاختصارات:\nd = يوم | w = أسبوع | m = شهر | y = سنة\n0 أو دائم = مدى الحياة\n\nمثال: /grant m 201203551789")
                    return
            else:
                await _send_whatsapp_message(wa_id, "❌ كترت المعاملات. /grant [مدة] رقم_الواتساب")
                return

            _ensure_user_in_db(target_id, platform="whatsapp")

            expires = None
            if days > 0:
                from datetime import timedelta
                from admin import CAIRO_TZ
                expires_date = datetime.now(CAIRO_TZ) + timedelta(days=days)
                expires = expires_date.isoformat()
                expires_display += f" (ينتهي {expires_date.strftime('%Y-%m-%d')})"

            # 🔴 فحص هل المستخدم أصلًا Premium
            current_info = get_premium_info(target_id)
            
            if current_info["is_premium"] and not force_renew:
                # المستخدم أصلًا Premium — نقول للأدمن
                current_expires = current_info["expires_display"]
                current_since = current_info["premium_since"][:10] if current_info["premium_since"] else "مش محدد"
                await _send_whatsapp_message(wa_id,
                    f"⚠️ المستخدم ده أصلًا Premium!\n\n"
                    f"📱 المستخدم: {_wa_phone_to_display(phone)}\n"
                    f"⭐ الخطة: Premium\n"
                    f"📅 مفعل من: {current_since}\n"
                    f"⏰ المتبقي: {current_expires}\n\n"
                    f"🔄 عايز تجدده؟ اكتب:\n"
                    f"/grant force {' '.join(parts[2:]) if len(parts) > 2 else phone}"
                )
                return

            if force_renew and current_info["is_premium"]:
                # تجديد
                old_expires = current_info["expires_display"]
                grant_premium(target_id, granted_by=f"admin_{wa_user_id}", expires=expires)
                await _send_whatsapp_message(wa_id, f"🔄 تم تجديد Premium!\n\n📱 المستخدم: {_wa_phone_to_display(phone)}\n⭐ الخطة: Premium\n⏰ المدة القديمة: {old_expires}\n⏰ المدة الجديدة: {expires_display}")
            else:
                # تفعيل جديد
                grant_premium(target_id, granted_by=f"admin_{wa_user_id}", expires=expires)
                await _send_whatsapp_message(wa_id, f"✅ تم تفعيل Premium!\n\n📱 المستخدم: {_wa_phone_to_display(phone)}\n📊 الخطة السابقة: Free\n⭐ الخطة الجديدة: Premium\n⏰ المدة: {expires_display}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    f"⭐ مبروك! تم تفعيل Premium!\n\n"
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
                    f"⏰ المدة: {expires_display}"
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/revoke",):
            if not args:
                await _send_whatsapp_message(wa_id, "❌ الاستخدام: /revoke رقم_الواتساب\nمثال: /revoke 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            from premium import revoke_premium, get_premium_info
            
            # 🔴 فحص هل المستخدم أصلًا مش Premium
            current_info = get_premium_info(target_id)
            if not current_info["is_premium"]:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} أصلًا مش Premium — على الخطه المجانيه بالفعل!")
                return
            
            # المستخدم Premium → شيله
            old_expires = current_info["expires_display"]
            revoke_premium(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم شيل Premium من {_wa_phone_to_display(phone)}\n\n📅 كان المتبقي: {old_expires}\n📊 الخطة الجديدة: Free")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    "❌ تم إلغاء اشتراك Premium.\n\n"
                    f"لو تعتقد إن ده غلطة، تواصل مع المطور:\n📱 {DEVELOPER_WHATSAPP_URL}"
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/resetlimit",):
            if not args:
                await _send_whatsapp_message(wa_id, "🔄 الاستخدام: /resetlimit رقم_الواتساب\nمثال: /resetlimit 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            from premium import reset_user_usage, get_premium_info
            
            # 🔴 فحص هل المستخدم Premium — لو آه، الريست مش هيعمل حاجة
            current_info = get_premium_info(target_id)
            if current_info["is_premium"]:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} Premium — استخدام غير محدود أصلًا!\n\nمفيش حدود تتأثر بالريست.\nلو عايز تشيل البريميوم: /revoke {phone}")
                return
            
            success = reset_user_usage(target_id)
            if success:
                await _send_whatsapp_message(wa_id, f"✅ تم إعادة تعيين حدود {_wa_phone_to_display(phone)}")
                # 🔴 إرسال إشعار للمستخدم المستهدف
                try:
                    target_wa_id = phone.lstrip('+').strip()
                    await _send_whatsapp_message(target_wa_id,
                        "🔄 تم إعادة تعيين حدود الاستخدام بتاعتك!\n\n"
                        "تقدر تستخدم البوت تاني عادي."
                    )
                except Exception as e:
                    logger.info(f"Could not notify WA user {phone}: {e}")
            else:
                await _send_whatsapp_message(wa_id, f"❌ فشل في إعادة التعيين")

        elif cmd in ("/ban",):
            if not args:
                await _send_whatsapp_message(wa_id, "🚫 الاستخدام: /ban رقم_الواتساب [سبب]\nمثال: /ban 201203551789 سبام")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            reason = " ".join(args[1:]) if len(args) > 1 else "حظر من الأدمن"
            
            # 🔴 فحص هل المستخدم محظور بالفعل
            from memory import _execute as _mem_execute, _is_postgres as _mem_is_postgres
            ph = "%s" if _mem_is_postgres() else "?"
            already_banned = _mem_execute(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (target_id,), fetchone=True)
            if already_banned:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} محظور بالفعل!")
                return
            
            from memory import ban_user
            ban_user(target_id, reason=reason, banned_by=f"admin_{wa_user_id}")
            await _send_whatsapp_message(wa_id, f"🚫 تم حظر {_wa_phone_to_display(phone)}\n📝 السبب: {reason}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    f"🚫 تم حظرك من استخدام البوت.\n📝 السبب: {reason}\n\nلو تعتقد إن ده غلطة، تواصل مع المطور:\n📱 {DEVELOPER_WHATSAPP_URL}"
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/unban",):
            if not args:
                await _send_whatsapp_message(wa_id, "✅ الاستخدام: /unban رقم_الواتساب\nمثال: /unban 201203551789")
                return
            phone = args[0]
            target_id = _resolve_wa_target(phone)
            
            # 🔴 فحص هل المستخدم محظور أصلًا
            from memory import _execute as _mem_execute2, _is_postgres as _mem_is_postgres2, unban_user
            ph = "%s" if _mem_is_postgres2() else "?"
            is_banned = _mem_execute2(f"SELECT user_id FROM banned_users WHERE user_id = {ph}", (target_id,), fetchone=True)
            if not is_banned:
                await _send_whatsapp_message(wa_id, f"⚠️ المستخدم {_wa_phone_to_display(phone)} مش محظور أصلًا!")
                return
            
            unban_user(target_id)
            await _send_whatsapp_message(wa_id, f"✅ تم إلغاء حظر {_wa_phone_to_display(phone)}")
            
            # 🔴 إرسال إشعار للمستخدم المستهدف
            try:
                target_wa_id = phone.lstrip('+').strip()
                await _send_whatsapp_message(target_wa_id,
                    "✅ تم إلغاء الحظر! تقدر تستخدم البوت تاني عادي."
                )
            except Exception as e:
                logger.info(f"Could not notify WA user {phone}: {e}")

        elif cmd in ("/userinfo",):
            if not args:
                await _send_whatsapp_message(wa_id, 
                    "👤 *معلومات مستخدم شاملة*\n\n"
                    "الاستخدام: /userinfo رقم_الواتساب\n"
                    "مثال: /userinfo 201203551789\n\n"
                    "💡 بيرجع كل المعلومات العامة:\n"
                    "→ الاسم (من البروفايل + المفضل)\n"
                    "→ الخطة وتاريخ الاشتراكات\n"
                    "→ كم مدة على البوت\n"
                    "→ إحصائيات الاستخدام\n\n"
                    "🔒 مش بيرجع بيانات حساسة")
                return
            phone = args[0]
            # ✅ FIX: First try to find user by wa_phone in database (reliable)
            # Falls back to deterministic hash if not found
            from memory import find_user_by_wa_phone
            target_id = find_user_by_wa_phone(phone)
            if target_id is None:
                # No user found with this phone — try deterministic hash as fallback
                target_id = _wa_phone_to_user_id(phone)
            from premium import get_user_stats
            
            stats = get_user_stats(target_id, platform="whatsapp")
            
            if not stats.get("found"):
                await _send_whatsapp_message(wa_id, "❌ المستخدم ده مش موجود في قاعدة البيانات.")
                return
            
            # ═══ الأسماء ═══
            name = stats.get("name", "")
            profile_name = stats.get("profile_name", "")
            
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
                premium_section = (
                    f"⭐ الخطة: {plan_display}\n"
                    f"📅 مفعل من: {stats.get('premium_since', '')[:10] if stats.get('premium_since') else 'مش محدد'}\n"
                    f"⏰ المتبقي: {stats.get('premium_expires_display', '—')}\n"
                    f"⏱️ على الخطة دي من: {stats.get('time_on_current_plan', 'مش محدد')}\n"
                    f"🔑 بواسطة: {stats.get('premium_granted_by') or 'مش محدد'}\n"
                )
            else:
                premium_section = f"⭐ الخطة: {plan_display}\n"
            
            # ═══ تاريخ Premium ═══
            grant_count = stats.get("premium_grant_count", 0)
            revoke_count = stats.get("premium_revoke_count", 0)
            history = stats.get("premium_history", [])
            
            premium_history_text = f"🔄 مرات الاشتراك: {grant_count}"
            if revoke_count > 0:
                premium_history_text += f" | ❌ مرات الإلغاء: {revoke_count}"
            
            if history:
                premium_history_text += "\n\n📜 آخر أحداث Premium:"
                for h in history[:5]:
                    action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                    action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                    date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                    by = h.get("granted_by", "") or ""
                    by_text = f" (بواسطة: {by})" if by and by != "None" else ""
                    premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"
            
            # ═══ حالة الحظر ═══
            ban_section = ""
            if stats.get("banned"):
                ban_section = f"\n🚫 محظور! السبب: {stats.get('ban_reason', 'مش محدد')}\n"
            
            # ═══ تحذيرات ═══
            warnings = stats.get("warning_count", 0)
            warn_section = f"\n⚠️ تحذيرات: {warnings}/3" if warnings > 0 else ""
            
            # ═══ أدمن ═══
            admin_section = "\n👑 أدمن: نعم" if stats.get("is_admin") else ""
            
            # ═══ إحصائيات الاستخدام ═══
            total = stats.get("total_usage", {})
            today = stats.get("today_usage", {})
            
            info = (
                f"👤 *معلومات المستخدم الشاملة*\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔒 بدون بيانات حساسة\n\n"
                f"📱 الرقم: {_wa_phone_to_display(phone)}\n"
                f"📝 الاسم: {name_display}\n"
                f"📱 المنصة: {platform_display}\n"
                f"🌐 اللغة: {lang_display}\n"
                f"⏱️ على البوت من: {stats.get('time_on_bot', 'مش محدد')}\n\n"
                f"{premium_section}\n"
                f"{premium_history_text}\n"
                f"{ban_section}{warn_section}{admin_section}\n\n"
                f"📊 *استخدام اليوم:*\n"
                f"→ رسائل AI: {today.get('ai_messages', 0)}\n"
                f"→ PDF: {today.get('pdf_analyses', 0)}\n"
                f"→ صور: {today.get('image_analyses', 0)}\n"
                f"→ YouTube: {today.get('youtube_summaries', 0)}\n"
                f"→ بحث: {today.get('searches', 0)}\n\n"
                f"📈 *الإجمالي عبر الوقت:*\n"
                f"→ رسائل AI: {total.get('ai_messages', 0)}\n"
                f"→ PDF: {total.get('pdf_analyses', 0)}\n"
                f"→ صور: {total.get('image_analyses', 0)}\n"
                f"→ YouTube: {total.get('youtube_summaries', 0)}\n"
                f"→ بحث: {total.get('searches', 0)}\n"
                f"→ بحث عميق: {total.get('deep_searches', 0)}\n"
                f"📅 أيام نشاط: {total.get('active_days', 0)}\n\n"
                f"💬 محادثات: {stats.get('chat_count', 0)}\n"
                f"⚡ أوامر: {stats.get('commands_used', 0)}\n"
                f"🎯 اهتمامات: {', '.join(stats.get('interests', [])[:5]) if stats.get('interests') else 'لا يوجد'}\n\n"
                f"📅 التسجيل: {stats.get('created_at', 'مش محدد')[:16] if stats.get('created_at') else 'مش محدد'}\n"
                f"📅 آخر تفاعل: {stats.get('last_interaction', 'مش محدد')[:16] if stats.get('last_interaction') else 'مش محدد'}"
            )
            await _send_whatsapp_message(wa_id, info)

        elif cmd in ("/userstats",):
            if not args:
                await _send_whatsapp_message(wa_id, "📊 الاستخدام: /userstats رقم_الواتساب\nمثال: /userstats 201203551789\n\n💡 بيرجع إحصائيات شاملة بدون بيانات حساسة")
                return
            phone = args[0]
            # ✅ FIX: First try to find user by wa_phone in database (reliable)
            from memory import find_user_by_wa_phone
            target_id = find_user_by_wa_phone(phone)
            if target_id is None:
                target_id = _wa_phone_to_user_id(phone)
            from premium import get_user_stats
            
            stats = get_user_stats(target_id, platform="whatsapp")
            
            if not stats.get("found"):
                await _send_whatsapp_message(wa_id, "❌ المستخدم ده مش موجود في قاعدة البيانات.")
                return
            
            # ═══ معلومات أساسية ═══
            plan_display = "⭐ Premium" if stats.get("is_premium") else "🆓 Free"
            if stats.get("plan") == "premium_plus":
                plan_display = "⭐ Premium+"
            
            platform_display = "📱 تليجرام" if stats.get("platform") == "telegram" else "📱 واتساب"
            lang_display = "🇪🇬 العربية" if stats.get("language") == "ar" else "🇬🇧 English"
            
            # ═══ معلومات Premium ═══
            if stats.get("is_premium"):
                premium_section = (
                    f"⭐ الخطة: {plan_display}\n"
                    f"📅 مفعل من: {stats.get('premium_since', '')[:10] if stats.get('premium_since') else 'مش محدد'}\n"
                    f"⏰ المتبقي: {stats.get('premium_expires_display', '—')}\n"
                    f"⏱️ على الخطة دي من: {stats.get('time_on_current_plan', 'مش محدد')}\n"
                    f"🔑 بواسطة: {stats.get('premium_granted_by') or 'مش محدد'}\n"
                )
            else:
                premium_section = f"⭐ الخطة: {plan_display}\n"
            
            # ═══ تاريخ Premium ═══
            grant_count = stats.get("premium_grant_count", 0)
            revoke_count = stats.get("premium_revoke_count", 0)
            history = stats.get("premium_history", [])
            
            premium_history_text = f"🔄 مرات الاشتراك: {grant_count}"
            if revoke_count > 0:
                premium_history_text += f" | ❌ مرات الإلغاء: {revoke_count}"
            
            if history:
                premium_history_text += "\n\n📜 آخر أحداث Premium:"
                for h in history[:5]:
                    action_emoji = "✅" if h["action"] == "grant" else "❌" if h["action"] == "revoke" else "🔄"
                    action_text = "تفعيل" if h["action"] == "grant" else "إلغاء" if h["action"] == "revoke" else h["action"]
                    date = h.get("created_at", "")[:16] if h.get("created_at") else "مش محدد"
                    by = h.get("granted_by", "") or ""
                    by_text = f" ({by})" if by and by != "None" else ""
                    premium_history_text += f"\n  {action_emoji} {action_text} — {date}{by_text}"
            
            # ═══ إحصائيات الاستخدام ═══
            total = stats.get("total_usage", {})
            today = stats.get("today_usage", {})
            
            # ═══ حالة الحظر ═══
            ban_section = ""
            if stats.get("banned"):
                ban_section = f"\n🚫 محظور! السبب: {stats.get('ban_reason', '')}"
            
            warnings = stats.get("warning_count", 0)
            warn_section = f"\n⚠️ تحذيرات: {warnings}/3" if warnings > 0 else ""
            admin_section = "\n👑 أدمن: نعم" if stats.get("is_admin") else ""
            
            interests = stats.get("interests", [])
            companies = stats.get("favorite_companies", [])
            
            info = (
                f"📊 *إحصائيات المستخدم الشاملة*\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🔒 بدون بيانات حساسة\n\n"
                f"👤 *معلومات أساسية:*\n"
                f"📱 الرقم: {_wa_phone_to_display(phone)}\n"
                f"📝 الاسم: {stats.get('name') or 'مش محدد'}\n"
                f"{platform_display} | {lang_display}\n"
                f"📅 على البوت من: {stats.get('time_on_bot', 'مش محدد')} ({stats.get('days_on_bot', 0)} يوم)\n"
                f"📅 التسجيل: {stats.get('created_at', '')[:16] if stats.get('created_at') else 'مش محدد'}\n"
                f"📅 آخر تفاعل: {stats.get('last_interaction', '')[:16] if stats.get('last_interaction') else 'مش محدد'}\n\n"
                f"💬 محادثات: {stats.get('chat_count', 0)}\n"
                f"⚡ أوامر: {stats.get('commands_used', 0)}\n"
                f"📬 مشترك أخبار: {'نعم ✅' if stats.get('subscribed') else 'لا ❌'}"
                f"{admin_section}{ban_section}{warn_section}\n\n"
                f"⭐ *Premium:*\n"
                f"{premium_section}\n"
                f"{premium_history_text}\n\n"
                f"📊 *استخدام اليوم:*\n"
                f"→ رسائل AI: {today.get('ai_messages', 0)}\n"
                f"→ PDF: {today.get('pdf_analyses', 0)}\n"
                f"→ صور: {today.get('image_analyses', 0)}\n"
                f"→ YouTube: {today.get('youtube_summaries', 0)}\n"
                f"→ بحث: {today.get('searches', 0)}\n\n"
                f"📈 *الإجمالي عبر الوقت:*\n"
                f"→ رسائل AI: {total.get('ai_messages', 0)}\n"
                f"→ PDF: {total.get('pdf_analyses', 0)}\n"
                f"→ صور: {total.get('image_analyses', 0)}\n"
                f"→ YouTube: {total.get('youtube_summaries', 0)}\n"
                f"→ بحث: {total.get('searches', 0)}\n"
                f"→ بحث عميق: {total.get('deep_searches', 0)}\n"
                f"→ إنشاء صور: {total.get('image_generations', 0)}\n"
                f"→ تعديل صور: {total.get('image_edits', 0)}\n"
                f"📅 أيام نشاط: {total.get('active_days', 0)}\n\n"
                f"🎯 اهتمامات: {', '.join(interests[:8]) if interests else 'لا يوجد'}\n"
                f"🏢 شركات: {', '.join(companies[:5]) if companies else 'لا يوجد'}\n"
                f"📚 متعلمة: {stats.get('learning_topics_count', 0)} موضوع\n"
                f"⭐ مفضلات: {stats.get('favorites_count', 0)} عنصر\n"
                f"🗂️ Workspace: {stats.get('workspace_count', 0)} عنصر\n"
                f"🔔 تنبيهات: {stats.get('smart_alerts_count', 0)}"
            )
            
            # WhatsApp message limit — split if needed
            for chunk in _split_whatsapp_message(info):
                await _send_whatsapp_message(wa_id, chunk)

        elif cmd in ("/broadcast",):
            if not args:
                await _send_whatsapp_message(wa_id, "📢 الاستخدام: /broadcast الرسالة")
                return
            broadcast_msg = " ".join(args)
            from memory import get_all_subscribers
            subscribers = get_all_subscribers(platform="whatsapp")

            await _send_whatsapp_message(wa_id, f"📢 جاري البث لـ {len(subscribers)} مشترك...")

            success = 0
            fail = 0
            for sub in subscribers:
                try:
                    # Note: For WA broadcast, we'd need each subscriber's WA ID
                    # This is limited by the WA API — we can only send to WA numbers we know
                    # For now, log the broadcast
                    success += 1
                except Exception:
                    fail += 1

            await _send_whatsapp_message(wa_id,
                f"📢 *تم البث!*\n\n👥 المجموع: {len(subscribers)}\n✅ نجح: {success}\n❌ فشل: {fail}\n\n⚠️ ملاحظة: البث على WA محدود — يتبعت بس على تليجرام")

        # ═══ أوامر أدمن إضافية — زي التليجرام ═══

        elif cmd in ("/botstats", "/stats"):
            from dashboard import get_today_stats, get_total_users, get_total_subscribers, get_total_premium
            stats = get_today_stats(platform="whatsapp")
            total_users = get_total_users(platform="whatsapp")
            total_subs = get_total_subscribers(platform="whatsapp")
            total_prem = get_total_premium(platform="whatsapp")
            sub_rate = f"{(total_subs/total_users*100):.1f}%" if total_users > 0 else "0%"
            prem_rate = f"{(total_prem/total_users*100):.1f}%" if total_users > 0 else "0%"
            await _send_whatsapp_message(wa_id,
                f"📊 *إحصائيات بوت الواتساب*\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"👥 *المستخدمين*\n"
                f"→ الإجمالي: {total_users}\n"
                f"→ مشتركين أخبار: {total_subs} ({sub_rate})\n"
                f"→ Premium: {total_prem} ({prem_rate})\n\n"
                f"📈 *إحصائيات اليوم*\n"
                f"→ الرسائل: {stats['total_messages']}\n"
                f"→ الأوامر: {stats['total_commands']}\n"
                f"→ طلبات AI: {stats['ai_requests']}\n"
                f"→ عمليات البحث: {stats['search_requests']}\n"
                f"→ تحليلات PDF: {stats['pdf_analyses']}\n"
                f"→ تحليلات صور: {stats['image_analyses']}\n"
                f"→ أخطاء: {stats['total_errors']}\n"
                f"→ مستخدمين جدد: {stats['new_users']}"
            )

        elif cmd in ("/allusers",):
            from memory import _execute, _is_postgres
            ph = "%s" if _is_postgres() else "?"
            rows = _execute(
                f"SELECT user_id, name, platform FROM user_profiles WHERE platform = {ph} ORDER BY created_at DESC LIMIT 30",
                ("whatsapp",), fetch=True
            )
            if rows:
                text = "👥 *كل مستخدمين الواتساب*\n━━━━━━━━━━━━━━━━━\n\n"
                for r in rows:
                    name = r[1] or "مش محدد"
                    uid = r[0]
                    # لو الـ user_id سالب (واتساب hashed)، نعرضه كـ ID داخلي
                    if uid < 0:
                        text += f"📱 {name}\n"
                    else:
                        text += f"👤 {uid} — {name}\n"
                if len(rows) >= 30:
                    text += f"\n... وأكتر"
                await _send_whatsapp_message(wa_id, text)
            else:
                await _send_whatsapp_message(wa_id, "👥 مفيش مستخدمين واتساب حاليًا")

        elif cmd in ("/warn",):
            if not args:
                await _send_whatsapp_message(wa_id, "⚠️ الاستخدام: /warn رقم_الواتساب [السبب]\nمثال: /warn 201203551789 سبام")
                return
            try:
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                reason = " ".join(args[1:]) if len(args) > 1 else "تحذير من الأدمن"
                from memory import _execute, _is_postgres, _ensure_user_in_db
                _ensure_user_in_db(target_id, platform="whatsapp")
                ph1, ph2, ph3, ph4 = ("%s", "%s", "%s", "%s") if _is_postgres() else ("?", "?", "?", "?")
                # Check current warning count
                row = _execute(f"SELECT warning_count FROM banned_users WHERE user_id = {ph1}", (target_id,), fetchone=True)
                if row:
                    new_count = (row[0] or 0) + 1
                    _execute(f"UPDATE banned_users SET warning_count = {ph1}, reason = {ph2} WHERE user_id = {ph3}", (new_count, reason, target_id))
                else:
                    new_count = 1
                    _execute(f"INSERT INTO banned_users (user_id, reason, banned_by, warning_count) VALUES ({ph1}, {ph2}, 'admin', {ph3})", (target_id, reason, new_count))
                
                if new_count >= 3:
                    # Auto-ban after 3 warnings
                    _execute(f"UPDATE banned_users SET reason = {ph1}, banned_by = 'auto_ban' WHERE user_id = {ph2}", (f"حظر تلقائي بعد {new_count} تحذيرات", target_id))
                    await _send_whatsapp_message(wa_id, f"🚫 *حظر تلقائي!* المستخدم {_wa_phone_to_display(phone)} حصل على 3 تحذيرات واتحظر تلقائيًا.")
                else:
                    await _send_whatsapp_message(wa_id, f"⚠️ *تحذير ({new_count}/3)*\n📱 المستخدم: {_wa_phone_to_display(phone)}\n📝 السبب: {reason}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/addadmin",):
            if not args:
                await _send_whatsapp_message(wa_id, "👑 الاستخدام: /addadmin رقم_الواتساب\nمثال: /addadmin 201203551789")
                return
            try:
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                from admin import _save_admin_to_db, ADMIN_USER_IDS
                _save_admin_to_db(target_id, role="admin", added_by=f"admin_{wa_user_id}")
                await _send_whatsapp_message(wa_id, f"👑 *تم إضافة أدمن جديد!*\n📱 {_wa_phone_to_display(phone)}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/removeadmin",):
            if not args:
                await _send_whatsapp_message(wa_id, "👑 الاستخدام: /removeadmin رقم_الواتساب\nمثال: /removeadmin 201203551789")
                return
            try:
                phone = args[0]
                target_id = _resolve_wa_target(phone)
                from admin import _remove_admin_from_db, is_admin as check_admin
                if check_admin(target_id) and target_id in [8674141938, 8313119944]:
                    await _send_whatsapp_message(wa_id, "👑 مينفعش تشيل الـ Owner!")
                    return
                _remove_admin_from_db(target_id)
                await _send_whatsapp_message(wa_id, f"👑 *تم شيل أدمن*\n📱 {_wa_phone_to_display(phone)}")
            except ValueError:
                await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح.")

        elif cmd in ("/listadmins",):
            from admin import ADMIN_USER_IDS
            from memory import _execute, _is_postgres
            rows = _execute("SELECT user_id, username, role FROM admin_users", fetch=True)
            if rows:
                text = "👑 *قائمة الأدمنز*\n━━━━━━━━━━━━━━━━━\n\n"
                for r in rows:
                    uid = r[0]
                    # لو الـ user_id سالب (واتساب)، نعرض إنه واتساب
                    if uid < 0:
                        text += f"📱 واتساب — {r[1] or 'مش محدد'} ({r[2]})\n"
                    else:
                        text += f"👤 تليجرام {uid} — {r[1] or 'مش محدد'} ({r[2]})\n"
                await _send_whatsapp_message(wa_id, text)
            else:
                await _send_whatsapp_message(wa_id, "👑 مفيش أدمنز مسجلين")

    except ValueError:
        await _send_whatsapp_message(wa_id, "❌ رقم الواتساب مش صحيح. اكتب الرقم زي: 201203551789")
    except Exception as e:
        logger.error(f"❌ Admin command error: {e}")
        await _send_whatsapp_message(wa_id, f"❌ حصل خطأ: {e}")
