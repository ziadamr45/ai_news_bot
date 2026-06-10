"""
Cookie Auto-Rotation Module 🍪🔄
تدوير تلقائي لكوكيز YouTube كل 1-2 دقيقة لتقليل الحظر

🔴 كيف بيشتغل:
1. بينشأ كوكيز زيارة حقيقية (Visitor Cookies) بشكل دوري
2. بيمر على YouTube بـ headless request وبيجيب cookies جديدة
3. بيحفظها في cookies.txt بتنسيق Netscape (اللي yt-dlp بيتفهمه)
4. بيدور على User-Agents عشان ميتبعش نمط واحد

🔴 ليه ده بيفيد:
- YouTube بيحظر الـ IPs اللي بتعمل طلبات كتير بدون كوكيز
- الكوكيز بتقول لـ YouTube "أنا زائر حقيقي مش بوت"
- تدوير الكوكيز بيمنع YouTube يكتشف إن الكوكيز ثابتة (pattern detection)
- كل 1-2 دقيقة كوكيز جديدة = كل طلب شكله كأنه من زائر مختلف

🔴 ملاحظات مهمة:
- الكوكيز دي "visitor cookies" (مش authenticated) — يعني مش محتاجة حساب
- لو في ملف cookies.txt رفعه الأدمن يدوياً (بكوكيز حقيقية)، النظام ده مش بيمسحه
- النظام بيضيف الكوكيز الجديدة ABOVE الكوكيز القديمة
- yt-dlp بياخذ أول كوكيز مطابقة من الملف
"""

import logging
import os
import random
import string
import time
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات التدوير
# ═══════════════════════════════════════

_COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

# الفترة الزمنية بين كل تدوير (ثانية) — عشوائي بين MIN و MAX
ROTATION_INTERVAL_MIN = 60    # دقيقة واحدة
ROTATION_INTERVAL_MAX = 120   # دقيقتين

# عدد الكوكيز اللي بتتولد كل مرة
COOKIES_PER_ROTATION = 3

# أقصى عدد كوكيز في الملف — لو زاد نمسح القديمة
MAX_COOKIE_ENTRIES = 50

# ═══════════════════════════════════════
# User-Agent Pool — تنويع الهوية
# ═══════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
]


def _generate_visitor_id() -> str:
    """توليد VISITOR_INFO1_LIVE cookie value — 11 حرف عشوائي"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(11))


def _generate_session_token(length: int = 24) -> str:
    """توليد session token عشوائي"""
    chars = string.ascii_letters + string.digits + '_-'
    return ''.join(random.choice(chars) for _ in range(length))


def _generate_youtube_visitor_cookies() -> list:
    """توليد مجموعة كوكيز زيارة YouTube جديدة
    
    🔴 الكوكيز دي بتشتغل كالتالي:
    - VISITOR_INFO1_LIVE: تعريف الزائر — YouTube بيستخدمه عشان يتتبع الزوار
    - CONSENT: الموافقة على سياسة الخصوصية — لازم تكون موجودة
    - GPS: الجغرافيا — YouTube بيستخدمه
    - YSC: YouTube Session Cookie — بيتولد لكل زيارة
    - PREF: التفضيلات — اللغة والمنطقة الزمنية
    
    كل كوكيزة بتبقى في تنسيق Netscape:
    domain\tinclude_subdomains\tpath\tsecure\texpiry\tname\tvalue
    """
    now = int(time.time())
    # صلاحية الكوكيز — بين 30 يوم و 90 يوم
    expiry = now + random.randint(30 * 86400, 90 * 86400)
    # صلاحية الكوكيز القصيرة — بين ساعة و 24 ساعة
    short_expiry = now + random.randint(3600, 86400)
    
    visitor_id = _generate_visitor_id()
    ysc_token = _generate_session_token(16)
    session_token = _generate_session_token(32)
    
    # اختيار عشوائي لخصائص الزائر
    languages = ["en", "en-US", "en-GB", "ar", "fr", "de", "es", "ja"]
    timezones = ["UTC", "Africa/Cairo", "America/New_York", "Europe/London", "Asia/Tokyo"]
    regions = ["US", "GB", "EG", "DE", "FR", "SA"]
    
    lang = random.choice(languages)
    tz = random.choice(timezones)
    region = random.choice(regions)
    
    cookies = [
        # VISITOR_INFO1_LIVE — أهم كوكيزة — تعريف الزائر
        f".youtube.com\tTRUE\t/\tTRUE\t{expiry}\tVISITOR_INFO1_LIVE\t{visitor_id}",
        
        # CONSENT — موافقة الخصوصية (YES تعني الموافقة)
        f".youtube.com\tTRUE\t/\tFALSE\t{expiry}\tCONSENT\tYES+cb.20210328-17-p0.en+FX+999",
        
        # GPS — الجغرافيا
        f".youtube.com\tTRUE\t/\tFALSE\t{short_expiry}\tGPS\t1",
        
        # YSC — Session Cookie
        f".youtube.com\tTRUE\t/\tTRUE\t{short_expiry}\tYSC\t{ysc_token}",
        
        # PREF — التفضيلات (اللغة والمنطقة)
        f".youtube.com\tTRUE\t/\tFALSE\t{expiry}\tPREF\thl={lang}&tz={tz.replace('/', '%2F')}&gl={region}",
        
        # VISITOR_PRIVACY_METADATA — بيانات خصوصية الزائر (جديدة من YouTube)
        f".youtube.com\tTRUE\t/\tTRUE\t{short_expiry}\tVISITOR_PRIVACY_METADATA\tCgJQ%7D",
        
        # _gcl_au — Google Conversion Label (تتبع الإعلانات)
        f".youtube.com\tTRUE\t/\tFALSE\t{short_expiry}\t_gcl_au\t{_generate_session_token(28)}",
        
        # SIDCC — Session ID Confirmation
        f".youtube.com\tTRUE\t/\tTRUE\t{short_expiry}\tSIDCC\t{_generate_session_token(40)}",
    ]
    
    return cookies


def _fetch_real_cookies_via_request() -> Optional[list]:
    """محاولة جلب كوكيز حقيقية من YouTube عن طريق HTTP request
    
    🔴 الطريقة دي بتساعد إننا نحصل على كوكيز زيارة حقيقية من YouTube نفسه
    مش مجرد كوكيز توليد — ده بيخلي الطلب يبان أكثر واقعية
    
    Returns: قائمة كوكيز في تنسيق Netscape أو None لو فشلت
    """
    try:
        import requests
        
        ua = random.choice(USER_AGENTS)
        
        # بنعمل طلب لصفحة YouTube الرئيسية عشان نحصل على كوكيز الزيارة
        response = requests.get(
            "https://www.youtube.com/",
            headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            },
            timeout=10,
            allow_redirects=True,
        )
        
        if response.status_code == 200:
            cookies = response.cookies
            if cookies:
                # تحويل الكوكيز لتنسيق Netscape
                now = int(time.time())
                netscape_cookies = []
                
                for cookie in cookies:
                    domain = cookie.domain if cookie.domain else ".youtube.com"
                    if not domain.startswith('.'):
                        domain = '.' + domain
                    
                    path = cookie.path if cookie.path else "/"
                    secure = "TRUE" if cookie.secure else "FALSE"
                    expiry = int(cookie.expires) if cookie.expires else (now + 86400)
                    name = cookie.name
                    value = cookie.value
                    
                    netscape_cookies.append(
                        f"{domain}\tTRUE\t{path}\t{secure}\t{expiry}\t{name}\t{value}"
                    )
                
                if netscape_cookies:
                    logger.info(f"🍪 Got {len(netscape_cookies)} real cookies from YouTube visit")
                    return netscape_cookies
        
        return None
        
    except Exception as e:
        logger.debug(f"🍪 Could not fetch real cookies from YouTube: {e}")
        return None


def _read_existing_admin_cookies() -> list:
    """قراءة الكوكيز الأصلية (اللي رفعها الأدمن يدوياً) من cookies.txt
    
    🔴 المبدأ: الكوكيز اللي رفعها الأدمن أغلى وأهم من الكوكيز المولّدة
    عشان كده بنحتفظ بيها دايماً وبنضيف الكوكيز الجديدة فوقها
    """
    if not os.path.exists(_COOKIES_FILE):
        return []
    
    try:
        with open(_COOKIES_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        admin_cookies = []
        for line in lines:
            line = line.strip()
            # سطور التعليقات والسطور الفاضية — نحتفظ بيها
            if not line or line.startswith('#'):
                continue
            
            # الكوكيز اللي فيها SID أو HSID أو SSID أو SAPISID — دي كوكيز حقيقية (مصرح بيها)
            # بنعتبر أي كوكيز فيها أكتر من 30 حرف في الـ value كوكيز أصلية
            parts = line.split('\t')
            if len(parts) >= 7:
                value = parts[6]
                # لو الكوكيز طويلة أو فيها tokens حقيقية — دي كوكيز أدمن
                if len(value) > 30 or any(k in parts[5].upper() for k in ['SID', 'HSID', 'SSID', 'SAPISID', 'APISID', 'LOGIN_INFO']):
                    admin_cookies.append(line)
        
        return admin_cookies
        
    except Exception as e:
        logger.warning(f"🍪 Error reading admin cookies: {e}")
        return []


def _count_cookie_lines() -> int:
    """عد سطور الكوكيز الفعلي في الملف"""
    if not os.path.exists(_COOKIES_FILE):
        return 0
    try:
        with open(_COOKIES_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    except:
        return 0


def rotate_cookies() -> dict:
    """تبديل الكوكيز — الوظيفة الرئيسية
    
    🔴 الاستراتيجية:
    1. نجرب نجيب كوكيز حقيقية من YouTube (HTTP request)
    2. لو فشلت، نولّد كوكيز زيارة واقعية
    3. نحتفظ بالكوكيز الأصلية (الأدمن) دايماً
    4. نكتب الملف الجديد
    
    Returns: dict فيه معلومات عن العملية
    """
    try:
        # 1. قراءة الكوكيز الأصلية (الأدمن)
        admin_cookies = _read_existing_admin_cookies()
        
        # 2. محاولة جلب كوكيز حقيقية
        real_cookies = _fetch_real_cookies_via_request()
        
        # 3. توليد كوكيز زيارة جديدة
        generated_cookies = []
        for _ in range(COOKIES_PER_ROTATION):
            generated_cookies.extend(_generate_youtube_visitor_cookies())
        
        # 4. بناء الملف الجديد
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        header = [
            "# Netscape HTTP Cookie File",
            "# https://curl.se/docs/http-cookies.html",
            "# This file was generated by Cookie Rotator! Do not edit manually.",
            f"# Last rotation: {now}",
            "#",
            "# 🔴 Admin cookies (SID/HSID/etc) are preserved at the top.",
            "# 🔴 Auto-generated visitor cookies are below.",
            "",
        ]
        
        # كل الكوكيز الجديدة
        new_cookies = []
        
        # كوكيز حقيقية من HTTP request (أولوية عالية)
        if real_cookies:
            new_cookies.extend(real_cookies)
        
        # كوكيز مولّدة
        new_cookies.extend(generated_cookies)
        
        # 5. تنظيف — لو عدد الكوكيز المولّدة كتير، نحتفظ بآخر N فقط
        if len(new_cookies) > MAX_COOKIE_ENTRIES:
            # نحتفظ بآخر MAX_COOKIE_ENTRIES
            new_cookies = new_cookies[-MAX_COOKIE_ENTRIES:]
        
        # 6. كتابة الملف
        all_lines = header + admin_cookies + [""] + new_cookies
        
        with open(_COOKIES_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(all_lines) + '\n')
        
        total_cookies = len(admin_cookies) + len(new_cookies)
        
        logger.info(
            f"🍪 Cookie rotation complete: "
            f"{len(admin_cookies)} admin + {len(real_cookies) or 0} real + "
            f"{len(generated_cookies)} generated = {total_cookies} total cookies"
        )
        
        return {
            "success": True,
            "admin_cookies": len(admin_cookies),
            "real_cookies": len(real_cookies) if real_cookies else 0,
            "generated_cookies": len(generated_cookies),
            "total_cookies": total_cookies,
            "timestamp": now,
        }
        
    except Exception as e:
        logger.error(f"🍪 Cookie rotation failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def get_cookie_rotation_status() -> dict:
    """حالة نظام تدوير الكوكيز — للأدمن"""
    exists = os.path.exists(_COOKIES_FILE)
    count = _count_cookie_lines() if exists else 0
    admin_cookies = _read_existing_admin_cookies() if exists else []
    
    # تاريخ آخر تعديل
    last_modified = ""
    if exists:
        try:
            mtime = os.path.getmtime(_COOKIES_FILE)
            last_modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except:
            pass
    
    return {
        "file_exists": exists,
        "file_path": _COOKIES_FILE,
        "total_cookies": count,
        "admin_cookies": len(admin_cookies),
        "auto_cookies": max(0, count - len(admin_cookies)),
        "last_modified": last_modified,
        "rotation_interval": f"{ROTATION_INTERVAL_MIN}-{ROTATION_INTERVAL_MAX}s",
    }


# ═══════════════════════════════════════
# خلفية التدوير التلقائي — Background Thread
# ═══════════════════════════════════════

_rotation_thread = None
_rotation_running = False


def _rotation_loop():
    """حلقة التدوير — بتشغل في thread منفصل"""
    global _rotation_running
    
    logger.info("🍪 Cookie rotation thread started")
    
    # أول مرة — نولّد كوكيز فوراً
    try:
        result = rotate_cookies()
        if result.get("success"):
            logger.info(f"🍪 Initial cookie rotation: {result['total_cookies']} cookies")
    except Exception as e:
        logger.warning(f"🍪 Initial cookie rotation failed: {e}")
    
    while _rotation_running:
        # ننتظر فترة عشوائية بين MIN و MAX
        wait_time = random.randint(ROTATION_INTERVAL_MIN, ROTATION_INTERVAL_MAX)
        
        # نستنى بالثواني لكن نشيك كل 5 ثواني لو محدش وقف الـ thread
        for _ in range(wait_time // 5):
            if not _rotation_running:
                break
            time.sleep(5)
        
        if not _rotation_running:
            break
        
        # تدوير الكوكيز
        try:
            result = rotate_cookies()
            if result.get("success"):
                logger.info(
                    f"🍪 Cookie rotated: {result['total_cookies']} cookies "
                    f"({result.get('real_cookies', 0)} real + {result.get('generated_cookies', 0)} generated)"
                )
            else:
                logger.warning(f"🍪 Cookie rotation failed: {result.get('error', 'unknown')}")
        except Exception as e:
            logger.warning(f"🍪 Cookie rotation error: {e}")


def start_cookie_rotation():
    """تشغيل نظام تدوير الكوكيز التلقائي
    
    🔴 بيشتغل في background thread عشان ميعطلش البوت
    الكوكيز بتتدور كل 1-2 دقيقة تلقائياً
    """
    global _rotation_thread, _rotation_running
    
    if _rotation_running:
        logger.info("🍪 Cookie rotation already running")
        return
    
    _rotation_running = True
    _rotation_thread = threading.Thread(
        target=_rotation_loop,
        name="CookieRotator",
        daemon=True,  # البيموت لو البرنامج الرئيسي مات
    )
    _rotation_thread.start()
    logger.info("🍪 Auto cookie rotation started (every 1-2 minutes)")


def stop_cookie_rotation():
    """إيقاف نظام تدوير الكوكيز"""
    global _rotation_running
    
    _rotation_running = False
    logger.info("🍪 Cookie rotation stopped")


def is_rotation_running() -> bool:
    """هل نظام التدوير شغال؟"""
    return _rotation_running
