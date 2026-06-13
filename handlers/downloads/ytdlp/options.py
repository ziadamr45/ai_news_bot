"""yt-dlp options generation.

Contains _get_ydl_opts — generates yt-dlp download options based on quality,
platform, ffmpeg availability, and player client configuration.
"""

import logging

from handlers.downloads.utils import (
    _is_audio_quality,
    _get_audio_bitrate,
    _is_ffmpeg_available,
    _get_cookies_file,
    _ensure_deno_in_path,
    _YOUTUBE_PLAYER_CLIENTS,
    _USER_AGENT,
)

logger = logging.getLogger(__name__)


def _get_ydl_opts(quality: str, output_template: str, platform: str = "", 
                  use_ffmpeg: bool = True, player_client_idx: int = 0) -> dict:
    """إعداد خيارات yt-dlp حسب الجودة والمنصة وتوفر ffmpeg
    
    🔴 FIX v3: 
    - بنضيف cookies.txt لو موجود — الحل الأقوى لتخطي bot detection
    - 🔴 الكوكيز الوهمية اتشالت نهائيًا — مش بتفيد وبتضر
    - بنستخدم player_client=mweb أولًا (أقل كشف) مع fallback لـ android → ios → tv → web
    - بنكشف ffmpeg تلقائي وبنعدل التنسيقات حسب التوفر
    """
    ffmpeg_ok = use_ffmpeg and _is_ffmpeg_available()
    platform_lower = platform.lower() if platform else ""
    # 🔴 FIX: لازم نعرّف is_youtube و platform_lower جوه الدالة
    # platform بتتباصى من _detect_platform() — لو فاضي بنعامل كأنه YouTube
    is_youtube = platform_lower == "youtube" or platform_lower == ""
    
    # 🔴 الكوكيز الوهمية اتشالت نهائيًا!
    # الكوكيز الوهمية (visitor cookies) بتضر أكتر مما تنفع لأن:
    # 1. YouTube بيكتشف إنها random/generated وبيعتبرنا bot
    # 2. كل محاولة بتولد visitor_id مختلف = سلوك مش طبيعي
    # 3. yt-dlp بيدير كوكيز YouTube داخليًا حسب player_client
    # بنستخدم الكوكيز الوهمية بس للمنصات التانية
    
    # 🔴 الكوكيز الوهمية اتشالت نهائيًا — مش بتفيد وبتضر
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
        # Facebook/Instagram مش بيوفر separate video+audio دايمًا
        # فبنفضل pre-merged formats (best[ext=mp4]) عشان نتجنب مشاكل الدمج
        
        is_facebook_family = platform_lower in ("facebook", "instagram", "threads")
        
        if ffmpeg_ok:
            if is_facebook_family:
                # 🔴 FIX v5: Facebook family — بنفضل pre-merged formats بقوة عشان:
                # 1. Facebook بيوفر فيديوهات pre-merged بجودة عالية
                # 2. دمج separate streams من Facebook بيدي فيديو شاشة سوداء
                # 3. Pre-merged بتكون h264 جاهزة للتليجرام
                # 4. بنحط pre-mergedmp4 الأول دايمًا عشان نتجنب مشاكل الدمج
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
    
    # 🔴 PO Token مش بيضاف هنا — بيضاف بس كـ fallback في download_main.py
    # لو أضفناه هنا → هيكون في كل محاولة بما فيها الأولى
    # ولو الـ token باطل → هيخلي المحاولة الأولى تفشل وهي كانت هتنجح بدونه
    # فبنضيفه بس كـ fallback منفصل بعد ما الطرق العادية تفشل
    
    return opts
