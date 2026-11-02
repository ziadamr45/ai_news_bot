"""
🟦 Dailymotion Downloader via Apify — إصلاح 2026-11-02
═══════════════════════════════════════════════════════
🔴 المشكلة: Dailymotion بقى يحظر أي TLS fingerprint مش بتاعة متصفح
   (yt-dlp بيطلب impersonation=firefox → محتاج curl_cffi → مش بيتثبت
   على FreeBSD/serv00) → كل تحميلات Dailymotion كانت بتفشل.

✅ الحل: epctex~dailymotion-video-downloader على Apify (بيحمل بـ TLS متصفح
   حقيقي من سيرفراتهم) → الملف بيتخزن في KV store → بنجيبه بالتوكن مباشرة.

🔴 ملاحظة: الـ actor بيرجّع downloadUrl فيه امتداد .mp4 زيادة على اسم
   المفتاح الحقيقي (باج في الـ actor نفسه) → بنصحّح الرابط ونجيب الملف
   بالتوكن مباشرة — مضمون 100%.

المسار: dailymotion.com/video/ID أو dai.ly/ID → actor run → KV record
→ mp4 (أو mp3 بـ ffmpeg لو المطلوب صوت) → إرسال تليجرام.
"""

import os
import re
import logging
import asyncio

import aiohttp

logger = logging.getLogger("dailymotion_apify")

# ═══════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════

APIFY_API_KEY = os.environ.get("APIFY_API_KEY", "")
APIFY_BASE_URL = "https://api.apify.com/v2"

# 🔴 Actor تحميل Dailymotion — الأعلى استخدامًا في الـ store (2424+ runs)
DM_ACTOR = "epctex~dailymotion-video-downloader"

DM_URL_PATTERN = re.compile(
    r'(?:dailymotion\.com/(?:video|embed/video)/|dai\.ly/)([a-z0-9]+)',
    re.IGNORECASE,
)


def _extract_video_id(url: str) -> str | None:
    m = DM_URL_PATTERN.search(url or "")
    return m.group(1) if m else None


def _safe_name(title: str) -> str:
    """تنظيف العنوان عشان يبقى اسم ملف سليم"""
    t = re.sub(r'[\\/:*?"<>|\n\r]+', ' ', title or "").strip()
    return (t[:80] or "dailymotion_audio")


async def _fetch_title(session: aiohttp.ClientSession, url: str) -> str:
    """جلب العنوان من player metadata (غير حرجة — لو فشلت بنرجّع بديل)"""
    vid = _extract_video_id(url)
    if not vid:
        return "Dailymotion Video"
    try:
        meta_url = f"https://www.dailymotion.com/player/metadata/video/{vid}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.dailymotion.com/",
        }
        async with session.get(meta_url, params={"embedder": "https://www.dailymotion.com"},
                               headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                t = data.get("title")
                if t:
                    return str(t).strip()[:150]
    except Exception as e:
        logger.debug(f"🟦 Dailymotion title fetch failed (non-critical): {e}")
    return f"Dailymotion {vid}"


async def download_dailymotion_apify(url: str, quality: str, tmpdir: str) -> dict | None:
    """
    تحميل فيديو Dailymotion عبر Apify actor.

    Args:
        url: رابط الفيديو (dailymotion.com/video/ID أو dai.ly/ID)
        quality: الجودة المطلوبة (best/medium/low/audio/audio_320/...)
        tmpdir: المجلد المؤقت للتنزيل

    Returns:
        dict: {success, filepath, title, size, is_audio} لو نجح
        None: لو فشل (المُنادي يكمّل على yt-dlp العادي)
    """
    if not APIFY_API_KEY:
        logger.warning("🟦 Dailymotion Apify: مفيش APIFY_API_KEY — تخطي")
        return None

    vid = _extract_video_id(url)
    if not vid:
        logger.warning(f"🟦 Dailymotion Apify: مش عارف أستخرج ID من {url[:80]}")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            # ═══ 1) تشغيل الـ actor (run-sync — لحد ما يخلص) ═══
            run_url = (
                f"{APIFY_BASE_URL}/acts/{DM_ACTOR}/run-sync-get-dataset-items"
                f"?token={APIFY_API_KEY}&timeout=200"
            )
            payload = {
                "startUrls": [f"https://www.dailymotion.com/video/{vid}"],
                "proxy": {"useApifyProxy": True},
                "maxVideos": 1,
            }
            try:
                async with session.post(run_url, json=payload,
                                        timeout=aiohttp.ClientTimeout(total=230)) as resp:
                    body = await resp.text()
                    if resp.status not in (200, 201):
                        logger.warning(f"🟦 Dailymotion Apify: run status {resp.status}: {body[:120]}")
                        return None
                    import json as _json
                    try:
                        items = _json.loads(body)
                    except Exception:
                        logger.warning("🟦 Dailymotion Apify: JSON مفيش من الـ run")
                        return None
            except asyncio.TimeoutError:
                logger.warning("🟦 Dailymotion Apify: run timed out بعد 230s")
                return None

            if not isinstance(items, list) or not items:
                logger.warning("🟦 Dailymotion Apify: dataset فاضي")
                return None

            item = items[0] if isinstance(items[0], dict) else {}
            dl_url = item.get("downloadUrl") or ""

            # ═══ 2) تصحيح رابط الـ KV (الباج: .mp4 زيادة على المفتاح) ═══
            m = re.search(
                r'/key-value-stores/([A-Za-z0-9]+)/records/([A-Za-z0-9._-]+?)(?:\.mp4)?(?:\?|$)',
                dl_url,
            )
            if not m:
                logger.warning(f"🟦 Dailymotion Apify: مش قاريت downloadUrl: {dl_url[:90]}")
                return None
            store_id, record_key = m.group(1), m.group(2)

            # ═══ 3) تحميل الملف بالتوكن ═══
            file_url = f"{APIFY_BASE_URL}/key-value-stores/{store_id}/records/{record_key}?token={APIFY_API_KEY}"
            raw_path = os.path.join(tmpdir, f"dm_{vid}.mp4")
            total = 0
            try:
                async with session.get(file_url, timeout=aiohttp.ClientTimeout(total=300, sock_read=90)) as fresp:
                    if fresp.status != 200:
                        logger.warning(f"🟦 Dailymotion Apify: file fetch status {fresp.status}")
                        return None
                    with open(raw_path, "wb") as out:
                        async for chunk in fresp.content.iter_chunked(256 * 1024):
                            if chunk:
                                out.write(chunk)
                                total += len(chunk)
            except asyncio.TimeoutError:
                logger.warning("🟦 Dailymotion Apify: تحميل الملف timed out")
                return None

            if total < 50 * 1024:
                logger.warning(f"🟦 Dailymotion Apify: الملف صغير جدًا ({total} bytes)")
                try: os.remove(raw_path)
                except: pass
                return None

            logger.info(f"🟦 Dailymotion Apify: file downloaded ({total / (1024*1024):.1f}MB)")

            # ═══ 4) العنوان ═══
            title = await _fetch_title(session, url)

            # ═══ 5) صوت؟ استخراج mp3 بـ ffmpeg ═══
            is_audio = quality in ("audio", "audio_320", "audio_192", "audio_128", "audio_64")
            if is_audio:
                bitrate_map = {"audio_320": "320K", "audio_192": "192K",
                               "audio_128": "128K", "audio_64": "64K"}
                bitrate = bitrate_map.get(quality, "320K")
                mp3_path = os.path.join(tmpdir, f"{_safe_name(title)}.mp3")
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", raw_path, "-vn",
                    "-acodec", "libmp3lame", "-ab", bitrate, mp3_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=300)
                except asyncio.TimeoutError:
                    proc.kill()
                    logger.warning("🟦 Dailymotion Apify: ffmpeg audio timed out")
                    return None
                try: os.remove(raw_path)
                except: pass
                if proc.returncode != 0 or not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 30 * 1024:
                    logger.warning("🟦 Dailymotion Apify: فشل تحويل الصوت بـ ffmpeg")
                    return None
                logger.info(f"🟦 Dailymotion Apify: mp3 ready ({bitrate})")
                return {
                    "success": True,
                    "filepath": mp3_path,
                    "title": title,
                    "size": os.path.getsize(mp3_path),
                    "is_audio": True,
                }

            return {
                "success": True,
                "filepath": raw_path,
                "title": title,
                "size": total,
                "is_audio": False,
            }
    except Exception as e:
        logger.warning(f"🟦 Dailymotion Apify: exception: {e}")
        return None
