"""Download handlers - shared utilities.

Audio quality helpers, ensure_audio_only, send_audio_file, URL caching,
platform detection, cookies helpers, ffmpeg check, quality keyboards,
and shared constants.
"""

import logging
import os
import re
import time
import hashlib
import subprocess

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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


