"""Download handlers - Callback handlers and cookies/potoken commands.

Quality selection callback handler and /cookies, /potoken command handlers.
"""

import logging
import asyncio
import os

from telegram import Update
from telegram.ext import ContextTypes

from memory import get_language
from premium import (
    check_limit, premium_required_message,
    get_premium_keyboard,
)

from handlers.downloads.utils import (
    _retrieve_url,
    _cookies_status,
    _merge_cookies,
    _COOKIES_FILE,
)

logger = logging.getLogger(__name__)


def _get_download_with_ytdlp():
    """Lazy import to avoid circular dependency."""
    from handlers.downloads.ytdlp_core import _download_with_ytdlp
    return _download_with_ytdlp


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار اختيار الجودة"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    lang = get_language(user_id)
    
    if not check_limit(user_id, "image_gen")["allowed"]:
        feature_name = "📥 تحميل وسائط / Media Download"
        await query.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return
    
    if not data.startswith("dl_"):
        return
    
    parts = data.split("_")
    if len(parts) < 3:
        return
    
    dl_type = parts[1]
    
    if dl_type == "v":
        if len(parts) < 4: return
        quality_map = {"b": "best", "m": "medium", "l": "low"}
        quality = quality_map.get(parts[2], "best")
        url_key = parts[3]
    elif dl_type == "a":
        quality = "audio"
        url_key = parts[2]
    elif dl_type == "aq":
        # 🔴 Audio quality selection: dl_aq_{bitrate}_{url_key}
        # e.g., dl_aq_320_abc123 → audio with 320kbps bitrate
        if len(parts) < 4: return
        bitrate = parts[2]  # 320, 192, 128, 64
        quality = f"audio_{bitrate}"  # e.g., "audio_320"
        url_key = parts[3]
    else:
        return
    
    url = _retrieve_url(url_key)
    
    if not url:
        if lang == "ar":
            await query.message.edit_text("❌ انتهت صلاحية الرابط. جرب /download تاني.")
        else:
            await query.message.edit_text("❌ Link expired. Please try /download again.")
        return
    
    try:
        if lang == "ar":
            await query.message.edit_text("⏳ جاري تجهيز التحميل...")
        else:
            await query.message.edit_text("⏳ Preparing download...")
    except: pass
    
    await _get_download_with_ytdlp()(query, url, quality, lang, user_id)


# ═══════════════════════════════════════
# أمر /cookies — رفع ملف cookies.txt (كل المستخدمين)
# ═══════════════════════════════════════

async def cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /cookies — رفع ملف cookies.txt (كل المستخدمين، الأدمن يشوف تفاصيل أكتر)"""
    from admin import is_admin
    from config import CHAT_ID
    
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user else None
    lang = get_language(user_id)
    is_user_admin = is_admin(user_id, username) or str(user_id) == str(CHAT_ID)
    
    # 🔴 حذف الملف — أدمن بس
    args = " ".join(context.args) if context.args else ""
    if args.lower() in ("delete", "remove", "مسح", "حذف"):
        if not is_user_admin:
            await update.message.reply_text("❌ الأمر ده للأدمن بس." if lang == "ar" else "❌ Admin only command.")
            return
        try:
            if os.path.exists(_COOKIES_FILE):
                os.remove(_COOKIES_FILE)
                msg = "✅ تم حذف ملف الكوكيز." if lang == "ar" else "✅ Cookies file deleted."
                logger.info(f"🍪 Cookies file deleted by admin {user_id}")
            else:
                msg = "❌ ملف الكوكيز مش موجود أصلاً." if lang == "ar" else "❌ Cookies file doesn't exist."
        except Exception as e:
            msg = f"❌ فشل الحذف: {e}" if lang == "ar" else f"❌ Delete failed: {e}"
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    # ✅ للمستخدم العادي — رسالة بسيطة
    if not is_user_admin:
        if lang == "ar":
            msg = """🍪 <b>ارفع ملف الكوكيز بتاعك</b>

ابعت ملف cookies.txt من جهازك وهنسخه للبوت عشان نساعد في تحميل الفيديوهات.

💡 <b>إزاي تجيب الملف:</b>
1️⃣ افتح Chrome على الكمبيوتر
2️⃣ ثبّت إضافة "Get cookies.txt LOCALLY"
3️⃣ افتح youtube.com واعمل login
4️⃣ اضغط على الإضافة واختار "Export"
5️⃣ ابعت الملف هنا كـ document"""
        else:
            msg = """🍪 <b>Upload your cookies file</b>

Send a cookies.txt file from your device and we'll add it to the bot to help with video downloads.

💡 <b>How to get the file:</b>
1️⃣ Open Chrome on your computer
2️⃣ Install the "Get cookies.txt LOCALLY" extension
3️⃣ Open youtube.com and log in
4️⃣ Click the extension and select "Export"
5️⃣ Send the file here as a document"""
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    # 🔴 للأدمن — عرض الحالة الكاملة
    status = _cookies_status()
    
    # 🔴 حالة نظام الكوكيز — بس كوكيز مرفوعة (لا تلقائية)
    auto_rotation_status = ""
    try:
        from cookie_rotator import is_rotation_running, get_cookie_rotation_status
        rot_status = get_cookie_rotation_status()
        if is_rotation_running():
            auto_rotation_status = (
                f"\n\n🔄 <b>مراقبة الكوكيز:</b> ✅ شغال"
                f"\n⏰ آخر فحص: {rot_status.get('last_modified', 'غير معروف')}"
                f"\n🔴 لا كوكيز تلقائية — بس كوكيز مرفوعة من المستخدمين"
            )
        else:
            auto_rotation_status = "\n\n🔄 <b>مراقبة الكوكيز:</b> ❌ مش شغال"
    except ImportError:
        auto_rotation_status = ""
    except Exception:
        auto_rotation_status = ""
    
    if status.get("exists"):
        msg = f"""🍪 <b>حالة ملف الكوكيز</b>

📁 المسار: <code>{status.get('path', '')}</code>
📊 الحجم: {status.get('size_bytes', 0)} bytes
🔢 عدد الكوكيز: {status.get('total_cookies', 0)}
▶️ كوكيز YouTube: {status.get('youtube_cookies', 0)}

✅ الملف موجود وشغال!{auto_rotation_status}

💡 <b>لتجديد الملف:</b>
1️⃣ افتح Chrome على الكمبيوتر
2️⃣ ثبّت إضافة "Get cookies.txt LOCALLY"
3️⃣ افتح youtube.com واعمل login
4️⃣ اضغط على الإضافة واختار "Export"
5️⃣ ابعت الملف هنا كـ document

🗑️ لمسح الملف: <code>/cookies delete</code>"""
    else:
        msg = f"""🍪 <b>ملف الكوكيز مش موجود</b>

⚠️ بدون ملف كوكيز، YouTube ممكن يطلب sign in ويمنع التحميل.{auto_rotation_status}

💡 <b>إزاي ترفع ملف cookies.txt:</b>
1️⃣ افتح Chrome على الكمبيوتر
2️⃣ ثبّت إضافة "Get cookies.txt LOCALLY" من Chrome Web Store
3️⃣ افتح youtube.com واعمل login بحسابك
4️⃣ اضغط على الإضافة واختار "Export as cookies.txt"
5️⃣ ابعت الملف هنا كـ document (ملف)

⚡ بعد رفع الملف، التحميل من YouTube هيشتغل بشكل أفضل بكثير!
🔴 مفيش كوكيز تلقائية — بس كوكيز مرفوعة من المستخدمين!

📁 أو ارفع الملف يدوياً: <code>{_COOKIES_FILE}</code>"""
    
    await update.message.reply_text(msg, parse_mode="HTML")



async def handle_cookies_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رفع ملف cookies.txt — كل المستخدمين يقدروا يرفعوا كوكيز"""
    from admin import is_admin
    from config import CHAT_ID
    
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user else None
    lang = get_language(user_id)
    is_user_admin = is_admin(user_id, username) or str(user_id) == str(CHAT_ID)
    
    # ✅ كل المستخدمين يقدروا يرفعوا كوكيز — مفيش قيود أدمن هنا
    
    if not update.message.document:
        return
    
    doc = update.message.document
    filename = doc.file_name or ""
    
    # 🔴 بنقبل بس ملفات cookies.txt
    if not (filename.lower().endswith('.txt') and 'cookie' in filename.lower()) and filename.lower() != 'cookies.txt':
        # ممكن الملف اسمه حاجة تانية — بنشوف المحتوى
        pass  # هنفحص المحتوى بعد التحميل
    
    try:
        # تحميل الملف
        file = await asyncio.wait_for(context.bot.get_file(doc.file_id), timeout=15.0)
        file_bytes = await asyncio.wait_for(file.download_as_bytearray(), timeout=30.0)
        content = bytes(file_bytes).decode('utf-8', errors='ignore')
        
        # 🔴 فحص المحتوى — نتأكد إنه ملف كوكيز حقيقي
        is_valid = False
        has_netscape_header = '# Netscape HTTP Cookie File' in content
        has_youtube = '.youtube.com' in content or 'youtube.com' in content
        
        # لازم يكون فيه هيدر Netscape أو كوكيز YouTube
        if has_netscape_header or has_youtube:
            # بنشوف فيه سطور كوكيز فعلية (7 أعمدة مفصولة بـ tab)
            cookie_lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith('#')]
            valid_lines = [l for l in cookie_lines if len(l.split('\t')) >= 7]
            if valid_lines:
                is_valid = True
        
        if not is_valid:
            # الملف مش كوكيز صحيح
            if lang == "ar":
                await update.message.reply_text("❌ الملف ده مش ملف كوكيز صحيح. لازم يكون Netscape HTTP Cookie File وفيه كوكيز YouTube.")
            else:
                await update.message.reply_text("❌ This doesn't look like a valid cookies file. It needs to be a Netscape HTTP Cookie File with YouTube cookies.")
            return
        
        # 🔴 دمج الكوكيز مع الملف الموجود
        existing_content = ""
        if os.path.exists(_COOKIES_FILE):
            try:
                with open(_COOKIES_FILE, 'r', encoding='utf-8') as f:
                    existing_content = f.read()
            except Exception:
                existing_content = ""
        
        if existing_content.strip():
            # في ملف موجود — ندمج
            merged_content, new_added, new_yt_added = _merge_cookies(existing_content, content)
            with open(_COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write(merged_content)
            logger.info(f"🍪 Cookies merged from user {user_id}: {new_added} new cookies ({new_yt_added} YouTube)")
        else:
            # مفيش ملف موجود — نكتب مباشرة
            with open(_COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write(content)
            new_added = 0  # مش دمج
            new_yt_added = 0
            logger.info(f"🍪 Cookies file created by user {user_id}")
        
        # التحقق
        new_status = _cookies_status()
        yt_count = new_status.get('youtube_cookies', 0)
        total_count = new_status.get('total_cookies', 0)
        
        # ✅ للمستخدم العادي — رسالة بسيطة
        if not is_user_admin:
            if lang == "ar":
                msg = "✅ تم رفع ملف الكوكيز بنجاح! شكراً لمساعدتنا 🎬"
            else:
                msg = "✅ Cookies uploaded successfully! Thanks for helping 🎬"
        else:
            # 🔴 للأدمن — تفاصيل كاملة
            if lang == "ar":
                if new_added > 0:
                    msg = f"""✅ <b>تم دمج الكوكيز بنجاح!</b>

🆕 كوكيز جديدة: {new_added} ({new_yt_added} YouTube)
📊 إجمالي الكوكيز: {total_count}
▶️ كوكيز YouTube: {yt_count}
📁 المحتوى محفوظ في: <code>{_COOKIES_FILE}</code>

🎬 تحميل الفيديوهات من YouTube هيشتغل بشكل أفضل!"""
                else:
                    msg = f"""✅ <b>تم رفع ملف الكوكيز بنجاح!</b>

📊 عدد كوكيز YouTube: {yt_count}
📁 المحتوى محفوظ في: <code>{_COOKIES_FILE}</code>

🎬 دلوقتي تحميل الفيديوهات من YouTube هيشتغل بشكل أفضل!"""
            else:
                if new_added > 0:
                    msg = f"""✅ <b>Cookies merged successfully!</b>

🆕 New cookies: {new_added} ({new_yt_added} YouTube)
📊 Total cookies: {total_count}
▶️ YouTube cookies: {yt_count}
📁 Saved to: <code>{_COOKIES_FILE}</code>

🎬 YouTube downloads should work much better now!"""
                else:
                    msg = f"""✅ <b>Cookies file uploaded successfully!</b>

📊 YouTube cookies: {yt_count}
📁 Saved to: <code>{_COOKIES_FILE}</code>

🎬 YouTube downloads should work much better now!"""
        
        await update.message.reply_text(msg, parse_mode="HTML")
    
    except asyncio.TimeoutError:
        await update.message.reply_text("❌ انتهى وقت تحميل الملف. جرب تاني." if lang == "ar" else "❌ File download timed out. Try again.")
    except Exception as e:
        logger.error(f"Error handling cookies file upload: {e}")
        await update.message.reply_text(f"❌ حصل خطأ: {e}" if lang == "ar" else f"❌ Error: {e}")


# ═══════════════════════════════════════
# أمر /potoken — إدارة PO Token (أدمن بس)
# ═══════════════════════════════════════

async def potoken_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /potoken — إدارة PO Token لتخطي حظر YouTube (أدمن بس)
    
    الاستخدام:
    /potoken — عرض حالة PO Token
    /potoken set TOKEN — تعيين PO Token جديد
    /potoken clear — مسح PO Token
    """
    from admin import is_admin
    from config import CHAT_ID
    
    user_id = update.effective_user.id
    username = update.effective_user.username if update.effective_user else None
    lang = get_language(user_id)
    is_user_admin = is_admin(user_id, username) or str(user_id) == str(CHAT_ID)
    
    if not is_user_admin:
        await update.message.reply_text("❌ الأمر ده للأدمن بس." if lang == "ar" else "❌ Admin only command.")
        return
    
    args = context.args or []
    
    try:
        from po_token_manager import (
            get_po_token_status, set_po_token, clear_po_token, init_po_token
        )
    except ImportError:
        await update.message.reply_text(
            "❌ po_token_manager مش متاح." if lang == "ar" else "❌ po_token_manager not available."
        )
        return
    
    # ═══ /potoken set TOKEN ═══
    if args and args[0].lower() in ("set", "اضافة", "إضافة"):
        if len(args) < 2:
            msg = (
                "❌ اكتب الـ Token بعد الأمر.\n\n"
                "مثال: <code>/potoken set MiM2...طويل...</code>\n\n"
                "💡 إزاي تجيب PO Token:\n"
                "1️⃣ افتح youtube.com في Chrome\n"
                "2️⃣ افتح DevTools (F12) → Console\n"
                "3️⃣ اكتب: <code>document.cookie.split(';').find(c=>c.includes('po_token'))</code>\n"
                "4️⃣ أو استخدم أداة yt-dlp --extractor-args \"youtube:po_token=web+TOKEN\""
            ) if lang == "ar" else (
                "❌ Provide the token after the command.\n\n"
                "Example: <code>/potoken set MiM2...long...</code>\n\n"
                "💡 How to get PO Token:\n"
                "1️⃣ Open youtube.com in Chrome\n"
                "2️⃣ Open DevTools (F12) → Console\n"
                "3️⃣ Run: <code>document.cookie.split(';').find(c=>c.includes('po_token'))</code>\n"
                "4️⃣ Or use: yt-dlp --extractor-args \"youtube:po_token=web+TOKEN\""
            )
            await update.message.reply_text(msg, parse_mode="HTML")
            return
        
        token = " ".join(args[1:]).strip()
        # نشيل web+ prefix لو المستخدم حطه
        if token.startswith("web+"):
            token = token[4:]
        
        if len(token) < 20:
            await update.message.reply_text(
                "❌ الـ Token قصير أوي — لازم يكون أطول من كده." if lang == "ar"
                else "❌ Token too short — it should be longer."
            )
            return
        
        success = set_po_token(token, source="manual")
        if success:
            status = get_po_token_status()
            if lang == "ar":
                msg = f"""✅ <b>تم تعيين PO Token بنجاح!</b>

🔑 المعاينة: <code>{status.get('token_preview', '***')}</code>
📍 المصدر: manual
⏰ العمر: {status.get('age_hours', 0):.1f} ساعة
⏳ صالح لحد: {status.get('ttl_hours', 0):.1f} ساعة

🎬 دلوقتي لما YouTube يطلب "Sign in to confirm" → البوت هيجرب PO Token تلقائي!

⚠️ <b>ملاحظة:</b> PO Token بيفضل شغال لـ 6-12 ساعة وبعدين بيحتاج تجديد"""
            else:
                msg = f"""✅ <b>PO Token set successfully!</b>

🔑 Preview: <code>{status.get('token_preview', '***')}</code>
📍 Source: manual
⏰ Age: {status.get('age_hours', 0):.1f} hours
⏳ Valid for: {status.get('ttl_hours', 0):.1f} hours

🎬 Now when YouTube asks "Sign in to confirm" → the bot will try PO Token automatically!

⚠️ <b>Note:</b> PO Token stays valid for 6-12 hours, then needs renewal"""
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(
                "❌ فشل تعيين PO Token." if lang == "ar" else "❌ Failed to set PO Token."
            )
        return
    
    # ═══ /potoken clear ═══
    if args and args[0].lower() in ("clear", "delete", "remove", "مسح", "حذف"):
        clear_po_token()
        await update.message.reply_text(
            "✅ تم مسح PO Token." if lang == "ar" else "✅ PO Token cleared."
        )
        return
    
    # ═══ /potoken (بدون args) — عرض الحالة ═══
    status = get_po_token_status()
    
    if status.get("available"):
        if lang == "ar":
            msg = f"""🔑 <b>حالة PO Token</b>

✅ متوفر
📍 المصدر: {status.get('source', 'غير معروف')}
🔑 المعاينة: <code>{status.get('token_preview', '***')}</code>
⏰ العمر: {status.get('age_hours', 0):.1f} ساعة
⏳ صالح لحد: {status.get('ttl_hours', 0):.1f} ساعة
{'⚠️ <b>منتهي الصلاحية!</b>' if status.get('expired') else '✅ صالح'}

🔧 <b>الأوامر:</b>
➕ إضافة: <code>/potoken set TOKEN</code>
🗑️ مسح: <code>/potoken clear</code>"""
        else:
            msg = f"""🔑 <b>PO Token Status</b>

✅ Available
📍 Source: {status.get('source', 'unknown')}
🔑 Preview: <code>{status.get('token_preview', '***')}</code>
⏰ Age: {status.get('age_hours', 0):.1f} hours
⏳ Valid for: {status.get('ttl_hours', 0):.1f} hours
{'⚠️ <b>Expired!</b>' if status.get('expired') else '✅ Valid'}

🔧 <b>Commands:</b>
➕ Set: <code>/potoken set TOKEN</code>
🗑️ Clear: <code>/potoken clear</code>"""
    else:
        if lang == "ar":
            msg = """🔑 <b>PO Token — مش متوفر</b>

❌ مفيش PO Token حالياً

💡 <b>إزاي تجيب PO Token:</b>
1️⃣ افتح youtube.com في Chrome
2️⃣ افتح DevTools (F12) → Console
3️⃣ شغّل السكريبت ده:
<code>const poToken = await window.__ytplayer__.config?.args?.raw_player_response?.serviceTrackingParams?.find(p => p.key === 'qoeurl')?.params?.find(p => p.key === 'pot')?.value; console.log(poToken || 'Not found - try visiting a video page');</code>
4️⃣ انسخ الناتج وابعت هنا:
<code>/potoken set الناتج</code>

⚠️ أو استخدم المتغير البيئي: <code>PO_TOKEN=الناتج</code>

🎬 PO Token بيقدر يتخطى "Sign in to confirm you're not a bot"

🔧 <b>الأوامر:</b>
➕ إضافة: <code>/potoken set TOKEN</code>"""
        else:
            msg = """🔑 <b>PO Token — Not Available</b>

❌ No PO Token currently set

💡 <b>How to get a PO Token:</b>
1️⃣ Open youtube.com in Chrome
2️⃣ Open DevTools (F12) → Console
3️⃣ Run this script:
<code>const poToken = await window.__ytplayer__.config?.args?.raw_player_response?.serviceTrackingParams?.find(p => p.key === 'qoeurl')?.params?.find(p => p.key === 'pot')?.value; console.log(poToken || 'Not found - try visiting a video page');</code>
4️⃣ Copy the output and send:
<code>/potoken set OUTPUT</code>

⚠️ Or set environment variable: <code>PO_TOKEN=OUTPUT</code>

🎬 PO Token can bypass "Sign in to confirm you're not a bot"

🔧 <b>Commands:</b>
➕ Set: <code>/potoken set TOKEN</code>"""
    
    await update.message.reply_text(msg, parse_mode="HTML")


