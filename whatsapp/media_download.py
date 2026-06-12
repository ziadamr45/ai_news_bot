"""
WhatsApp Video Download & Quality Selection
=============================================
Video download and quality selection functions for WhatsApp bot.

Extracted from whatsapp/media.py for modularity.
"""

import os
import re
import json
import logging
import asyncio
import tempfile
import shutil
import subprocess
import aiohttp
import requests

from whatsapp.state import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_API_URL,
    _detect_platform,
    _is_youtube_url,
    _is_threads_url,
    _store_url,
)

from whatsapp.api import (
    _send_whatsapp_message,
    _send_whatsapp_image,
    _send_whatsapp_document_from_file,
    _send_whatsapp_audio,
    _send_whatsapp_video,
    _send_interactive_list,
    ThinkingFeedback,
)

from content_safety import (
    comprehensive_media_safety_check,
)

logger = logging.getLogger(__name__)

async def _download_threads_media_wa(url: str, tmpdir: str) -> dict | None:
    """تحميل فيديو/صورة من Threads — نفس الـ fallback chain زي التليجرام
    
    🔴 الترتيب (مزامنة مع download_handlers.py v5):
    0. Playwright headless browser — الأضمن (بيرندر الصفحة ويسحب الفيديو)
    1. RapidAPI — الأسرع (لو المفتاح متاح)
    2. data-sjs JSON parsing — استخراج من <script data-sjs> tags في HTML
       ⚠️ video_versions بيبقي null دلوقتي → شغال للصور بس
    3. GraphQL API — طلب مباشر من threads.net/api/graphql
    4. Cobalt API — خدمة مفتوحة المصدر كـ fallback
    
    Returns: dict فيه {success, file_path, title, is_video} أو None
    """
    try:
        # 🔴 نستورد الدوال المشتركة من download_handlers (نفس الكود بالظبط)
        from handlers.download_handlers import _download_threads_media as _tg_threads_download
        
        logger.info(f"🧵 Threads WA: Using shared download (Playwright → RapidAPI → data-sjs → GraphQL → Cobalt)")
        
        result = await _tg_threads_download(url, tmpdir, quality="best")
        
        if result and result.get("success"):
            logger.info(f"🧵 Threads WA: Download succeeded via {result.get('method', 'unknown')} method")
            return result
        
        logger.warning(f"🧵 Threads WA: All methods failed for {url[:80]}")
        return None
    
    except Exception as e:
        logger.warning(f"🧵 Threads WA: Error using shared download: {e}")
        return None



async def _show_quality_selection(wa_id: str, url: str, wa_user_id: int, 
                                   contact_name: str, message_id: str = "", is_admin: bool = False):
    """Show quality selection buttons for video download (like Telegram)"""
    platform = _detect_platform(url)
    platform_names = {
        "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
        "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
        "threads": "Threads", "reddit": "Reddit", "dailymotion": "Dailymotion",
        "soundcloud": "SoundCloud", "unknown": "🌐",
    }
    platform_display = platform_names.get(platform, platform)
    url_key = _store_url(url)
    
    body = f"📥 *اختار الجودة*\n\n🔗 المنصة: {platform_display}"
    
    await _send_interactive_list(wa_id, 
        body_text=body,
        button_text="اختار الجودة",
        sections=[{
            "title": "جودة الفيديو",
            "rows": [
                {"id": f"dl_v_b_{url_key}", "title": "🎬 أعلى جودة", "description": "1080p - أفضل جودة متاحة"},
                {"id": f"dl_v_m_{url_key}", "title": "📹 جودة متوسطة", "description": "720p - توازن بين الجودة والحجم"},
                {"id": f"dl_v_l_{url_key}", "title": "📱 جودة منخفضة", "description": "480p - حجم صغير"},
            ],
        }, {
            "title": "صوت فقط",
            "rows": [
                {"id": f"dl_a_{url_key}", "title": "🎵 صوت بس MP3", "description": "استخراج الصوت فقط"},
            ],
        }],
        header_text=f"📥 تحميل من {platform_display}")




async def _show_quality_selection_for_search(wa_id: str, url: str, title: str, 
                                              wa_user_id: int, contact_name: str, 
                                              message_id: str, is_admin: bool,
                                              search_type: str = "video"):
    """عرض اختيار الجودة بعد اختيار نتيجة من البحث — نفس قائمة التحميل العادي
    
    🔴 الفرق عن _show_quality_selection:
    - دي بتتكلم بعد اختيار نتيجة بحث (مش بعد إرسال رابط)
    - لو search_type="audio" → بتحط خيار الصوت كأول اختيار
    - بتعرض عنوان الفيديو كمان
    """
    platform = _detect_platform(url)
    platform_names = {
        "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
        "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
        "threads": "Threads", "reddit": "Reddit", "dailymotion": "Dailymotion",
        "soundcloud": "SoundCloud", "unknown": "🌐",
    }
    platform_display = platform_names.get(platform, platform)
    url_key = _store_url(url)
    
    display_title = title[:50] if title else "فيديو"
    body = f"📥 *اختار الجودة*\n\n📺 {display_title}\n🔗 المنصة: {platform_display}"
    
    # 🔴 لو البحث كان صوت → نحط خيارات الصوت بس (مفيش فيديو — المستخدم طلب صوت)
    if search_type == "audio":
        sections = [{
            "title": "🎵 جودة الصوت",
            "rows": [
                {"id": f"dl_aq_320_{url_key}", "title": "🎧 320kbps", "description": "أعلى جودة صوت - وضوح ممتاز"},
                {"id": f"dl_aq_192_{url_key}", "title": "🎵 192kbps", "description": "جودة عالية - توازن مثالي"},
                {"id": f"dl_aq_128_{url_key}", "title": "🎶 128kbps", "description": "جودة متوسطة - حجم أقل"},
                {"id": f"dl_aq_64_{url_key}", "title": "📻 64kbps", "description": "جودة منخفضة - حجم صغير جداً"},
            ],
        }]
    else:
        sections = [{
            "title": "🎬 جودة الفيديو",
            "rows": [
                {"id": f"dl_v_b_{url_key}", "title": "🎬 أعلى جودة", "description": "1080p - أفضل جودة متاحة"},
                {"id": f"dl_v_m_{url_key}", "title": "📹 جودة متوسطة", "description": "720p - توازن بين الجودة والحجم"},
                {"id": f"dl_v_l_{url_key}", "title": "📱 جودة منخفضة", "description": "480p - حجم صغير"},
            ],
        }, {
            "title": "🎵 صوت فقط",
            "rows": [
                {"id": f"dl_a_{url_key}", "title": "🎵 صوت بس MP3", "description": "استخراج الصوت فقط"},
            ],
        }]
    
    await _send_interactive_list(wa_id, 
        body_text=body,
        button_text="اختار الجودة",
        sections=sections,
        header_text=f"📥 تحميل من {platform_display}")



async def _download_and_send_video(wa_id: str, url: str, wa_user_id: int,
                                     contact_name: str, message_id: str = "", is_admin: bool = False,
                                     quality: str = "best", force_audio: bool = False):
    """Download a video and send it via WhatsApp — Invidious/Piped FIRST then yt-dlp
    
    🔴 FIX v11: نفس fallback chain زي التليجرام بالظبط!
    0. 🖥️ سيرفر التحميل الخاص (VPS بـ IP نظيف)
    1. 🟣 Invidious API (IP مختلف — مش من Railway!)
    2. 🟢 Piped API (IP مختلف — سيرفرات مختلفة عن Invidious)
    3. yt-dlp + deno + remote_components + كوكيز
    4. yt-dlp player_client fallback (android → ios → mweb → tv → web) + كوكيز
    5. 🟠 Cobalt API
    6. 🔵 Apify
    7. 🔄 yt-dlp WITHOUT cookies (أحياناً الكوكيز بتسبب مشاكل!) — جديد!
    8. 🟢 Piped API (fallback إضافي)
    9. 🟣 Invidious API (fallback إضافي)
    10. 🔵 Cobalt Self-Hosted — جديد!
    11. 🔐 Cobalt JWT
    12. 🔄 Cloudflare Worker proxy (آخر محاولة)
    
    WhatsApp has a 100MB media size limit. For larger files, we send the download link instead.
    
    quality: "best" (1080p), "medium" (720p), "low" (480p), "audio" (MP3)
    force_audio: if True, force audio-only download regardless of quality param
    """
    # If force_audio, override quality
    if force_audio:
        quality = "audio"
    # Start thinking feedback
    feedback = ThinkingFeedback(wa_id, message_id, context_type="download")
    await feedback.start()
    
    try:
        import yt_dlp
        
        platform = _detect_platform(url)
        is_youtube = _is_youtube_url(url)  # 🔴 FIX: لازم نعرّف is_youtube هنا عشان الكود اللي بعد كده يستخدمه
        is_threads = _is_threads_url(url)   # 🔴 FIX: Threads مش مدعوم من yt-dlp
        platform_names = {
            "youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram",
            "tiktok": "TikTok", "twitter": "Twitter/X", "telegram": "Telegram",
            "threads": "Threads", "reddit": "Reddit", "dailymotion": "Dailymotion",
            "soundcloud": "SoundCloud", "unknown": "🌐",
        }
        platform_display = platform_names.get(platform, platform)
        
        # Send progress message
        _is_audio_dl = (quality == "audio" or quality.startswith("audio_"))
        if is_threads:
            # 🔴 Threads فيديو → هيتبعت كملف مباشر (زي التليجرام!)
            await _send_whatsapp_message(wa_id, f"🧵 جاري تحميل فيديو Threads...")
        elif _is_audio_dl:
            # 🔴 FIX: لو تحميل صوت → نقول صوت مش فيديو
            await _send_whatsapp_message(wa_id, f"🎵 جاري تحميل الصوت من {platform_display}...")
        else:
            await _send_whatsapp_message(wa_id, f"📥 جاري تحميل الفيديو من {platform_display}...")
        
        tmpdir = tempfile.mkdtemp(prefix="mybro_wa_dl_")
        output_template = os.path.join(tmpdir, "%(title).80s.%(ext)s")
        
        # 🔴 FIX: Threads — yt-dlp مش بيدعمه، نستخدم طريقة مخصصة
        if is_threads:
            logger.info(f"🧵 WhatsApp: Threads detected — using custom download method")
            threads_result = await _download_threads_media_wa(url, tmpdir)
            
            if threads_result and threads_result.get("success"):
                file_path = threads_result["file_path"]
                file_size = threads_result.get("file_size", os.path.getsize(file_path))
                real_title = threads_result.get("title", "Threads Post")
                is_video = threads_result.get("is_video", True)
                size_mb = file_size / (1024 * 1024)
                size_str = f"{size_mb:.1f}MB"
                
                # 🛡️ Safety check on downloaded media (زي التليجرام بالظبط)
                try:
                    media_type = "video" if is_video else "image"
                    is_safe_dl, block_msg_dl, _reason_dl = await comprehensive_media_safety_check(
                        title=real_title, file_path=file_path, file_type=media_type,
                        platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                    )
                    if not is_safe_dl:
                        await _send_whatsapp_message(wa_id, block_msg_dl)
                        try: os.remove(file_path)
                        except: pass
                        await feedback.error()
                        return
                except Exception:
                    pass  # Fail-open
                
                # ═══ إرسال الملف — فيديو: رفع على السحابة مباشرة | صورة: إرسال مباشر ═══
                
                if is_video:
                    # ═══════════════════════════════════════════════════════════
                    # 🔴 FIX v10: فيديوهات Threads على واتساب
                    # نفس طريقة الفيديوهات العادية (YouTube وغيرها):
                    # إرسال كـ document (ملف) بدل video — أضمن بكثير!
                    # ═══════════════════════════════════════════════════════════
                    
                    # 🔴 Step 1: تحويل لـ H.264+AAC+MP4 لو مش كده (زي الفيديوهات العادية)
                    try:
                        import subprocess as _sp
                        import multiprocessing
                        conv_threads = min(multiprocessing.cpu_count(), 4)
                        
                        # فحص الكودك الحالي بـ ffprobe
                        probe_result = _sp.run(
                            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', file_path],
                            capture_output=True, timeout=15
                        )
                        video_vcodec = None
                        if probe_result.returncode == 0:
                            try:
                                import json as _json
                                probe_data = _json.loads(probe_result.stdout)
                                for stream in probe_data.get('streams', []):
                                    if stream.get('codec_type') == 'video':
                                        video_vcodec = stream.get('codec_name', '')
                                        break
                            except Exception:
                                pass
                        
                        # تحويل بس لو مش H.264
                        if video_vcodec and video_vcodec not in ("h264", "avc1", "avc", "mpeg4", ""):
                            converted_path = file_path + "_h264.mp4"
                            logger.info(f"🧵 Threads WA: Converting {video_vcodec} to H.264 for WhatsApp...")
                            
                            conv_cmd = [
                                'ffmpeg', '-y', '-i', file_path,
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                                '-threads', str(conv_threads),
                                '-c:a', 'aac', '-b:a', '128k',
                                '-movflags', '+faststart',
                                '-y', converted_path
                            ]
                            
                            conv_result = _sp.run(conv_cmd, capture_output=True, timeout=180)
                            
                            if conv_result.returncode == 0 and os.path.exists(converted_path) and os.path.getsize(converted_path) > 1000:
                                try: os.remove(file_path)
                                except: pass
                                file_path = converted_path
                                file_size = os.path.getsize(file_path)
                                size_mb = file_size / (1024 * 1024)
                                size_str = f"{size_mb:.1f}MB"
                                logger.info(f"🧵 Threads WA: ✅ H.264 conversion OK! Size: {size_str}")
                            else:
                                logger.warning(f"🧵 Threads WA: Conversion failed, using original file")
                                try: os.remove(converted_path)
                                except: pass
                        else:
                            logger.info(f"🧵 Threads WA: Video is already H.264 ({video_vcodec}), no conversion needed")
                    except ImportError:
                        pass
                    except Exception as conv_err:
                        logger.warning(f"🧵 Threads WA: Conversion check error: {conv_err}")
                    
                    # 🔴 Step 2: إرسال كـ document (ملف) — نفس طريقة الفيديوهات العادية!
                    # ده أضمن بكتير من إرسال كـ video عشان واتساب مش بيرفض الملفات
                    MAX_WHATSAPP_DIRECT_SIZE = 25 * 1024 * 1024  # 25MB — زي الفيديوهات العادية
                    
                    if file_size <= MAX_WHATSAPP_DIRECT_SIZE:
                        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', real_title) + '.mp4'
                        caption = f"📥 {real_title[:200]}\n🧵 Threads\n📊 {size_str}"
                        
                        logger.info(f"🧵 Threads WA: Sending as document ({size_str})...")
                        result = await _send_whatsapp_document_from_file(
                            wa_id, file_path, safe_filename, caption, "video/mp4"
                        )
                        
                        if "error" not in result:
                            logger.info(f"🧵 Threads WA: ✅ Document send succeeded!")
                            await feedback.success()
                            try: os.remove(file_path)
                            except: pass
                            return
                        else:
                            error_msg = str(result.get("error", ""))
                            logger.warning(f"🧵 Threads WA: Document send failed: {error_msg}")
                    
                    # 🔴 Step 3: لو الملف أكبر من 25MB أو الإرسال المباشر فشل → رفع على السحابة
                    logger.info(f"🧵 Threads WA: Trying Supabase cloud upload...")
                    
                    # 🔴 Silent: no user message for cloud upload
                    
                    try:
                        from supabase_storage import upload_and_get_link
                        cloud_msg = await asyncio.wait_for(
                            upload_and_get_link(
                                file_path=file_path,
                                filename=f"threads_video.mp4",
                                content_type="video/mp4",
                                platform="whatsapp",
                                title=real_title,
                                lang="ar",
                            ),
                            timeout=600
                        )
                        
                        if cloud_msg:
                            await _send_whatsapp_message(wa_id, cloud_msg)
                            await feedback.success()
                            try: os.remove(file_path)
                            except: pass
                            logger.info(f"🧵 Threads WA: ✅ Supabase upload succeeded!")
                            return
                        else:
                            logger.error(f"🧵 Threads WA: Supabase returned None!")
                    except asyncio.TimeoutError:
                        logger.error(f"🧵 Threads WA: Supabase upload timed out after 600s")
                    except Exception as supa_err:
                        logger.error(f"🧵 Threads WA: Supabase upload exception: {supa_err}")
                    
                    # 🔴 Fallback أخير
                    await _send_whatsapp_message(wa_id, f"❌ فشل إرسال فيديو Threads ({size_str}). جرب تاني!")
                    await feedback.error()
                    
                    try: os.remove(file_path)
                    except: pass
                    return
                else:
                    # صورة
                    try:
                        with open(file_path, 'rb') as img_f:
                            media_response = requests.post(
                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                files={"file": (f"{real_title[:50]}.jpg", img_f, "image/jpeg")},
                                data={"messaging_product": "whatsapp", "type": "image"},
                                timeout=60
                            )
                            if media_response.status_code == 200:
                                media_id = media_response.json().get("id")
                                await _send_whatsapp_image(wa_id, media_id, caption=f"🧵 {real_title[:200]}\n📥 Threads")
                                await feedback.success()
                                try: os.remove(file_path)
                                except: pass
                                return
                            else:
                                logger.warning(f"⚠️ Threads WA: image upload returned {media_response.status_code}")
                    except Exception as send_err:
                        logger.warning(f"⚠️ Threads WA image send failed: {send_err}")
                    
                    await _send_whatsapp_message(wa_id, f"❌ فشل إرسال الصورة من Threads. جرب تاني!")
                    await feedback.error()
                    try: os.remove(file_path)
                    except: pass
                    return
            else:
                # 🔴 FIX v5: Threads مش مدعوم من yt-dlp — لا fallback!
                # yt-dlp بيرجع "Unsupported URL" لـ threads.com/threads.net
                logger.warning("🧵 Threads WA: All custom methods failed — yt-dlp doesn't support Threads, not trying it")
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الفيديو من Threads. جرب تاني!")
                await feedback.error()
                return
        
        # ═══════════════════════════════════════════════════════════════
        # 🔴 FIX v9: Cobalt API كـ fallback تالت!
        # نفس ترتيب التليجرام بالظبط
        # ═══════════════════════════════════════════════════════════════
        
        # ═══ المرحلة 1: yt-dlp + deno + remote_components (الأفضل!) ═══
        # 🔴 الكوكيز الوهمية اتشالت — بنستخدم headers نظيفة فقط
        # 🔴 بنستخدم cookies.txt لو موجود — الحل الأقوى
        
        try:
            # yt-dlp options — with multi-quality support (like Telegram)
            # WhatsApp limit: ~100MB for media
            
            # Quality format strings (like Telegram's download_handlers)
            is_audio_only = (quality == "audio" or quality.startswith("audio_"))
            
            # 🔴 FIX v9: Facebook family format + acodec!=none + no filesize limit
            is_facebook_family = platform in ("facebook", "instagram", "threads")
            
            if is_audio_only:
                # 🔴 FIX v2: نفس تحسينات التليجرام — audio-only format بدون /best fallback
                # الـ /best بيحمل فيديو لو مفيش audio-only format متاح
                format_str = 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio[ext=mp3]/bestaudio/best[ext=mp4]/best'
                merge_output = None
                remux = None
                progress_msg = f"🎵 جاري استخراج الصوت من {platform_display}..."
            elif platform in ("dailymotion", "soundcloud"):
                # 🔴 FIX v2: Dailymotion/SoundCloud — نفس صيغة التليجرام بالظبط!
                # Dailymotion بيوفر separate video+audio streams → لازم نجرب merge الأول
                # التليجرام بيستخدم bestvideo+bestaudio وبيشتغل → نستخدم نفس الحاجة
                if quality == "best":
                    format_str = (
                        'bestvideo[vcodec^=avc1][ext=mp4][height<=1080]+bestaudio[ext=m4a]/'
                        'bestvideo[vcodec^=avc1]+bestaudio/'
                        'bestvideo[ext=mp4][height<=1080]+bestaudio/'
                        'best[ext=mp4][height<=1080]/'
                        'best[height<=1080]/'
                        'best'
                    )
                elif quality == "medium":
                    format_str = (
                        'bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[ext=m4a]/'
                        'bestvideo[vcodec^=avc1][height<=720]+bestaudio/'
                        'bestvideo[ext=mp4][height<=720]+bestaudio/'
                        'best[ext=mp4][height<=720]/'
                        'best[height<=720]/'
                        'best'
                    )
                else:  # low
                    format_str = (
                        'bestvideo[vcodec^=avc1][height<=480]+bestaudio/'
                        'best[ext=mp4][height<=480]/'
                        'best[height<=480]/'
                        'best'
                    )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display}..."
            elif is_facebook_family:
                # Facebook family: prefer merge (bestvideo+bestaudio) for audio guarantee
                if quality == "best":
                    format_str = (
                        'bestvideo[vcodec^=avc1][height<=1080]+bestaudio/'
                        'bestvideo[ext=mp4][height<=1080]+bestaudio/'
                        'bestvideo[height<=1080]+bestaudio/'
                        'best[ext=mp4][height<=1080][acodec!=none]/'
                        'best[acodec!=none][height<=1080]/'
                        'best[height<=1080]/'
                        'best'
                    )
                elif quality == "medium":
                    format_str = (
                        'bestvideo[vcodec^=avc1][height<=720]+bestaudio/'
                        'bestvideo[ext=mp4][height<=720]+bestaudio/'
                        'bestvideo[height<=720]+bestaudio/'
                        'best[ext=mp4][height<=720][acodec!=none]/'
                        'best[acodec!=none][height<=720]/'
                        'best[height<=720]/'
                        'best'
                    )
                else:  # low
                    format_str = (
                        'best[ext=mp4][height<=480][acodec!=none]/'
                        'best[acodec!=none][height<=480]/'
                        'best[height<=480]/'
                        'best'
                    )
                merge_output = 'mp4'
                remux = None  # Don't remux — let ffmpeg merge properly
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} ({'أعلى جودة' if quality=='best' else 'جودة متوسطة' if quality=='medium' else 'جودة منخفضة'})..."
            elif quality == "best":
                format_str = (
                    'bestvideo[vcodec^=avc1][height<=1080]+bestaudio/'
                    'best[ext=mp4][height<=1080][acodec!=none]/'
                    'best[acodec!=none][height<=1080]/'
                    'best[height<=1080]/'
                    'best'
                )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} (أعلى جودة)..."
            elif quality == "medium":
                format_str = (
                    'bestvideo[vcodec^=avc1][height<=720]+bestaudio/'
                    'best[ext=mp4][height<=720][acodec!=none]/'
                    'best[acodec!=none][height<=720]/'
                    'best[height<=720]/'
                    'best'
                )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} (جودة متوسطة)..."
            else:  # low
                format_str = (
                    'best[ext=mp4][height<=480][acodec!=none]/'
                    'best[acodec!=none][height<=480]/'
                    'best[height<=480]/'
                    'best'
                )
                merge_output = 'mp4'
                remux = 'mp4'
                progress_msg = f"📥 جاري تحميل الفيديو من {platform_display} (جودة منخفضة)..."
            
            # 🔴 WhatsApp: لا نرسل رسائل تقدم وسيطة — رسالة واحدة بس (الاولى)
            # المستخدم مش شايف الخدمات — بس الشغل بيحصل في الباك اند
            
            ydl_opts = {
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 5,
                'file_access_retries': 3,
                'no_check_certificates': True,
                'format': format_str,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                },
            }
            
            if merge_output:
                ydl_opts['merge_output_format'] = merge_output
            if remux:
                ydl_opts['remux_video'] = remux
            
            # Audio-only: extract to MP3
            if is_audio_only:
                # 🔴 FIX: استخدام الـ bitrate المحدد من جودة الصوت
                audio_bitrate = '192'
                if quality.startswith("audio_"):
                    try: audio_bitrate = quality.split("_")[1]
                    except: pass
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': audio_bitrate,
                }]
            
            # ═══ إضافة كوكيز + إعدادات YouTube المحسّنة ═══
            # 🔴 FIX: استخدام _get_cookies_file() من التليجرام — بيدور في أماكن كتير
            try:
                from handlers.download_handlers import _get_cookies_file
                cookies_path = _get_cookies_file()
            except (ImportError, Exception):
                cookies_path = None
            
            # Fallback: البحث المباشر لو _get_cookies_file مش متاح
            if not cookies_path:
                cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            
            if cookies_path and os.path.exists(cookies_path):
                try:
                    ydl_opts['cookiefile'] = cookies_path
                    logger.info(f"🍪 WhatsApp: Using cookies file: {cookies_path}")
                except Exception:
                    pass
            
            # 🔴 FIX: إضافة deno + remote_components لليوتيوب (زي التليجرام بالظبط)
            # ده أفضل طريقة لتخطي bot detection — بيدي 37 تنسيق لحد 1080p
            is_youtube_platform = platform.lower() == "youtube"
            if is_youtube_platform:
                try:
                    from handlers.download_handlers import _ensure_deno_in_path
                    _ensure_deno_in_path()
                    ydl_opts['remote_components'] = ['ejs:github']
                    logger.info("🔧 WhatsApp yt-dlp: default mode + deno + remote_components (best method)")
                except Exception:
                    logger.warning("⚠️ Could not add deno/remote_components for WhatsApp yt-dlp")
            
            # 🔴 PO Token مش بيضاف هنا — بيضاف بس كـ fallback (المرحلة 1.5)
            # لو أضفناه هنا → هيكون في كل محاولة بما فيها الأولى
            # ولو الـ token باطل → هيخلي المحاولة الأولى تفشل وهي كانت هتنجح بدونه
            # فبنضيفه بس كـ fallback منفصل بعد ما الطرق العادية تفشل
            
            # Download video — Multi-stage approach
            loop = asyncio.get_event_loop()
            info = None
            last_error = None
            
            # Progress timer removed — no periodic updates
            
            # ═══ المرحلة 0: سيرفر التحميل الخاص (VPS بـ IP نظيف) ═══
            # 🔴 ده أفضل طريقة — السيرفر بيحمل من YouTube بـ IP نظيف ومبيحصلش حظر
            if is_youtube:
                try:
                    from config import DOWNLOAD_SERVICE_URL, DOWNLOAD_SERVICE_KEY
                    if DOWNLOAD_SERVICE_URL:
                        logger.info(f"🖥️ WA Download Service: Trying VPS download for {url[:80]}")
                        # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة — الشغل بصمت في الباك اند
                        
                        from urllib.parse import quote as _wa_quote
                        def wa_quote(s): return _wa_quote(s, safe='')
                        
                        import aiohttp as _aiohttp_wa_ds
                        ds_url = DOWNLOAD_SERVICE_URL.rstrip("/")
                        api_url = f"{ds_url}/download?url={wa_quote(url)}&quality={quality}&platform=whatsapp&lang=ar"
                        ds_headers = {}
                        if DOWNLOAD_SERVICE_KEY:
                            ds_headers["X-API-Key"] = DOWNLOAD_SERVICE_KEY
                        
                        try:
                            async with _aiohttp_wa_ds.ClientSession(timeout=_aiohttp_wa_ds.ClientTimeout(total=360)) as ds_session:
                                async with ds_session.get(api_url, headers=ds_headers) as ds_resp:
                                    if ds_resp.status == 200:
                                        ds_result = await ds_resp.json()
                                        if ds_result and ds_result.get("success"):
                                            logger.info(f"🖥️ WA Download Service succeeded!")
                                            
                                            
                                            # بعت الرابط للمستخدم
                                            cloud_msg = ds_result.get("cloud_msg", "")
                                            if cloud_msg:
                                                await _send_whatsapp_message(wa_id, cloud_msg)
                                            else:
                                                dl_url = ds_result.get("url", "")
                                                title = ds_result.get("title", "Video")
                                                size_mb = ds_result.get("size_mb", 0)
                                                await _send_whatsapp_message(wa_id,
                                                    f"🎬 *{title}*\n\n☁️ تم رفعه على السحابة ({size_mb:.1f}MB)\n\n🔗 رابط التحميل:\n{dl_url}"
                                                )
                                            
                                            await feedback.success()
                                            
                                            # Increment usage
                                            if not is_admin:
                                                try:
                                                    from premium import increment_usage
                                                    increment_usage(wa_user_id, "downloads")
                                                except:
                                                    pass
                                            
                                            try: shutil.rmtree(tmpdir, ignore_errors=True)
                                            except: pass
                                            return  # ✅ السيرفر الخاص نجح!
                                        else:
                                            error_msg = ds_result.get("message", "unknown error") if ds_result else "no response"
                                            logger.warning(f"🖥️ WA Download Service failed: {error_msg}")
                                    else:
                                        logger.warning(f"🖥️ WA Download Service returned status {ds_resp.status}")
                        except asyncio.TimeoutError:
                            logger.warning("🖥️ WA Download Service timed out")
                        except Exception as ds_err:
                            logger.warning(f"🖥️ WA Download Service error: {ds_err}")
                        
                        logger.info("🖥️ WA Download Service failed, falling back to local yt-dlp...")
                except ImportError:
                    pass
                except Exception as ds_outer_err:
                    logger.warning(f"🖥️ WA Download Service outer error: {ds_outer_err}")
            
            # ═══ المرحلة 1: Invidious API (IP مختلف — مش بيتأثر بـ YouTube bot detection!) ═══
            # 🔴 Invidious بيشتغل من سيرفرات مختلفة — مش من Railway IP
            # ده أحسن من yt-dlp عشان yt-dlp بيستخدم Railway IP وبيتحظر
            if is_youtube:
                try:
                    from invidious_api import download_youtube_invidious_file
                    
                    inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                       "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    inv_quality = inv_quality_map.get(quality, "best")
                    
                    logger.info(f"🟣 WA Invidious (early): Attempting download quality={inv_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    inv_result = None
                    try:
                        inv_result = await asyncio.wait_for(
                            download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                            timeout=60
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"⚠️ WA Invidious (early) timed out after 60s")
                    
                    if inv_result and inv_result.get("success") and inv_result.get("file_path"):
                        logger.info(f"🟣 WA Invidious (early) succeeded! File: {inv_result['file_path']}")
                        
                        inv_file = inv_result["file_path"]
                        inv_size = inv_result.get("file_size", os.path.getsize(inv_file))
                        inv_title = inv_result.get("title", "YouTube Video")
                        inv_duration = inv_result.get("duration", 0)
                        inv_format = inv_result.get("format_info", {})
                        
                        if inv_file and os.path.exists(inv_file):
                            target = os.path.join(tmpdir, f"{inv_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(inv_file, target)
                            except Exception:
                                target = inv_file
                            
                            # 🛡️ Safety check
                            try:
                                inv_file_type = "audio" if is_audio_only else "video"
                                is_safe_inv, block_msg_inv, _ = await comprehensive_media_safety_check(
                                    title=inv_title, file_path=target, file_type=inv_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_inv:
                                    await _send_whatsapp_message(wa_id, block_msg_inv)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass
                            
                            inv_size_mb = inv_size / (1024 * 1024)
                            inv_quality_label = inv_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{inv_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ WA Invidious (early) audio send failed: {audio_send_err}")
                            else:
                                if inv_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{inv_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {inv_title[:200]}\n📥 Invidious | {inv_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ WA Invidious (early) video send failed: {video_send_err}")
                                else:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        inv_size_str = f"{inv_size_mb:.1f}MB"
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{inv_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=inv_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Invidious: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ WA Invidious (early) failed, trying Piped...")
                except ImportError:
                    logger.warning("⚠️ invidious_api module not available, skipping Invidious")
                except Exception as inv_err:
                    logger.warning(f"⚠️ WA Invidious (early) error: {inv_err}, trying Piped...")
            
            # ═══ المرحلة 2: Piped API (IP مختلف — سيرفرات مختلفة عن Invidious!) ═══
            # 🔴 Piped بيستخدم NewPipe Extractor — سيرفرات مختلفة عن Invidious
            # لو Invidious فشل، Piped ممكن يشتغل لأنه بيستخدم طريقة مختلفة
            if is_youtube:
                try:
                    from piped_api import download_youtube_piped_file
                    
                    piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                         "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    piped_quality = piped_quality_map.get(quality, "best")
                    
                    logger.info(f"🟢 WA Piped (early): Attempting download quality={piped_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    piped_result = None
                    try:
                        piped_result = await asyncio.wait_for(
                            download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                            timeout=90
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"⚠️ WA Piped (early) timed out after 90s")
                    
                    if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                        logger.info(f"🟢 WA Piped (early) succeeded! File: {piped_result['file_path']}")
                        
                        piped_file = piped_result["file_path"]
                        piped_size = piped_result.get("file_size", os.path.getsize(piped_file))
                        piped_title = piped_result.get("title", "YouTube Video")
                        piped_duration = piped_result.get("duration", 0)
                        piped_format = piped_result.get("format_info", {})
                        
                        if piped_file and os.path.exists(piped_file):
                            target = os.path.join(tmpdir, f"{piped_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(piped_file, target)
                            except Exception:
                                target = piped_file
                            
                            # 🛡️ Safety check
                            try:
                                pp_file_type = "audio" if is_audio_only else "video"
                                is_safe_pp, block_msg_pp, _ = await comprehensive_media_safety_check(
                                    title=piped_title, file_path=target, file_type=pp_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_pp:
                                    await _send_whatsapp_message(wa_id, block_msg_pp)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass
                            
                            piped_size_mb = piped_size / (1024 * 1024)
                            piped_quality_label = piped_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{piped_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ WA Piped (early) audio send failed: {audio_send_err}")
                            else:
                                if piped_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{piped_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {piped_title[:200]}\n📥 Piped | {piped_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ WA Piped (early) video send failed: {video_send_err}")
                                else:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        piped_size_str = f"{piped_size_mb:.1f}MB"
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{piped_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=piped_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Piped: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ WA Piped (early) failed, falling back to yt-dlp...")
                except ImportError:
                    logger.warning("⚠️ piped_api module not available, skipping Piped")
                except Exception as piped_err:
                    logger.warning(f"⚠️ WA Piped (early) error: {piped_err}, falling back to yt-dlp...")
            
            # ═══ المرحلة 3: yt-dlp مباشر + deno + remote_components ═══
            try:
                def _run_ytdlp():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        return info
                
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, _run_ytdlp),
                    timeout=300  # 5 minutes max
                )
                if info:
                    logger.info(f"✅ yt-dlp download succeeded directly (deno + remote_components)")
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ yt-dlp direct download failed: {e}")
                # 🔴 لو YouTube حجبنا — حدث yt-dlp فوراً
                err_str = str(e).lower()
                if any(kw in err_str for kw in ["sign in", "bot", "captcha", "confirm", "login", "403"]):
                    logger.warning("🔴 YouTube bot detection in WA! Triggering yt-dlp update...")
                    try:
                        from handlers.download_handlers import trigger_ytdlp_update
                        trigger_ytdlp_update()
                    except Exception:
                        pass
            
            # 🔴 FIX: Retry with simpler format for non-YouTube platforms (Dailymotion/SoundCloud)
            # لو أول محاولة فشلت والمنصة مش YouTube → نجرب بـ format أبسط
            if info is None and not is_youtube:
                try:
                    retry_format = 'best'
                    retry_opts = dict(ydl_opts)
                    retry_opts['format'] = retry_format
                    # شيلنا postprocessors عشان ممكن تكون سبب المشكلة
                    retry_opts.pop('postprocessors', None)
                    retry_opts.pop('remote_components', None)
                    retry_opts.pop('merge_output_format', None)
                    retry_opts.pop('remux_video', None)
                    
                    logger.info(f"🔧 WhatsApp yt-dlp: Retrying with 'best' format for {platform}")
                    
                    def _run_ytdlp_simple():
                        with yt_dlp.YoutubeDL(retry_opts) as ydl:
                            return ydl.extract_info(url, download=True)
                    
                    info = await asyncio.wait_for(
                        loop.run_in_executor(None, _run_ytdlp_simple),
                        timeout=180
                    )
                    if info:
                        logger.info(f"✅ yt-dlp simple format retry succeeded for {platform}")
                except Exception as retry_err:
                    last_error = retry_err
                    logger.warning(f"⚠️ yt-dlp simple format retry failed for {platform}: {retry_err}")
            
            # 🔴 FIX v2: Dailymotion player API fallback — بنجرب نجيب الفيديو من الـ API مباشرة
            # لو yt-dlp فشل تمام مع Dailymotion → نجرب الـ player API
            if info is None and platform == "dailymotion":
                try:
                    logger.info(f"🔧 WhatsApp: Trying Dailymotion player API fallback for {url[:80]}")
                    dm_video_id = None
                    # استخراج الـ video ID من الرابط
                    dm_match = re.search(r'dailymotion\.com/video/([a-zA-Z0-9]+)', url)
                    if not dm_match:
                        dm_match = re.search(r'dai\.ly/([a-zA-Z0-9]+)', url)
                    if dm_match:
                        dm_video_id = dm_match.group(1)
                    
                    if dm_video_id:
                        import aiohttp as _aiohttp_dm
                        dm_api_url = f"https://www.dailymotion.com/player/metadata/video/{dm_video_id}"
                        async with _aiohttp_dm.ClientSession() as dm_session:
                            async with dm_session.get(
                                dm_api_url,
                                headers={
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                    "Accept": "application/json",
                                },
                                timeout=_aiohttp_dm.ClientTimeout(total=30)
                            ) as dm_resp:
                                if dm_resp.status == 200:
                                    dm_data = await dm_resp.json()
                                    dm_title = dm_data.get("title", "Dailymotion Video")[:80]
                                    dm_qualities = dm_data.get("qualities", {})
                                    
                                    # بنختار أفضل جودة متاحة
                                    dm_stream_url = None
                                    for q_key in ["1080", "720", "480", "380", "240", "auto"]:
                                        q_list = dm_qualities.get(q_key, [])
                                        for q_item in q_list:
                                            if q_item.get("type") == "application/mp4" and q_item.get("url"):
                                                dm_stream_url = q_item["url"]
                                                break
                                        if dm_stream_url:
                                            break
                                    
                                    if dm_stream_url:
                                        logger.info(f"🔧 Dailymotion player API: Got stream URL ({q_key}p)")
                                        # نحمل الفيديو من الـ stream URL
                                        dm_file_path = os.path.join(tmpdir, f"{dm_title[:50]}.mp4")
                                        async with dm_session.get(
                                            dm_stream_url,
                                            timeout=_aiohttp_dm.ClientTimeout(total=180)
                                        ) as dl_resp:
                                            if dl_resp.status == 200:
                                                dm_file_size = 0
                                                with open(dm_file_path, 'wb') as dm_f:
                                                    async for chunk in dl_resp.content.iter_chunked(8192):
                                                        dm_f.write(chunk)
                                                        dm_file_size += len(chunk)
                                                
                                                if dm_file_size > 10000:
                                                    info = {
                                                        "title": dm_title,
                                                        "duration": 0,
                                                        "height": int(q_key) if q_key.isdigit() else 720,
                                                        "vcodec": "h264",
                                                        "acodec": "aac",
                                                        "_cobalt_file": dm_file_path,
                                                        "_cobalt_size": dm_file_size,
                                                    }
                                                    logger.info(f"✅ Dailymotion player API: Download succeeded! Size: {dm_file_size // 1024}KB")
                                                else:
                                                    try: os.remove(dm_file_path)
                                                    except: pass
                                            else:
                                                logger.warning(f"⚠️ Dailymotion stream download failed: HTTP {dl_resp.status}")
                                    else:
                                        logger.warning(f"⚠️ Dailymotion player API: No stream URL found in qualities")
                                else:
                                    logger.warning(f"⚠️ Dailymotion player API: HTTP {dm_resp.status}")
                except asyncio.TimeoutError:
                    logger.warning("⚠️ Dailymotion player API timed out")
                except Exception as dm_err:
                    logger.warning(f"⚠️ Dailymotion player API error: {dm_err}")
            
            # ═══ المرحلة 1.5: PO Token fallback (YouTube فقط!) ═══
            # 🔑 PO Token بيقدر يتخطى "Sign in to confirm you're not a bot"
            # 🔴 بنستخدمه بس لو الخطأ هو bot detection — مش لكل الأخطاء
            # 🔴 مش بنضيفه في المحاولة الأولى عشان لو باطل يخليها تفشل
            if info is None and is_youtube and last_error:
                wa_err_str = str(last_error).lower()
                is_wa_bot_error = any(kw in wa_err_str for kw in [
                    "sign in", "bot", "captcha", "confirm you", "login", "403",
                ])
                
                if is_wa_bot_error:
                    try:
                        from po_token_manager import get_po_token, add_po_token_to_opts
                        po_token = get_po_token()
                        if po_token:
                            logger.info("🔑 WhatsApp: Bot detection — trying PO Token fallback...")
                            
                            # ═══ محاولة A: PO Token + cookies + remote_components ═══
                            po_opts_a = dict(ydl_opts)
                            po_opts_a = add_po_token_to_opts(po_opts_a)
                            
                            try:
                                def _run_ytdlp_po_a():
                                    with yt_dlp.YoutubeDL(po_opts_a) as ydl:
                                        return ydl.extract_info(url, download=True)
                                
                                info = await asyncio.wait_for(
                                    loop.run_in_executor(None, _run_ytdlp_po_a),
                                    timeout=300
                                )
                                if info:
                                    logger.info("✅ WhatsApp: Download succeeded with PO Token + cookies + deno!")
                            except Exception as po_err_a:
                                logger.warning(f"⚠️ WhatsApp PO Token + deno failed: {po_err_a}")
                                last_error = po_err_a
                            
                            # ═══ محاولة B: PO Token بس (بدون remote_components) ═══
                            if info is None:
                                logger.info("🔑 WhatsApp: Trying PO Token without remote_components...")
                                po_opts_b = dict(ydl_opts)
                                po_opts_b.pop('remote_components', None)
                                po_opts_b = add_po_token_to_opts(po_opts_b)
                                
                                try:
                                    def _run_ytdlp_po_b():
                                        with yt_dlp.YoutubeDL(po_opts_b) as ydl:
                                            return ydl.extract_info(url, download=True)
                                    
                                    info = await asyncio.wait_for(
                                        loop.run_in_executor(None, _run_ytdlp_po_b),
                                        timeout=300
                                    )
                                    if info:
                                        logger.info("✅ WhatsApp: Download succeeded with PO Token (no remote_components)!")
                                except Exception as po_err_b:
                                    logger.warning(f"⚠️ WhatsApp PO Token (no deno) failed: {po_err_b}")
                                    last_error = po_err_b
                        else:
                            logger.info("🔑 WhatsApp: No PO Token available — skipping fallback")
                    except ImportError:
                        pass  # po_token_manager مش متاح — مش مشكلة
                    except Exception as po_outer_err:
                        logger.debug(f"🔑 WhatsApp PO Token fallback error: {po_outer_err}")
            
            # ═══ المرحلة 2: yt-dlp player_client fallback chain (YouTube فقط!) ═══
            # 🔴 FIX: player_client ده لليوتيوب بس — مش بيشتغل مع Dailymotion/SoundCloud
            # 🔴 FIX v2: استخدام أزواج client زي التليجرام بالظبط — كل زوج فيه client + web fallback
            if info is None and is_youtube:
                _YOUTUBE_PLAYER_CLIENTS = [
                    ['android', 'web'],    # Android client — fallback أول
                    ['ios', 'web'],        # iOS client
                    ['mweb', 'web'],       # Mobile Web
                    ['tv', 'web'],         # TV client
                    ['web'],               # Default web — آخر حل
                ]
                for pc_idx, pc in enumerate(_YOUTUBE_PLAYER_CLIENTS):
                    try:
                        alt_opts = dict(ydl_opts)
                        alt_opts['extractor_args'] = {'youtube': {'player_client': pc}}
                        # 🔴 FIX: نشيل remote_components مع player_client (مش متوافقين)
                        alt_opts.pop('remote_components', None)
                        
                        logger.info(f"🔧 WhatsApp yt-dlp fallback: player_client={pc} (attempt {pc_idx + 1})")
                        
                        def _run_ytdlp_alt():
                            with yt_dlp.YoutubeDL(alt_opts) as ydl:
                                info = ydl.extract_info(url, download=True)
                                return info
                        
                        info = await asyncio.wait_for(
                            loop.run_in_executor(None, _run_ytdlp_alt),
                            timeout=300
                        )
                        if info:
                            logger.info(f"✅ yt-dlp {pc} client download succeeded")
                            break
                    except Exception as e2:
                        last_error = e2
                        logger.warning(f"⚠️ yt-dlp {pc} client failed: {e2}")
                        # 🔴 لو bot detection — حدث yt-dlp فوراً
                        err_str2 = str(e2).lower()
                        if any(kw in err_str2 for kw in ["sign in", "bot", "captcha", "confirm", "login", "403"]):
                            try:
                                from handlers.download_handlers import trigger_ytdlp_update
                                trigger_ytdlp_update()
                            except Exception:
                                pass
            
            # 🔴 FIX: Cobalt API لكل المنصات (مش بس YouTube!)
            # Cobalt بيدعم Dailymotion و SoundCloud و TikTok و Instagram وغيرهم
            if info is None and not is_youtube:
                try:
                    import aiohttp as _aiohttp_cobalt
                    cobalt_instances = [
                        'https://api.cobalt.tools',
                        'https://cobalt-api.kwiatekmiki.com',
                    ]
                    
                    for cobalt_url in cobalt_instances:
                        try:
                            cobalt_headers = {
                                'Accept': 'application/json',
                                'Content-Type': 'application/json',
                            }
                            cobalt_payload = {'url': url}
                            if is_audio_only:
                                cobalt_payload['downloadMode'] = 'audio'
                            elif quality in ("medium", "low"):
                                cobalt_payload['videoQuality'] = '720' if quality == 'medium' else '480'
                            
                            async with _aiohttp_cobalt.ClientSession() as cobalt_session:
                                async with cobalt_session.post(
                                    cobalt_url, headers=cobalt_headers, json=cobalt_payload,
                                    timeout=_aiohttp_cobalt.ClientTimeout(total=30)
                                ) as cobalt_resp:
                                    if cobalt_resp.status != 200:
                                        continue
                                    
                                    cobalt_data = await cobalt_resp.json()
                                    cobalt_status = cobalt_data.get('status', '')
                                    
                                    dl_url = None
                                    if cobalt_status in ('redirect', 'tunnel'):
                                        dl_url = cobalt_data.get('url', '')
                                    elif cobalt_status == 'picker':
                                        picker = cobalt_data.get('picker', [])
                                        if picker:
                                            dl_url = picker[0].get('url', '')
                                    
                                    if dl_url:
                                        logger.info(f"🟠 WA Cobalt: Got download URL from {cobalt_url} for {platform}")
                                        ext = "mp3" if is_audio_only else "mp4"
                                        cobalt_file = os.path.join(tmpdir, f"cobalt_dl.{ext}")
                                        
                                        dl_headers = {'Referer': 'https://www.youtube.com/'}
                                        async with cobalt_session.get(dl_url, headers=dl_headers,
                                              timeout=_aiohttp_cobalt.ClientTimeout(total=120)) as dl_resp:
                                            if dl_resp.status == 200:
                                                cobalt_file_size = 0
                                                with open(cobalt_file, 'wb') as cf:
                                                    async for chunk in dl_resp.content.iter_chunked(8192):
                                                        cf.write(chunk)
                                                        cobalt_file_size += len(chunk)
                                                
                                                if cobalt_file_size > 1000:
                                                    # 🔴 Build info dict for the standard send flow
                                                    cobalt_title = cobalt_data.get('filename', '')
                                                    if cobalt_title:
                                                        cobalt_title = os.path.splitext(cobalt_title)[0][:80]
                                                    if not cobalt_title:
                                                        cobalt_title = f"{platform_display} Video"
                                                    info = {
                                                        "title": cobalt_title,
                                                        "duration": 0,
                                                        "height": 720,
                                                        "vcodec": "h264",
                                                        "acodec": "aac",
                                                        "_cobalt_file": cobalt_file,
                                                        "_cobalt_size": cobalt_file_size,
                                                    }
                                                    logger.info(f"🟠 WA Cobalt: Download succeeded! Size: {cobalt_file_size // 1024}KB")
                                                    break
                                                else:
                                                    try: os.remove(cobalt_file)
                                                    except: pass
                        except asyncio.TimeoutError:
                            logger.debug(f"🟠 WA Cobalt {cobalt_url} timed out")
                        except Exception as cobalt_err:
                            logger.debug(f"🟠 WA Cobalt {cobalt_url} error: {cobalt_err}")
                except Exception as cobalt_outer_err:
                    logger.warning(f"🟠 WA Cobalt non-YT error: {cobalt_outer_err}")
            
            # ═══ المرحلة 3: Cobalt API Fallback (fallback تالت — أسرع وأضمن من Piped) ═══
            # 🔴 نفس fallback chain زي التليجرام بالظبط
            # Cobalt Public API + Self-Hosted
            if info is None and is_youtube:
                try:
                    from handlers.download_handlers import _try_cobalt_for_youtube
                    
                    logger.info(f"🟠 WhatsApp Cobalt: Attempting download as 3rd fallback for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    cobalt_result = await asyncio.wait_for(
                        _try_cobalt_for_youtube(url, quality, tmpdir),
                        timeout=90
                    )
                    
                    if cobalt_result and cobalt_result.get("filepath"):
                        logger.info(f"🟠 WhatsApp Cobalt (3rd fallback) succeeded! File: {cobalt_result['filepath']}")
                        
                        cobalt_file = cobalt_result["filepath"] if "filepath" in cobalt_result else cobalt_result.get("file_path")
                        cobalt_size = cobalt_result.get("size", os.path.getsize(cobalt_file) if os.path.exists(cobalt_file) else 0)
                        cobalt_title = cobalt_result.get("title", "YouTube Video")
                        cobalt_height = cobalt_result.get("height", 720)
                        cobalt_size_mb = cobalt_size / (1024 * 1024)
                        size_str = f"{cobalt_size_mb:.1f}MB"
                        
                        if cobalt_file and os.path.exists(cobalt_file):
                            # 🛡️ Safety check
                            try:
                                from content_safety import comprehensive_media_safety_check
                                cb_file_type = "audio" if is_audio_only else "video"
                                is_safe_cb, block_msg_cb, _ = await comprehensive_media_safety_check(
                                    title=cobalt_title, file_path=cobalt_file, file_type=cb_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_cb:
                                    await _send_whatsapp_message(wa_id, block_msg_cb)
                                    try: os.remove(cobalt_file)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(cobalt_file, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{cobalt_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(cobalt_file)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Cobalt audio send failed: {audio_send_err}")
                            else:
                                # 🔴 استخدام Supabase للملفات الكبيرة — صامت، بدون رسالة للمستخدم
                                if cobalt_size_mb > 25:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=cobalt_file,
                                            filename=f"{cobalt_title[:50]}.mp4",
                                            content_type="video/mp4",
                                            platform="whatsapp",
                                            title=cobalt_title,
                                            lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(cobalt_file)
                                            except: pass
                                            return
                                    except Exception as sup_err:
                                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                                    logger.warning(f"⚠️ WA Cobalt: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(cobalt_file)
                                    except: pass
                                else:
                                    # File <= 25MB — try direct WhatsApp send
                                    try:
                                        with open(cobalt_file, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{cobalt_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                tech_info = f"{cobalt_height}p | {size_str} | Cobalt"
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {cobalt_title[:200]}\n📥 {tech_info}")
                                                await feedback.success()
                                                try: os.remove(cobalt_file)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Cobalt video send failed: {video_send_err}")
                    
                    logger.warning(f"⚠️ Cobalt (3rd fallback) failed, trying Apify...")
                except ImportError:
                    logger.warning("⚠️ Cobalt download handler not available, trying Apify...")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Cobalt timed out, trying Apify...")
                except Exception as cobalt_err:
                    logger.warning(f"⚠️ Cobalt error: {cobalt_err}, trying Apify...")
            
            # ═══ المرحلة 4: Apify — fallback رابع (سيرفرات مختلفة عن YouTube خالص) ═══
            # 🔵 Apify بيستخدم actors عشان يحمل الفيديو — مش بيتأثر بـ bot detection
            if info is None and is_youtube:
                try:
                    from apify_download import download_youtube_apify
                    
                    logger.info(f"🔵 WhatsApp Apify: Attempting download as 4th fallback for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    apify_result = await asyncio.wait_for(
                        download_youtube_apify(url, quality, tmpdir),
                        timeout=150
                    )
                    
                    if apify_result and apify_result.get("success") and apify_result.get("filepath"):
                        logger.info(f"🔵 WhatsApp Apify (4th fallback) succeeded! File: {apify_result['filepath']}")
                        
                        apify_file = apify_result["filepath"]
                        apify_size = apify_result.get("size", os.path.getsize(apify_file) if os.path.exists(apify_file) else 0)
                        apify_title = apify_result.get("title", "YouTube Video")
                        apify_height = apify_result.get("height", 720)
                        apify_size_mb = apify_size / (1024 * 1024)
                        size_str = f"{apify_size_mb:.1f}MB"
                        
                        if apify_file and os.path.exists(apify_file):
                            # 🛡️ Safety check
                            try:
                                from content_safety import comprehensive_media_safety_check
                                af_file_type = "audio" if is_audio_only else "video"
                                is_safe_af, block_msg_af, _ = await comprehensive_media_safety_check(
                                    title=apify_title, file_path=apify_file, file_type=af_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_af:
                                    await _send_whatsapp_message(wa_id, block_msg_af)
                                    try: os.remove(apify_file)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(apify_file, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{apify_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(apify_file)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Apify audio send failed: {audio_send_err}")
                            else:
                                # 🔴 استخدام Supabase للملفات الكبيرة — صامت، بدون رسالة للمستخدم
                                if apify_size_mb > 25:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=apify_file,
                                            filename=f"{apify_title[:50]}.mp4",
                                            content_type="video/mp4",
                                            platform="whatsapp",
                                            title=apify_title,
                                            lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(apify_file)
                                            except: pass
                                            return
                                    except Exception as sup_err:
                                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                                    logger.warning(f"⚠️ WA Apify: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(apify_file)
                                    except: pass
                                else:
                                    # File <= 25MB — try direct WhatsApp send
                                    try:
                                        with open(apify_file, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{apify_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                tech_info = f"{apify_height}p | {size_str} | Apify"
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {apify_title[:200]}\n📥 {tech_info}")
                                                await feedback.success()
                                                try: os.remove(apify_file)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Apify video send failed: {video_send_err}")
                    
                    logger.warning(f"⚠️ Apify (4th fallback) failed, trying yt-dlp without cookies...")
                except ImportError:
                    logger.warning("⚠️ Apify module not available, trying yt-dlp without cookies...")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Apify timed out, trying yt-dlp without cookies...")
                except Exception as apify_err:
                    logger.warning(f"⚠️ Apify error: {apify_err}, trying yt-dlp without cookies...")
            
            # ═══ المرحلة 4.5: yt-dlp WITHOUT cookies (زي التليجرام بالظبط!) ═══
            # 🔴 أحياناً الكوكيز نفسها بتسبب مشاكل (expired/invalid) → نجرب بدونها
            # 🔴 FIX: زي التليجرام — بنشيل الكوكيز بس، مش remote_components
            if info is None and is_youtube:
                logger.info("🔄 WhatsApp: All methods failed (including Cobalt & Apify), trying WITHOUT cookies...")
                
                try:
                    # المحاولة الأولى: default + deno بدون كوكيز (بإبقاء remote_components زي التليجرام)
                    clean_opts = dict(ydl_opts)
                    clean_opts.pop('cookiefile', None)
                    # 🔴 FIX: مش بنشيل remote_components — زي التليجرام بالظبط
                    clean_opts['format'] = format_str if not is_audio_only else 'bestaudio/best'
                    
                    logger.info("🔄 WhatsApp: Clean attempt (default, no cookies, keeping remote_components)...")
                    
                    def _run_ytdlp_clean():
                        with yt_dlp.YoutubeDL(clean_opts) as ydl:
                            return ydl.extract_info(url, download=True)
                    
                    try:
                        info = await asyncio.wait_for(
                            loop.run_in_executor(None, _run_ytdlp_clean),
                            timeout=300
                        )
                        if info is not None:
                            logger.info("✅ WhatsApp: Download succeeded with default (no cookies)!")
                    except Exception as clean_error:
                        last_error = clean_error
                        logger.warning(f"⚠️ WhatsApp clean attempt (no cookies) failed: {clean_error}")
                        
                        # المحاولة التانية: android player_client بدون كوكيز
                        android_clean = dict(ydl_opts)
                        android_clean.pop('cookiefile', None)
                        # 🔴 نشيل remote_components مع player_client (مش متوافقين)
                        android_clean.pop('remote_components', None)
                        android_clean['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}
                        android_clean['format'] = format_str if not is_audio_only else 'bestaudio/best'
                        
                        logger.info("🔄 WhatsApp: Android+web player_client clean attempt (no cookies)...")
                        
                        def _run_ytdlp_android_clean():
                            with yt_dlp.YoutubeDL(android_clean) as ydl:
                                return ydl.extract_info(url, download=True)
                        
                        try:
                            info = await asyncio.wait_for(
                                loop.run_in_executor(None, _run_ytdlp_android_clean),
                                timeout=300
                            )
                            if info is not None:
                                logger.info("✅ WhatsApp: Download succeeded with android (no cookies)!")
                        except Exception as ac_error:
                            last_error = ac_error
                            logger.warning(f"⚠️ WhatsApp android clean attempt also failed: {ac_error}")
                except Exception as clean_outer_err:
                    logger.warning(f"⚠️ WhatsApp yt-dlp without cookies error: {clean_outer_err}")
            
            # ═══ المرحلة 5: Invidious API (تم تجربته فوق — هنا fallback إضافي) ═══
            # 🔴 نفس ترتيب التليجرام: Invidious قبل Piped
            # Invidious = واجهة بديلة لليوتيوب مفتوحة المصدر
            if info is None and is_youtube:
                try:
                    from invidious_api import download_youtube_invidious_file
                    
                    inv_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                       "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    inv_quality = inv_quality_map.get(quality, "best")
                    
                    logger.info(f"🟣 WhatsApp Invidious (retry): Attempting download quality={inv_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    inv_result = await asyncio.wait_for(
                        download_youtube_invidious_file(url, quality=inv_quality, output_dir=tmpdir),
                        timeout=60
                    )
                    
                    if inv_result and inv_result.get("success") and inv_result.get("file_path"):
                        logger.info(f"🟣 WhatsApp Invidious (retry) succeeded! File: {inv_result['file_path']}")
                        
                        inv_file = inv_result["file_path"]
                        inv_size = inv_result.get("file_size", os.path.getsize(inv_file))
                        inv_title = inv_result.get("title", "YouTube Video")
                        inv_duration = inv_result.get("duration", 0)
                        inv_format = inv_result.get("format_info", {})
                        
                        info = {
                            "title": inv_title,
                            "duration": int(inv_duration) if inv_duration else 0,
                            "height": 720,
                            "vcodec": "h264",
                            "acodec": "aac",
                            "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                        }
                        
                        if inv_file and os.path.exists(inv_file):
                            target = os.path.join(tmpdir, f"{inv_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(inv_file, target)
                            except Exception:
                                target = inv_file
                            
                            # 🛡️ Safety check on Invidious downloaded media
                            try:
                                inv_file_type = "audio" if is_audio_only else "video"
                                is_safe_inv, block_msg_inv, _ = await comprehensive_media_safety_check(
                                    title=inv_title, file_path=target, file_type=inv_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_inv:
                                    await _send_whatsapp_message(wa_id, block_msg_inv)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            inv_size_mb = inv_size / (1024 * 1024)
                            inv_quality_label = inv_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{inv_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Invidious (retry) audio send failed: {audio_send_err}")
                            else:
                                if inv_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{inv_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {inv_title[:200]}\n📥 Invidious | {inv_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Invidious (retry) video send failed: {video_send_err}")
                                else:
                                    # File too large for WhatsApp — upload to Supabase (silent)
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{inv_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=inv_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Invidious (retry): File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ Invidious (retry) failed, trying Piped...")
                except ImportError:
                    logger.warning("⚠️ invidious_api module not available, skipping Invidious")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Invidious (retry) timed out, trying Piped...")
                except Exception as inv_err:
                    logger.warning(f"⚠️ Invidious (retry) error: {inv_err}, trying Piped...")
            
            # ═══ المرحلة 6: Piped API (تم تجربته فوق — هنا fallback إضافي) ═══
            # 🔴 نفس ترتيب التليجرام: Piped بعد Invidious
            # Piped = واجهة بديلة لليوتيوب مفتوحة المصدر — مختلفة عن Invidious
            # بيستخدم NewPipe Extractor — أحياناً بيشتغل لما Invidious يبقى منطفي
            if info is None and is_youtube:
                try:
                    from piped_api import download_youtube_piped_file
                    
                    piped_quality_map = {"best": "best", "medium": "medium", "low": "low", "audio": "audio",
                                         "audio_320": "audio", "audio_192": "audio", "audio_128": "audio", "audio_64": "audio"}
                    piped_quality = piped_quality_map.get(quality, "best")
                    
                    logger.info(f"🟢 WhatsApp Piped (retry): Attempting download quality={piped_quality} for {url[:80]}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    piped_result = await asyncio.wait_for(
                        download_youtube_piped_file(url, quality=piped_quality, output_dir=tmpdir),
                        timeout=90
                    )
                    
                    if piped_result and piped_result.get("success") and piped_result.get("file_path"):
                        logger.info(f"🟢 WhatsApp Piped (retry) succeeded! File: {piped_result['file_path']}")
                        
                        piped_file = piped_result["file_path"]
                        piped_size = piped_result.get("file_size", os.path.getsize(piped_file))
                        piped_title = piped_result.get("title", "YouTube Video")
                        piped_duration = piped_result.get("duration", 0)
                        piped_format = piped_result.get("format_info", {})
                        
                        # Construct info dict for the send logic below
                        info = {
                            "title": piped_title,
                            "duration": int(piped_duration) if piped_duration else 0,
                            "height": 720,
                            "vcodec": "h264",
                            "acodec": "aac",
                            "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                        }
                        
                        # Move the Piped file to the expected location
                        if piped_file and os.path.exists(piped_file):
                            target = os.path.join(tmpdir, f"{piped_title[:80]}.mp4")
                            try:
                                import shutil
                                shutil.move(piped_file, target)
                            except Exception:
                                target = piped_file
                            
                            # 🛡️ Safety check on Piped downloaded media
                            try:
                                pp_file_type = "audio" if is_audio_only else "video"
                                is_safe_pp, block_msg_pp, _ = await comprehensive_media_safety_check(
                                    title=piped_title, file_path=target, file_type=pp_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_pp:
                                    await _send_whatsapp_message(wa_id, block_msg_pp)
                                    try: os.remove(target)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            # Send the file directly from here
                            piped_size_mb = piped_size / (1024 * 1024)
                            piped_quality_label = piped_format.get("quality_label", quality)
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(target, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{piped_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Piped (retry) audio send failed: {audio_send_err}")
                            else:
                                if piped_size_mb <= 25:
                                    try:
                                        with open(target, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{piped_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {piped_title[:200]}\n📥 Piped | {piped_quality_label}")
                                                await feedback.success()
                                                try: os.remove(target)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Piped (retry) video send failed: {video_send_err}")
                                else:
                                    # File too large for WhatsApp — upload to Supabase (silent)
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=target, filename=f"{piped_title[:50]}.mp4",
                                            content_type="video/mp4", platform="whatsapp", title=piped_title, lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(target)
                                            except: pass
                                            return
                                    except Exception:
                                        pass
                                    logger.warning(f"⚠️ WA Piped (retry): File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(target)
                                    except: pass
                    
                    logger.warning(f"⚠️ Piped (retry) failed, trying Cobalt Self-Hosted...")
                except ImportError:
                    logger.warning("⚠️ piped_api module not available, skipping Piped")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Piped (retry) timed out, trying Cobalt Self-Hosted...")
                except Exception as piped_err:
                    logger.warning(f"⚠️ Piped (retry) error: {piped_err}, trying Cobalt Self-Hosted...")
            
            # ═══ المرحلة 6.5: Cobalt Self-Hosted (زي التليجرام بالظبط!) ═══
            # 🔵 _try_cobalt_download بيجرب الـ COBALT_API_URL (self-hosted) 
            # ده مختلف عن _try_cobalt_for_youtube اللي اتجرب فوق — ده مرحلة إضافية
            if info is None:
                try:
                    from handlers.download_handlers import _try_cobalt_download
                    
                    logger.info(f"🔵 WhatsApp Cobalt Self-Hosted: Attempting download for {url[:80]}")
                    
                    cobalt_sh_result = await asyncio.wait_for(
                        _try_cobalt_download(url, quality, tmpdir),
                        timeout=90
                    )
                    
                    if cobalt_sh_result and cobalt_sh_result.get("filepath"):
                        logger.info(f"🔵 WhatsApp Cobalt Self-Hosted succeeded! File: {cobalt_sh_result['filepath']}")
                        
                        cobalt_sh_file = cobalt_sh_result["filepath"]
                        cobalt_sh_size = cobalt_sh_result.get("size", os.path.getsize(cobalt_sh_file) if os.path.exists(cobalt_sh_file) else 0)
                        cobalt_sh_title = cobalt_sh_result.get("title", "Video")
                        cobalt_sh_height = cobalt_sh_result.get("height", 720)
                        cobalt_sh_size_mb = cobalt_sh_size / (1024 * 1024)
                        cobalt_sh_size_str = f"{cobalt_sh_size_mb:.1f}MB"
                        
                        if cobalt_sh_file and os.path.exists(cobalt_sh_file):
                            # 🛡️ Safety check
                            try:
                                from content_safety import comprehensive_media_safety_check
                                sh_file_type = "audio" if is_audio_only else "video"
                                is_safe_sh, block_msg_sh, _ = await comprehensive_media_safety_check(
                                    title=cobalt_sh_title, file_path=cobalt_sh_file, file_type=sh_file_type,
                                    platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                )
                                if not is_safe_sh:
                                    await _send_whatsapp_message(wa_id, block_msg_sh)
                                    try: os.remove(cobalt_sh_file)
                                    except: pass
                                    await feedback.error()
                                    return
                            except Exception:
                                pass  # Fail-open
                            
                            if is_audio_only or quality == "audio" or quality.startswith("audio_"):
                                try:
                                    with open(cobalt_sh_file, 'rb') as af:
                                        media_response = requests.post(
                                            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                            files={"file": (f"{cobalt_sh_title[:50]}.mp3", af, "audio/mpeg")},
                                            data={"messaging_product": "whatsapp", "type": "audio"},
                                            timeout=120
                                        )
                                        if media_response.status_code == 200:
                                            media_id = media_response.json().get("id")
                                            await _send_whatsapp_audio(wa_id, media_id)
                                            await feedback.success()
                                            try: os.remove(cobalt_sh_file)
                                            except: pass
                                            return
                                except Exception as audio_send_err:
                                    logger.warning(f"⚠️ Cobalt Self-Hosted audio send failed: {audio_send_err}")
                            else:
                                # 🔴 صامت — بدون رسالة للمستخدم
                                if cobalt_sh_size_mb > 25:
                                    try:
                                        from supabase_storage import upload_and_get_link
                                        cloud_msg = await upload_and_get_link(
                                            file_path=cobalt_sh_file,
                                            filename=f"{cobalt_sh_title[:50]}.mp4",
                                            content_type="video/mp4",
                                            platform="whatsapp",
                                            title=cobalt_sh_title,
                                            lang="ar",
                                        )
                                        if cloud_msg:
                                            await _send_whatsapp_message(wa_id, cloud_msg)
                                            await feedback.success()
                                            try: os.remove(cobalt_sh_file)
                                            except: pass
                                            return
                                    except Exception as sup_err:
                                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                                    logger.warning(f"⚠️ WA Cobalt Self-Hosted: File downloaded but sending failed, trying next fallback...")
                                    try: os.remove(cobalt_sh_file)
                                    except: pass
                                else:
                                    # File <= 25MB — try direct WhatsApp send
                                    try:
                                        with open(cobalt_sh_file, 'rb') as vf:
                                            media_response = requests.post(
                                                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                files={"file": (f"{cobalt_sh_title[:50]}.mp4", vf, "video/mp4")},
                                                data={"messaging_product": "whatsapp", "type": "video"},
                                                timeout=180
                                            )
                                            if media_response.status_code == 200:
                                                media_id = media_response.json().get("id")
                                                tech_info = f"{cobalt_sh_height}p | {cobalt_sh_size_str} | Cobalt Self-Hosted"
                                                await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {cobalt_sh_title[:200]}\n📥 {tech_info}")
                                                await feedback.success()
                                                try: os.remove(cobalt_sh_file)
                                                except: pass
                                                return
                                    except Exception as video_send_err:
                                        logger.warning(f"⚠️ Cobalt Self-Hosted video send failed: {video_send_err}")
                    
                    logger.warning(f"⚠️ Cobalt Self-Hosted failed, trying Cobalt JWT...")
                except ImportError:
                    logger.warning("⚠️ _try_cobalt_download not available, trying Cobalt JWT...")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Cobalt Self-Hosted timed out, trying Cobalt JWT...")
                except Exception as cobalt_sh_err:
                    logger.warning(f"⚠️ Cobalt Self-Hosted error: {cobalt_sh_err}, trying Cobalt JWT...")
            
            # ═══ المرحلة 7: Cobalt JWT — آخر fallback قبل Cloudflare Worker ═══
            # 🔴 ده JWT شخصي من cobalt.tools — بنستخدمه كـ آخر حل لو كل حاجة فشلت
            if info is None and is_youtube:
                try:
                    from config import COBALT_JWT
                    
                    if COBALT_JWT:
                        logger.info(f"🔐 WhatsApp Cobalt JWT: Last-resort attempt for {url[:80]}")
                        # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                        
                        import aiohttp as _aiohttp_wa
                        import json as _json_wa
                        
                        is_audio_jwt = (quality == "audio" or quality.startswith("audio_"))
                        jwt_quality_map = {"best": "1080", "medium": "720", "low": "480", "audio": "720"}
                        jwt_v_quality = jwt_quality_map.get(quality, "1080")
                        
                        jwt_payload = {
                            "url": url,
                            "videoQuality": jwt_v_quality,
                            "filenameStyle": "classic",
                        }
                        if is_audio_jwt:
                            jwt_payload["downloadMode"] = "audio"
                            jwt_payload["audioFormat"] = "mp3"
                        
                        jwt_headers = {
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {COBALT_JWT}",
                        }
                        
                        try:
                            from handlers.download_handlers import _cobalt_api_request
                            jwt_result = await asyncio.wait_for(
                                _cobalt_api_request(
                                    "https://api.cobalt.tools", jwt_payload, jwt_headers,
                                    jwt_v_quality, is_audio_jwt, tmpdir
                                ),
                                timeout=90
                            )
                            
                            if jwt_result and jwt_result.get("filepath"):
                                logger.info(f"🔐 WhatsApp Cobalt JWT succeeded! File: {jwt_result['filepath']}")
                                
                                jwt_file = jwt_result["filepath"]
                                jwt_size = jwt_result.get("size", os.path.getsize(jwt_file) if os.path.exists(jwt_file) else 0)
                                jwt_title = jwt_result.get("title", "YouTube Video")
                                jwt_height = jwt_result.get("height", 720)
                                jwt_size_mb = jwt_size / (1024 * 1024)
                                size_str = f"{jwt_size_mb:.1f}MB"
                                
                                if jwt_file and os.path.exists(jwt_file):
                                    # 🛡️ Safety check on Cobalt JWT downloaded media
                                    try:
                                        jwt_file_type = "audio" if is_audio_jwt else "video"
                                        is_safe_jwt, block_msg_jwt, _ = await comprehensive_media_safety_check(
                                            title=jwt_title, file_path=jwt_file, file_type=jwt_file_type,
                                            platform="whatsapp", user_id=str(wa_user_id), lang="ar",
                                        )
                                        if not is_safe_jwt:
                                            await _send_whatsapp_message(wa_id, block_msg_jwt)
                                            try: os.remove(jwt_file)
                                            except: pass
                                            await feedback.error()
                                            return
                                    except Exception:
                                        pass  # Fail-open
                                    
                                    if is_audio_jwt:
                                        try:
                                            with open(jwt_file, 'rb') as af:
                                                media_response = requests.post(
                                                    f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                    headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                    files={"file": (f"{jwt_title[:50]}.mp3", af, "audio/mpeg")},
                                                    data={"messaging_product": "whatsapp", "type": "audio"},
                                                    timeout=120
                                                )
                                                if media_response.status_code == 200:
                                                    media_id = media_response.json().get("id")
                                                    await _send_whatsapp_audio(wa_id, media_id)
                                                    await feedback.success()
                                                    try: os.remove(jwt_file)
                                                    except: pass
                                                    return
                                        except Exception as audio_send_err:
                                            logger.warning(f"⚠️ Cobalt JWT audio send failed: {audio_send_err}")
                                    else:
                                        if jwt_size_mb <= 25:
                                            try:
                                                with open(jwt_file, 'rb') as vf:
                                                    media_response = requests.post(
                                                        f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                                        headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
                                                        files={"file": (f"{jwt_title[:50]}.mp4", vf, "video/mp4")},
                                                        data={"messaging_product": "whatsapp", "type": "video"},
                                                        timeout=180
                                                    )
                                                    if media_response.status_code == 200:
                                                        media_id = media_response.json().get("id")
                                                        tech_info = f"{jwt_height}p | {size_str} | Cobalt JWT"
                                                        await _send_whatsapp_video(wa_id, media_id, caption=f"🎬 {jwt_title[:200]}\n📥 {tech_info}")
                                                        await feedback.success()
                                                        try: os.remove(jwt_file)
                                                        except: pass
                                                        return
                                            except Exception as video_send_err:
                                                logger.warning(f"⚠️ Cobalt JWT video send failed: {video_send_err}")
                                        else:
                                            # File too large for WhatsApp — upload to Supabase
                                            try:
                                                from supabase_storage import upload_and_get_link
                                                jwt_size_str = f"{jwt_size_mb:.1f}MB"
                                                cloud_msg = await upload_and_get_link(
                                                    file_path=jwt_file, filename=f"{jwt_title[:50]}.mp4",
                                                    content_type="video/mp4", platform="whatsapp", title=jwt_title, lang="ar",
                                                )
                                                if cloud_msg:
                                                    await _send_whatsapp_message(wa_id, cloud_msg)
                                                    await feedback.success()
                                                    try: os.remove(jwt_file)
                                                    except: pass
                                                    return
                                            except Exception:
                                                pass
                                            logger.warning(f"⚠️ WA Cobalt JWT: File downloaded but sending failed, trying next fallback...")
                                            try: os.remove(jwt_file)
                                            except: pass
                            
                            logger.warning(f"⚠️ Cobalt JWT failed, trying Cloudflare Worker...")
                        except asyncio.TimeoutError:
                            logger.warning(f"⚠️ Cobalt JWT timed out, trying Cloudflare Worker...")
                    else:
                        logger.info("🔐 Cobalt JWT: No COBALT_JWT configured, skipping")
                except Exception as jwt_err:
                    logger.warning(f"⚠️ Cobalt JWT error: {jwt_err}")
            
            # ═══ المرحلة 8: Cloudflare Worker Proxy Fallback (آخر محاولة) ═══
            # لو yt-dlp فشل على Railway (IPs محجوبة)، نجرب عبر Cloudflare Worker
            if info is None:
                from config import CLOUDFLARE_WORKER_URL
                if CLOUDFLARE_WORKER_URL:
                    logger.info(f"🔄 All yt-dlp methods failed, trying Cloudflare Worker proxy: {CLOUDFLARE_WORKER_URL}")
                    # 🔴 WhatsApp: لا نرسل رسالة لكل خدمة
                    
                    try:
                        import aiohttp as _aiohttp
                        from urllib.parse import quote
                        
                        worker_url = CLOUDFLARE_WORKER_URL.rstrip("/")
                        dl_type = "audio" if is_audio_only else "video"
                        api_url = f"{worker_url}/download?url={quote(url)}&type={dl_type}"
                        
                        async with _aiohttp.ClientSession() as cf_session:
                            async with cf_session.get(api_url, timeout=_aiohttp.ClientTimeout(total=180)) as cf_resp:
                                if cf_resp.status == 200:
                                    content_type = cf_resp.headers.get('Content-Type', '')
                                    if 'video' in content_type or 'audio' in content_type or 'octet-stream' in content_type:
                                        # Save the streamed file
                                        ext = "mp3" if is_audio_only else "mp4"
                                        cf_filepath = os.path.join(tmpdir, f"video_cf.{ext}")
                                        
                                        file_data = await cf_resp.read()
                                        with open(cf_filepath, 'wb') as cf_f:
                                            cf_f.write(file_data)
                                        
                                        cf_size = os.path.getsize(cf_filepath)
                                        if cf_size > 10000:  # At least 10KB
                                            # Get video info from headers
                                            cf_title = cf_resp.headers.get('X-Video-Title', 'فيديو')[:80]
                                            cf_author = cf_resp.headers.get('X-Video-Author', '')
                                            cf_duration = cf_resp.headers.get('X-Video-Duration', '0')
                                            
                                            info = {
                                                "title": cf_title or "YouTube Video",
                                                "duration": int(cf_duration) if cf_duration.isdigit() else 0,
                                                "height": 720,
                                                "vcodec": "h264",
                                                "acodec": "aac",
                                                "author": cf_author,
                                                "requested_downloads": [{"height": 720, "vcodec": "h264", "acodec": "aac"}],
                                            }
                                            logger.info(f"✅ CF Worker proxy download succeeded! Size: {cf_size // 1024}KB")
                                        else:
                                            try: os.remove(cf_filepath)
                                            except: pass
                                    else:
                                        # Worker returned JSON (might be "needs_decipher")
                                        try:
                                            cf_data = await cf_resp.json(content_type=None)
                                            if cf_data.get('error') == 'needs_decipher':
                                                # Get stream URLs using yt-dlp (info-only) then proxy through Worker
                                                logger.info("🔄 Worker says needs_decipher, trying yt-dlp info + Worker proxy approach")
                                                try:
                                                    # Use yt-dlp to get stream URL only (no download)
                                                    info_opts = {
                                                        'quiet': True,
                                                        'no_warnings': True,
                                                        'format': format_str,
                                                        'skip_download': True,
                                                        'http_headers': ydl_opts.get('http_headers', {}),
                                                    }
                                                    # 🔴 FIX: إضافة كوكيز لو موجودة (زي باقي yt-dlp calls)
                                                    if 'cookiefile' in ydl_opts:
                                                        info_opts['cookiefile'] = ydl_opts['cookiefile']
                                                    if is_audio_only:
                                                        info_opts['postprocessors'] = ydl_opts.get('postprocessors')
                                                    
                                                    def _run_ytdlp_info():
                                                        with yt_dlp.YoutubeDL(info_opts) as ydl:
                                                            return ydl.extract_info(url, download=False)
                                                    
                                                    info_only = await asyncio.wait_for(
                                                        loop.run_in_executor(None, _run_ytdlp_info),
                                                        timeout=120
                                                    )
                                                    
                                                    if info_only:
                                                        # Get the best stream URL
                                                        stream_url = info_only.get('url', '')
                                                        if not stream_url and info_only.get('formats'):
                                                            # Find best format with URL
                                                            for fmt in info_only['formats']:
                                                                if fmt.get('url') and fmt.get('protocol', '') in ('https', 'http'):
                                                                    stream_url = fmt['url']
                                                                    break
                                                        
                                                        if stream_url:
                                                            # Proxy through Cloudflare Worker
                                                            proxy_api = f"{worker_url}/proxy?url={quote(stream_url)}&type={dl_type}"
                                                            async with cf_session.get(proxy_api, timeout=_aiohttp.ClientTimeout(total=180)) as proxy_resp:
                                                                if proxy_resp.status == 200:
                                                                    ext = "mp3" if is_audio_only else "mp4"
                                                                    proxy_filepath = os.path.join(tmpdir, f"video_proxy.{ext}")
                                                                    proxy_data = await proxy_resp.read()
                                                                    with open(proxy_filepath, 'wb') as pf:
                                                                        pf.write(proxy_data)
                                                                    
                                                                    proxy_size = os.path.getsize(proxy_filepath)
                                                                    if proxy_size > 10000:
                                                                        info = {
                                                                            "title": info_only.get('title', 'فيديو')[:80],
                                                                            "duration": info_only.get('duration', 0),
                                                                            "height": info_only.get('height', 720),
                                                                            "author": info_only.get('uploader', ''),
                                                                            "vcodec": "h264",
                                                                            "acodec": "aac",
                                                                            "requested_downloads": [{"height": 720}],
                                                                        }
                                                                        logger.info(f"✅ yt-dlp info + CF Worker proxy succeeded! Size: {proxy_size // 1024}KB")
                                                                    else:
                                                                        try: os.remove(proxy_filepath)
                                                                        except: pass
                                                except Exception as proxy_err:
                                                    logger.warning(f"⚠️ yt-dlp info + CF Worker proxy failed: {proxy_err}")
                                        except Exception as json_err:
                                            logger.warning(f"⚠️ CF Worker JSON parse error: {json_err}")
                                else:
                                    logger.warning(f"⚠️ CF Worker returned status {cf_resp.status}")
                    except Exception as cf_err:
                        logger.warning(f"⚠️ Cloudflare Worker proxy fallback failed: {cf_err}")
            
            if not info:
                await _send_whatsapp_message(wa_id, "❌ فشل تحميل الفيديو. جرب تاني! 📥")
                await feedback.error()
                return
            
            # 🔴 FIX: لو Cobalt نزل الملف مباشرة (مش عبر yt-dlp)
            cobalt_direct_file = info.get('_cobalt_file') if isinstance(info, dict) else None
            if cobalt_direct_file and os.path.exists(cobalt_direct_file):
                video_file = cobalt_direct_file
                file_size = info.get('_cobalt_size', os.path.getsize(video_file))
                title = info.get('title', 'فيديو')[:80]
            else:
                # Find the downloaded file (yt-dlp case)
                downloaded_files = os.listdir(tmpdir)
                if not downloaded_files:
                    await _send_whatsapp_message(wa_id, "❌ فشل تحميل الفيديو. جرب تاني! 📥")
                    await feedback.error()
                    return
                
                video_file = os.path.join(tmpdir, downloaded_files[0])
                file_size = os.path.getsize(video_file)
                title = info.get('title', 'فيديو')[:80]
            
            logger.info(f"📥 Downloaded video: {title} ({file_size / 1024 / 1024:.1f}MB, quality={quality})")
            
            # 🔴 FIX v9: ffprobe audio check + smart h264 re-encoding (SPEED-OPTIMIZED)
            # Check if video has audio using ffprobe, and convert non-h264 codecs
            if not is_audio_only and file_size > 0:
                try:
                    import subprocess as _sp
                    
                    # ffprobe check for audio
                    probe_result = _sp.run(
                        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', video_file],
                        capture_output=True, timeout=15
                    )
                    video_vcodec = None
                    has_audio = False
                    
                    if probe_result.returncode == 0:
                        try:
                            import json as _json
                            probe_data = _json.loads(probe_result.stdout)
                            for stream in probe_data.get('streams', []):
                                if stream.get('codec_type') == 'video':
                                    video_vcodec = stream.get('codec_name', '')
                                elif stream.get('codec_type') == 'audio':
                                    has_audio = True
                        except Exception:
                            pass
                    
                    # 🔴 No audio detected — retry with different format (Facebook fix)
                    if not has_audio and is_facebook_family:
                        logger.warning(f"⚠️ No audio detected in {platform} video — retrying with merge format")
                        try:
                            shutil.rmtree(tmpdir, ignore_errors=True)
                            tmpdir = tempfile.mkdtemp(prefix="mybro_wa_dl_")
                            retry_output = os.path.join(tmpdir, "%(title).80s.%(ext)s")
                            
                            retry_format = (
                                'bestvideo+bestaudio/'
                                'bestvideo[vcodec^=avc1]+bestaudio/'
                                'best[ext=mp4][acodec!=none]/'
                                'best[acodec!=none]/'
                                'best'
                            )
                            
                            retry_opts = {
                                'outtmpl': retry_output,
                                'quiet': True, 'no_warnings': True,
                                'format': retry_format,
                                'merge_output_format': 'mp4',
                                'socket_timeout': 30, 'retries': 3,
                                'fragment_retries': 5, 'file_access_retries': 3,
                                'no_check_certificates': True,
                                'http_headers': ydl_opts.get('http_headers', {}),
                            }
                            # 🔴 FIX: إضافة كوكيز لو موجودة (زي باقي yt-dlp calls)
                            if 'cookiefile' in ydl_opts:
                                retry_opts['cookiefile'] = ydl_opts['cookiefile']
                            
                            def _run_ytdlp_retry():
                                with yt_dlp.YoutubeDL(retry_opts) as ydl:
                                    return ydl.extract_info(url, download=True)
                            
                            retry_info = await asyncio.wait_for(
                                loop.run_in_executor(None, _run_ytdlp_retry),
                                timeout=300
                            )
                            
                            if retry_info:
                                info = retry_info
                                downloaded_files = os.listdir(tmpdir)
                                if downloaded_files:
                                    video_file = os.path.join(tmpdir, downloaded_files[0])
                                    file_size = os.path.getsize(video_file)
                                    logger.info(f"✅ Audio retry succeeded: {file_size / 1024 / 1024:.1f}MB")
                        except Exception as retry_err:
                            logger.warning(f"⚠️ Audio retry failed: {retry_err}")
                    
                    # 🔴 h264 re-encoding — ONLY if codec is NOT h264 (VP9/AV1 etc.)
                    # SPEED OPTIMIZED: preset ultrafast + CRF 23 + 128k audio
                    if (video_vcodec and video_vcodec not in ("h264", "avc1", "avc", "mpeg4", "")
                        and not is_audio_only):
                        logger.info(f"🔧 Converting {video_vcodec} to h264 (ultrafast) for WhatsApp compatibility...")
                        try:
                            import multiprocessing
                            threads = min(multiprocessing.cpu_count(), 4)
                            converted_path = video_file + "_h264.mp4"
                            
                            convert_result = _sp.run(
                                ['ffmpeg', '-i', video_file,
                                 '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                                 '-threads', str(threads),
                                 '-c:a', 'aac', '-b:a', '128k',
                                 '-movflags', '+faststart',
                                 '-y', converted_path],
                                capture_output=True, timeout=180
                            )
                            
                            if convert_result.returncode == 0 and os.path.exists(converted_path):
                                converted_size = os.path.getsize(converted_path)
                                if converted_size > 0:
                                    try: os.remove(video_file)
                                    except: pass
                                    video_file = converted_path
                                    file_size = converted_size
                                    logger.info(f"✅ Converted to h264 (ultrafast): {file_size // (1024*1024)}MB")
                                else:
                                    try: os.remove(converted_path)
                                    except: pass
                            else:
                                try: os.remove(converted_path)
                                except: pass
                                logger.warning(f"⚠️ h264 conversion failed, keeping original")
                        except _sp.TimeoutExpired:
                            logger.warning("⚠️ h264 conversion timed out, keeping original")
                            try: os.remove(video_file + "_h264.mp4")
                            except: pass
                        except Exception as conv_err:
                            logger.warning(f"⚠️ h264 conversion error: {conv_err}")
                            
                except ImportError:
                    pass  # subprocess not available
                except Exception as e:
                    logger.warning(f"⚠️ Video check/conversion error: {e}")
            
            # 🛡️ Safety: Comprehensive media safety check before sending
            try:
                media_type = "audio" if is_audio_only else "video"
                is_safe, block_msg, safety_reason = await comprehensive_media_safety_check(
                    title=title,
                    file_path=video_file,
                    file_type=media_type,
                    platform="whatsapp",
                    user_id=str(wa_user_id),
                    lang="ar",
                )
                if not is_safe:
                    await _send_whatsapp_message(wa_id, block_msg)
                    try:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                    except Exception:
                        pass
                    await feedback.error()
                    return
            except Exception as e:
                logger.warning(f"🛡️ Media safety check failed (allowing): {e}")
            
            # ═══ إرسال الملف — Direct Send أو Supabase Cloud Upload ═══
            #
            # 🔴 FIX v3: Supabase free tier has a 50MB per-file upload limit!
            # upload_and_get_link() now auto-compresses files > 50MB with ffmpeg before uploading.
            #
            # Flow:
            # 1. لو الملف <= 100MB → إرسال مباشر عبر WhatsApp
            # 2. لو الإرسال المباشر فشل → Supabase (مع ضغط تلقائي لو > 50MB)
            # 3. لو الملف > 100MB → Supabase مباشرة (مع ضغط تلقائي)
            # 4. لو Supabase فشل (حتى بعد الضغط) → رسالة خطأ
            #
            MAX_WHATSAPP_DIRECT_SIZE = 25 * 1024 * 1024    # 25MB — عشان نتجنب OOM على Railway (كان 100MB)
            MAX_SUPABASE_SIZE = 2 * 1024 * 1024 * 1024      # 2GB — أقصى حد للرفع على السحابة
            
            # 🔴 Step 1: لو الملف <= 100MB → إرسال مباشر
            if file_size <= MAX_WHATSAPP_DIRECT_SIZE:
                # 🔴 FIX: بنستخدم streaming send عشان نتجنب OOM
                if is_audio_only:
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + '.mp3'
                    caption = f"🎵 {title}\n🔗 {platform_display}\n📊 {file_size / 1024 / 1024:.1f}MB"
                    result = await _send_whatsapp_document_from_file(
                        wa_id, video_file, safe_filename, caption, "audio/mpeg"
                    )
                else:
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + '.mp4'
                    quality_label = {"best": "1080p", "medium": "720p", "low": "480p"}.get(quality, "")
                    caption = f"📥 {title}\n🔗 {platform_display}\n📊 {file_size / 1024 / 1024:.1f}MB"
                    if quality_label:
                        caption += f"\n🎬 {quality_label}"
                    result = await _send_whatsapp_document_from_file(
                        wa_id, video_file, safe_filename, caption, "video/mp4"
                    )
                
                if "error" not in result:
                    # ✅ الإرسال المباشر نجح
                    pass
                else:
                    # الإرسال المباشر فشل — نجرب Supabase
                    error_msg = str(result.get("error", ""))
                    logger.warning(f"⚠️ WhatsApp direct send failed: {error_msg}")
                    
                    # 🔴 محاولة رفع على Supabase (مع ضغط تلقائي لو > 50MB) — silent, no user message
                    
                    content_type = "audio/mpeg" if is_audio_only else "video/mp4"
                    ext = ".mp3" if is_audio_only else ".mp4"
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + ext
                    
                    try:
                        from supabase_storage import upload_and_get_link
                        cloud_msg = await upload_and_get_link(
                            file_path=video_file,
                            filename=safe_filename,
                            content_type=content_type,
                            platform="whatsapp",
                            title=title,
                            lang="ar",
                        )
                        if cloud_msg:
                            await _send_whatsapp_message(wa_id, cloud_msg)
                            await feedback.success()
                            try: shutil.rmtree(tmpdir, ignore_errors=True)
                            except: pass
                            return  # ✅ رفع السحابة نجح
                        else:
                            # 🔴 FIX v2: Supabase فشل → نجرب جودة أقل (زي الملفات الكبيرة)
                            logger.warning(f"⚠️ Supabase upload failed for small file ({file_size / 1024 / 1024:.1f}MB), trying lower quality...")
                            if quality != "low":
                                try:
                                    shutil.rmtree(tmpdir, ignore_errors=True)
                                except Exception:
                                    pass
                                await feedback.complete()
                                lower_quality = {"best": "medium", "medium": "low", "audio": "low"}.get(quality, "low")
                                return await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=lower_quality)
                            else:
                                # جودة منخفضة بالفعل — رسالة خطأ نهائية
                                await _send_whatsapp_message(wa_id,
                                    f"📥 *{title}*\n\n"
                                    f"🔗 المنصة: {platform_display}\n\n"
                                    f"❌ فشل إرسال الملف. جرب تاني!")
                    except Exception as sup_err:
                        logger.error(f"☁️ Supabase upload error: {sup_err}")
                        # 🔴 FIX v2: حتى لو Supabase رمي استثناء → نجرب جودة أقل
                        if quality != "low":
                            try:
                                shutil.rmtree(tmpdir, ignore_errors=True)
                            except Exception:
                                pass
                            await feedback.complete()
                            lower_quality = {"best": "medium", "medium": "low", "audio": "low"}.get(quality, "low")
                            return await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=lower_quality)
                        else:
                            await _send_whatsapp_message(wa_id,
                                f"📥 *{title}*\n\n"
                                f"🔗 المنصة: {platform_display}\n\n"
                                f"❌ فشل إرسال الملف. جرب تاني!")
            
            # 🔴 Step 2: لو الملف > 100MB → رفع على Supabase مباشرة (مع ضغط تلقائي)
            else:
                # 🔴 FIX v3: Supabase free tier = 50MB limit, but upload_and_get_link auto-compresses — silent, no user message
                size_mb_str = f"{file_size / 1024 / 1024:.0f}MB"
                
                content_type = "audio/mpeg" if is_audio_only else "video/mp4"
                ext = ".mp3" if is_audio_only else ".mp4"
                safe_filename = re.sub(r'[<>:"/\\|?*]', '_', title) + ext
                
                cloud_msg = None
                try:
                    from supabase_storage import upload_and_get_link
                    cloud_msg = await upload_and_get_link(
                        file_path=video_file,
                        filename=safe_filename,
                        content_type=content_type,
                        platform="whatsapp",
                        title=title,
                        lang="ar",
                    )
                except Exception as sup_err:
                    logger.error(f"☁️ Supabase upload error: {sup_err}")
                
                if cloud_msg:
                    # ✅ رفع السحابة نجح
                    await _send_whatsapp_message(wa_id, cloud_msg)
                else:
                    # 🔴 Supabase فشل حتى بعد الضغط — نجرب جودة أقل كآخر محاولة
                    logger.error("☁️ Supabase upload failed even after compression")
                    
                    if quality != "low":
                        # نجرب نحمل بجودة أقل ونحاول تاني — silent, no user message
                        try:
                            shutil.rmtree(tmpdir, ignore_errors=True)
                        except Exception:
                            pass
                        await feedback.complete()
                        lower_quality = {"best": "medium", "medium": "low", "audio": "low"}.get(quality, "low")
                        return await _download_and_send_video(wa_id, url, wa_user_id, contact_name, message_id, is_admin, quality=lower_quality)
                    else:
                        await _send_whatsapp_message(wa_id,
                            f"📥 *{title}*\n\n"
                            f"🔗 المنصة: {platform_display}\n\n"
                            f"❌ فشل رفع الملف على السحابة. جرب تاني!")
            
            # Increment usage
            if not is_admin:
                try:
                    from premium import increment_usage
                    increment_usage(wa_user_id, "downloads")
                except Exception:
                    pass
            
            await feedback.complete()
            
        finally:
            # Cleanup temp directory
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass
        
    except ImportError:
        logger.error("❌ yt-dlp not installed!")
        await _send_whatsapp_message(wa_id, "❌ تحميل الفيديوهات مش متاح دلوقتي. جرب تاني بعد شوية! 📥")
        await feedback.error()
    except asyncio.TimeoutError:
        await _send_whatsapp_message(wa_id, "❌ انتهى وقت التحميل. حاول مرة تانية! 📥")
        await feedback.error()
    except Exception as e:
        logger.error(f"❌ Video download error for WA {wa_id}: {e}", exc_info=True)
        error_str = str(e).lower()
        
        # User-friendly error messages
        if "sign in" in error_str or "login" in error_str or "bot" in error_str:
            await _send_whatsapp_message(wa_id, 
                "❌ مش قادر أحمل الفيديو ده — YouTube طلب تسجيل دخول.\n\n"
                "💡 جرب فيديو تاني أو استخدم التليجرام!")
        elif "private" in error_str or "age" in error_str:
            await _send_whatsapp_message(wa_id, 
                "❌ الفيديو ده خاص أو مقيد بالعمر.\n\n💡 جرب فيديو تاني!")
        elif "not found" in error_str or "does not exist" in error_str:
            await _send_whatsapp_message(wa_id, 
                "❌ الرابط مش صحيح أو الفيديو مش موجود.\n\n💡 تأكد من الرابط وجرب تاني!")
        else:
            await _send_whatsapp_message(wa_id, "❌ حصل خطأ في التحميل. جرب تاني! 📥")
        
        await feedback.error()
