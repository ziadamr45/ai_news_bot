"""
Media Download Handler
📥 /download — تحميل فيديوهات/صور/صوت من أي منصة اجتماعية
يدعم: YouTube, Facebook, Instagram, TikTok, Twitter/X, Telegram, Threads, وغيرها

🔴 FIX v3: إعادة كتابة كاملة عشان نحل مشكلة YouTube bot detection نهائياً
  - ✅ دعم ملف cookies.txt — الحل الأقوى والأضمن لتخطي bot detection
  - ✅ YouTube visitor cookies في HTTP headers (VISITOR_INFO1_LIVE, CONSENT)
  - ✅ Fallback chain أقوى: mweb → android → ios → tv → default (5 محاولات)
  - ✅ تحديث yt-dlp تلقائي عند تشغيل البوت
  - ✅ أمر /cookies لكل المستخدمين عشان يرفعوا ملف cookies.txt (الأدمن يشوف تفاصيل أكتر)
  - ✅ رسائل خطأ أوضح مع نصائح حقيقية
  - ✅ كشف ffmpeg تلقائي وتعديل التنسيقات حسب التوفر
  - ✅ Logging مفصل عشان نقدر ن debugging
"""

import logging
import asyncio
import io
import os
import re
import hashlib
import tempfile
import shutil
import time
import subprocess
import random
import string

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from memory import get_language, increment_command_count
from premium import (
    check_limit, increment_usage, premium_required_message,
    get_premium_keyboard,
)
from dashboard import track_event
from handlers.dedup import _is_duplicate_update

from content_safety import (
    check_query_safety,
    comprehensive_media_safety_check,
    get_block_message,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# 🔴 Helper: Audio Quality Detection
# quality = "audio" → default audio (192kbps)
# quality = "audio_320", "audio_192", "audio_128", "audio_64" → audio with specific bitrate
# ═══════════════════════════════════════

def _is_audio_quality(quality: str) -> bool:
    """هل الجودة دي صوت بس (مش فيديو)"""
    return quality == "audio" or quality.startswith("audio_")

def _get_audio_bitrate(quality: str) -> int:
    """استخراج الـ bitrate من جودة الصوت — 192 كـ default"""
    if quality.startswith("audio_"):
        try:
            return int(quality.split("_")[1])
        except (ValueError, IndexError):
            return 192
    return 192  # default for plain "audio"


def _ensure_audio_only(file_path: str, bitrate: int = 192) -> str:
    """تأكد إن الملف صوت بس — لو فيه فيديو، استخرج الصوت بـ ffmpeg
    
    🔴 المشكلة: بعض طرق التحميل (Cobalt, Invidious, yt-dlp fallback)
    بترجع ملف فيديو حتى لو طلبنا صوت. الدالة دي بتتأكد إن الملف صوت بس.
    
    🔴 FIX v6: إضافة طريقة تانية لاستخراج الصوت لو الطريقة الأولى فشلت
    
    Returns:
        مسار الملف الصوتي (ممكن نفس الملف لو كان صوت أصلاً، أو ملف جديد MP3)
    """
    if not os.path.exists(file_path):
        return file_path
    
    # 🔴 Step 1: فحص الملف بـ ffprobe
    has_video = False
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_type',
             '-of', 'csv=p=0', file_path],
            capture_output=True, timeout=10, text=True
        )
        if probe.returncode == 0 and probe.stdout.strip():
            has_video = 'video' in probe.stdout.strip().lower()
    except Exception:
        # لو ffprobe فشل، نتاكد من الامتداد
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ('.mp4', '.mkv', '.avi', '.webm', '.mov', '.flv'):
            has_video = True
    
    if not has_video:
        # ✅ الملف صوت بس — خلاص
        return file_path
    
    # 🔴 Step 2: الملف فيه فيديو — استخرج الصوت بـ ffmpeg
    logger.info(f"🎵 Audio fix: File has video stream, extracting audio only...")
    
    audio_path = file_path + "_audio.mp3"
    try:
        extract_result = subprocess.run(
            ['ffmpeg', '-i', file_path,
             '-vn',  # لا فيديو
             '-acodec', 'libmp3lame',
             '-ab', f'{bitrate}k',
             '-ar', '44100',
             '-ac', '2',
             '-y', audio_path],
            capture_output=True, timeout=120
        )
        
        if extract_result.returncode == 0 and os.path.exists(audio_path):
            audio_size = os.path.getsize(audio_path)
            if audio_size > 1000:
                # ✅ الاستخراج نجح — نحذف الملف القديم
                try: os.remove(file_path)
                except: pass
                logger.info(f"🎵 Audio fix: Extracted audio ({audio_size // 1024}KB)")
                return audio_path
            else:
                try: os.remove(audio_path)
                except: pass
    except subprocess.TimeoutExpired:
        try: os.remove(audio_path)
        except: pass
        logger.warning("🎵 Audio fix: ffmpeg timed out")
    except Exception as e:
        try:
            if os.path.exists(audio_path): os.remove(audio_path)
        except: pass
        logger.warning(f"🎵 Audio fix: ffmpeg error: {e}")
    
    # 🔴 FIX v6: محاولة تانية بـ ffmpeg بطريقة مختلفة
    # الطريقة الأولى ممكن تفشل لو الملف مش standard format
    audio_path2 = file_path + "_audio2.mp3"
    try:
        # بنستخدم -map 0:a عشان نختار الـ audio stream الأول بس
        extract_result2 = subprocess.run(
            ['ffmpeg', '-i', file_path,
             '-map', '0:a',  # audio stream بس
             '-c:a', 'libmp3lame',
             '-b:a', f'{bitrate}k',
             '-ar', '44100',
             '-ac', '2',
             '-y', audio_path2],
            capture_output=True, timeout=120
        )
        
        if extract_result2.returncode == 0 and os.path.exists(audio_path2):
            audio_size2 = os.path.getsize(audio_path2)
            if audio_size2 > 1000:
                # ✅ الاستخراج التاني نجح
                try: os.remove(file_path)
                except: pass
                logger.info(f"🎵 Audio fix v2: Extracted audio ({audio_size2 // 1024}KB)")
                return audio_path2
            else:
                try: os.remove(audio_path2)
                except: pass
    except subprocess.TimeoutExpired:
        try: os.remove(audio_path2)
        except: pass
        logger.warning("🎵 Audio fix v2: ffmpeg timed out")
    except Exception as e:
        try:
            if os.path.exists(audio_path2): os.remove(audio_path2)
        except: pass
        logger.warning(f"🎵 Audio fix v2: ffmpeg error: {e}")
    
    # 🔴 Fallback: لو كل المحاولات فشلت، نرجع الملف الأصلي
    # (التليجرام هيحاول يتعامل معاه كصوت)
    logger.warning("🎵 Audio fix: Could not extract audio, sending original file")
    return file_path


async def _send_telegram_audio(message, file_path: str, title: str, size_str: str, 
                                lang: str, method_name: str = "", bitrate: int = 192):
    """إرسال ملف صوتي للتليجرام — مع التأكد إن الملف فعلاً صوت مش فيديو
    
    🔴 المشكلة: بعض طرق التحميل بترجع ملف فيديو حتى لو طلبنا صوت
    الدالة دي بتتأكد إن الملف صوت بس قبل الإرسال
    
    Returns: True لو الإرسال نجح، False لو فشل
    """
    # 🔴 Step 1: تأكد إن الملف صوت بس
    file_path = _ensure_audio_only(file_path, bitrate)
    
    if not os.path.exists(file_path):
        return False
    
    filename = os.path.basename(file_path)
    # لو الامتداد مش .mp3، غيّره
    if not filename.lower().endswith('.mp3'):
        filename = filename.rsplit('.', 1)[0] + '.mp3'
    
    method_tag = f" | {method_name}" if method_name else ""
    caption = f"📥 {'تم تحميل الصوت!' if lang == 'ar' else 'Audio downloaded!'}\n🎵 {title[:200]}\n📁 {size_str}{method_tag}"
    
    try:
        with open(file_path, 'rb') as f:
            await message.reply_audio(
                audio=f, filename=filename,
                caption=caption,
                parse_mode="HTML",
            )
        return True
    except Exception as send_err:
        logger.warning(f"⚠️ Audio send failed: {send_err}")
        return False


# ═══════════════════════════════════════
# ملف Cookies — الحل الأقوى لتخطي Bot Detection
# ═══════════════════════════════════════

_COOKIES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt")


def _get_cookies_file() -> str:
    """التحقق من وجود ملف cookies.txt وإرجاع المسار لو موجود"""
    if os.path.exists(_COOKIES_FILE):
        # نتأكد إن الملف مش فاضي
        try:
            with open(_COOKIES_FILE, 'r') as f:
                content = f.read().strip()
                if content and len(content) > 50:  # ملف صالح فيه كوكيز
                    return _COOKIES_FILE
        except Exception:
            pass
    return ""


def _cookies_status() -> dict:
    """حالة ملف الكوكيز — للأدمن يعرف إيه اللي شغال"""
    path = _get_cookies_file()
    if not path:
        return {"exists": False, "path": _COOKIES_FILE}
    try:
        size = os.path.getsize(path)
        with open(path, 'r') as f:
            lines = f.readlines()
        # عدد سطور الكوكيز الفعلي (مش تعليقات ولا سطور فاضية)
        cookie_lines = [l for l in lines if l.strip() and not l.strip().startswith('#')]
        # نبحث عن كوكيز YouTube
        yt_cookies = [l for l in cookie_lines if 'youtube.com' in l.lower()]
        return {
            "exists": True,
            "path": path,
            "size_bytes": size,
            "total_cookies": len(cookie_lines),
            "youtube_cookies": len(yt_cookies),
        }
    except Exception as e:
        return {"exists": True, "path": path, "error": str(e)}


# ═══════════════════════════════════════
# كشف الروابط - URL Detection
# ═══════════════════════════════════════

URL_PATTERNS = {
    "youtube": re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube\.com/shorts)/', re.IGNORECASE),
    "facebook": re.compile(r'(https?://)?(www\.)?(facebook\.com|fb\.watch|m\.facebook\.com)/', re.IGNORECASE),
    "instagram": re.compile(r'(https?://)?(www\.)?(instagram\.com|instagr\.am)/', re.IGNORECASE),
    "tiktok": re.compile(r'(https?://)?(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/', re.IGNORECASE),
    "twitter": re.compile(r'(https?://)?(www\.)?(twitter\.com|x\.com|t\.co)/', re.IGNORECASE),
    "telegram": re.compile(r'(https?://)?(t\.me|telegram\.me|telegram\.org)/', re.IGNORECASE),
    "threads": re.compile(r'(https?://)?(www\.)?threads\.(net|com)/', re.IGNORECASE),
    "reddit": re.compile(r'(https?://)?(www\.)?(reddit\.com|redd\.it)/', re.IGNORECASE),
    "pinterest": re.compile(r'(https?://)?(www\.)?pinterest\.(com|co)/', re.IGNORECASE),
    "vimeo": re.compile(r'(https?://)?(www\.)?vimeo\.com/', re.IGNORECASE),
    "dailymotion": re.compile(r'(https?://)?(www\.)?dailymotion\.com/', re.IGNORECASE),
    "twitch": re.compile(r'(https?://)?(www\.)?(twitch\.tv|clips\.twitch\.tv)/', re.IGNORECASE),
    "snapchat": re.compile(r'(https?://)?(www\.)?(snapchat\.com|story\.snapchat\.com)/', re.IGNORECASE),
}

GENERAL_URL_PATTERN = re.compile(r'https?://[^\s<>\"]+', re.IGNORECASE)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma', '.opus'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.m4v'}

# User-Agent عشان المنصات مش تبلوكنا
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def _detect_platform(url: str) -> str:
    """كشف المنصة من الرابط"""
    for platform, pattern in URL_PATTERNS.items():
        if pattern.search(url):
            return platform
    return "unknown"


def _is_direct_media_url(url: str) -> str:
    """كشف هل الرابط مباشر لصورة أو صوت"""
    from urllib.parse import urlparse
    parsed = urlparse(url.lower())
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in IMAGE_EXTENSIONS: return "image"
    if ext in AUDIO_EXTENSIONS: return "audio"
    if ext in VIDEO_EXTENSIONS: return "video"
    return ""


def _extract_url(text: str) -> str:
    """استخراج أول رابط من النص"""
    match = GENERAL_URL_PATTERN.search(text)
    return match.group(0) if match else ""


# ═══════════════════════════════════════
# تحميل Threads — الحل النهائي v3
# ═══════════════════════════════════════
#
# 🔴 ليه Threads صعب؟
# 1. yt-dlp مش بيدعم threads.com/threads.net (مفيش extractor — open issue من 2023)
# 2. Cobalt مش بيدعم Threads (بيدعم Instagram بس مش Threads)
# 3. الـ ?__a=1 مش شغالة لـ Threads (شغالة لـ Instagram بس)
# 4. الـ og:meta tags مش فيها media URLs (Threads SPA مش server-rendered)
# 5. Official Threads API للنشر بس — مش بينزل محتوى الناس التانية
#
# ✅ الحل: Threads بيحط بيانات البوست في <script type="application/json" data-sjs>
#    دي Server-Side Rendering data فيها video_versions و image_versions2
#    روابط CDN على fbcdn.net — نفس سيستم Instagram
#
# ✅ Fallback Chain:
# 1. data-sjs JSON parsing — استخراج من script tags (الأضمن)
# 2. GraphQL API — طلب مباشر من threads.net/api/graphql
# 3. RapidAPI — خدمة خارجية كـ fallback أخير

_THREADS_URL_PATTERN = re.compile(r'(https?://)?(www\.)?threads\.(net|com)/', re.IGNORECASE)


def _is_threads_url(url: str) -> bool:
    """كشف هل الرابط من Threads"""
    return bool(_THREADS_URL_PATTERN.search(url))


def _find_thread_items(obj, depth=0, max_depth=25):
    """بحث recursive في JSON عشان نلاقي thread_items أو containing_thread
    
    Threads بيحط بيانات البوست في هيكل متداخل عميق:
    - require > [...] > [__bbox, {result: {data: {containing_thread: {thread_items}}}}]
    - أو: thread_items مباشرة
    """
    if depth > max_depth or obj is None:
        return None
    
    if isinstance(obj, dict):
        # 🔴 الأولوية: containing_thread (البوست الرئيسي)
        if "containing_thread" in obj:
            ct = obj["containing_thread"]
            if isinstance(ct, dict) and "thread_items" in ct:
                return ct["thread_items"]
        
        # thread_items مباشرة
        if "thread_items" in obj:
            return obj["thread_items"]
        
        # search في القيم
        for v in obj.values():
            result = _find_thread_items(v, depth + 1, max_depth)
            if result is not None:
                return result
    
    elif isinstance(obj, list):
        for item in obj:
            result = _find_thread_items(item, depth + 1, max_depth)
            if result is not None:
                return result
    
    return None


def _parse_threads_post(post: dict) -> dict | None:
    """استخراج بيانات الميديا من post object واحد
    
    الهيكل:
    - video_versions: [{url, width, height}, ...] — فيديو بجودات مختلفة
    - image_versions2.candidates: [{url, width, height}, ...] — صورة بأحجام مختلفة
    - carousel_media: [...] — ألبوم (صور/فيديوهات متعددة)
    - caption.text — النص
    - user.username — اسم المستخدم
    """
    if not isinstance(post, dict):
        return None
    
    result = {
        "video_url": None,
        "image_url": None,
        "title": "Threads Post",
        "username": "",
        "is_carousel": False,
        "carousel": [],
    }
    
    # 🔴 فيديو — نختار أعلى جودة (أول عنصر)
    video_versions = post.get("video_versions", [])
    if video_versions and isinstance(video_versions, list):
        # أول عنصر = أعلى جودة
        best = video_versions[0] if isinstance(video_versions[0], dict) else {}
        result["video_url"] = best.get("url")
        if result["video_url"]:
            result["video_url"] = result["video_url"].replace("\\u0026", "&").replace("\\/", "/")
    
    # 🔴 صورة — نختار أكبر حجم
    if not result["video_url"]:
        img_v2 = post.get("image_versions2", {})
        if isinstance(img_v2, dict):
            candidates = img_v2.get("candidates", [])
            if candidates and isinstance(candidates, list):
                best_img = candidates[0] if isinstance(candidates[0], dict) else {}
                result["image_url"] = best_img.get("url")
                if result["image_url"]:
                    result["image_url"] = result["image_url"].replace("\\u0026", "&").replace("\\/", "/")
    
    # 🔴 ألبوم (carousel) — لو فيه صور/فيديوهات متعددة
    carousel = post.get("carousel_media", [])
    if carousel and isinstance(carousel, list):
        result["is_carousel"] = True
        for media in carousel:
            if not isinstance(media, dict):
                continue
            # فيديو في الألبوم
            cv = media.get("video_versions", [])
            if cv and isinstance(cv, list):
                best_c = cv[0] if isinstance(cv[0], dict) else {}
                c_url = best_c.get("url", "").replace("\\u0026", "&").replace("\\/", "/")
                if c_url:
                    result["carousel"].append({"url": c_url, "is_video": True})
                    continue
            # صورة في الألبوم
            ci = media.get("image_versions2", {})
            if isinstance(ci, dict):
                cc = ci.get("candidates", [])
                if cc and isinstance(cc, list):
                    best_ci = cc[0] if isinstance(cc[0], dict) else {}
                    c_url = best_ci.get("url", "").replace("\\u0026", "&").replace("\\/", "/")
                    if c_url:
                        result["carousel"].append({"url": c_url, "is_video": False})
    
    # 🔴 عنوان / نص
    caption = post.get("caption")
    if isinstance(caption, dict):
        result["title"] = caption.get("text", "Threads Post")[:200]
    elif isinstance(caption, str):
        result["title"] = caption[:200]
    
    # 🔴 اسم المستخدم
    user = post.get("user", {})
    if isinstance(user, dict):
        result["username"] = user.get("username", "")
    
    # لو فيه بيانات مفيدة
    if result["video_url"] or result["image_url"] or result["carousel"]:
        return result
    
    return None


async def _threads_playwright_download(url: str, tmpdir: str, quality: str = "best") -> dict | None:
    """تحميل فيديو/صورة من Threads باستخدام Playwright (headless browser)
    
    🔴 ده الحل الأضمن عشان:
    - yt-dlp مش بيدعم Threads (مفيش extractor)
    - الـ HTML مش فيه video data (SPA — client-rendered)
    - GraphQL بيرجع null بدون session cookie
    - Playwright بيرندر الصفحة بالكامل ويسحب رابط الفيديو من الـ <video> tag
    
    Returns: dict فيه {success, file_path, title, is_video, file_size} أو None
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("🧵 Threads: Playwright not installed, skipping headless browser method")
        return None
    
    # 🔴 حوّل threads.com → threads.net (Playwright بيتعامل مع الـ redirect صح)
    normalized_url = url
    if 'threads.com' in normalized_url:
        normalized_url = normalized_url.replace('threads.com', 'threads.net')
    
    # 🔴 شيل الـ tracking parameters زي ?xmt=
    clean_url = re.sub(r'\?xmt=.*$', '', normalized_url)
    clean_url = re.sub(r'\?utm_.*$', '', clean_url)
    # شيل أي query params مش لازمة
    if '?' in clean_url:
        base_url = clean_url.split('?')[0]
        # احتفظ بـ post ID بس
        clean_url = base_url
    
    logger.info(f"🧵 Threads: Trying Playwright headless browser for {clean_url[:80]}")
    
    try:
        async with async_playwright() as p:
            # 🔴 Launch headless Chromium
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 720},
                locale='en-US',
            )
            
            page = await context.new_page()
            
            try:
                # 🔴 Navigate to the Threads post
                await page.goto(clean_url, wait_until='networkidle', timeout=30000)
                
                # 🔴 استنى شوية عشان الفيديو يتحمل
                await page.wait_for_timeout(3000)
                
                # 🔴 استخرج رابط الفيديو من الـ <video> tag
                video_url = await page.evaluate('''
                    () => {
                        const video = document.querySelector('video');
                        if (video) {
                            return video.src || video.currentSrc || 
                                   (video.querySelector('source') ? video.querySelector('source').src : null);
                        }
                        return null;
                    }
                ''')
                
                # 🔴 لو ملقيناش video.src، نجرب نلاقيه في الـ network requests
                if not video_url:
                    # نجرب نلاقي رابط الفيديو من الـ performance entries
                    video_url = await page.evaluate('''
                        () => {
                            const entries = performance.getEntriesByType('resource');
                            for (const entry of entries) {
                                if (entry.name && entry.name.includes('cdninstagram.com') && 
                                    (entry.name.includes('.mp4') || entry.name.includes('video'))) {
                                    return entry.name;
                                }
                            }
                            return null;
                        }
                    ''')
                
                # 🔴 لو لسه ملقيناش، نجرب نضغط على الفيديو عشان يشتغل
                if not video_url:
                    try:
                        play_button = await page.query_selector('[data-pressable-container="true"]')
                        if play_button:
                            await play_button.click()
                            await page.wait_for_timeout(2000)
                            
                            video_url = await page.evaluate('''
                                () => {
                                    const video = document.querySelector('video');
                                    if (video) {
                                        return video.src || video.currentSrc;
                                    }
                                    return null;
                                }
                            ''')
                    except Exception:
                        pass
                
                # 🔴 استخرج عنوان البوست
                title = await page.evaluate('''
                    () => {
                        // جرّب selector مختلفين للعنوان
                        const selectors = [
                            'div[data-pressable-container="true"] span',
                            'span.x1lliihq',
                            'div[role="main"] span',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim().length > 5) {
                                return el.textContent.trim().substring(0, 200);
                            }
                        }
                        return document.title || 'Threads Post';
                    }
                ''')
                
                # 🔴 لو ملقيناش فيديو، نجرب نلاقي صورة
                image_url = None
                if not video_url:
                    image_url = await page.evaluate('''
                        () => {
                            const img = document.querySelector('article img[src*="fbcdn"]') ||
                                       document.querySelector('article img[src*="cdninstagram"]');
                            if (img) {
                                return img.src;
                            }
                            return null;
                        }
                    ''')
                
                await browser.close()
                
            except Exception as nav_err:
                await browser.close()
                logger.warning(f"🧵 Threads: Playwright navigation error: {nav_err}")
                return None
        
        # 🔴 الحمل الميديا اللي لقيناها
        if video_url:
            logger.info(f"🧵 Threads: Playwright found video URL: {video_url[:100]}...")
            
            import aiohttp
            file_path = os.path.join(tmpdir, "threads_video.mp4")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    video_url,
                    headers={'Referer': 'https://www.threads.net/', 'User-Agent': 'Mozilla/5.0'},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"🧵 Threads: Video download failed with status {resp.status}")
                        return None
                    
                    file_size = 0
                    with open(file_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                            file_size += len(chunk)
                    
                    if file_size < 1000:
                        try: os.remove(file_path)
                        except: pass
                        logger.warning(f"🧵 Threads: Downloaded file too small ({file_size} bytes)")
                        return None
            
            return {
                "success": True,
                "file_path": file_path,
                "file_size": file_size,
                "title": title or "Threads Post",
                "is_video": True,
                "method": "playwright",
            }
        
        elif image_url:
            logger.info(f"🧵 Threads: Playwright found image URL: {image_url[:100]}...")
            
            import aiohttp
            file_path = os.path.join(tmpdir, "threads_image.jpg")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    image_url,
                    headers={'Referer': 'https://www.threads.net/', 'User-Agent': 'Mozilla/5.0'},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"🧵 Threads: Image download failed with status {resp.status}")
                        return None
                    
                    file_size = 0
                    with open(file_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                            file_size += len(chunk)
                    
                    if file_size < 500:
                        try: os.remove(file_path)
                        except: pass
                        return None
            
            return {
                "success": True,
                "file_path": file_path,
                "file_size": file_size,
                "title": title or "Threads Post",
                "is_video": False,
                "method": "playwright",
            }
        
        else:
            logger.warning("🧵 Threads: Playwright could not find any media on the page")
            return None
    
    except asyncio.TimeoutError:
        logger.warning("🧵 Threads: Playwright timed out")
        return None
    except Exception as e:
        logger.warning(f"🧵 Threads: Playwright error: {e}")
        return None


async def _download_threads_media(url: str, tmpdir: str, quality: str = "best") -> dict | None:
    """تحميل فيديو/صورة من Threads — الحل النهائي v5
    
    🔴 الترتيب (محدث 2025-06):
    0. Playwright headless browser — الأضمن (بيرندر الصفحة ويسحب الفيديو)
    1. RapidAPI — سريع لو المفتاح متاح
    2. data-sjs JSON parsing — استخراج من <script data-sjs> tags في HTML
       ⚠️ ملاحظة: Threads بيبقي video_versions=null في الـ HTML دلوقتي!
       بس image_versions2 لسه شغال → بنستخدمه للصور
    3. GraphQL API — طلب مباشر من threads.com/api/graphql
    4. Cobalt API — خدمة مفتوحة المصدر كـ fallback
    
    🔴 تغييرات v5:
    - إضافة Playwright كطريقة أولى (الأضمن — الـ SPA بيتعمل render كامل)
    - شيل الـ tracking parameters (?xmt=, ?utm_) من الروابط
    - لا fallback لـ yt-dlp (مش بيدعم Threads)
    
    Returns: dict فيه {success, file_path, title, is_video, file_size} أو None
    """
    import aiohttp
    import json as _json
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
    }
    
    # 🔴 FIX v5: شيل الـ tracking parameters (?xmt=, ?utm_) من الروابط
    clean_url = re.sub(r'\?xmt=.*$', '', url)
    clean_url = re.sub(r'\?utm_.*$', '', clean_url)
    if '?' in clean_url:
        base = clean_url.split('?')[0]
        clean_url = base
    
    # 🔴 FIX v4: threads.net بيعمل redirect لـ threads.com دلوقتي
    # نوحد الرابط — كلاهما يقبلوا threads.com و threads.net
    # بنحتفظ بالرابط الأصلي وبنجرب الاتنين لو الاول فشل
    normalized_url = clean_url
    # حوّل threads.com → threads.net للتوافق (الاتنين بيرجعوا نفس البيانات)
    # بس threads.net أضمن عشان الـ redirect بيتعامل معاه صح
    if 'threads.com' in normalized_url:
        normalized_url = normalized_url.replace('threads.com', 'threads.net')
    
    # 🔴 FIX v4: بنجرب الاتنين threads.net و threads.com لو الاول فشل
    urls_to_try = [normalized_url]
    if 'threads.net' in normalized_url:
        urls_to_try.append(normalized_url.replace('threads.net', 'threads.com'))
    elif 'threads.com' in normalized_url:
        urls_to_try.append(normalized_url.replace('threads.com', 'threads.net'))
    
    # ═══════════════════════════════════════
    # الطريقة 0: Playwright headless browser — الأضمن!
    # 🔴 بيرندر الصفحة بالكامل ويسحب رابط الفيديو من <video> tag
    # ═══════════════════════════════════════
    try:
        pw_result = await _threads_playwright_download(url, tmpdir, quality)
        if pw_result:
            logger.info(f"🧵 Threads: Playwright succeeded! ({pw_result.get('method', 'playwright')})")
            return pw_result
        else:
            logger.warning("🧵 Threads: Playwright failed, trying other methods...")
    except Exception as e:
        logger.warning(f"🧵 Threads: Playwright error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 1: RapidAPI — سريع لو المفتاح متاح
    # ═══════════════════════════════════════
    try:
        from config import RAPIDAPI_KEY
        
        if RAPIDAPI_KEY:
            logger.info(f"🧵 Threads: Trying RapidAPI first (most reliable for video) for {url[:80]}")
            
            rapidapi_result = await _threads_rapidapi_download(url, tmpdir, headers, quality)
            if rapidapi_result:
                rapidapi_result["method"] = "rapidapi"
                return rapidapi_result
            else:
                logger.warning("🧵 Threads: RapidAPI failed, trying other methods...")
        else:
            logger.info("🧵 Threads: No RAPIDAPI_KEY configured, skipping RapidAPI")
    
    except Exception as e:
        logger.warning(f"🧵 Threads: RapidAPI error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 1: data-sjs JSON Parsing
    # 🔴 ملاحظة: video_versions بيبقي null في الـ HTML دلوقتي!
    # بس image_versions2 لسه شغال → بنستخدمه للصور
    # ═══════════════════════════════════════
    html_data = None  # بنخزن الـ HTML عشان نستخدمه في GraphQL
    for attempt_url in urls_to_try:
        try:
            logger.info(f"🧵 Threads: Trying data-sjs parsing for {attempt_url[:80]}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(attempt_url, headers=headers, 
                                      timeout=aiohttp.ClientTimeout(total=30),
                                      allow_redirects=True) as resp:
                    final_url = str(resp.url)
                    
                    if resp.status != 200:
                        logger.warning(f"🧵 Threads: Page returned status {resp.status}")
                        continue
                    
                    html = await resp.text()
                    
                    # 🔴 FIX: حتى لو الـ redirect راح لصفحة error،
                    # Threads بيبعت البيانات في الـ HTML أصلاً!
                    # صفحة error=? بتحتوي على الـ data-sjs scripts بالفيديو
                    # لازم نحاول parse في كل الحالات
                    
                    if html and len(html) > 500:
                        html_data = html  # خزن للـ GraphQL
                        
                        # 🔴 نبحث عن <script type="application/json" data-sjs>
                        script_pattern = r'<script[^>]*type="application/json"[^>]*data-sjs[^>]*>(.*?)</script>'
                        scripts = re.findall(script_pattern, html, re.DOTALL | re.IGNORECASE)
                        
                        logger.info(f"🧵 Threads: Found {len(scripts)} data-sjs script tags")
                        
                        for i, script_content in enumerate(scripts):
                            if '"ScheduledServerJS"' not in script_content and 'thread_items' not in script_content:
                                continue
                            
                            try:
                                data = _json.loads(script_content)
                            except _json.JSONDecodeError:
                                continue
                            
                            # 🔴 بحث recursive عن thread_items
                            thread_items = _find_thread_items(data)
                            
                            if thread_items and isinstance(thread_items, list):
                                logger.info(f"🧵 Threads: Found thread_items with {len(thread_items)} items")
                                
                                for item in thread_items:
                                    if not isinstance(item, dict):
                                        continue
                                    
                                    post = item.get("post", item)
                                    parsed = _parse_threads_post(post)
                                    if parsed:
                                        # 🔴 FIX v4: لو video_url موجود (مش null) → نحمل
                                        # لو image_url بس → نحمل الصورة
                                        # لو الاتنين null → نكمل للطريقة التالية
                                        has_video = bool(parsed.get('video_url'))
                                        has_image = bool(parsed.get('image_url'))
                                        has_carousel = len(parsed.get('carousel', [])) > 0
                                        
                                        logger.info(f"🧵 Threads: Parsed post — video={has_video} image={has_image} carousel={has_carousel}")
                                        
                                        if has_video or has_image or has_carousel:
                                            result = await _threads_download_media(parsed, tmpdir, headers, quality)
                                            if result:
                                                result["method"] = "data_sjs"
                                                return result
                            
                            logger.warning(f"🧵 Threads: Script #{i} had no usable media (video_versions is null)")
            
            # لو وصلنا هنا → data-sjs مفيش فيديو → نكمل
            break  # مفيش داعي نجرب الـ URL التاني
            
        except asyncio.TimeoutError:
            logger.warning("🧵 Threads: data-sjs request timed out")
        except Exception as e:
            logger.warning(f"🧵 Threads: data-sjs parsing error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 2: GraphQL API — طلب مباشر
    # 🔴 FIX v4: doc_ids محدثة + بنستخدم threads.com بدل threads.net
    # ═══════════════════════════════════════
    try:
        logger.info(f"🧵 Threads: Trying GraphQL API for {url[:80]}")
        
        # استخراج post shortcode من الرابط
        post_code = None
        match = re.search(r'/post/([A-Za-z0-9_-]+)', url)
        if not match:
            match = re.search(r'/t/([A-Za-z0-9_-]+)', url)
        if match:
            post_code = match.group(1)
        
        if post_code:
            # 🔴 FIX v4: نستخرج LSD token من الـ HTML اللي حملناه
            lsd_token = ''
            if html_data:
                lsd_match = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', html_data)
                if lsd_match:
                    lsd_token = lsd_match.group(1)
            
            graphql_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'x-ig-app-id': '238260118697367',
                'x-fb-lsd': lsd_token,
                'content-type': 'application/x-www-form-urlencoded',
                'Accept': '*/*',
                'Origin': 'https://www.threads.net',
                'Referer': url,
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
            }
            
            async with aiohttp.ClientSession() as session:
                # 🔴 FIX v4: doc_ids محدثة + بنجرب الاتنين threads.net و threads.com
                # doc_id القديم 5587632691339264 بيرجع data=null
                # بنجرب doc_ids جديدة من الـ JS bundles
                doc_ids = [
                    '5587632691339264',  # القديم (ممكن يشتغل لو الـ variables صح)
                    '27448316234780989',  # BarcelonaLightboxDialogRootViewerQuery
                    '27125403363779788',  # BarcelonaLightboxDialogRootQuery
                ]
                
                for doc_id in doc_ids:
                    try:
                        payload = {
                            'lsd': lsd_token,
                            'variables': _json.dumps({"postID": post_code}),
                            'doc_id': doc_id,
                        }
                        
                        for api_origin in ['https://www.threads.net', 'https://www.threads.com']:
                            try:
                                async with session.post(
                                    f'{api_origin}/api/graphql',
                                    headers=graphql_headers,
                                    data=payload,
                                    timeout=aiohttp.ClientTimeout(total=15)
                                ) as resp:
                                    if resp.status != 200:
                                        continue
                                    try:
                                        gql_data = await resp.json()
                                        text_str = _json.dumps(gql_data)
                                        
                                        # 🔴 لو فيه errors → جرب doc_id التالي
                                        if 'errors' in gql_data:
                                            err_msg = gql_data['errors'][0].get('message', '')[:60]
                                            logger.debug(f"🧵 Threads: GraphQL doc_id {doc_id} @ {api_origin}: {err_msg}")
                                            continue
                                        
                                        # 🔴 لو data=null → جرب doc_id التاني
                                        if gql_data.get('data', {}).get('data') is None:
                                            continue
                                        
                                        thread_items = _find_thread_items(gql_data)
                                        
                                        if thread_items and isinstance(thread_items, list):
                                            for item in thread_items:
                                                if not isinstance(item, dict):
                                                    continue
                                                post = item.get("post", item)
                                                parsed = _parse_threads_post(post)
                                                if parsed and (parsed.get('video_url') or parsed.get('image_url')):
                                                    logger.info(f"🧵 Threads: GraphQL found media!")
                                                    result = await _threads_download_media(parsed, tmpdir, headers, quality)
                                                    if result:
                                                        result["method"] = "graphql"
                                                        return result
                                    except:
                                        pass
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"🧵 Threads: GraphQL doc_id {doc_id} failed: {e}")
        else:
            logger.warning("🧵 Threads: Could not extract post code from URL for GraphQL")
    
    except Exception as e:
        logger.warning(f"🧵 Threads: GraphQL error: {e}")
    
    # ═══════════════════════════════════════
    # الطريقة 3: Cobalt API — خدمة مفتوحة المصدر
    # 🔴 Cobalt بيدعم Threads وبيشتغل من غير API key
    # ═══════════════════════════════════════
    try:
        cobalt_result = await _threads_cobalt_download(url, tmpdir, headers, quality)
        if cobalt_result:
            cobalt_result["method"] = "cobalt"
            return cobalt_result
    except Exception as e:
        logger.debug(f"🧵 Threads: Cobalt error: {e}")
    
    logger.warning(f"🧵 Threads: All methods failed for {url[:80]}")
    logger.warning("🧵 Threads: NOTE — Threads changed their API and video URLs are no longer in HTML. RapidAPI key is recommended.")
    return None


async def _threads_cobalt_download(url: str, tmpdir: str, headers: dict, quality: str = "best") -> dict | None:
    """تحميل من Threads عبر Cobalt API — خدمة مفتوحة المصدر
    
    Cobalt بيدعم Threads وبيقدر يجيب روابط الفيديو اللي مش موجودة في الـ HTML
    
    🔴 ملاحظة: Cobalt API instances بتتغير، بنجرب أكتر من واحد
    """
    import aiohttp
    
    # 🔴 Cobalt API instances (مفتوحة المصدر)
    cobalt_instances = [
        'https://api.cobalt.tools',
        'https://cobalt-api.kwiatekmiki.com',
    ]
    
    for api_url in cobalt_instances:
        try:
            api_headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
            payload = {
                'url': url,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    headers=api_headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        continue
                    
                    data = await resp.json()
                    status = data.get('status', '')
                    
                    if status == 'redirect' or status == 'tunnel':
                        # 🔴 رابط التحميل المباشر
                        download_url = data.get('url', '')
                        if download_url:
                            logger.info(f"🧵 Threads: Cobalt got download URL from {api_url}")
                            
                            # تحديد نوع الملف
                            is_video = '.mp4' in download_url or 'video' in data.get('filename', '')
                            ext = "mp4" if is_video else "jpg"
                            file_path = os.path.join(tmpdir, f"threads_cobalt.{ext}")
                            timeout = 120 if is_video else 60
                            
                            dl_headers = dict(headers)
                            dl_headers['Referer'] = 'https://www.threads.net/'
                            
                            async with session.get(download_url, headers=dl_headers,
                                                  timeout=aiohttp.ClientTimeout(total=timeout)) as dl_resp:
                                if dl_resp.status != 200:
                                    continue
                                
                                file_size = 0
                                with open(file_path, 'wb') as f:
                                    async for chunk in dl_resp.content.iter_chunked(8192):
                                        f.write(chunk)
                                        file_size += len(chunk)
                                
                                if file_size < 1000:
                                    try: os.remove(file_path)
                                    except: pass
                                    continue
                            
                            return {
                                "success": True,
                                "file_path": file_path,
                                "file_size": file_size,
                                "title": "Threads Post",
                                "is_video": is_video,
                            }
                    
                    elif status == 'picker':
                        # 🔴 عندنا اختيارات (carousel) → نحمل أول واحد
                        picker = data.get('picker', [])
                        if picker and isinstance(picker, list):
                            first = picker[0]
                            download_url = first.get('url', '')
                            if download_url:
                                is_video = first.get('type', '') == 'video'
                                ext = "mp4" if is_video else "jpg"
                                file_path = os.path.join(tmpdir, f"threads_cobalt.{ext}")
                                
                                async with session.get(download_url, headers={'Referer': 'https://www.threads.net/'},
                                                      timeout=aiohttp.ClientTimeout(total=120)) as dl_resp:
                                    if dl_resp.status != 200:
                                        continue
                                    file_size = 0
                                    with open(file_path, 'wb') as f:
                                        async for chunk in dl_resp.content.iter_chunked(8192):
                                            f.write(chunk)
                                            file_size += len(chunk)
                                
                                if file_size < 1000:
                                    try: os.remove(file_path)
                                    except: pass
                                    continue
                                
                                return {
                                    "success": True,
                                    "file_path": file_path,
                                    "file_size": file_size,
                                    "title": "Threads Post",
                                    "is_video": is_video,
                                }
                    
                    elif status == 'error':
                        logger.debug(f"🧵 Threads: Cobalt error: {data.get('error', {}).get('code', 'unknown')}")
                    
        except asyncio.TimeoutError:
            logger.debug(f"🧵 Threads: Cobalt {api_url} timed out")
        except Exception as e:
            logger.debug(f"🧵 Threads: Cobalt {api_url} error: {e}")
    
    return None


async def _threads_download_media(parsed: dict, tmpdir: str, headers: dict, quality: str = "best") -> dict | None:
    """تحميل الميديا من parsed Threads post data
    
    بيتعامل مع: فيديو واحد، صورة واحدة، أو ألبوم (carousel)
    """
    import aiohttp
    
    username = parsed.get("username", "")
    title = parsed.get("title", "Threads Post")
    if username and title == "Threads Post":
        title = f"@{username} on Threads"
    
    # 🔴 أولوية: فيديو > صورة > أول عنصر في الألبوم
    media_url = None
    is_video = False
    
    if parsed.get("video_url"):
        media_url = parsed["video_url"]
        is_video = True
    elif parsed.get("image_url"):
        media_url = parsed["image_url"]
        is_video = False
    elif parsed.get("carousel") and len(parsed["carousel"]) > 0:
        first = parsed["carousel"][0]
        media_url = first.get("url")
        is_video = first.get("is_video", False)
    
    if not media_url:
        return None
    
    # 🔴 لو الجودة مش best وفيه فيديو، بنحاول نختار الجودة المناسبة
    if is_video and quality != "best" and parsed.get("video_url"):
        # video_versions مرتبة من أعلى جودة لأقلها
        # لو المستخدم طلب medium أو low، مش لازم نعمل حاجة لأننا بنحمل أعلى جودة بس
        pass
    
    try:
        if is_video:
            logger.info(f"🧵 Threads: Downloading video from {media_url[:100]}...")
            ext = "mp4"
            file_path = os.path.join(tmpdir, f"threads_video.{ext}")
            timeout = 120
        else:
            logger.info(f"🧵 Threads: Downloading image from {media_url[:100]}...")
            ext = "jpg"
            file_path = os.path.join(tmpdir, f"threads_image.{ext}")
            timeout = 60
        
        dl_headers = dict(headers)
        dl_headers['Referer'] = 'https://www.threads.net/'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url, headers=dl_headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    logger.warning(f"🧵 Threads: Download failed with status {resp.status}")
                    return None
                
                file_size = 0
                with open(file_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
                        file_size += len(chunk)
                
                if file_size < 1000:
                    logger.warning(f"🧵 Threads: File too small ({file_size} bytes) — probably error page")
                    try: os.remove(file_path)
                    except: pass
                    return None
        
        return {
            "success": True,
            "file_path": file_path,
            "file_size": file_size,
            "title": title,
            "is_video": is_video,
        }
    
    except asyncio.TimeoutError:
        logger.warning("🧵 Threads: Download timed out")
        return None
    except Exception as e:
        logger.warning(f"🧵 Threads: Download error: {e}")
        return None


async def _threads_rapidapi_download(url: str, tmpdir: str, headers: dict, quality: str = "best") -> dict | None:
    """تحميل من Threads عبر RapidAPI — fallback أخير
    
    Endpoint: POST https://threads-downloader.p.rapidapi.com/v1/threads/download
    Body: {"url": "https://www.threads.net/@user/post/CODE"}
    
    Response expected:
    - success: true/false
    - data.medias[] — قائمة بروابط التحميل
    - data.medias[].url — رابط الميديا
    - data.medias[].type — "video" أو "image"
    - data.caption — نص البوست
    """
    import aiohttp
    import json as _json
    
    try:
        from config import RAPIDAPI_KEY
        
        api_url = "https://threads-downloader.p.rapidapi.com/v1/threads/download"
        
        api_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": "threads-downloader.p.rapidapi.com",
        }
        
        payload = {"url": url}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=api_headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    resp_text = await resp.text()
                    logger.warning(f"🧵 Threads: RapidAPI returned status {resp.status}: {resp_text[:200]}")
                    return None
                
                data = await resp.json()
                
                # 🔴 نتأكد إن الـ API رجع success
                if not data.get("success", True):
                    logger.warning(f"🧵 Threads: RapidAPI error: {data.get('message', 'Unknown error')}")
                    return None
                
                # 🔴 استخراج بيانات الميديا من الرد
                # الهيكل الممكن:
                # 1. data.medias[] — قائمة بروابط التحميل
                # 2. data.video_url / data.image_url — رابط واحد
                # 3. data.download_url — رابط واحد
                download_url = None
                is_video = True
                title = "Threads Post"
                
                inner = data.get("data", data)
                
                # 🔴 الطريقة 1: medias array (الأحدث)
                medias = inner.get("medias", [])
                if isinstance(medias, list) and len(medias) > 0:
                    first_media = medias[0] if isinstance(medias[0], dict) else {}
                    download_url = first_media.get("url") or first_media.get("download_url")
                    media_type = first_media.get("type", "").lower()
                    is_video = media_type == "video" or first_media.get("is_video", True)
                    logger.info(f"🧵 Threads: RapidAPI medias[0] type={media_type}")
                
                # 🔴 الطريقة 2: video_url / image_url مباشرة
                if not download_url:
                    download_url = (
                        inner.get("video_url") or
                        inner.get("download_url") or
                        inner.get("url")
                    )
                    if not download_url:
                        download_url = inner.get("image_url") or inner.get("thumbnail_url")
                        if download_url:
                            is_video = False
                
                # 🔴 الطريقة 3: video_urls array
                if not download_url:
                    video_urls = inner.get("video_urls", [])
                    if isinstance(video_urls, list) and len(video_urls) > 0:
                        first = video_urls[0]
                        download_url = first.get("url") if isinstance(first, dict) else first
                
                # 🔴 العنوان
                title = inner.get("caption") or inner.get("title") or inner.get("text") or "Threads Post"
                
                if not download_url:
                    logger.warning(f"🧵 Threads: RapidAPI returned no download URL. Response: {str(data)[:300]}")
                    return None
                
                logger.info(f"🧵 Threads: RapidAPI got download URL — is_video={is_video}")
                
                # 🔴 تحميل الملف
                dl_headers = dict(headers)
                dl_headers['Referer'] = 'https://www.threads.net/'
                
                if is_video:
                    file_path = os.path.join(tmpdir, "threads_video.mp4")
                    timeout = 120
                else:
                    file_path = os.path.join(tmpdir, "threads_image.jpg")
                    timeout = 60
                
                async with session.get(download_url, headers=dl_headers, timeout=aiohttp.ClientTimeout(total=timeout)) as dl_resp:
                    if dl_resp.status != 200:
                        logger.warning(f"🧵 Threads: RapidAPI download failed with status {dl_resp.status}")
                        return None
                    
                    file_size = 0
                    with open(file_path, 'wb') as f:
                        async for chunk in dl_resp.content.iter_chunked(8192):
                            f.write(chunk)
                            file_size += len(chunk)
                    
                    if file_size < 1000:
                        logger.warning(f"🧵 Threads: RapidAPI file too small ({file_size} bytes)")
                        try: os.remove(file_path)
                        except: pass
                        return None
                
                return {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "title": title,
                    "is_video": is_video,
                }
    
    except asyncio.TimeoutError:
        logger.warning("🧵 Threads: RapidAPI timed out")
        return None
    except Exception as e:
        logger.warning(f"🧵 Threads: RapidAPI error: {e}")
        return None


# ═══════════════════════════════════════
# كشف ffmpeg - FFmpeg Availability Check
# ═══════════════════════════════════════

_FFMPEG_AVAILABLE = None

def _is_ffmpeg_available() -> bool:
    """كشف هل ffmpeg متاح على النظام — نتأكد مرة واحدة بس"""
    global _FFMPEG_AVAILABLE
    if _FFMPEG_AVAILABLE is None:
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True, timeout=5
            )
            _FFMPEG_AVAILABLE = result.returncode == 0
        except Exception:
            _FFMPEG_AVAILABLE = False
        logger.info(f"🔧 FFmpeg available: {_FFMPEG_AVAILABLE}")
    return _FFMPEG_AVAILABLE


def _log_ytdlp_version():
    """تسجيل نسخة yt-dlp عشان نعرف لو محتاجة تحديث"""
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
        logger.info(f"📦 yt-dlp version: {version}")
        return version
    except Exception:
        try:
            result = subprocess.run(
                ['yt-dlp', '--version'],
                capture_output=True, timeout=5, text=True
            )
            logger.info(f"📦 yt-dlp CLI version: {result.stdout.strip()}")
            return result.stdout.strip()
        except Exception:
            logger.warning("📦 yt-dlp version could not be determined")
            return "unknown"


# ═══════════════════════════════════════
# 🔴 yt-dlp Auto-Update System v2
# - يتحدث تلقائياً كل ساعة
# - يتحدث فوراً لو YouTube رفض التحميل (bot detection)
# - يتحدث عند تشغيل البوت
# - بيستخدم --break-system-packages عشان Railway
# ═══════════════════════════════════════

_ytdlp_last_update_time = 0        # آخر مرة اتحديث فيها
_YTDLP_UPDATE_INTERVAL = 3600      # كل ساعة (3600 ثانية)
_ytdlp_updating = False            # منع تحديثات متزامنة


def _do_ytdlp_update(reason: str = "scheduled") -> bool:
    """تحديث yt-dlp — يرجع True لو اتحديث فعلاً"""
    global _ytdlp_last_update_time, _ytdlp_updating
    
    if _ytdlp_updating:
        logger.info(f"📦 yt-dlp update already in progress, skipping ({reason})")
        return False
    
    _ytdlp_updating = True
    try:
        import yt_dlp
        current_version = getattr(yt_dlp.version, '__version__', '0')
        logger.info(f"📦 yt-dlp auto-update ({reason}): current={current_version}")
        
        # التحديث باستخدام pip مع --break-system-packages (مهم لـ Railway)
        result = subprocess.run(
            [subprocess.sys.executable, '-m', 'pip', 'install', '--upgrade', 
             'yt-dlp', '--break-system-packages'],
            capture_output=True, timeout=180, text=True
        )
        
        _ytdlp_last_update_time = time.time()
        
        if result.returncode == 0:
            # نتحقق لو فعلاً اتحديث
            try:
                # لازم نعمل reload عشان النسخة الجديدة تشتغل
                import importlib
                importlib.reload(yt_dlp)
                new_version = getattr(yt_dlp.version, '__version__', 'unknown')
            except Exception:
                new_version = _log_ytdlp_version()
            
            if new_version != current_version:
                logger.info(f"📦 ✅ yt-dlp UPDATED: {current_version} → {new_version} ({reason})")
                return True
            else:
                logger.info(f"📦 yt-dlp already up to date: {current_version} ({reason})")
                return False
        else:
            logger.warning(f"📦 yt-dlp auto-update failed: {result.stderr[:300]}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"📦 yt-dlp auto-update timed out ({reason})")
        return False
    except Exception as e:
        logger.warning(f"📦 yt-dlp auto-update error: {e}")
        return False
    finally:
        _ytdlp_updating = False


def _auto_update_ytdlp():
    """تحديث yt-dlp عند تشغيل البوت"""
    _do_ytdlp_update(reason="startup")


def _ytdlp_periodic_updater():
    """تحديث yt-dlp كل ساعة في الـ background"""
    while True:
        time.sleep(_YTDLP_UPDATE_INTERVAL)
        try:
            _do_ytdlp_update(reason="hourly")
        except Exception as e:
            logger.warning(f"📦 yt-dlp periodic update error: {e}")


def trigger_ytdlp_update():
    """تحديث yt-dlp فوراً — يتنادي لو YouTube رفض التحميل
    
    يستخدمها الكود لو شاف خطأ bot detection أو sign in
    """
    import threading as _th
    _th.Thread(target=_do_ytdlp_update, args=("bot_detection",), daemon=True).start()


def should_update_ytdlp() -> bool:
    """هل محتاجين نحدث yt-dlp؟ — بنستخدمها لو التحميل فشل عشان نشوف السبب"""
    time_since_update = time.time() - _ytdlp_last_update_time
    return time_since_update > _YTDLP_UPDATE_INTERVAL


# تسجيل النسخ + تحديث تلقائي عند تشغيل الموديول
try:
    _log_ytdlp_version()
except Exception:
    pass

# 🔴 تحديث yt-dlp في الـ background عند التشغيل
import threading
try:
    _update_thread = threading.Thread(target=_auto_update_ytdlp, daemon=True)
    _update_thread.start()
    logger.info("📦 yt-dlp startup update started in background")
except Exception:
    pass

# 🔴 تحديث دوري كل ساعة في الـ background
try:
    _periodic_thread = threading.Thread(target=_ytdlp_periodic_updater, daemon=True)
    _periodic_thread.start()
    logger.info(f"📦 yt-dlp periodic updater started (every {_YTDLP_UPDATE_INTERVAL}s)")
except Exception:
    pass


# ═══════════════════════════════════════
# تخزين مؤقت للروابط - URL Cache
# ═══════════════════════════════════════

_download_urls = {}
_URL_CACHE_TTL = 600  # 10 دقائق


def _store_url(url: str) -> str:
    """تخزين الرابط وإرجاع مفتاح قصير"""
    now = time.time()
    expired = [k for k, v in _download_urls.items() if now - v["created_at"] > _URL_CACHE_TTL]
    for k in expired:
        del _download_urls[k]
    key = hashlib.md5(url.encode()).hexdigest()[:8]
    _download_urls[key] = {"url": url, "created_at": now}
    return key


def _retrieve_url(key: str) -> str:
    """استرجاع الرابط من المفتاح"""
    entry = _download_urls.get(key)
    return entry["url"] if entry else ""


# ═══════════════════════════════════════
# 🔴 الكوكيز الوهمية اتشالت نهائياً!
# الكوكيز الوهمية (visitor cookies) بتضر أكتر مما تنفع لأن:
# 1. YouTube بيكتشف إنها random/generated وبيعتبرنا bot
# 2. كل محاولة بتولد visitor_id مختلف = سلوك مش طبيعي
# 3. yt-dlp بيدير كوكيز YouTube داخلياً حسب player_client
# الحل الحقيقي: ملف cookies.txt حقيقي من المتصفح
# ═══════════════════════════════════════


# ═══════════════════════════════════════
# كيبورد اختيار الجودة
# ═══════════════════════════════════════

def _get_quality_keyboard(url: str, lang: str = "ar") -> InlineKeyboardMarkup:
    """أزرار اختيار جودة الفيديو"""
    url_key = _store_url(url)
    if lang == "ar":
        keyboard = [
            [
                InlineKeyboardButton("🎬 أعلى جودة", callback_data=f"dl_v_b_{url_key}"),
                InlineKeyboardButton("📹 جودة متوسطة", callback_data=f"dl_v_m_{url_key}"),
            ],
            [
                InlineKeyboardButton("📱 جودة منخفضة", callback_data=f"dl_v_l_{url_key}"),
                InlineKeyboardButton("🎵 صوت بس MP3", callback_data=f"dl_a_{url_key}"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🎬 Best Quality", callback_data=f"dl_v_b_{url_key}"),
                InlineKeyboardButton("📹 Medium Quality", callback_data=f"dl_v_m_{url_key}"),
            ],
            [
                InlineKeyboardButton("📱 Low Quality", callback_data=f"dl_v_l_{url_key}"),
                InlineKeyboardButton("🎵 Audio Only MP3", callback_data=f"dl_a_{url_key}"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def _get_audio_quality_keyboard(url: str, lang: str = "ar") -> InlineKeyboardMarkup:
    """أزرار اختيار جودة الصوت فقط — لما المستخدم يطلب /audio
    
    🔴 الفرق عن _get_quality_keyboard:
    - بيظهر خيارات جودة الصوت بس (320kbps, 192kbps, 128kbps, 64kbps)
    - مفيش خيارات فيديو — المستخدم طلب صوت أصلاً
    - callback data: dl_aq_{bitrate}_{url_key}
    """
    url_key = _store_url(url)
    if lang == "ar":
        keyboard = [
            [
                InlineKeyboardButton("🎧 320kbps", callback_data=f"dl_aq_320_{url_key}"),
                InlineKeyboardButton("🎵 192kbps", callback_data=f"dl_aq_192_{url_key}"),
            ],
            [
                InlineKeyboardButton("🎶 128kbps", callback_data=f"dl_aq_128_{url_key}"),
                InlineKeyboardButton("📻 64kbps", callback_data=f"dl_aq_64_{url_key}"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🎧 320kbps", callback_data=f"dl_aq_320_{url_key}"),
                InlineKeyboardButton("🎵 192kbps", callback_data=f"dl_aq_192_{url_key}"),
            ],
            [
                InlineKeyboardButton("🎶 128kbps", callback_data=f"dl_aq_128_{url_key}"),
                InlineKeyboardButton("📻 64kbps", callback_data=f"dl_aq_64_{url_key}"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


# ═══════════════════════════════════════
# أوامر التحميل
# ═══════════════════════════════════════

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /download <url> — تحميل فيديو/صورة/صوت من أي منصة"""
    user_id = update.effective_user.id
    lang = get_language(user_id)
    increment_command_count(user_id)

    if not check_limit(user_id, "image_gen")["allowed"]:
        feature_name = "📥 تحميل وسائط / Media Download"
        await update.message.reply_text(
            premium_required_message(feature_name, lang),
            parse_mode="HTML",
            reply_markup=get_premium_keyboard(lang, user_id=user_id)
        )
        return

    url = " ".join(context.args) if context.args else ""
    if not url:
        if lang == "ar":
            msg = """📥 <b>تحميل وسائط من أي منصة</b>

💡 <b>طريقتين:</b>
1️⃣ ابعت الرابط لوحده في الشات وهيحملهولك تلقائي!
2️⃣ أو استخدم الأمر: <code>/download الرابط</code>

<b>المنصات المدعومة:</b>
→ YouTube, Facebook, Instagram
→ TikTok, Twitter/X, Telegram
→ Threads, Reddit, Vimeo
→ وأي منصة تانية!

⭐ الميزة دي للمشتركين Premium بس"""
        else:
            msg = """📥 <b>Download Media from Any Platform</b>

💡 <b>Two ways:</b>
1️⃣ Just paste the URL in chat and it will auto-download!
2️⃣ Or use the command: <code>/download URL</code>

<b>Supported Platforms:</b>
→ YouTube, Facebook, Instagram
→ TikTok, Twitter/X, Telegram
→ Threads, Reddit, Vimeo
→ And many more!

⭐ This feature is Premium only"""
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    await _process_download_request(update, context, url, lang, user_id)


async def _process_download_request(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, lang: str, user_id: int):
    """معالجة طلب التحميل"""
    # 🛡️ Safety check on URL
    try:
        is_safe, reason = await check_query_safety(url, platform="telegram", user_id=str(user_id))
        if not is_safe:
            msg = get_block_message(lang, reason)
            await update.message.reply_text(msg, parse_mode="HTML")
            return
    except Exception:
        pass  # Fail-open
    
    platform = _detect_platform(url)
    direct_type = _is_direct_media_url(url)
    
    if direct_type == "image":
        await _download_direct_image(update, url, lang, user_id)
        return
    if direct_type == "audio":
        await _download_direct_audio(update, url, lang, user_id)
        return
    if direct_type == "video":
        await _download_with_ytdlp(update, url, "best", lang, user_id)
        return
    
    platform_names = {
        "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
        "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
        "threads": "Threads", "reddit": "Reddit", "pinterest": "Pinterest",
        "vimeo": "Vimeo", "dailymotion": "Dailymotion", "twitch": "Twitch",
        "snapchat": "Snapchat", "unknown": "🌐",
    }
    platform_display = platform_names.get(platform, platform)
    keyboard = _get_quality_keyboard(url, lang)
    
    if lang == "ar":
        msg = f"📥 <b>تحميل من {platform_display}</b>\n\n🔗 <code>{url[:80]}{'...' if len(url) > 80 else ''}</code>\n\nاختر الجودة اللي عايزها:"
    else:
        msg = f"📥 <b>Download from {platform_display}</b>\n\n🔗 <code>{url[:80]}{'...' if len(url) > 80 else ''}</code>\n\nChoose the quality you want:"
    
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)


# ═══════════════════════════════════════
# تحميل مباشر (صور/صوت)
# ═══════════════════════════════════════

async def _download_direct_image(update: Update, url: str, lang: str, user_id: int):
    """تحميل صورة مباشرة من رابط"""
    import aiohttp
    if lang == "ar":
        status_msg = await update.message.reply_text("⏳ جاري تحميل الصورة...")
    else:
        status_msg = await update.message.reply_text("⏳ Downloading image...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    await status_msg.edit_text("❌ فشل تحميل الصورة." if lang == "ar" else "❌ Failed to download image.")
                    return
                image_bytes = await resp.read()
        
        # 🛡️ Safety check on image
        try:
            from content_safety import check_image_safety
            is_safe_img, reason_img, _score = await check_image_safety(
                image_bytes=image_bytes, platform="telegram", user_id=str(user_id)
            )
            if not is_safe_img:
                msg = get_block_message(lang, reason_img)
                await status_msg.edit_text(msg, parse_mode="HTML")
                return
        except Exception:
            pass  # Fail-open
        
        increment_usage(user_id, "image_analyses")
        try: track_event("media_downloads")
        except: pass
        await status_msg.delete()
        await update.message.reply_photo(
            photo=io.BytesIO(image_bytes),
            caption=f"📥 {'تم تحميل الصورة!' if lang == 'ar' else 'Image downloaded!'}\n🔗 <code>{url[:100]}</code>",
            parse_mode="HTML",
        )
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ انتهى وقت تحميل الصورة." if lang == "ar" else "❌ Image download timed out.")
    except Exception as e:
        logger.error(f"Error downloading direct image: {e}")
        await status_msg.edit_text("❌ فشل تحميل الصورة. جرب تاني." if lang == "ar" else "❌ Failed to download image. Try again.")


async def _download_direct_audio(update: Update, url: str, lang: str, user_id: int):
    """تحميل صوت مباشر من رابط"""
    import aiohttp
    if lang == "ar":
        status_msg = await update.message.reply_text("⏳ جاري تحميل الصوت...")
    else:
        status_msg = await update.message.reply_text("⏳ Downloading audio...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    await status_msg.edit_text("❌ فشل تحميل الصوت." if lang == "ar" else "❌ Failed to download audio.")
                    return
                audio_bytes = await resp.read()
        
        # 🛡️ Safety check on audio
        from urllib.parse import urlparse, unquote
        filename = os.path.basename(unquote(urlparse(url).path)) or "audio.mp3"
        try:
            from content_safety import check_audio_safety
            is_safe_audio, reason_audio, _score = await check_audio_safety(
                title=filename, platform="telegram", user_id=str(user_id)
            )
            if not is_safe_audio:
                msg = get_block_message(lang, reason_audio)
                await status_msg.edit_text(msg, parse_mode="HTML")
                return
        except Exception:
            pass  # Fail-open
        
        increment_usage(user_id, "youtube_summaries")
        try: track_event("media_downloads")
        except: pass
        await status_msg.delete()
        await update.message.reply_audio(
            audio=io.BytesIO(audio_bytes), filename=filename,
            caption=f"📥 {'تم تحميل الصوت!' if lang == 'ar' else 'Audio downloaded!'}\n🔗 <code>{url[:100]}</code>",
            parse_mode="HTML",
        )
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ انتهى وقت تحميل الصوت." if lang == "ar" else "❌ Audio download timed out.")
    except Exception as e:
        logger.error(f"Error downloading direct audio: {e}")
        await status_msg.edit_text("❌ فشل تحميل الصوت. جرب تاني." if lang == "ar" else "❌ Failed to download audio. Try again.")


# ═══════════════════════════════════════
# Cobalt Public API — لليوتيوب بس (بدل yt-dlp)
# ═══════════════════════════════════════

# 🔴 Cobalt v6 API (api/json) اتنفصل في نوفمبر 2024
# v7 API بيتطلب JWT — بنستخدمه في المحاولة 8 (Cobalt JWT)
# Self-hosted Cobalt لسه شغال لو عندك COBALT_API_URL

# 🔴 استراتيجية جديدة: أي رابط YouTube (youtube.com, youtu.be, youtube.com/shorts)
# بنستخدم Invidious + Piped الأول (IP مختلف) ثم Cobalt ثم yt-dlp
# السبب: yt-dlp بيتحجب باستمرار من YouTube (bot detection)
# Cobalt Public API أسرع وأضمن لليوتيوب

_COBALT_PUBLIC_API = "https://api.cobalt.tools/api/json"

_YOUTUBE_URL_PATTERN = re.compile(
    r'(https?://)?(www\.)?(youtube\.com|youtu\.be|youtube\.com/shorts)/',
    re.IGNORECASE
)


def _is_youtube_url(url: str) -> bool:
    """فحص هل الرابط يوتيوب — يشمل youtube.com, youtu.be, youtube.com/shorts"""
    return bool(_YOUTUBE_URL_PATTERN.search(url))


async def _try_cobalt_for_youtube(url: str, quality: str, tmpdir: str) -> dict | None:
    """تحميل فيديو يوتيوب عبر Cobalt API — Self-Hosted أولاً ثم Public
    
    🔴 بيتعمل ليوتيوب بس — باقي المنصات شغالة بـ yt-dlp زي ما هي
    
    Cobalt API بيشتغل كالتالي:
    - POST للـ API endpoint
    - Payload: {"url": video_url, "vQuality": "720", "filenamePattern": "classic"}
    - لو status == "stream" / "redirect" / "tunnel" → رجّع الـ url
    - لو status == "picker" → رجّع أول رابط في القائمة
    
    يرجع dict فيه:
    - filepath: مسار الملف المحمل
    - filename: اسم الملف
    - title: عنوان الفيديو
    - duration: المدة
    - size: حجم الملف
    
    أو None لو فشل
    """
    import aiohttp
    
    # تحويل الجودة لصيغة Cobalt
    quality_map = {
        "best": "1080",
        "medium": "720",
        "low": "480",
        "audio": "720",  # الجودة مش مهمة للأوديو
    }
    v_quality = quality_map.get(quality, "720")
    
    is_audio = _is_audio_quality(quality)
    
    # ═══ محاولة 1: Self-Hosted Cobalt (COBALT_API_URL) ═══
    # لو عندنا سيرفر Cobalt شغال — ده الأضمن
    try:
        from config import COBALT_API_URL, COBALT_API_KEY
        
        if COBALT_API_URL:
            api_url = COBALT_API_URL.rstrip("/")
            
            # v8 format for self-hosted
            payload = {
                "url": url,
                "videoQuality": v_quality,
                "downloadMode": "audio" if is_audio else "auto",
                "audioFormat": "mp3" if is_audio else "best",
                "filenameStyle": "classic",
                "youtubeVideoCodec": "h264",
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            
            if COBALT_API_KEY:
                headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
            
            logger.info(f"🟠 Cobalt Self-Hosted: requesting download for {url[:80]} (quality={v_quality}, audio={is_audio})")
            
            result = await _cobalt_api_request(api_url, payload, headers, v_quality, is_audio, tmpdir)
            if result:
                return result
            
            logger.warning(f"⚠️ Cobalt Self-Hosted failed, trying next...")
    except Exception as e:
        logger.warning(f"⚠️ Cobalt Self-Hosted error: {e}")
    
    # ═══ محاولة 2: Cobalt Public API (api.cobalt.tools) ═══
    # الـ API الرسمي محتاج API key (JWT) — بنستخدم الـ COBALT_API_KEY لو متاح
    try:
        from config import COBALT_API_KEY
        
        public_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        if COBALT_API_KEY:
            public_headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
        
        # v8 format for public API
        public_payload = {
            "url": url,
            "videoQuality": v_quality,
            "filenameStyle": "classic",
        }
        
        if is_audio:
            public_payload["downloadMode"] = "audio"
            public_payload["audioFormat"] = "mp3"
        
        logger.info(f"🟠 Cobalt Public API: requesting download for {url[:80]}")
        
        result = await _cobalt_api_request("https://api.cobalt.tools", public_payload, public_headers, v_quality, is_audio, tmpdir)
        if result:
            return result
        
        logger.warning(f"⚠️ Cobalt Public API failed")
    except Exception as e:
        logger.warning(f"⚠️ Cobalt Public API error: {e}")
    
    # كل المحاولات فشلت
    logger.warning(f"🟠 All Cobalt methods failed for {url[:80]}")
    return None


async def _cobalt_api_request(api_url: str, payload: dict, headers: dict, 
                               v_quality: str, is_audio: bool, tmpdir: str) -> dict | None:
    """طلب تحميل من أي Cobalt API endpoint — مشتركة بين Self-Hosted و Public
    
    Args:
        api_url: رابط الـ API (بدون trailing slash)
        payload: الـ request payload
        headers: الـ request headers
        v_quality: الجودة (720, 1080, 480)
        is_audio: هل تحميل صوت
        tmpdir: مجلد التحميل المؤقت
    """
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            # الخطوة 1: طلب رابط التحميل من Cobalt
            async with session.post(
                f"{api_url}/",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    resp_text = await resp.text()
                    logger.warning(f"🟠 Cobalt: API returned status {resp.status}: {resp_text[:200]}")
                    return None
                
                data = await resp.json()
            
            status = data.get("status", "")
            
            if status == "error":
                error_code = data.get("error", {})
                if isinstance(error_code, dict):
                    error_code = error_code.get("code", "unknown")
                logger.warning(f"🟠 Cobalt: error response: {error_code}")
                return None
            
            download_url = None
            filename = None
            
            if status in ("stream", "redirect", "tunnel"):
                # رابط مباشر للفيديو
                download_url = data.get("url")
                filename = data.get("filename", "")
            elif status == "picker":
                # محتوى متعدد (carousel, shorts playlist, إلخ)
                picker_items = data.get("picker", [])
                audio_url = data.get("audio")
                if picker_items:
                    # نختار أول عنصر — زي ما المستخدم طلب
                    download_url = picker_items[0].get("url")
                    filename = data.get("filename", "")
                elif audio_url:
                    download_url = audio_url
                    filename = data.get("audioFilename", "audio.mp3")
            else:
                logger.warning(f"🟠 Cobalt: unknown status '{status}'")
                return None
            
            if not download_url:
                logger.warning("🟠 Cobalt: no download URL in response")
                return None
            
            logger.info(f"🟠 Cobalt: got download URL, downloading file...")
            
            # الخطوة 2: تحميل الملف من الرابط
            ext = "mp3" if is_audio else "mp4"
            if not filename:
                filename = f"youtube_download.{ext}"
            # تنظيف اسم الملف
            filename = re.sub(r'[^\w\-.]', '_', filename)
            if not filename.endswith(ext):
                filename = f"{filename.rsplit('.', 1)[0] if '.' in filename else filename}.{ext}"
            
            filepath = os.path.join(tmpdir, filename)
            
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 دقائق للملفات الكبيرة
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.warning(f"🟠 Cobalt: download URL returned status {dl_resp.status}")
                    return None
                
                content_length = dl_resp.headers.get("Content-Length", "unknown")
                logger.info(f"🟠 Cobalt: downloading file (size: {content_length} bytes)...")
                
                with open(filepath, 'wb') as f:
                    async for chunk in dl_resp.content.iter_chunked(8192):
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                logger.warning("🟠 Cobalt: downloaded file is empty")
                os.remove(filepath)
                return None
            
            logger.info(f"🟠 Cobalt: download succeeded! Size: {file_size // (1024*1024)}MB")
            
            return {
                "filepath": filepath,
                "filename": filename,
                "title": filename.rsplit('.', 1)[0] if filename else "YouTube Video",
                "duration": 0,
                "height": int(v_quality) if v_quality.isdigit() else 720,
                "size": file_size,
                "method": "cobalt",
            }
    
    except asyncio.TimeoutError:
        logger.warning("🟠 Cobalt: request timed out")
        return None
    except Exception as e:
        logger.warning(f"🟠 Cobalt: error: {e}")
        return None


# ═══════════════════════════════════════
# تحميل بـ Cobalt Self-Hosted (طبقة إضافية)
# ═══════════════════════════════════════

# 🔴 Cobalt Self-Hosted: طبقة إضافية لو الـ Public API فشل
# بنشغله على سيرفر Railway منفصل ونربطه بالبوت

async def _try_cobalt_download(url: str, quality: str, tmpdir: str) -> dict | None:
    """تحميل فيديو/صوت عبر Cobalt Self-Hosted API
    
    يرجع dict فيه:
    - filepath: مسار الملف المحمل
    - filename: اسم الملف
    - title: عنوان الفيديو (لو موجود)
    - duration: المدة (لو موجودة)
    
    أو None لو فشل
    """
    import aiohttp
    from config import COBALT_API_URL, COBALT_API_KEY
    
    if not COBALT_API_URL:
        logger.info("🔵 Cobalt: COBALT_API_URL not set, skipping")
        return None
    
    api_url = COBALT_API_URL.rstrip("/")
    
    # تحويل الجودة لصيغة Cobalt
    quality_map = {
        "best": "1080",
        "medium": "720",
        "low": "480",
        "audio": "720",  # الجودة مش مهمة للأوديو
    }
    cobalt_quality = quality_map.get(quality, "1080")
    
    is_audio = _is_audio_quality(quality)
    
    payload = {
        "url": url,
        "videoQuality": cobalt_quality,
        "downloadMode": "audio" if is_audio else "auto",
        "audioFormat": "mp3" if is_audio else "best",
        "audioBitrate": "128",
        "filenameStyle": "basic",
        "youtubeVideoCodec": "h264",  # هام لتوافق Telegram/WhatsApp
        "youtubeVideoContainer": "mp4" if not is_audio else "auto",
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    if COBALT_API_KEY:
        headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
    
    logger.info(f"🔵 Cobalt: requesting download for {url[:80]} (quality={cobalt_quality}, audio={is_audio})")
    
    try:
        async with aiohttp.ClientSession() as session:
            # الخطوة 1: طلب رابط التحميل من Cobalt
            async with session.post(
                f"{api_url}/",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"🔵 Cobalt: API returned status {resp.status}")
                    return None
                
                data = await resp.json()
            
            status = data.get("status", "")
            
            if status == "error":
                error_code = data.get("error", {}).get("code", "unknown")
                logger.warning(f"🔵 Cobalt: error response: {error_code}")
                return None
            
            download_url = None
            filename = None
            picker_items = None
            
            if status in ("tunnel", "redirect"):
                download_url = data.get("url")
                filename = data.get("filename", "")
            elif status == "picker":
                # Instagram carousel أو محتوى متعدد
                picker_items = data.get("picker", [])
                audio_url = data.get("audio")
                # نختار أول فيديو من الـ picker
                if picker_items:
                    for item in picker_items:
                        if item.get("type") == "video":
                            download_url = item.get("url")
                            break
                    if not download_url and picker_items:
                        download_url = picker_items[0].get("url")
                elif audio_url:
                    download_url = audio_url
                    filename = data.get("audioFilename", "audio.mp3")
            elif status == "local-processing":
                # Cobalt بيعمل merge محلي — نحتاج نستنى
                tunnel_urls = data.get("tunnel", [])
                output_info = data.get("output", {})
                filename = output_info.get("filename", "")
                if tunnel_urls:
                    download_url = tunnel_urls[0]
            else:
                logger.warning(f"🔵 Cobalt: unknown status '{status}'")
                return None
            
            if not download_url:
                logger.warning("🔵 Cobalt: no download URL in response")
                return None
            
            logger.info(f"🔵 Cobalt: got download URL, downloading file...")
            
            # الخطوة 2: تحميل الملف من رابط الـ tunnel
            ext = "mp3" if is_audio else "mp4"
            if not filename:
                filename = f"cobalt_download.{ext}"
            
            filepath = os.path.join(tmpdir, filename)
            
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 دقائق للملفات الكبيرة
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.warning(f"🔵 Cobalt: download URL returned status {dl_resp.status}")
                    return None
                
                content_length = dl_resp.headers.get("Content-Length", "unknown")
                logger.info(f"🔵 Cobalt: downloading file (size: {content_length} bytes)...")
                
                with open(filepath, 'wb') as f:
                    async for chunk in dl_resp.content.iter_chunked(8192):
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                logger.warning("🔵 Cobalt: downloaded file is empty")
                os.remove(filepath)
                return None
            
            logger.info(f"🔵 Cobalt: download succeeded! Size: {file_size // (1024*1024)}MB")
            
            return {
                "filepath": filepath,
                "filename": filename,
                "title": filename.rsplit('.', 1)[0] if filename else "Video",
                "duration": 0,
                "height": int(cobalt_quality) if cobalt_quality.isdigit() else 720,
                "size": file_size,
                "method": "cobalt",
            }
    
    except asyncio.TimeoutError:
        logger.warning("🔵 Cobalt: request timed out")
        return None
    except Exception as e:
        logger.warning(f"🔵 Cobalt: error: {e}")
        return None


# ═══════════════════════════════════════
# تحميل بـ yt-dlp (مُحسّن بالكامل v5)
# ═══════════════════════════════════════

# 🔴 FIX v5: إعداد deno + remote_components
# yt-dlp 2025+ محتاج JavaScript runtime (deno) عشان يحل YouTube challenges
# بدونه، مبنقدرش نحصل على كل التنسيقات

_DENO_PATH = os.path.expanduser('~/.deno/bin/deno')


def _ensure_deno_in_path():
    """إضافة deno للـ PATH عشان yt-dlp يقدر يستخدمه"""
    deno_dir = os.path.dirname(_DENO_PATH)
    current_path = os.environ.get('PATH', '')
    if deno_dir not in current_path:
        os.environ['PATH'] = f"{deno_dir}:{current_path}"
        logger.info(f"🔧 Added deno to PATH: {deno_dir}")


# إضافة deno للـ PATH عند تحميل الموديول
try:
    _ensure_deno_in_path()
    if os.path.exists(_DENO_PATH):
        logger.info(f"🔧 Deno found: {_DENO_PATH}")
except Exception:
    pass


# 🔴 FIX v5: YouTube player_client fallback order
# الطريقة الأساسية: بدون player_client (الافتراضي) + deno + remote_components
# ده بيدي أحسن نتيجة (37 تنسيق لحد 1080p)
# player_client بنستخدمه كـ fallback بس لو الطريقة الأساسية فشلت
_YOUTUBE_PLAYER_CLIENTS = [
    ['android', 'web'],    # Android client — fallback أول
    ['ios', 'web'],        # iOS client
    ['mweb', 'web'],       # Mobile Web
    ['tv', 'web'],         # TV client
    ['web'],               # Default web — آخر حل
]


def _get_ydl_opts(quality: str, output_template: str, platform: str = "", 
                  use_ffmpeg: bool = True, player_client_idx: int = 0) -> dict:
    """إعداد خيارات yt-dlp حسب الجودة والمنصة وتوفر ffmpeg
    
    🔴 FIX v3: 
    - بنضيف cookies.txt لو موجود — الحل الأقوى لتخطي bot detection
    - 🔴 الكوكيز الوهمية اتشالت نهائياً — مش بتفيد وبتضر
    - بنستخدم player_client=mweb أولاً (أقل كشف) مع fallback لـ android → ios → tv → web
    - بنكشف ffmpeg تلقائي وبنعدل التنسيقات حسب التوفر
    """
    ffmpeg_ok = use_ffmpeg and _is_ffmpeg_available()
    platform_lower = platform.lower() if platform else ""
    # 🔴 FIX: لازم نعرّف is_youtube و platform_lower جوه الدالة
    # platform بتتباصى من _detect_platform() — لو فاضي بنعامل كأنه YouTube
    is_youtube = platform_lower == "youtube" or platform_lower == ""
    
    # 🔴 الكوكيز الوهمية اتشالت نهائياً!
    # الكوكيز الوهمية (visitor cookies) بتضر أكتر مما تنفع لأن:
    # 1. YouTube بيكتشف إنها random/generated وبيعتبرنا bot
    # 2. كل محاولة بتولد visitor_id مختلف = سلوك مش طبيعي
    # 3. yt-dlp بيدير كوكيز YouTube داخلياً حسب player_client
    # بنستخدم الكوكيز الوهمية بس للمنصات التانية
    
    # 🔴 الكوكيز الوهمية اتشالت نهائياً — مش بتفيد وبتضر
    # بنستخدم headers نظيفة بدون أي Cookie
    headers = {
        'User-Agent': _USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
    }
    
    # إعدادات مشتركة
    common_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 3,
        'file_access_retries': 3,
        'extractor_retries': 3,
        'no_check_certificates': True,
        'http_headers': headers,
    }
    
    # 🔴 FIX: ملف cookies.txt — الحل الأقوى
    cookies_path = _get_cookies_file()
    if cookies_path:
        common_opts['cookiefile'] = cookies_path
        logger.info(f"🍪 Using cookies file: {cookies_path}")
    
    # 🔴 FIX v5: استراتيجية YouTube جديدة
    # الطريقة الأساسية: بدون player_client + deno + remote_components
    # ده بيدي 37 تنسيق لحد 1080p بدون ما YouTube يعتبرنا bot
    # player_client بنستخدمه كـ fallback بس
    
    if is_youtube:
        # 🔴 إضافة deno للـ PATH
        _ensure_deno_in_path()
        
        if player_client_idx == 0:
            # المحاولة الأولى: بدون player_client + deno + remote_components
            # ده الأفضل — بيدي كل التنسيقات
            common_opts['remote_components'] = ['ejs:github']
            # لا نضيف player_client خالص — نخلي yt-dlp يستخدم الطريقة الافتراضية
            logger.info("🔧 YouTube: default mode + deno + remote_components (best method)")
        else:
            # Fallback: نستخدم player_client محدد
            if player_client_idx - 1 < len(_YOUTUBE_PLAYER_CLIENTS):
                pc = _YOUTUBE_PLAYER_CLIENTS[player_client_idx - 1]
            else:
                pc = _YOUTUBE_PLAYER_CLIENTS[-1]
            common_opts['extractor_args'] = {'youtube': {'player_client': pc}}
            logger.info(f"🔧 YouTube player_client fallback: {pc} (attempt {player_client_idx + 1})")
    elif platform_lower == "tiktok":
        common_opts['extractor_args'] = {'tiktok': {'api_hostname': 'api22-normal-c-useast2a.tiktokv.com'}}
    
    # 🔴 FIX v4: إعدادات حسب نوع المحتوى
    if _is_audio_quality(quality):
        if ffmpeg_ok:
            opts = {
                **common_opts,
                # 🔴 FIX v6: bestaudio فقط — بدون /best fallback
                # الـ /best بيحمل فيديو لو مفيش audio-only format متاح
                # yt-dlp هيحاول أفضل صوت متاح، ولو مفيش هيستخدم bestaudio
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio[ext=mp3]/bestaudio/best[ext=mp4]/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': str(_get_audio_bitrate(quality)),
                }],
            }
        else:
            opts = {
                **common_opts,
                # 🔴 بدون ffmpeg → بنحاول نحمل audio فقط بدون تحويل
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
            }
    else:
        # ═══ فيديو ═══
        # 🔴 FIX v4: format strings بتفضل h264 (avc1) عشان Telegram
        # Telegram مش بيشغل VP9/AV1 — لازم h264 + aac في mp4
        #
        # vcodec^=avc1 = h264 video codec (اللي Telegram بيشغله)
        # بنحط h264 الأول، وبعدين fallback لـ أي mp4، وبعدين best
        #
        # Facebook/Instagram مش بيوفر separate video+audio دايماً
        # فبنفضل pre-merged formats (best[ext=mp4]) عشان نتجنب مشاكل الدمج
        
        is_facebook_family = platform_lower in ("facebook", "instagram", "threads")
        
        if ffmpeg_ok:
            if is_facebook_family:
                # 🔴 FIX v5: Facebook family — بنفضل pre-merged formats بقوة عشان:
                # 1. Facebook بيوفر فيديوهات pre-merged بجودة عالية
                # 2. دمج separate streams من Facebook بيدي فيديو شاشة سوداء
                # 3. Pre-merged بتكون h264 جاهزة للتليجرام
                # 4. بنحط pre-mergedmp4 الأول دايماً عشان نتجنب مشاكل الدمج
                format_map = {
                    "best": (
                        # 🔴 pre-merged mp4 الأول — أضمن حل للشاشة السوداء
                        "best[ext=mp4][height<=1080]/"
                        # h264 separate + audio
                        "bestvideo[vcodec^=avc1][height<=1080]+bestaudio/"
                        # أي pre-merged mp4
                        "best[ext=mp4]/"
                        # أي h264 video + audio
                        "bestvideo[vcodec^=avc1]+bestaudio/"
                        # أي mp4 video + audio
                        "bestvideo[ext=mp4]+bestaudio/"
                        # آخر حل
                        "best"
                    ),
                    "medium": (
                        "best[ext=mp4][height<=720]/"
                        "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
                        "best[ext=mp4][height<=720]/"
                        "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
                        "bestvideo[ext=mp4][height<=720]+bestaudio/"
                        "best[height<=720]/"
                        "best"
                    ),
                    "low": (
                        "best[ext=mp4][height<=480]/"
                        "bestvideo[vcodec^=avc1][height<=480]+bestaudio/"
                        "best[ext=mp4][height<=480]/"
                        "bestvideo[vcodec^=avc1][height<=480]+bestaudio/"
                        "bestvideo[ext=mp4][height<=480]+bestaudio/"
                        "best[height<=480]/"
                        "best"
                    ),
                }
            else:
                # YouTube + باقي المنصات — بنفضل h264 بشكل واضح
                format_map = {
                    "best": (
                        # 1. h264 video + aac audio في mp4 (أفضل للتليجرام)
                        "bestvideo[vcodec^=avc1][ext=mp4][height<=1080]+bestaudio[ext=m4a]/"
                        "bestvideo[vcodec^=avc1]+bestaudio/"
                        # 2. أي mp4 video + audio
                        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/"
                        "bestvideo[ext=mp4]+bestaudio/"
                        # 3. Pre-merged mp4
                        "best[ext=mp4]/"
                        # 4. آخر حل: أي حاجة
                        "best"
                    ),
                    "medium": (
                        "bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[ext=m4a]/"
                        "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
                        "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/"
                        "bestvideo[ext=mp4][height<=720]+bestaudio/"
                        "best[ext=mp4][height<=720]/"
                        "best[height<=720]/"
                        "best"
                    ),
                    "low": (
                        "bestvideo[vcodec^=avc1][ext=mp4][height<=480]+bestaudio[ext=m4a]/"
                        "bestvideo[vcodec^=avc1][height<=480]+bestaudio/"
                        "bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/"
                        "bestvideo[ext=mp4][height<=480]+bestaudio/"
                        "best[ext=mp4][height<=480]/"
                        "best[height<=480]/"
                        "best"
                    ),
                }
            
            opts = {
                **common_opts,
                'format': format_map.get(quality, format_map["best"]),
                'merge_output_format': 'mp4',
                # 🔴 FIX v4: remux_video يضمن إن الحاوية mp4 حتى لو المنصة بترجع webm
                'remux_video': 'mp4',
            }
        else:
            # مش موجود ffmpeg → تنسيقات بسيطة (pre-merged)
            format_map = {
                "best": "best[ext=mp4]/best",
                "medium": "best[ext=mp4][height<=720]/best[height<=720]/best",
                "low": "best[ext=mp4][height<=480]/best[height<=480]/best",
            }
            opts = {
                **common_opts,
                'format': format_map.get(quality, format_map["best"]),
            }
    
    return opts


async def _download_with_ytdlp(update_or_query, url: str, quality: str, lang: str, user_id: int, status_msg=None):
    """تحميل فيديو أو صوت — مُحسّن v9 مع yt-dlp كأولوية
    
    🔴 FIX v9: Cobalt API كـ fallback تالت + Apify كـ fallback رابع
    1. yt-dlp + deno + remote_components (الأفضل)
    2. yt-dlp player_client fallback (android → ios → mweb → tv → web)
    3. 🟠 Cobalt API (fallback تالت — أسرع وأضمن من yt-dlp بدون كوكيز)
    4. 🔵 Apify (fallback رابع — سيرفرات مختلفة عن YouTube خالص)
    5. yt-dlp بدون كوكيز
    6. Invidious API (fallback)
    7. Piped API (fallback — زي Invidious بس سيرفرات مختلفة)
    8. Cobalt JWT (fallback)
    9. Cloudflare Worker (آخر محاولة)
    """
    # تحديد الرسالة
    if hasattr(update_or_query, 'message'):
        message = update_or_query.message
    else:
        message = update_or_query.message
    
    # كشف المنصة عشان نستخدم إعداداتها
    platform = _detect_platform(url)
    is_youtube = _is_youtube_url(url)  # 🔴 FIX: لازم نعرّف is_youtube هنا عشان الكود اللي بعد كده يستخدمه
    is_threads = _is_threads_url(url)   # 🔴 FIX: Threads مش مدعوم من yt-dlp — لازم طريقة مخصصة
    ffmpeg_ok = _is_ffmpeg_available()
    cookies_available = bool(_get_cookies_file())
    
    logger.info(f"📥 Download request: platform={platform}, quality={quality}, ffmpeg={ffmpeg_ok}, cookies={cookies_available}, url={url[:80]}")
    
    tmpdir = tempfile.mkdtemp(prefix="mybro_dl_")
    
    try:
        if not status_msg:
            if lang == "ar":
                status_msg = await message.reply_text("⏳ جاري التحميل...")
            else:
                status_msg = await message.reply_text("⏳ Downloading...")
        
        # 🔴 FIX: Threads — yt-dlp مش بيدعمه، نستخدم طريقة مخصصة
        if is_threads:
            logger.info(f"🧵 Threads detected — using custom download method (yt-dlp doesn't support threads.com)")
            try:
                await status_msg.edit_text(
                    "🧵 جاري التحميل من Threads..." if lang == "ar"
                    else "🧵 Downloading from Threads..."
                )
            except:
                pass
            
            threads_result = await _download_threads_media(url, tmpdir, quality)
            
            if threads_result and threads_result.get("success"):
                file_path = threads_result["file_path"]
                file_size = threads_result.get("file_size", os.path.getsize(file_path))
                real_title = threads_result.get("title", "Threads Post")
                is_video = threads_result.get("is_video", True)
                size_mb = file_size / (1024 * 1024)
                size_str = f"{size_mb:.1f}MB"
                
                # 🛡️ Safety check on downloaded media
                try:
                    media_type = "video" if is_video else "image"
                    is_safe_dl, block_msg_dl, _reason_dl = await comprehensive_media_safety_check(
                        title=real_title, file_path=file_path, file_type=media_type,
                        platform="telegram", user_id=str(user_id), lang=lang,
                    )
                    if not is_safe_dl:
                        await message.reply_text(block_msg_dl, parse_mode="HTML")
                        try: os.remove(file_path)
                        except: pass
                        return
                except Exception:
                    pass  # Fail-open
                
                increment_usage(user_id, "youtube_summaries")
                try: track_event("media_downloads")
                except: pass
                
                await status_msg.delete()
                
                # 🔴 FIX: لو المستخدم طلب صوت بس، نستخرج الصوت من الفيديو
                if is_video and _is_audio_quality(quality):
                    bitrate = _get_audio_bitrate(quality)
                    audio_sent = await _send_telegram_audio(
                        message, file_path, real_title, size_str, lang,
                        method_name="Threads", bitrate=bitrate
                    )
                    if not audio_sent:
                        # لو فشل إرسال الصوت، نجرب نبعت الفيديو عادي
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🧵 {real_title[:200]}\n📁 {size_str} | Threads"
                                await message.reply_video(
                                    video=f,
                                    caption=caption,
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                await message.reply_text(
                                    f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                    else f"❌ File too large for Telegram ({size_str})"
                                )
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                                    else f"❌ Failed to send audio ({size_str}). Try again!"
                                )
                elif is_video:
                    try:
                        with open(file_path, 'rb') as f:
                            caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🧵 {real_title[:200]}\n📁 {size_str} | Threads"
                            await message.reply_video(
                                video=f,
                                caption=caption,
                                supports_streaming=True,
                            )
                    except Exception as send_err:
                        if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                            await message.reply_text(
                                f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                else f"❌ File too large for Telegram ({size_str})"
                            )
                        else:
                            await message.reply_text(
                                f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send video ({size_str}). Try again!"
                            )
                else:
                    try:
                        with open(file_path, 'rb') as f:
                            caption = f"📥 {'تم تحميل الصورة!' if lang == 'ar' else 'Image downloaded!'}\n🧵 {real_title[:200]}\n📁 {size_str} | Threads"
                            await message.reply_photo(
                                photo=f,
                                caption=caption,
                            )
                    except Exception as send_err:
                        await message.reply_text(
                            f"❌ فشل إرسال الصورة. جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send image. Try again!"
                        )
                
                try: os.remove(file_path)
                except: pass
                return  # ✅ Threads نجح!
            else:
                # 🔴 FIX v5: Threads مش مدعوم من yt-dlp — لا fallback!
                # yt-dlp بيرجع "Unsupported URL" لـ threads.com/threads.net
                logger.warning("🧵 Threads: All custom methods failed — yt-dlp doesn't support Threads, not trying it")
                error_msg = (
                    "❌ فشل تحميل الفيديو من Threads. جرب تاني!" if lang == "ar"
                    else "❌ Failed to download from Threads. Try again!"
                )
                await message.reply_text(error_msg)
                try:
                    await status_msg.delete()
                except:
                    pass
                return
        
        output_template = os.path.join(tmpdir, "%(title).100s.%(ext)s")
        
        # تحديث رسالة الحالة
        if _is_audio_quality(quality):
            status_text = "🎵 جاري تحميل الصوت..." if lang == "ar" else "🎵 Downloading audio..."
        else:
            quality_names = {"best": "عالية", "medium": "متوسطة", "low": "منخفضة"} if lang == "ar" else {"best": "high", "medium": "medium", "low": "low"}
            q_name = quality_names.get(quality, quality)
            status_text = f"🎬 جاري تحميل الفيديو بجودة {q_name}..." if lang == "ar" else f"🎬 Downloading video in {q_name} quality..."
        
        try:
            await status_msg.edit_text(status_text)
        except Exception:
            pass
        
        # ═══════════════════════════════════════════════════════════════
        # 🔴 FIX v9: yt-dlp هو الأولوية الأولى!
        # الترتيب الجديد:
        # 1. yt-dlp + deno + remote_components (الأفضل)
        # 2. yt-dlp player_client fallback (android → ios → mweb → tv → web)
        # 3. 🟠 Cobalt API (fallback تالت — أسرع وأضمن)
        # 4. 🔵 Apify (fallback رابع — سيرفرات مختلفة عن YouTube)
        # 5. yt-dlp بدون كوكيز
        # 6. Invidious API (fallback)
        # 7. Piped API (fallback)
        # 8. Cobalt JWT (fallback)
        # 9. Cloudflare Worker (آخر محاولة)
        # ═══════════════════════════════════════════════════════════════
        
        info = None
        last_error = None
        
        def _run_ytdlp(opts):
            import yt_dlp
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=True)
        
        loop = asyncio.get_event_loop()
        
        # Progress timer removed — no periodic updates
        
        from urllib.parse import quote as _url_quote
        # 🔴 FIX: quote for URL encoding
        def quote(s): return _url_quote(s, safe='')
        
        # ═══ المحاولة 0: سيرفر التحميل الخاص (VPS بـ IP نظيف) ═══
        # 🔴 ده أفضل طريقة — السيرفر بيحمل من YouTube بـ IP نظيف ومبيحصلش حظر
        # السيرفر بيرفع على Supabase وبيرجع رابط — مفيش OOM على Railway
        if is_youtube:
            try:
                from config import DOWNLOAD_SERVICE_URL, DOWNLOAD_SERVICE_KEY
                if DOWNLOAD_SERVICE_URL:
                    logger.info(f"🖥️ Download Service: Trying VPS download for {url[:80]}")
                    try:
                        await status_msg.edit_text(
                            "🖥️ جاري التحميل عبر السيرفر الخاص..." if lang == "ar"
                            else "🖥️ Downloading via dedicated server..."
                        )
                    except:
                        pass
                    
                    import aiohttp as _aiohttp_ds
                    ds_url = DOWNLOAD_SERVICE_URL.rstrip("/")
                    api_url = f"{ds_url}/download?url={quote(url)}&quality={quality}&platform=telegram&lang={lang}"
                    ds_headers = {}
                    if DOWNLOAD_SERVICE_KEY:
                        ds_headers["X-API-Key"] = DOWNLOAD_SERVICE_KEY
                    
                    try:
                        async with _aiohttp_ds.ClientSession(timeout=_aiohttp_ds.ClientTimeout(total=360)) as ds_session:
                            async with ds_session.get(api_url, headers=ds_headers) as ds_resp:
                                if ds_resp.status == 200:
                                    ds_result = await ds_resp.json()
                                    if ds_result and ds_result.get("success"):
                                        logger.info(f"🖥️ Download Service succeeded! URL: {ds_result.get('url', '')[:60]}")
                                        
                                        # بعت الرابط للمستخدم
                                        cloud_msg = ds_result.get("cloud_msg", "")
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                        else:
                                            dl_url = ds_result.get("url", "")
                                            title = ds_result.get("title", "Video")
                                            size_mb = ds_result.get("size_mb", 0)
                                            if lang == "ar":
                                                await message.reply_text(
                                                    f"🎬 {title}\n\n☁️ تم رفعه على السحابة ({size_mb:.1f}MB)\n\n🔗 رابط التحميل:\n{dl_url}",
                                                    parse_mode="HTML", disable_web_page_preview=False
                                                )
                                            else:
                                                await message.reply_text(
                                                    f"🎬 {title}\n\n☁️ Uploaded to cloud ({size_mb:.1f}MB)\n\n🔗 Download link:\n{dl_url}",
                                                    parse_mode="HTML", disable_web_page_preview=False
                                                )
                                        
                                        try: await status_msg.delete()
                                        except: pass
                                        
                                        # Increment usage
                                        increment_usage(user_id, "youtube_summaries")
                                        try: track_event("media_downloads")
                                        except: pass
                                        
                                        try: shutil.rmtree(tmpdir, ignore_errors=True)
                                        except: pass
                                        return  # ✅ السيرفر الخاص نجح!
                                    else:
                                        error_msg = ds_result.get("message", "unknown error") if ds_result else "no response"
                                        logger.warning(f"🖥️ Download Service failed: {error_msg}")
                                else:
                                    logger.warning(f"🖥️ Download Service returned status {ds_resp.status}")
                    except asyncio.TimeoutError:
                        logger.warning("🖥️ Download Service timed out")
                    except Exception as ds_err:
                        logger.warning(f"🖥️ Download Service error: {ds_err}")
                    
                    logger.info("🖥️ Download Service failed, falling back to local yt-dlp...")
            except ImportError:
                pass
            except Exception as ds_outer_err:
                logger.warning(f"🖥️ Download Service outer error: {ds_outer_err}")
        
        # ═══ المحاولة 1: Invidious API (IP مختلف — مش بيتأثر بـ YouTube bot detection!) ═══
        # 🔴 Invidious بيشتغل من سيرفرات مختلفة — مش من Railway IP
        # ده أحسن من yt-dlp عشان yt-dlp بيستخدم Railway IP وبيتحظر
        if is_youtube:
            try:
                from invidious_api import download_youtube_invidious_file
                
                inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                    "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                inv_quality = inv_quality_map.get(quality, "audio" if _is_audio_quality(quality) else "best")
                
                logger.info(f"🟣 Invidious (early): Attempting download quality={inv_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟣 جاري التحميل عبر Invidious..." if lang == "ar"
                        else "🟣 Downloading via Invidious..."
                    )
                except:
                    pass
                
                try:
                    invidious_result = await asyncio.wait_for(
                        download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                        timeout=60
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Invidious (early) timed out after 60s")
                    invidious_result = None
                
                if invidious_result and invidious_result.get("success") and invidious_result.get("file_path"):
                    logger.info(f"🟣 Invidious (early) succeeded! File: {invidious_result['file_path']}")
                    
                    file_path = invidious_result["file_path"]
                    file_size = invidious_result.get("file_size", os.path.getsize(file_path))
                    real_title = invidious_result.get("title", "YouTube Video")
                    real_duration = invidious_result.get("duration", 0)
                    format_info = invidious_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "") or format_info.get("resolution", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{inv_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check
                    try:
                        inv_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_inv, block_msg_inv, _reason_inv = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=inv_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_inv:
                            await message.reply_text(block_msg_inv, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Invidious", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                tech_info = f"{quality_label} | {size_str} | Invidious"
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {real_title[:200]}\n📊 {tech_info}"
                                await message.reply_video(
                                    video=f, filename=f"{real_title[:50]}.mp4",
                                    caption=caption,
                                    parse_mode="HTML",
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            logger.warning(f"⚠️ Invidious video send failed: {send_err}")
                            try:
                                from supabase_storage import upload_and_get_link
                                cloud_msg = await upload_and_get_link(
                                    file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                    content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                )
                                if cloud_msg:
                                    await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                    try: os.remove(file_path)
                                    except: pass
                                    return
                            except:
                                pass
                            await message.reply_text(
                                f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send video ({size_str}). Try again!"
                            )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Invidious (early) نجح!
                
                logger.warning(f"⚠️ Invidious (early) failed, trying Piped...")
                    
            except ImportError:
                logger.warning("⚠️ invidious_api module not available, skipping Invidious")
            except Exception as inv_err:
                logger.warning(f"⚠️ Invidious (early) error: {inv_err}, trying Piped...")
        
        # ═══ المحاولة 2: Piped API (IP مختلف — سيرفرات مختلفة عن Invidious!) ═══
        # 🔴 Piped بيستخدم NewPipe Extractor — سيرفرات مختلفة عن Invidious
        # لو Invidious فشل، Piped ممكن يشتغل لأنه بيستخدم طريقة مختلفة
        if is_youtube:
            try:
                from piped_api import download_youtube_piped_file
                
                piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio"}
                piped_quality = piped_quality_map.get(quality, "best")
                
                logger.info(f"🟢 Piped (early): Attempting download quality={piped_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟢 جاري التحميل عبر Piped..." if lang == "ar"
                        else "🟢 Downloading via Piped..."
                    )
                except:
                    pass
                
                try:
                    piped_result = await asyncio.wait_for(
                        download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                        timeout=90
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Piped (early) timed out after 90s")
                    piped_result = None
                
                if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                    logger.info(f"🟢 Piped (early) succeeded! File: {piped_result['file_path']}")
                    
                    file_path = piped_result["file_path"]
                    file_size = piped_result.get("file_size", os.path.getsize(file_path))
                    real_title = piped_result.get("title", "YouTube Video")
                    real_duration = piped_result.get("duration", 0)
                    format_info = piped_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{piped_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check
                    try:
                        pp_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_pp, block_msg_pp, _reason_pp = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=pp_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_pp:
                            await message.reply_text(block_msg_pp, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Piped", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {real_title[:200]}\n📁 {size_str} | {quality_label} | Piped"
                                await message.reply_video(
                                    video=f,
                                    caption=caption,
                                    duration=int(real_duration) if real_duration else None,
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                        content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                        try: os.remove(file_path)
                                        except: pass
                                        return
                                except Exception:
                                    pass
                                await message.reply_text(
                                    f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                    else f"❌ File too large for Telegram ({size_str})"
                                )
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                    else f"❌ Failed to send video ({size_str}). Try again!"
                                )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Piped (early) نجح!
                
                logger.warning(f"⚠️ Piped (early) failed, falling back to yt-dlp...")
                    
            except ImportError:
                logger.warning("⚠️ piped_api module not available, skipping Piped")
            except Exception as piped_err:
                logger.warning(f"⚠️ Piped (early) error: {piped_err}, falling back to yt-dlp...")
        
        # ═══ المحاولة 3: yt-dlp + deno + remote_components ═══
        logger.info(f"📥 yt-dlp: Attempting download with deno+remote_components for {url[:80]}")
        ydl_opts = _get_ydl_opts(quality, output_template, platform, player_client_idx=0)
        
        try:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: _run_ytdlp(ydl_opts)),
                timeout=300  # 5 دقائق
            )
        except Exception as first_error:
            err_str = str(first_error).lower()
            last_error = first_error
            logger.warning(f"⚠️ yt-dlp first attempt failed (default+deno): {first_error}")
            
            # 🔴 لو YouTube حجبنا (bot detection) — حدث yt-dlp فوراً
            if any(kw in err_str for kw in ["sign in", "bot", "captcha", "confirm", "login", "403"]):
                logger.warning("🔴 YouTube bot detection detected! Triggering yt-dlp update...")
                trigger_ytdlp_update()
            
            # ═══ Fallback chain — نجرب طرق مختلفة ═══
            should_retry = any(kw in err_str for kw in [
                "requested format", "ffmpeg", "merge", "format not available",
                "no video formats", "unable to", "error", "http error",
                "sign in", "login", "bot", "captcha", "confirm",
                "http error 403", "forbidden", "age", "inappropriate",
            ])
            
            if not should_retry:
                raise  # خطأ مش متعلق — بنرفعه على طول
            
            is_youtube = platform.lower() == "youtube"
            
            # 🔴 FIX v5: لو YouTube — fallback chain محسّن
            if is_youtube:
                # ═══ المحاولة 2: نجرب player_clients كـ fallback ═══
                for client_idx in range(1, 1 + len(_YOUTUBE_PLAYER_CLIENTS)):
                    client_name = _YOUTUBE_PLAYER_CLIENTS[client_idx - 1][0]
                    retry_label = {
                        "android": "Android", "ios": "iOS", "mweb": "Mobile Web", "tv": "TV", "web": "Web"
                    }.get(client_name, client_name)
                    
                    logger.info(f"🔄 Trying YouTube with {client_name} player_client (attempt {client_idx + 1})...")
                    
                    try:
                        await status_msg.edit_text(
                            f"🔄 جاري تجربة طريقة تانية ({retry_label})..." if lang == "ar" 
                            else f"🔄 Trying another method ({retry_label})..."
                        )
                    except:
                        pass
                    
                    fallback_opts = _get_ydl_opts(quality, output_template, platform, player_client_idx=client_idx)
                    
                    try:
                        info = await asyncio.wait_for(
                            loop.run_in_executor(None, lambda o=fallback_opts: _run_ytdlp(o)),
                            timeout=300
                        )
                        if info is not None:
                            logger.info(f"✅ Download succeeded with {client_name} player_client!")
                            break
                    except Exception as retry_error:
                        last_error = retry_error
                        err_str_retry = str(retry_error).lower()
                        logger.warning(f"⚠️ Attempt {client_idx + 1} ({client_name}) also failed: {retry_error}")
                        
                        bot_keywords = ["sign in", "bot", "confirm", "captcha", "login", "403"]
                        if not any(kw in err_str_retry for kw in bot_keywords):
                            break
                
                # ═══ المحاولة 3: Cobalt API (fallback تالت — أسرع وأضمن من yt-dlp بدون كوكيز) ═══
                # 🔴 لو yt-dlp فشل مع player_clients → Cobalt أضمن من تجربة yt-dlp تاني
                if info is None:
                    logger.info("🟠 yt-dlp player_clients failed, trying Cobalt API as 3rd fallback...")
                    try:
                        await status_msg.edit_text(
                            "🟠 جاري التحميل عبر Cobalt..." if lang == "ar"
                            else "🟠 Downloading via Cobalt..."
                        )
                    except:
                        pass
                    
                    try:
                        cobalt_3rd_result = await _try_cobalt_for_youtube(url, quality, tmpdir)
                        
                        if cobalt_3rd_result and cobalt_3rd_result.get("filepath"):
                            logger.info(f"🟠 Cobalt (3rd fallback) succeeded! File: {cobalt_3rd_result['filepath']}")
                            
                            cb_file_path = cobalt_3rd_result.get("file_path", cobalt_3rd_result["filepath"])
                            cb_file_size = cobalt_3rd_result.get("size", os.path.getsize(cb_file_path))
                            cb_title = cobalt_3rd_result.get("title", "YouTube Video")
                            cb_height = cobalt_3rd_result.get("height", 720)
                            
                            cb_size_mb = cb_file_size / (1024 * 1024)
                            cb_size_str = f"{cb_size_mb:.1f}MB"
                            
                            # 🛡️ Safety check on Cobalt downloaded media
                            try:
                                cb_file_type = "audio" if _is_audio_quality(quality) else "video"
                                is_safe_cb, block_msg_cb, _reason_cb = await comprehensive_media_safety_check(
                                    title=cb_title, file_path=cb_file_path, file_type=cb_file_type,
                                    platform="telegram", user_id=str(user_id), lang=lang,
                                )
                                if not is_safe_cb:
                                    await message.reply_text(block_msg_cb, parse_mode="HTML")
                                    try: os.remove(cb_file_path)
                                    except: pass
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            increment_usage(user_id, "youtube_summaries")
                            try: track_event("media_downloads")
                            except: pass
                            
                            await status_msg.delete()
                            
                            if _is_audio_quality(quality):
                                bitrate = _get_audio_bitrate(quality)
                                audio_sent = await _send_telegram_audio(message, cb_file_path, cb_title, cb_size_str, lang, method_name="Cobalt", bitrate=bitrate)
                                if audio_sent:
                                    try: os.remove(cb_file_path)
                                    except: pass
                                    return
                                # 🔴 لو الإرسال فشل — نجرب Supabase
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=cb_file_path, filename=f"{cb_title[:50]}.mp3",
                                        content_type="audio/mpeg", platform="telegram",
                                        title=cb_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML")
                                        try: await status_msg.delete()
                                        except: pass
                                        try: os.remove(cb_file_path)
                                        except: pass
                                        return  # ✅ رفع السحابة نجح
                                except:
                                    pass
                                if lang == "ar":
                                    await message.reply_text(f"❌ فشل إرسال الصوت ({cb_size_str}). جرب تاني!")
                                else:
                                    await message.reply_text(f"❌ Failed to send audio ({cb_size_str}). Try again!")
                                try: os.remove(cb_file_path)
                                except: pass
                                return
                            else:
                                try:
                                    with open(cb_file_path, 'rb') as f:
                                        tech_info = f"{cb_height}p | {cb_size_str} | Cobalt"
                                        caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {cb_title[:200]}\n📊 {tech_info}"
                                        await message.reply_video(
                                            video=f, filename=f"{cb_title[:50]}.mp4",
                                            caption=caption,
                                            parse_mode="HTML",
                                            supports_streaming=True,
                                        )
                                except Exception as send_err:
                                    logger.warning(f"⚠️ Cobalt video send failed (likely too large): {send_err}")
                                    # 🔴 لو الإرسال فشل — نجرب Supabase
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=cb_file_path, filename=f"{cb_title[:50]}.mp4",
                                            content_type="video/mp4", platform="telegram",
                                            title=cb_title, lang=lang,
                                        )
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                            try: await status_msg.delete()
                                            except: pass
                                            try: os.remove(cb_file_path)
                                            except: pass
                                            return  # ✅ رفع السحابة نجح
                                    except:
                                        pass
                                    if lang == "ar":
                                        await message.reply_text(f"❌ فشل إرسال الفيديو ({cb_size_str}). جرب تاني!")
                                    else:
                                        await message.reply_text(f"❌ Failed to send video ({cb_size_str}). Try again!")
                            
                            try: os.remove(cb_file_path)
                            except: pass
                            return  # ✅ Cobalt (3rd fallback) نجح!
                        
                        logger.warning(f"⚠️ Cobalt (3rd fallback) also failed, trying Apify...")
                    except Exception as cobalt_3rd_err:
                        logger.warning(f"⚠️ Cobalt (3rd fallback) error: {cobalt_3rd_err}, trying Apify...")
                
                # ═══ المحاولة 4: Apify — fallback رابع (سيرفرات مختلفة عن YouTube خالص) ═══
                # 🔵 Apify بيستخدم actors عشان يحمل الفيديو — مش بيتأثر بـ bot detection
                if info is None:
                    logger.info("🔵 Cobalt failed, trying Apify as 4th fallback...")
                    try:
                        await status_msg.edit_text(
                            "🔵 جاري التحميل عبر Apify..." if lang == "ar"
                            else "🔵 Downloading via Apify..."
                        )
                    except:
                        pass
                    
                    try:
                        from apify_download import download_youtube_apify
                        
                        apify_result = await asyncio.wait_for(
                            download_youtube_apify(url, quality, tmpdir),
                            timeout=150  # Apify بيستنى الـ actor يخلص
                        )
                        
                        if apify_result and apify_result.get("success") and apify_result.get("filepath"):
                            logger.info(f"🔵 Apify (4th fallback) succeeded! File: {apify_result['filepath']}")
                            
                            af_file_path = apify_result["filepath"]
                            af_file_size = apify_result.get("size", os.path.getsize(af_file_path))
                            af_title = apify_result.get("title", "YouTube Video")
                            af_height = apify_result.get("height", 720)
                            
                            af_size_mb = af_file_size / (1024 * 1024)
                            af_size_str = f"{af_size_mb:.1f}MB"
                            
                            # 🛡️ Safety check on Apify downloaded media
                            try:
                                af_file_type = "audio" if _is_audio_quality(quality) else "video"
                                is_safe_af, block_msg_af, _reason_af = await comprehensive_media_safety_check(
                                    title=af_title, file_path=af_file_path, file_type=af_file_type,
                                    platform="telegram", user_id=str(user_id), lang=lang,
                                )
                                if not is_safe_af:
                                    await message.reply_text(block_msg_af, parse_mode="HTML")
                                    try: os.remove(af_file_path)
                                    except: pass
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            increment_usage(user_id, "youtube_summaries")
                            try: track_event("media_downloads")
                            except: pass
                            
                            await status_msg.delete()
                            
                            if _is_audio_quality(quality):
                                bitrate = _get_audio_bitrate(quality)
                                audio_sent = await _send_telegram_audio(message, af_file_path, af_title, af_size_str, lang, method_name="Apify", bitrate=bitrate)
                                if audio_sent:
                                    try: os.remove(af_file_path)
                                    except: pass
                                    return
                                # 🔴 لو الإرسال فشل — نجرب Supabase
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=af_file_path, filename=f"{af_title[:50]}.mp3",
                                        content_type="audio/mpeg", platform="telegram",
                                        title=af_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML")
                                        try: await status_msg.delete()
                                        except: pass
                                        try: os.remove(af_file_path)
                                        except: pass
                                        return  # ✅ رفع السحابة نجح
                                except:
                                    pass
                                if lang == "ar":
                                    await message.reply_text(f"❌ فشل إرسال الصوت ({af_size_str}). جرب تاني!")
                                else:
                                    await message.reply_text(f"❌ Failed to send audio ({af_size_str}). Try again!")
                                try: os.remove(af_file_path)
                                except: pass
                                return
                            else:
                                try:
                                    with open(af_file_path, 'rb') as f:
                                        tech_info = f"{af_height}p | {af_size_str} | Apify"
                                        caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {af_title[:200]}\n📊 {tech_info}"
                                        await message.reply_video(
                                            video=f, filename=f"{af_title[:50]}.mp4",
                                            caption=caption,
                                            parse_mode="HTML",
                                            supports_streaming=True,
                                        )
                                except Exception as send_err:
                                    logger.warning(f"⚠️ Apify video send failed (likely too large): {send_err}")
                                    # 🔴 لو الإرسال فشل — نجرب Supabase
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=af_file_path, filename=f"{af_title[:50]}.mp4",
                                            content_type="video/mp4", platform="telegram",
                                            title=af_title, lang=lang,
                                        )
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                            try: await status_msg.delete()
                                            except: pass
                                            try: os.remove(af_file_path)
                                            except: pass
                                            return  # ✅ رفع السحابة نجح
                                    except:
                                        pass
                                    if lang == "ar":
                                        await message.reply_text(f"❌ فشل إرسال الفيديو ({af_size_str}). جرب تاني!")
                                    else:
                                        await message.reply_text(f"❌ Failed to send video ({af_size_str}). Try again!")
                            
                            try: os.remove(af_file_path)
                            except: pass
                            return  # ✅ Apify (4th fallback) نجح!
                        
                        logger.warning(f"⚠️ Apify (4th fallback) also failed, trying yt-dlp without cookies...")
                    except ImportError:
                        logger.warning("⚠️ Apify module not available, trying yt-dlp without cookies...")
                    except asyncio.TimeoutError:
                        logger.warning(f"⚠️ Apify timed out, trying yt-dlp without cookies...")
                    except Exception as apify_err:
                        logger.warning(f"⚠️ Apify error: {apify_err}, trying yt-dlp without cookies...")
                
                # ═══ المحاولة 5: كل الطرق فشلت — نجرب بدون كوكيز ═══
                if info is None:
                    logger.info("🔄 All methods failed (including Cobalt & Apify), trying WITHOUT cookies...")
                    
                    try:
                        await status_msg.edit_text(
                            "🔄 جاري تجربة طريقة نظيفة (بدون كوكيز)..." if lang == "ar" 
                            else "🔄 Trying clean method (no cookies)..."
                        )
                    except:
                        pass
                    
                    clean_opts = _get_ydl_opts(quality, output_template, platform, player_client_idx=0)
                    clean_opts.pop('cookiefile', None)
                    
                    logger.info("🔄 Clean attempt (default+deno, no cookies)...")
                    
                    try:
                        info = await asyncio.wait_for(
                            loop.run_in_executor(None, lambda o=clean_opts: _run_ytdlp(o)),
                            timeout=300
                        )
                        if info is not None:
                            logger.info("✅ Download succeeded with default+deno (no cookies)!")
                    except Exception as clean_error:
                        last_error = clean_error
                        logger.warning(f"⚠️ Clean attempt (no cookies) failed: {clean_error}")
                        
                        android_clean = _get_ydl_opts(quality, output_template, platform, player_client_idx=1)
                        android_clean.pop('cookiefile', None)
                        
                        try:
                            info = await asyncio.wait_for(
                                loop.run_in_executor(None, lambda o=android_clean: _run_ytdlp(o)),
                                timeout=300
                            )
                            if info is not None:
                                logger.info("✅ Download succeeded with android (no cookies)!")
                        except Exception as ac_error:
                            last_error = ac_error
                            logger.warning(f"⚠️ Android clean attempt also failed: {ac_error}")
        
        # ═══ المحاولة 5: Invidious API (تم تجربته فوق — هنا fallback إضافي لو حاجة اتغيرت) ═══
        # 🔴 لو Invidious (early) فشل فوق، مش هنجرب تاني هنا عشان مفيش فايدة
        # بس لو info لسه None (يعني كل المحاولات فوق فشلت) هنحاول مرة تانية
        # مع instance مختلف يمكن
        if info is None and is_youtube:
            try:
                from invidious_api import download_youtube_invidious_file
                
                inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                    "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                inv_quality = inv_quality_map.get(quality, "audio" if _is_audio_quality(quality) else "best")
                
                logger.info(f"🟣 Invidious: Attempting download quality={inv_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟣 جاري التحميل عبر Invidious..." if lang == "ar"
                        else "🟣 Downloading via Invidious..."
                    )
                except:
                    pass
                
                try:
                    invidious_result = await asyncio.wait_for(
                        download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                        timeout=60
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Invidious timed out after 60s")
                    invidious_result = None
                
                if invidious_result and invidious_result.get("success") and invidious_result.get("file_path"):
                    logger.info(f"🟣 Invidious succeeded! File: {invidious_result['file_path']}")
                    
                    file_path = invidious_result["file_path"]
                    file_size = invidious_result.get("file_size", os.path.getsize(file_path))
                    real_title = invidious_result.get("title", "YouTube Video")
                    real_duration = invidious_result.get("duration", 0)
                    format_info = invidious_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "") or format_info.get("resolution", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{inv_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check on Invidious downloaded media
                    try:
                        inv_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_inv, block_msg_inv, _reason_inv = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=inv_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_inv:
                            await message.reply_text(block_msg_inv, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass  # Fail-open
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Invidious", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                tech_info = f"{quality_label} | {size_str} | Invidious"
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {real_title[:200]}\n📊 {tech_info}"
                                await message.reply_video(
                                    video=f, filename=f"{real_title[:50]}.mp4",
                                    caption=caption,
                                    parse_mode="HTML",
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            logger.warning(f"⚠️ Invidious video send failed (likely too large): {send_err}")
                            # 🔴 لو الملف كبير → رفع على Supabase فوراً
                            try:
                                from supabase_storage import upload_and_get_link
                                cloud_msg = await upload_and_get_link(
                                    file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                    content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                )
                                if cloud_msg:
                                    await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                    try: await status_msg.delete()
                                    except: pass
                                    try: os.remove(file_path)
                                    except: pass
                                    return
                            except Exception:
                                pass
                            await message.reply_text(
                                f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send video ({size_str}). Try again!"
                            )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Invidious نجح!
                
                error_code = invidious_result.get("error", "unknown") if invidious_result else "unknown"
                logger.warning(f"⚠️ Invidious failed ({error_code}), trying Cobalt Self-Hosted...")
                    
            except ImportError:
                logger.warning("⚠️ invidious_api module not available, skipping Invidious")
            except Exception as inv_err:
                logger.warning(f"⚠️ Invidious error: {inv_err}, trying Piped...")
        
        # ═══ المحاولة 6: Piped API (تم تجربته فوق — هنا fallback إضافي) ═══
        if info is None and is_youtube:
            try:
                from piped_api import download_youtube_piped_file
                
                piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio"}
                piped_quality = piped_quality_map.get(quality, "best")
                
                logger.info(f"🟢 Piped: Attempting download quality={piped_quality} for {url[:80]}")
                
                try:
                    await status_msg.edit_text(
                        "🟢 جاري التحميل عبر Piped..." if lang == "ar"
                        else "🟢 Downloading via Piped..."
                    )
                except:
                    pass
                
                try:
                    piped_result = await asyncio.wait_for(
                        download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                        timeout=90
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Piped timed out after 90s")
                    piped_result = None
                
                if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                    logger.info(f"🟢 Piped succeeded! File: {piped_result['file_path']}")
                    
                    file_path = piped_result["file_path"]
                    file_size = piped_result.get("file_size", os.path.getsize(file_path))
                    real_title = piped_result.get("title", "YouTube Video")
                    real_duration = piped_result.get("duration", 0)
                    format_info = piped_result.get("format_info", {})
                    
                    quality_label = format_info.get("quality_label", "")
                    if not quality_label:
                        if _is_audio_quality(quality):
                            quality_label = "MP3"
                        else:
                            quality_label = f"{piped_quality} quality"
                    
                    size_mb = file_size / (1024 * 1024)
                    size_str = f"{size_mb:.1f}MB"
                    
                    # 🛡️ Safety check on Piped downloaded media
                    try:
                        pp_file_type = "audio" if _is_audio_quality(quality) else "video"
                        is_safe_pp, block_msg_pp, _reason_pp = await comprehensive_media_safety_check(
                            title=real_title, file_path=file_path, file_type=pp_file_type,
                            platform="telegram", user_id=str(user_id), lang=lang,
                        )
                        if not is_safe_pp:
                            await message.reply_text(block_msg_pp, parse_mode="HTML")
                            try: os.remove(file_path)
                            except: pass
                            return
                    except Exception:
                        pass  # Fail-open
                    
                    increment_usage(user_id, "youtube_summaries")
                    try: track_event("media_downloads")
                    except: pass
                    
                    await status_msg.delete()
                    
                    if _is_audio_quality(quality):
                        bitrate = _get_audio_bitrate(quality)
                        audio_sent = await _send_telegram_audio(message, file_path, real_title, size_str, lang, method_name="Piped", bitrate=bitrate)
                        if audio_sent:
                            try: os.remove(file_path)
                            except: pass
                            return
                        # 🔴 لو الإرسال فشل — نجرب Supabase
                        try:
                            from supabase_storage import upload_and_get_link
                            cloud_msg = await upload_and_get_link(
                                file_path=file_path, filename=f"{real_title[:50]}.mp3",
                                content_type="audio/mpeg", platform="telegram", title=real_title, lang=lang,
                            )
                            if cloud_msg:
                                await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                try: await status_msg.delete()
                                except: pass
                                try: os.remove(file_path)
                                except: pass
                                return
                        except:
                            pass
                        await message.reply_text(
                            f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                            else f"❌ Failed to send audio ({size_str}). Try again!"
                        )
                        try: os.remove(file_path)
                        except: pass
                        return
                    else:
                        try:
                            with open(file_path, 'rb') as f:
                                caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {real_title[:200]}\n📁 {size_str} | {quality_label} | Piped"
                                await message.reply_video(
                                    video=f,
                                    caption=caption,
                                    duration=int(real_duration) if real_duration else None,
                                    supports_streaming=True,
                                )
                        except Exception as send_err:
                            if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                # 🔴 لو الملف كبير → رفع على Supabase فوراً
                                try:
                                    from supabase_storage import upload_and_get_link
                                    cloud_msg = await upload_and_get_link(
                                        file_path=file_path, filename=f"{real_title[:50]}.mp4",
                                        content_type="video/mp4", platform="telegram", title=real_title, lang=lang,
                                    )
                                    if cloud_msg:
                                        await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                        try: await status_msg.delete()
                                        except: pass
                                        try: os.remove(file_path)
                                        except: pass
                                        return
                                except Exception:
                                    pass
                                await message.reply_text(
                                    f"❌ الملف كبير على التليجرام ({size_str})" if lang == "ar"
                                    else f"❌ File too large for Telegram ({size_str})"
                                )
                            else:
                                await message.reply_text(
                                    f"❌ فشل إرسال الفيديو ({size_str}). جرب تالي!" if lang == "ar"
                                    else f"❌ Failed to send video ({size_str}). Try again!"
                                )
                    
                    try: os.remove(file_path)
                    except: pass
                    return  # ✅ Piped نجح!
                
                error_code = piped_result.get("error", "unknown") if piped_result else "unknown"
                logger.warning(f"⚠️ Piped failed ({error_code}), trying Cobalt Self-Hosted...")
                    
            except ImportError:
                logger.warning("⚠️ piped_api module not available, skipping Piped")
            except Exception as piped_err:
                logger.warning(f"⚠️ Piped error: {piped_err}, trying Cobalt Self-Hosted...")
        
        # ═══ المحاولة 7: Cobalt Self-Hosted (fallback) ═══
        cobalt_result = None
        if info is None:
            cobalt_result = await _try_cobalt_download(url, quality, tmpdir)
        
        if cobalt_result:
            logger.info(f"🔵 Cobalt Self-Hosted succeeded! Sending file directly...")
            filepath = cobalt_result["filepath"]
            filename = cobalt_result["filename"]
            filesize = cobalt_result["size"]
            video_height = cobalt_result.get("height", 720)
            video_title = cobalt_result.get("title", "Video")
            video_vcodec = "h264"
            video_acodec = "aac"
            
            info = {
                "title": video_title,
                "duration": cobalt_result.get("duration", 0),
                "height": video_height,
                "vcodec": "h264",
                "acodec": "aac",
                "requested_downloads": [{"height": video_height, "vcodec": "h264", "acodec": "aac"}],
            }
        
        # ═══ المحاولة 8: Cobalt JWT — آخر طبقة قبل Cloudflare Worker ═══
        # 🔴 ده JWT شخصي من cobalt.tools — بنستخدمه كـ آخر حل لو كل حاجة فشلت
        # ليه آخر واحد؟ لأن الـ JWT بيتجدد وبيوقف — مش حل دائم
        # بس لو شغال هيحل المشكلة وقتها
        if info is None and is_youtube:
            try:
                from config import COBALT_JWT
                
                if COBALT_JWT:
                    logger.info(f"🔐 Cobalt JWT: Last-resort attempt for {url[:80]}")
                    
                    try:
                        await status_msg.edit_text(
                            "🔐 جاري التحميل عبر Cobalt JWT..." if lang == "ar"
                            else "🔐 Downloading via Cobalt JWT..."
                        )
                    except:
                        pass
                    
                    jwt_quality_map = {"best": "1080", "medium": "720", "low": "480", "audio": "720"}
                    jwt_quality = jwt_quality_map.get(quality, "720")
                    is_jwt_audio = _is_audio_quality(quality)
                    
                    jwt_headers = {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Authorization": f"Bearer {COBALT_JWT}",
                    }
                    
                    jwt_payload = {
                        "url": url,
                        "videoQuality": jwt_quality,
                        "filenameStyle": "classic",
                    }
                    
                    if is_jwt_audio:
                        jwt_payload["downloadMode"] = "audio"
                        jwt_payload["audioFormat"] = "mp3"
                    
                    jwt_result = await _cobalt_api_request(
                        "https://api.cobalt.tools", jwt_payload, jwt_headers,
                        jwt_quality, is_jwt_audio, tmpdir
                    )
                    
                    if jwt_result and jwt_result.get("filepath"):
                        logger.info(f"🔐 Cobalt JWT succeeded! File: {jwt_result['filepath']}")
                        
                        file_path = jwt_result["filepath"]
                        file_size = jwt_result.get("size", os.path.getsize(file_path))
                        video_title = jwt_result.get("title", "YouTube Video")
                        video_height = jwt_result.get("height", 720)
                        
                        size_mb = file_size / (1024 * 1024)
                        size_str = f"{size_mb:.1f}MB"
                        
                        # 🛡️ Safety check on Cobalt JWT downloaded media
                        try:
                            jwt_file_type = "audio" if _is_audio_quality(quality) else "video"
                            is_safe_jwt, block_msg_jwt, _reason_jwt = await comprehensive_media_safety_check(
                                title=video_title, file_path=file_path, file_type=jwt_file_type,
                                platform="telegram", user_id=str(user_id), lang=lang,
                            )
                            if not is_safe_jwt:
                                await message.reply_text(block_msg_jwt, parse_mode="HTML")
                                try: os.remove(file_path)
                                except: pass
                                return
                        except Exception:
                            pass  # Fail-open
                        
                        increment_usage(user_id, "youtube_summaries")
                        try: track_event("media_downloads")
                        except: pass
                        
                        await status_msg.delete()
                        
                        if _is_audio_quality(quality):
                            bitrate = _get_audio_bitrate(quality)
                            audio_sent = await _send_telegram_audio(message, file_path, video_title, size_str, lang, method_name="Cobalt JWT", bitrate=bitrate)
                            if audio_sent:
                                try: os.remove(file_path)
                                except: pass
                                return
                            # 🔴 لو الإرسال فشل — نجرب Supabase
                            try:
                                from supabase_storage import upload_and_get_link
                                cloud_msg = await upload_and_get_link(
                                    file_path=file_path, filename=f"{video_title[:50]}.mp3",
                                    content_type="audio/mpeg", platform="telegram", title=video_title, lang=lang,
                                )
                                if cloud_msg:
                                    await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                    try: os.remove(file_path)
                                    except: pass
                                    return
                            except:
                                pass
                            await message.reply_text(
                                f"❌ فشل إرسال الصوت ({size_str}). جرب تاني!" if lang == "ar"
                                else f"❌ Failed to send audio ({size_str}). Try again!"
                            )
                            try: os.remove(file_path)
                            except: pass
                            return
                        else:
                            try:
                                with open(file_path, 'rb') as f:
                                    tech_info = f"{video_height}p | {size_str} | Cobalt JWT"
                                    caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {video_title[:200]}\n📊 {tech_info}"
                                    await message.reply_video(
                                        video=f, filename=f"{video_title[:50]}.mp4",
                                        caption=caption,
                                        parse_mode="HTML",
                                        supports_streaming=True,
                                    )
                            except Exception as send_err:
                                logger.warning(f"⚠️ Cobalt JWT video send failed: {send_err}")
                                if "too large" in str(send_err).lower() or "file is too big" in str(send_err).lower():
                                    # 🔴 لو الملف كبير → رفع على Supabase فوراً
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=jwt_file_path, filename=f"{jwt_title[:50]}.mp4",
                                            content_type="video/mp4", platform="telegram", title=jwt_title, lang=lang,
                                        )
                                        if cloud_msg:
                                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                                            try: await status_msg.delete()
                                            except: pass
                                            try: os.remove(jwt_file_path)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    await message.reply_text(
                                        f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                        else f"❌ Failed to send video ({size_str}). Try again!"
                                    )
                                else:
                                    await message.reply_text(
                                        f"❌ فشل إرسال الفيديو ({size_str}). جرب تاني!" if lang == "ar"
                                        else f"❌ Failed to send video ({size_str}). Try again!"
                                    )
                        
                        try: os.remove(file_path)
                        except: pass
                        return  # ✅ Cobalt JWT نجح!
                    
                    logger.warning(f"⚠️ Cobalt JWT failed, trying Cloudflare Worker...")
                else:
                    logger.info("🔐 Cobalt JWT: No COBALT_JWT configured, skipping")
            except Exception as jwt_err:
                logger.warning(f"⚠️ Cobalt JWT error: {jwt_err}")
        
        # ═══ المحاولة 9: Cloudflare Worker (آخر محاولة نهائية) ═══
        if info is None and is_youtube:
            from config import CLOUDFLARE_WORKER_URL
            if CLOUDFLARE_WORKER_URL:
                logger.info(f"🔄 All methods failed, trying Cloudflare Worker: {CLOUDFLARE_WORKER_URL}")
                try:
                    await status_msg.edit_text(
                        "🔄 جاري التحميل عبر سيرفر خاص..." if lang == "ar"
                        else "🔄 Downloading via proxy server..."
                    )
                except:
                    pass
                
                try:
                    import requests as sync_requests
                    from urllib.parse import quote
                    worker_url = CLOUDFLARE_WORKER_URL.rstrip("/")
                    dl_type = "audio" if _is_audio_quality(quality) else "video"
                    api_url = f"{worker_url}/download?url={quote(url)}&type={dl_type}"
                    
                    cf_response = sync_requests.get(api_url, timeout=120, stream=True)
                    
                    if cf_response.status_code == 200:
                        content_type = cf_response.headers.get('Content-Type', '')
                        if 'video' in content_type or 'audio' in content_type or 'octet-stream' in content_type:
                            ext = "mp3" if _is_audio_quality(quality) else "mp4"
                            cf_filename = f"youtube_cf.{ext}"
                            cf_filepath = os.path.join(tmpdir, cf_filename)
                            
                            with open(cf_filepath, 'wb') as cf_f:
                                for chunk in cf_response.iter_content(chunk_size=8192):
                                    cf_f.write(chunk)
                            
                            cf_size = os.path.getsize(cf_filepath)
                            if cf_size > 0:
                                info = {
                                    "title": "YouTube Video",
                                    "duration": 0,
                                    "height": 720,
                                    "vcodec": "h264",
                                    "acodec": "aac",
                                    "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                                }
                                logger.info(f"✅ Cloudflare Worker download succeeded! Size: {cf_size // (1024*1024)}MB")
                            else:
                                os.remove(cf_filepath)
                        else:
                            try:
                                cf_data = cf_response.json()
                                if cf_data.get("url"):
                                    stream_url = cf_data["url"]
                                    ext = "mp3" if _is_audio_quality(quality) else "mp4"
                                    cf_filename = f"youtube_cf.{ext}"
                                    cf_filepath = os.path.join(tmpdir, cf_filename)
                                    
                                    dl_resp = sync_requests.get(stream_url, timeout=120, stream=True, headers={
                                        'User-Agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 14)',
                                        'Referer': 'https://www.youtube.com/',
                                    })
                                    
                                    if dl_resp.status_code == 200:
                                        with open(cf_filepath, 'wb') as cf_f:
                                            for chunk in dl_resp.iter_content(chunk_size=8192):
                                                cf_f.write(chunk)
                                        
                                        cf_size = os.path.getsize(cf_filepath)
                                        if cf_size > 0:
                                            info = {
                                                "title": "YouTube Video",
                                                "duration": 0,
                                                "height": 720,
                                                "vcodec": "h264",
                                                "acodec": "aac",
                                                "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                                            }
                                            logger.info(f"✅ CF Worker stream URL download succeeded! Size: {cf_size // (1024*1024)}MB")
                                        else:
                                            os.remove(cf_filepath)
                            except Exception as cf_json_err:
                                logger.warning(f"⚠️ CF Worker JSON parse error: {cf_json_err}")
                    else:
                        logger.warning(f"⚠️ CF Worker returned status {cf_response.status_code}")
                except Exception as cf_err:
                    logger.warning(f"⚠️ Cloudflare Worker fallback failed: {cf_err}")
            else:
                logger.info("⚠️ CLOUDFLARE_WORKER_URL not set, skipping CF Worker fallback")
        
        # ═══ البحث عن الملف المحمل ═══
        if info is None and last_error:
            raise last_error
        
        downloaded_files = os.listdir(tmpdir)
        if not downloaded_files:
            await status_msg.edit_text("❌ فشل التحميل — ملف مش موجود." if lang == "ar" else "❌ Download failed — file not found.")
            return
        
        filepath = os.path.join(tmpdir, downloaded_files[0])
        filesize = os.path.getsize(filepath)
        filename = downloaded_files[0]
        
        # 🔴 FIX v4: استخراج معلومات الجودة الحقيقية من info dict
        video_height = 0
        video_vcodec = ""
        video_acodec = ""
        if info:
            # لو فيه requested_downloads (بعد التحميل الفعلي)
            req_dl = info.get("requested_downloads", [])
            if req_dl:
                dl_info = req_dl[0]
                video_height = dl_info.get("height", 0) or 0
                # كوديك الفيديو
                vcodec_note = dl_info.get("vcodec", "") or ""
                acodec_note = dl_info.get("acodec", "") or ""
                video_vcodec = vcodec_note.split('.')[0] if vcodec_note else ""
                video_acodec = acodec_note.split('.')[0] if acodec_note else ""
            
            # fallback: من الـ info نفسه
            if not video_height:
                video_height = info.get("height", 0) or 0
            if not video_vcodec:
                vcodec = info.get("vcodec", "") or ""
                video_vcodec = vcodec.split('.')[0] if vcodec else ""
            if not video_acodec:
                acodec = info.get("acodec", "") or ""
                video_acodec = acodec.split('.')[0] if acodec else ""
        
        # لو مفيش info عن الكوديك، نجيبها بـ ffprobe
        if _is_ffmpeg_available() and quality != "audio" and (not video_vcodec or video_vcodec == "none"):
            try:
                probe_result = subprocess.run(
                    ['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
                     '-show_entries', 'stream=codec_name,width,height',
                     '-of', 'csv=p=0', filepath],
                    capture_output=True, timeout=10, text=True
                )
                if probe_result.returncode == 0 and probe_result.stdout.strip():
                    parts = probe_result.stdout.strip().split(',')
                    if len(parts) >= 3:
                        video_vcodec = parts[0]
                        try: 
                            h = int(parts[2])
                            video_height = h if h > (video_height or 0) else video_height
                        except (ValueError, IndexError): pass
                    elif len(parts) >= 1:
                        video_vcodec = parts[0]
            except Exception:
                pass
        
        # 🔴 FIX v4: لو الكوديك مش h264 والملف فيديو، نعمل remux لـ h264
        # عشان Telegram مش بيشغل VP9/AV1
        if (_is_ffmpeg_available() and quality != "audio" 
            and video_vcodec and video_vcodec not in ("h264", "avc1", "avc", "mpeg4", "")):
            logger.info(f"🔧 Video codec is {video_vcodec}, converting to h264 for Telegram compatibility...")
            try:
                converted_path = filepath + "_h264.mp4"
                convert_result = subprocess.run(
                    ['ffmpeg', '-i', filepath,
                     '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                     '-c:a', 'aac', '-b:a', '128k',
                     '-movflags', '+faststart',
                     '-y', converted_path],
                    capture_output=True, timeout=180
                )
                if convert_result.returncode == 0 and os.path.exists(converted_path):
                    converted_size = os.path.getsize(converted_path)
                    if converted_size > 0:
                        os.remove(filepath)
                        filepath = converted_path
                        filename = os.path.basename(filepath)
                        filesize = converted_size
                        video_vcodec = "h264"
                        logger.info(f"✅ Converted to h264: {filesize // (1024*1024)}MB")
                    else:
                        os.remove(converted_path)
                else:
                    if os.path.exists(converted_path):
                        os.remove(converted_path)
                    logger.warning(f"⚠️ h264 conversion failed, keeping original: {convert_result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ h264 conversion timed out, keeping original")
                try:
                    if os.path.exists(filepath + "_h264.mp4"):
                        os.remove(filepath + "_h264.mp4")
                except: pass
            except Exception as conv_err:
                logger.warning(f"⚠️ h264 conversion error: {conv_err}")
        
        # تحديد الدقة كنص
        if video_height:
            if video_height >= 1080: quality_label = "1080p"
            elif video_height >= 720: quality_label = "720p"
            elif video_height >= 480: quality_label = "480p"
            elif video_height >= 360: quality_label = "360p"
            else: quality_label = f"{video_height}p"
        else:
            quality_names_map = {"best": "1080p", "medium": "720p", "low": "480p"}
            quality_label = quality_names_map.get(quality, quality)
        
        logger.info(f"✅ Downloaded: {filename} ({filesize // (1024*1024)}MB, {quality_label}, codec={video_vcodec})")
        
        # ═══ إرسال الملف — Direct Send أو Supabase Cloud Upload ═══
        #
        # 🔴 المسار الجديد (بدون تجربة جودة أقل — على طول السحابة):
        # 1. لو الملف > 2GB → جودة أقل (الاستثناء الوحيد)
        # 2. لو الملف > 50MB → رفع على Supabase فوراً + بعت رابط
        # 3. لو الملف <= 50MB → إرسال مباشر
        # 4. لو الإرسال المباشر فشل → نحاول كـ document → Supabase
        #
        TELEGRAM_MAX_FREE = 50 * 1024 * 1024     # 50MB — بوت مجاني
        TELEGRAM_MAX_PREMIUM = 2000 * 1024 * 1024  # 2GB — بوت premium
        
        if filesize > TELEGRAM_MAX_PREMIUM:
            # فوق 2GB — ده الحد الأقصى الحقيقي
            if quality != "audio":
                if lang == "ar":
                    await status_msg.edit_text(f"⏳ جاري تحميل جودة أقل...")
                else:
                    await status_msg.edit_text(f"⏳ Trying lower quality...")
                os.remove(filepath)
                lower_quality = {"best": "medium", "medium": "low", "low": "audio"}.get(quality, "medium")
                # 🔴 FIX: نمرر status_msg=None عشان ينشئ واحد جديد — القديم ممكن يكون اتمسح
                return await _download_with_ytdlp(update_or_query, url, lower_quality, lang, user_id, status_msg=None)
            else:
                if lang == "ar":
                    await status_msg.edit_text(f"❌ الملف كبير جداً ({filesize // (1024*1024)}MB). الحد الأقصى 2GB.\n💡 جرب تحميل صوت أقل جودة.")
                else:
                    await status_msg.edit_text(f"❌ File too large ({filesize // (1024*1024)}MB). Maximum is 2GB.\n💡 Try downloading lower quality audio.")
                return
        
        # تتبع
        increment_usage(user_id, "youtube_summaries")
        try: track_event("media_downloads")
        except: pass
        
        # 🛡️ Safety check on downloaded media before sending
        try:
            dl_file_type = "audio" if _is_audio_quality(quality) else "video"
            dl_title = info.get("title", filename) if info else filename
            is_safe_dl, block_msg_dl, _reason_dl = await comprehensive_media_safety_check(
                title=dl_title, file_path=filepath, file_type=dl_file_type,
                platform="telegram", user_id=str(user_id), lang=lang,
            )
            if not is_safe_dl:
                await message.reply_text(block_msg_dl, parse_mode="HTML")
                try: shutil.rmtree(tmpdir, ignore_errors=True)
                except: pass
                return
        except Exception:
            pass  # Fail-open
        
        # إرسال الملف
        title = info.get("title", filename) if info else filename
        duration = info.get("duration", 0) if info else 0
        
        # 🔴 FIX v5: لو الجودة صوت، نتأكد إن الملف فعلاً صوت بس
        # بعض طرق التحميل بترجع فيديو حتى لو طلبنا صوت
        if _is_audio_quality(quality):
            bitrate = _get_audio_bitrate(quality)
            filepath = _ensure_audio_only(filepath, bitrate)
            if os.path.exists(filepath):
                filesize = os.path.getsize(filepath)
                filename = os.path.basename(filepath)
        
        # 🔴 FIX v4: معلومات الجودة الحقيقية في الـ caption
        size_mb = filesize / (1024 * 1024)
        size_str = f"{size_mb:.1f}MB"
        
        # 🔴 FIX: منحذفش status_msg هنا — ممكن نحتاجه لو الإرسال فشل
        # بنحذفه بس لو الإرسال نجح
        send_failed = False
        is_too_large = False
        
        if _is_audio_quality(quality):
            bitrate = _get_audio_bitrate(quality)
            audio_sent = await _send_telegram_audio(message, filepath, title, size_str, lang, bitrate=bitrate)
            if audio_sent:
                try: await status_msg.delete()
                except: pass
            else:
                send_failed = True
                is_too_large = filesize > TELEGRAM_MAX_FREE
                logger.warning(f"⚠️ Audio send failed | is_too_large={is_too_large}")
        else:
            try:
                with open(filepath, 'rb') as f:
                    # معلومات الجودة + الكوديك
                    tech_info = f"{quality_label} | {size_str}"
                    if video_vcodec and video_vcodec not in ("None", ""):
                        tech_info += f" | {video_vcodec}"
                    caption = f"📥 {'تم تحميل الفيديو!' if lang == 'ar' else 'Video downloaded!'}\n🎬 {title[:200]}\n📊 {tech_info}"
                    await message.reply_video(
                        video=f, filename=filename,
                        caption=caption,
                        parse_mode="HTML",
                        duration=int(duration) if duration else None,
                        supports_streaming=True,
                    )
                # ✅ الإرسال نجح — نحذف status_msg
                try: await status_msg.delete()
                except: pass
            except Exception as send_err:
                send_failed = True
                # 🔴 FIX: نفرق بين "ملف كبير" و "خطأ تاني"
                err_str = str(send_err).lower()
                # 🔴 FIX: نقول "كبير" بس لو فعلاً عدى الحد
                file_exceeds_limit = filesize > TELEGRAM_MAX_FREE  # 50MB — ده الحد الحقيقي للبوت المجاني
                is_too_large = file_exceeds_limit and any(kw in err_str for kw in ["too large", "file is too big", "file too large", "exceeds", "413"])
                logger.warning(f"⚠️ Video send failed: {send_err} | is_too_large={is_too_large} | file_size={filesize}")
        
        # 🔴 FIX v5: لو الإرسال فشل — Supabase Cloud Upload (مع ضغط تلقائي) → جودة أقل → خطأ
        if send_failed:
            if is_too_large or filesize > TELEGRAM_MAX_FREE:
                # الملف كبير (>50MB) — نحاول رفعه على Supabase (مع ضغط تلقائي)
                # 🔴 FIX v3: Supabase free tier = 50MB limit. upload_and_get_link auto-compresses.
                logger.info(f"☁️ File too large for Telegram ({size_str}), uploading to Supabase (with auto-compression)...")
                
                try:
                    await status_msg.edit_text(
                        "☁️ جاري ضغط الملف ورفعه على السحابة..." if lang == "ar" else "☁️ Compressing and uploading to cloud..."
                    )
                except:
                    pass
                
                # 🔴 رفع على Supabase (مع ضغط تلقائي لو > 50MB)
                cloud_success = False
                try:
                    from supabase_storage import upload_and_get_link
                    content_type = "audio/mpeg" if _is_audio_quality(quality) else "video/mp4"
                    ext = ".mp3" if _is_audio_quality(quality) else ".mp4"
                    safe_name = re.sub(r'[^\w\-.]', '_', title[:80]) + ext
                    
                    cloud_msg = await upload_and_get_link(
                        file_path=filepath,
                        filename=safe_name,
                        content_type=content_type,
                        platform="telegram",
                        title=title,
                        lang=lang,
                    )
                    
                    if cloud_msg:
                        # ✅ رفع السحابة نجح — نبعت الرابط
                        await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                        try: await status_msg.delete()
                        except: pass
                        cloud_success = True
                        try: shutil.rmtree(tmpdir, ignore_errors=True)
                        except: pass
                        return
                    else:
                        logger.warning("☁️ Supabase upload returned None (compression may have failed)")
                except Exception as sup_err:
                    logger.error(f"☁️ Supabase upload error: {sup_err}")
                
                if not cloud_success:
                    # 🔴 Supabase فشل — نجرب جودة أقل كآخر محاولة
                    logger.error(f"☁️ Supabase upload failed, trying lower quality")
                    if quality != "low" and quality != "audio":
                        # نجرب نحمل بجودة أقل
                        if lang == "ar":
                            await message.reply_text("⏳ فشل رفع الملف على السحابة. جاري تجربة جودة أقل...")
                        else:
                            await message.reply_text("⏳ Cloud upload failed. Trying lower quality...")
                        try: await status_msg.delete()
                        except: pass
                        try: shutil.rmtree(tmpdir, ignore_errors=True)
                        except: pass
                        # إعادة المحاولة بجودة أقل
                        lower_quality = {"best": "medium", "medium": "low"}.get(quality, "low")
                        # This is handled by the callback query handler, so we just return
                        return
                    else:
                        if lang == "ar":
                            await message.reply_text("❌ فشل رفع الملف على السحابة. جرب تاني!")
                        else:
                            await message.reply_text("❌ Failed to upload file to cloud. Try again!")
                        try: await status_msg.delete()
                        except: pass
                        return
            
            elif quality != "audio":
                # مشكلة تانية (مش حجم) — نجرب نبعته كـ document
                logger.info(f"⚠️ Video send failed (not size), trying send as document...")
                try:
                    with open(filepath, 'rb') as f:
                        await message.reply_document(
                            document=f, filename=filename,
                            caption=f"📥 {title[:200]}\n📁 {size_str}",
                        )
                    # لو وصل كـ document — نعتبره نجاح
                    try: os.remove(filepath)
                    except: pass
                    try: await status_msg.delete()
                    except: pass
                    return
                except Exception as doc_err:
                    logger.warning(f"⚠️ Document send also failed: {doc_err}")
                    
                    # 🔴 حتى الـ document فشل — نجرب Supabase كحل أخير
                    try:
                        from supabase_storage import upload_and_get_link
                        content_type = "video/mp4"
                        safe_name = re.sub(r'[^\w\-.]', '_', title[:80]) + ".mp4"
                        cloud_msg = await upload_and_get_link(
                            file_path=filepath,
                            filename=safe_name,
                            content_type=content_type,
                            platform="telegram",
                            title=title,
                            lang=lang,
                        )
                        if cloud_msg:
                            await message.reply_text(cloud_msg, parse_mode="HTML", disable_web_page_preview=False)
                            try: await status_msg.delete()
                            except: pass
                            return
                    except Exception as sup_err2:
                        logger.error(f"☁️ Final Supabase attempt failed: {sup_err2}")
                    
                    if lang == "ar":
                        await message.reply_text(f"❌ فشل إرسال الفيديو. جرب تاني!")
                    else:
                        await message.reply_text(f"❌ Failed to send video. Try again!")
                    try: await status_msg.delete()
                    except: pass
                    return
            
            else:
                # audio فشل بس مش بسبب حجم — نحاول Supabase
                try:
                    from supabase_storage import upload_and_get_link
                    safe_name = re.sub(r'[^\w\-.]', '_', title[:80]) + ".mp3"
                    cloud_msg = await upload_and_get_link(
                        file_path=filepath,
                        filename=safe_name,
                        content_type="audio/mpeg",
                        platform="telegram",
                        title=title,
                        lang=lang,
                    )
                    if cloud_msg:
                        await message.reply_text(cloud_msg, parse_mode="HTML")
                        try: await status_msg.delete()
                        except: pass
                        return
                except:
                    pass
                
                if lang == "ar":
                    await message.reply_text(f"❌ فشل إرسال الصوت. جرب تاني!")
                else:
                    await message.reply_text(f"❌ Failed to send audio. Try again!")
                try: await status_msg.delete()
                except: pass
    
    except asyncio.TimeoutError:
        logger.error("yt-dlp download timed out")
        try:
            await status_msg.edit_text("❌ انتهى وقت التحميل. جرب جودة أقل." if lang == "ar" else "❌ Download timed out. Try a lower quality.")
        except: pass
    
    except Exception as e:
        logger.error(f"Error in yt-dlp download: {e}", exc_info=True)
        error_hint = ""
        err_str = str(e).lower()
        
        # 🔴 FIX v3: رسائل خطأ أوضح مع نصائح حقيقية
        if "sign in" in err_str or "confirm you" in err_str or "bot" in err_str:
            # YouTube bot detection — نصايح حقيقية
            cookies_hint = ""
            if not cookies_available:
                cookies_hint = (
                    "\n\n🍪 <b>نصيحة:</b> لو المشكلة مستمرة، الأدمن يقدر يرفع ملف cookies.txt بأمر /cookies"
                    if lang == "ar" else
                    "\n\n🍪 <b>Tip:</b> If this keeps happening, admin can upload a cookies.txt file with /cookies"
                )
            error_hint = (
                f"\n💡 YouTube طلب تسجيل دخول — ده مش من الرابط، ده من YouTube نفسه.{cookies_hint}"
                if lang == "ar" else
                f"\n💡 YouTube requested sign-in — this isn't about the link, it's YouTube's bot detection.{cookies_hint}"
            )
        elif "private" in err_str and "sign in" not in err_str:
            error_hint = "\n💡 المحتوى خاص ومش متاح للتحميل." if lang == "ar" else "\n💡 Content is private and cannot be downloaded."
        elif "not found" in err_str or "404" in err_str or "does not exist" in err_str:
            error_hint = "\n💡 الرابط مش موجود أو اتمسح." if lang == "ar" else "\n💡 URL not found or deleted."
        elif "geo" in err_str or "country" in err_str or "region" in err_str or "blocked" in err_str:
            error_hint = "\n💡 المحتوى مش متاح في المنطقة دي." if lang == "ar" else "\n💡 Content not available in this region."
        elif "ffmpeg" in err_str or "merge" in err_str:
            error_hint = "\n💡 مشكل في تحويل الفيديو. جرب صوت بس." if lang == "ar" else "\n💡 Video conversion issue. Try audio only."
        elif "format" in err_str or "no video" in err_str:
            error_hint = "\n💡 التنسيق مش متاح. جرب جودة تانية أو صوت بس." if lang == "ar" else "\n💡 Format unavailable. Try another quality or audio only."
        elif "copyright" in err_str or "unavailable" in err_str:
            error_hint = "\n💡 المحتوى مش متاح للتحميل." if lang == "ar" else "\n💡 Content unavailable for download."
        elif "login" in err_str:
            error_hint = "\n💡 المحتوى محتاج حساب. جرب رابط تاني." if lang == "ar" else "\n💡 Content requires account. Try a different link."
        else:
            error_hint = f"\n💡 {str(e)[:150]}" 
            logger.error(f"📥 Unhandled download error for {url}: {e}")
        
        try:
            await status_msg.edit_text(f"❌ {'فشل التحميل' if lang == 'ar' else 'Download failed'}.{error_hint}")
        except:
            try:
                await message.reply_text(f"❌ {'فشل التحميل' if lang == 'ar' else 'Download failed'}.{error_hint}")
            except: pass
    
    finally:
        try: shutil.rmtree(tmpdir, ignore_errors=True)
        except: pass


# ═══════════════════════════════════════
# معالجة أزرار التحميل
# ═══════════════════════════════════════

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
    
    await _download_with_ytdlp(query, url, quality, lang, user_id)


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


def _merge_cookies(existing_content: str, new_content: str) -> str:
    """دمج كوكيز جديدة مع الملف الموجود — منضيفش كوكيز مكررة (حسب name+domain)"""
    # 🍪 بنبني dict من الكوكيز الموجودة — المفتاح هو (domain, name)
    existing_cookies = {}
    header_lines = []  # سطور الهيدر والتعليقات
    existing_cookie_lines = []
    
    for line in existing_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            header_lines.append(line)
            continue
        parts = stripped.split('\t')
        if len(parts) >= 7:
            domain = parts[0]
            name = parts[5]
            key = (domain.lower(), name.lower())
            existing_cookies[key] = line
            existing_cookie_lines.append(line)
        else:
            # سطر مش كوكيز — نسيبه
            header_lines.append(line)
    
    # 🍪 بنفحص الكوكيز الجديدة — منضيف بس اللي مش موجود
    new_added = 0
    new_yt_added = 0
    new_cookie_lines = []
    
    for line in new_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue  # نتجاهل تعليقات الملف الجديد
        parts = stripped.split('\t')
        if len(parts) >= 7:
            domain = parts[0]
            name = parts[5]
            key = (domain.lower(), name.lower())
            if key not in existing_cookies:
                existing_cookies[key] = line
                new_cookie_lines.append(line)
                new_added += 1
                if 'youtube.com' in domain.lower():
                    new_yt_added += 1
    
    # 🍪 نبني النتيجة: هيدر → كوكيز قديمة → كوكيز جديدة
    result_lines = []
    
    # هيدر Netscape لو مش موجود
    has_netscape_header = any('# Netscape HTTP Cookie File' in h for h in header_lines)
    if not has_netscape_header:
        result_lines.append('# Netscape HTTP Cookie File')
        result_lines.append('# https://curl.se/docs/http-cookies.html')
        result_lines.append('# This file was generated automatically! Edit at your own risk.')
        result_lines.append('')
    
    # سطور الهيدر الأصلية (باستثناء Netscape header لو حطينا واحد جديد)
    for h in header_lines:
        if '# Netscape HTTP Cookie File' in h:
            continue
        if '# https://curl.se/docs/http-cookies.html' in h:
            continue
        if '# This file was generated automatically' in h:
            continue
        result_lines.append(h)
    
    # كوكيز أصلية
    result_lines.extend(existing_cookie_lines)
    
    # كوكيز جديدة
    result_lines.extend(new_cookie_lines)
    
    return '\n'.join(result_lines), new_added, new_yt_added


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
