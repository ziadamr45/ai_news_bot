"""
وكيل يوتيوب - YouTube Agent
تلخيص فيديوهات YouTube مع fallback متعدد الطبقات

🔴 Pipeline:
1. Invidious Captions API (أكثر استقراراً — لا يعتمد على YouTube مباشرة)
2. youtube_transcript_api (مكتبة بايثون — يدعم v0.6+)
3. Piped Captions API (بديل لـ Invidious)
4. YouTube HTML Scraping (استخراج الترجمة من صفحة الفيديو)
5. Web Search Fallback (بحث عن ملخصات موجودة)
6. Video Info + AI (آخر حل — تلخيص بناءً على العنوان والوصف فقط)

🔴 جديد في v2:
- Invidious captions API كطريقة أولى (أضمن من scraping)
- دعم youtube_transcript_api v0.6.0+ (API جديد)
- Piped captions API كـ fallback إضافي
- تحسين الـ web search fallback
- caching للـ transcripts
- معالجة أخطاء شاملة
- إمكانية إنشاء كويز + ملاحظات مراجعة
"""

import asyncio
import logging
import re
import time
from typing import Optional, Dict, List
from html import unescape

logger = logging.getLogger(__name__)

# أنماط روابط YouTube
YOUTUBE_PATTERNS = [
    r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/|youtube\.com\/shorts\/|youtube\.com\/live\/)([a-zA-Z0-9_-]{11})',
    r'^([a-zA-Z0-9_-]{11})$',
]

# ═══════════════════════════════════════
# Invidious Instances — للـ captions
# ═══════════════════════════════════════

INVIVIOUS_CAPTION_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.materialio.us",
    "https://yewtu.be",
    "https://invidious.protokolla.fi",
    "https://invidious.nerdvpn.de",
    "https://inv.tux.pizza",
    "https://vid.puffyan.us",
    "https://invidious.lunar.icu",
    "https://invidious.privacyredirect.com",
]

# ═══════════════════════════════════════
# Piped Instances — للـ captions
# ═══════════════════════════════════════

PIPED_CAPTION_INSTANCES = [
    "https://api.piped.private.coffee",
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://api.piped.projectsegfau.lt",
]

# ═══════════════════════════════════════
# Transcript Cache
# ═══════════════════════════════════════

_transcript_cache: Dict[str, dict] = {}  # video_id -> {"transcript": str, "timestamp": float}
_TRANSCRIPT_CACHE_TTL = 1800  # 30 دقيقة


class YouTubeAgent:
    """وكيل YouTube - تلخيص فيديوهات مع fallback متعدد الطبقات"""

    @classmethod
    def extract_video_id(cls, url: str) -> Optional[str]:
        """استخراج معرف الفيديو من الرابط"""
        for pattern in YOUTUBE_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @classmethod
    def is_youtube_url(cls, text: str) -> bool:
        """فحص هل النص فيه رابط YouTube"""
        return cls.extract_video_id(text) is not None

    # ═══════════════════════════════════════
    # Transcript Extraction Pipeline
    # ═══════════════════════════════════════

    def _get_cached_transcript(self, video_id: str) -> Optional[str]:
        """الحصول على transcript من الـ cache"""
        if video_id in _transcript_cache:
            entry = _transcript_cache[video_id]
            if time.time() - entry["timestamp"] < _TRANSCRIPT_CACHE_TTL:
                logger.info(f"📦 Using cached transcript for {video_id}")
                return entry["transcript"]
            else:
                del _transcript_cache[video_id]
        return None

    def _cache_transcript(self, video_id: str, transcript: str):
        """حفظ transcript في الـ cache"""
        _transcript_cache[video_id] = {
            "transcript": transcript,
            "timestamp": time.time(),
        }

    def get_transcript(self, video_id: str, languages: list = None) -> str:
        """استخراج نص الفيديو - pipeline متعدد الطبقات

        🔴 الطرق بالترتيب:
        1. Invidious Captions API (الأكثر استقراراً)
        2. youtube_transcript_api (مكتبة بايثون)
        3. Piped Captions API (بديل)
        4. YouTube HTML Scraping (استخراج من الصفحة)
        """
        if not languages:
            languages = ["ar", "en"]

        # فحص الـ cache أولاً
        cached = self._get_cached_transcript(video_id)
        if cached:
            return cached

        # ═══ الطريقة 1: Invidious Captions API ═══
        transcript = self._get_transcript_invidious(video_id, languages)
        if transcript:
            self._cache_transcript(video_id, transcript)
            return transcript

        # ═══ الطريقة 2: youtube_transcript_api ═══
        transcript = self._get_transcript_yt_api(video_id, languages)
        if transcript:
            self._cache_transcript(video_id, transcript)
            return transcript

        # ═══ الطريقة 3: Piped Captions API ═══
        transcript = self._get_transcript_piped(video_id, languages)
        if transcript:
            self._cache_transcript(video_id, transcript)
            return transcript

        # ═══ الطريقة 4: YouTube HTML Scraping ═══
        transcript = self._get_transcript_html(video_id, languages)
        if transcript:
            self._cache_transcript(video_id, transcript)
            return transcript

        logger.warning(f"🔴 All transcript methods failed for {video_id}")
        return ""

    def _get_transcript_invidious(self, video_id: str, languages: list = None) -> str:
        """استخراج الترجمة من Invidious Captions API

        Invidious بيقدم endpoint خاص بالترجمة:
        GET /api/v1/captions/{video_id}

        ده أفضل من scraping لأنه:
        - مش بيتأثر بـ YouTube bot detection
        - الـ API مستقر ومتوثق
        - بيشتغل من سيرفرات مختلفة (fallback)
        """
        if not languages:
            languages = ["ar", "en"]

        import requests as req

        for instance in INVIVIOUS_CAPTION_INSTANCES[:4]:  # نجرب 4 سيرفرات
            try:
                api_url = f"{instance}/api/v1/captions/{video_id}"
                logger.info(f"🟣 Invidious Captions [{instance}]: Fetching for {video_id}")

                response = req.get(
                    api_url,
                    timeout=10,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/json",
                    }
                )

                if response.status_code == 404:
                    logger.debug(f"🟣 Invidious [{instance}]: No captions available (404)")
                    continue

                if response.status_code != 200:
                    logger.debug(f"🟣 Invidious [{instance}]: Status {response.status_code}")
                    continue

                data = response.json()
                tracks = data.get("captions", [])

                if not tracks:
                    logger.debug(f"🟣 Invidious [{instance}]: No caption tracks found")
                    continue

                # بنبحث عن الترجمة باللغة المطلوبة أولاً
                target_track = None

                # أولاً: اللغة المطلوبة
                for lang in languages:
                    for track in tracks:
                        track_lang = track.get("language_code", "") or track.get("languageCode", "")
                        if track_lang == lang:
                            target_track = track
                            break
                    if target_track:
                        break

                # ثانياً: أي ترجمة متاحة (أفضل من لا شيء)
                if not target_track and tracks:
                    # بنفضل الإنجليزي لو موجود
                    for track in tracks:
                        track_lang = track.get("language_code", "") or track.get("languageCode", "")
                        if track_lang in ("en", "en-US", "en-GB"):
                            target_track = track
                            break

                    # أي ترجمة
                    if not target_track:
                        target_track = tracks[0]

                if not target_track:
                    continue

                # استخراج رابط الترجمة
                caption_url = target_track.get("url", "")

                if not caption_url:
                    logger.debug(f"🟣 Invidious [{instance}]: No caption URL in track")
                    continue

                # ربط URL نسبي بالسيرفر
                if caption_url.startswith("/"):
                    caption_url = f"{instance}{caption_url}"

                # تحميل الترجمة
                cap_resp = req.get(caption_url, timeout=10, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })

                if cap_resp.status_code != 200:
                    logger.debug(f"🟣 Invidious [{instance}]: Caption download failed ({cap_resp.status_code})")
                    continue

                # استخراج النص من XML
                texts = re.findall(r'<text[^>]*>(.*?)</text>', cap_resp.text)
                if texts:
                    clean_texts = [unescape(re.sub(r'<[^>]+>', '', t)) for t in texts]
                    transcript = ' '.join(clean_texts).strip()
                    if transcript:
                        logger.info(f"✅ Invidious Captions: Got transcript for {video_id} ({len(transcript)} chars, {len(texts)} segments)")
                        return transcript

                # محاولة JSON format (بعض سيرفرات Invidious بترجع JSON)
                try:
                    cap_data = cap_resp.json()
                    if isinstance(cap_data, list):
                        texts = [entry.get("text", "") for entry in cap_data if entry.get("text")]
                        if texts:
                            transcript = ' '.join(texts).strip()
                            if transcript:
                                logger.info(f"✅ Invidious Captions (JSON): Got transcript for {video_id} ({len(transcript)} chars)")
                                return transcript
                except Exception:
                    pass

            except req.exceptions.Timeout:
                logger.debug(f"🟣 Invidious [{instance}]: Timeout")
                continue
            except req.exceptions.ConnectionError:
                logger.debug(f"🟣 Invidious [{instance}]: Connection error")
                continue
            except Exception as e:
                logger.debug(f"🟣 Invidious [{instance}]: Error: {e}")
                continue

        logger.debug(f"🟣 Invidious: All instances failed for {video_id}")
        return ""

    def _get_transcript_yt_api(self, video_id: str, languages: list = None) -> str:
        """استخراج الترجمة باستخدام youtube_transcript_api

        🔴 يدعم الإصدارات المختلفة:
        - v0.6.0+: YouTubeTranscriptApi.fetch(video_id, languages)
        - v0.5.x: YouTubeTranscriptApi.get_transcript(video_id, languages)
        - v0.4.x: YouTubeTranscriptApi.list_transcripts(video_id)
        """
        if not languages:
            languages = ["ar", "en"]

        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            logger.warning("youtube_transcript_api not installed")
            return ""

        # ═══ محاولة 1: fetch() — الإصدار الجديد (v0.6.0+) ═══
        try:
            transcript_list = YouTubeTranscriptApi.fetch(video_id, languages=languages)

            if hasattr(transcript_list, '__iter__'):
                texts = []
                for entry in transcript_list:
                    if isinstance(entry, dict):
                        text = entry.get('text', '')
                    elif hasattr(entry, 'text'):
                        text = getattr(entry, 'text', '')
                    elif isinstance(entry, (list, tuple)) and len(entry) >= 1:
                        text = entry[0] if isinstance(entry[0], str) else ''
                    else:
                        text = str(entry)

                    if text and text.strip():
                        texts.append(text.strip())

                transcript = ' '.join(texts).strip()
                if transcript:
                    logger.info(f"✅ youtube_transcript_api (fetch): Got transcript for {video_id} ({len(transcript)} chars)")
                    return transcript
        except TypeError as e:
            # ممكن الـ API بتاع الإصدار ده مختلف
            logger.debug(f"youtube_transcript_api fetch() TypeError: {e}")
        except Exception as e:
            logger.debug(f"youtube_transcript_api fetch() error: {e}")

        # ═══ محاولة 2: fetch() بدون languages ═══
        try:
            transcript_list = YouTubeTranscriptApi.fetch(video_id)

            if hasattr(transcript_list, '__iter__'):
                texts = []
                for entry in transcript_list:
                    if isinstance(entry, dict):
                        text = entry.get('text', '')
                    elif hasattr(entry, 'text'):
                        text = getattr(entry, 'text', '')
                    elif isinstance(entry, (list, tuple)) and len(entry) >= 1:
                        text = entry[0] if isinstance(entry[0], str) else ''
                    else:
                        text = str(entry)

                    if text and text.strip():
                        texts.append(text.strip())

                transcript = ' '.join(texts).strip()
                if transcript:
                    logger.info(f"✅ youtube_transcript_api (fetch no lang): Got transcript for {video_id} ({len(transcript)} chars)")
                    return transcript
        except Exception as e:
            logger.debug(f"youtube_transcript_api fetch(no lang) error: {e}")

        # ═══ محاولة 3: get_transcript() — الإصدار القديم ═══
        try:
            if hasattr(YouTubeTranscriptApi, 'get_transcript'):
                for lang in languages:
                    try:
                        transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                        if transcript_data:
                            texts = []
                            for entry in transcript_data:
                                if isinstance(entry, dict):
                                    text = entry.get('text', '')
                                elif hasattr(entry, 'text'):
                                    text = getattr(entry, 'text', '')
                                else:
                                    text = str(entry)
                                if text and text.strip():
                                    texts.append(text.strip())

                            transcript = ' '.join(texts).strip()
                            if transcript:
                                logger.info(f"✅ youtube_transcript_api (get_transcript): Got transcript for {video_id} lang={lang} ({len(transcript)} chars)")
                                return transcript
                    except Exception as e:
                        logger.debug(f"youtube_transcript_api get_transcript lang={lang} error: {e}")
                        continue
        except Exception as e:
            logger.debug(f"youtube_transcript_api get_transcript error: {e}")

        # ═══ محاولة 4: list_transcripts() + find_transcript() ═══
        try:
            if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

                # بنبحث عن ترجمة باللغات المطلوبة
                for lang in languages:
                    try:
                        transcript_obj = transcript_list.find_transcript([lang])
                        if transcript_obj:
                            transcript_data = transcript_obj.fetch()
                            texts = []
                            for entry in transcript_data:
                                if isinstance(entry, dict):
                                    text = entry.get('text', '')
                                elif hasattr(entry, 'text'):
                                    text = getattr(entry, 'text', '')
                                else:
                                    text = str(entry)
                                if text and text.strip():
                                    texts.append(text.strip())

                            transcript = ' '.join(texts).strip()
                            if transcript:
                                logger.info(f"✅ youtube_transcript_api (list+find): Got transcript for {video_id} lang={lang} ({len(transcript)} chars)")
                                return transcript
                    except Exception:
                        continue

                # لو مفيش ترجمة باللغة المطلوبة، نجيب أي ترجمة
                try:
                    available = list(transcript_list)
                    if available:
                        first = available[0]
                        transcript_data = first.fetch()
                        texts = []
                        for entry in transcript_data:
                            if isinstance(entry, dict):
                                text = entry.get('text', '')
                            elif hasattr(entry, 'text'):
                                text = getattr(entry, 'text', '')
                            else:
                                text = str(entry)
                            if text and text.strip():
                                texts.append(text.strip())

                        transcript = ' '.join(texts).strip()
                        if transcript:
                            logger.info(f"✅ youtube_transcript_api (list+any): Got transcript for {video_id} ({len(transcript)} chars)")
                            return transcript
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"youtube_transcript_api list_transcripts error: {e}")

        logger.debug(f"youtube_transcript_api: All methods failed for {video_id}")
        return ""

    def _get_transcript_piped(self, video_id: str, languages: list = None) -> str:
        """استخراج الترجمة من Piped API

        Piped بيقدم الترجمة في الـ streams response
        GET /streams/{video_id}
        الـ subtitles بتكون في data.subtitles
        """
        if not languages:
            languages = ["ar", "en"]

        import requests as req

        for instance in PIPED_CAPTION_INSTANCES[:3]:  # نجرب 3 سيرفرات
            try:
                api_url = f"{instance}/streams/{video_id}"
                logger.info(f"🟢 Piped [{instance}]: Fetching for {video_id}")

                response = req.get(
                    api_url,
                    timeout=10,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/json",
                    }
                )

                if response.status_code != 200:
                    logger.debug(f"🟢 Piped [{instance}]: Status {response.status_code}")
                    continue

                data = response.json()

                # Piped بيرجع الترجمة في "subtitles"
                subtitles = data.get("subtitles", [])
                if not subtitles:
                    # بنحاول في "captions" كمان
                    subtitles = data.get("captions", [])

                if not subtitles:
                    logger.debug(f"🟢 Piped [{instance}]: No subtitles found")
                    continue

                # بنبحث عن الترجمة باللغة المطلوبة
                target_sub = None

                # أولاً: اللغة المطلوبة
                for lang in languages:
                    for sub in subtitles:
                        sub_lang = sub.get("language_code", "") or sub.get("code", "") or sub.get("lang", "")
                        if sub_lang == lang:
                            target_sub = sub
                            break
                    if target_sub:
                        break

                # ثانياً: أي ترجمة
                if not target_sub and subtitles:
                    for sub in subtitles:
                        sub_lang = sub.get("language_code", "") or sub.get("code", "") or sub.get("lang", "")
                        if sub_lang in ("en", "en-US", "en-GB"):
                            target_sub = sub
                            break
                    if not target_sub:
                        target_sub = subtitles[0]

                if not target_sub:
                    continue

                # استخراج رابط الترجمة
                sub_url = target_sub.get("url", "")
                if not sub_url:
                    logger.debug(f"🟢 Piped [{instance}]: No subtitle URL")
                    continue

                # ربط URL نسبي
                if sub_url.startswith("/"):
                    sub_url = f"{instance}{sub_url}"

                # تحميل الترجمة
                sub_resp = req.get(sub_url, timeout=10, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })

                if sub_resp.status_code != 200:
                    continue

                # استخراج النص من الـ response
                # ممكن يكون JSON أو XML
                content = sub_resp.text

                # محاولة JSON أولاً
                try:
                    sub_data = sub_resp.json()
                    if isinstance(sub_data, list):
                        texts = [entry.get("text", "") for entry in sub_data if entry.get("text")]
                        if texts:
                            transcript = ' '.join(texts).strip()
                            if transcript:
                                logger.info(f"✅ Piped Captions (JSON): Got transcript for {video_id} ({len(transcript)} chars)")
                                return transcript
                    elif isinstance(sub_data, dict):
                        # WebVTT format in JSON
                        events = sub_data.get("events", [])
                        texts = []
                        for event in events:
                            segs = event.get("segs", [])
                            for seg in segs:
                                t = seg.get("utf8", "") or seg.get("text", "")
                                if t and t.strip() and not t.strip().startswith("<"):
                                    texts.append(t.strip())
                        if texts:
                            transcript = ' '.join(texts).strip()
                            if transcript:
                                logger.info(f"✅ Piped Captions (YouTube JSON3): Got transcript for {video_id} ({len(transcript)} chars)")
                                return transcript
                except Exception:
                    pass

                # محاولة XML
                texts = re.findall(r'<text[^>]*>(.*?)</text>', content)
                if texts:
                    clean_texts = [unescape(re.sub(r'<[^>]+>', '', t)) for t in texts]
                    transcript = ' '.join(clean_texts).strip()
                    if transcript:
                        logger.info(f"✅ Piped Captions (XML): Got transcript for {video_id} ({len(transcript)} chars)")
                        return transcript

                # محاولة WebVTT
                if "WEBVTT" in content or "Kind:" in content:
                    vtt_texts = []
                    for line in content.split('\n'):
                        line = line.strip()
                        # Skip VTT metadata lines
                        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or \
                           line.startswith("Language:") or '-->' in line or \
                           line.replace('.', '').replace(':', '').replace('-', '').replace(' ', '').isdigit():
                            continue
                        # Skip tags
                        clean_line = re.sub(r'<[^>]+>', '', line)
                        if clean_line.strip():
                            vtt_texts.append(clean_line.strip())

                    if vtt_texts:
                        transcript = ' '.join(vtt_texts).strip()
                        if transcript:
                            logger.info(f"✅ Piped Captions (WebVTT): Got transcript for {video_id} ({len(transcript)} chars)")
                            return transcript

            except req.exceptions.Timeout:
                logger.debug(f"🟢 Piped [{instance}]: Timeout")
                continue
            except req.exceptions.ConnectionError:
                logger.debug(f"🟢 Piped [{instance}]: Connection error")
                continue
            except Exception as e:
                logger.debug(f"🟢 Piped [{instance}]: Error: {e}")
                continue

        logger.debug(f"🟢 Piped: All instances failed for {video_id}")
        return ""

    def _get_transcript_html(self, video_id: str, languages: list = None) -> str:
        """استخراج الترجمة من صفحة YouTube HTML

        🔴 ده آخر طريقة مباشرة من YouTube — مش مضمونة لأن YouTube بيغير الصفحة
        بس ممكن تشتغل لما الطرق التانية تفشل
        """
        if not languages:
            languages = ["ar", "en"]

        try:
            import requests as req

            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = req.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return ""

            page_text = resp.text

            # ═══ محاولة 1: captions في player_response ═══
            captions_match = re.search(r'"captions":\s*(\{.*?\})\s*,\s*"videoDetails"', page_text)
            if not captions_match:
                # محاولة بنمط مختلف
                captions_match = re.search(r'"captionTracks":\s*(\[.*?\])', page_text)

            if captions_match:
                import json
                try:
                    captions_data = json.loads(captions_match.group(1))

                    # لو هو captionTracks مباشرة
                    if isinstance(captions_data, list):
                        tracks = captions_data
                    else:
                        tracks = captions_data.get('playerCaptionsTracklistRenderer', {}).get('captionTracks', [])

                    # بنبحث عن اللغة المطلوبة
                    target_url = None
                    for lang in languages:
                        for track in tracks:
                            track_lang = track.get('languageCode', '') or track.get('vssId', '')
                            if track_lang == lang or track_lang.startswith(lang):
                                target_url = track.get('baseUrl', '')
                                break
                        if target_url:
                            break

                    # أي ترجمة
                    if not target_url and tracks:
                        # بنفضل الإنجليزي
                        for track in tracks:
                            track_lang = track.get('languageCode', '')
                            if track_lang in ('en', 'en-US', 'en-GB'):
                                target_url = track.get('baseUrl', '')
                                break
                        if not target_url:
                            target_url = tracks[0].get('baseUrl', '')

                    if target_url:
                        cap_resp = req.get(target_url, headers=headers, timeout=10)
                        if cap_resp.status_code == 200:
                            texts = re.findall(r'<text[^>]*>(.*?)</text>', cap_resp.text)
                            if texts:
                                clean_texts = [unescape(re.sub(r'<[^>]+>', '', t)) for t in texts]
                                transcript = ' '.join(clean_texts).strip()
                                if transcript:
                                    logger.info(f"✅ HTML Captions: Got transcript for {video_id} ({len(transcript)} chars)")
                                    return transcript
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"HTML captions parse error: {e}")

            # ═══ محاولة 2: ytInitialPlayerResponse ═══
            player_match = re.search(r'ytInitialPlayerResponse\s*=\s*(\{.*?\});', page_text)
            if player_match:
                import json
                try:
                    player_data = json.loads(player_match.group(1))
                    captions = player_data.get('captions', {})
                    tracks = captions.get('playerCaptionsTracklistRenderer', {}).get('captionTracks', [])

                    target_url = None
                    for lang in languages:
                        for track in tracks:
                            track_lang = track.get('languageCode', '')
                            if track_lang == lang or track_lang.startswith(lang):
                                target_url = track.get('baseUrl', '')
                                break
                        if target_url:
                            break

                    if not target_url and tracks:
                        for track in tracks:
                            if track.get('languageCode', '') in ('en', 'en-US'):
                                target_url = track.get('baseUrl', '')
                                break
                        if not target_url and tracks:
                            target_url = tracks[0].get('baseUrl', '')

                    if target_url:
                        cap_resp = req.get(target_url, headers=headers, timeout=10)
                        if cap_resp.status_code == 200:
                            texts = re.findall(r'<text[^>]*>(.*?)</text>', cap_resp.text)
                            if texts:
                                clean_texts = [unescape(re.sub(r'<[^>]+>', '', t)) for t in texts]
                                transcript = ' '.join(clean_texts).strip()
                                if transcript:
                                    logger.info(f"✅ HTML Player Captions: Got transcript for {video_id} ({len(transcript)} chars)")
                                    return transcript
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"HTML player captions parse error: {e}")

        except Exception as e:
            logger.debug(f"HTML transcript fetch error: {e}")

        return ""

    # ═══════════════════════════════════════
    # Video Info
    # ═══════════════════════════════════════

    def get_video_info(self, video_id: str) -> Dict:
        """الحصول على معلومات الفيديو — طرق متعددة"""
        info = {"title": "", "description": "", "transcript": "", "duration": 0, "author": ""}

        # ═══ الطريقة 1: Invidious API (أسرع وأضمن) ═══
        try:
            import requests as req

            for instance in INVIVIOUS_CAPTION_INSTANCES[:2]:  # نجرب سيرفرين بس
                try:
                    api_url = f"{instance}/api/v1/videos/{video_id}"
                    resp = req.get(
                        api_url,
                        params={"fields": "title,description,lengthSeconds,author"},
                        timeout=8,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "application/json",
                        }
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        info["title"] = data.get("title", "")
                        info["description"] = data.get("description", "")
                        info["duration"] = data.get("lengthSeconds", 0)
                        info["author"] = data.get("author", "")
                        if info["title"]:
                            logger.info(f"✅ Invidious: Got video info for {video_id}")
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Invidious video info error: {e}")

        # ═══ الطريقة 2: oEmbed API ═══
        if not info["title"]:
            try:
                import requests as req
                url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                resp = req.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    info["title"] = data.get("title", "")
                    info["author"] = data.get("author_name", "")
            except Exception as e:
                logger.debug(f"oEmbed error: {e}")

        # ═══ الطريقة 3: HTML Scraping ═══
        if not info["title"]:
            try:
                import requests as req
                url = f"https://www.youtube.com/watch?v={video_id}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                }
                resp = req.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    title_match = re.search(r'<title>(.*?)</title>', resp.text)
                    if title_match:
                        info["title"] = title_match.group(1).replace(" - YouTube", "").strip()

                    # محاولة استخراج الوصف
                    desc_match = re.search(r'"shortDescription":"(.*?)"', resp.text)
                    if desc_match:
                        info["description"] = desc_match.group(1).replace("\\n", "\n").replace('\\"', '"')
            except Exception:
                pass

        # Get transcript
        info["transcript"] = self.get_transcript(video_id)

        return info

    # ═══════════════════════════════════════
    # Web Search Fallback
    # ═══════════════════════════════════════

    def _search_video_info(self, video_id: str, title: str = "", language: str = "ar") -> str:
        """بحث في الويب عن معلومات الفيديو كـ Fallback"""
        try:
            from web_search import _search_web_sync

            search_query = title if title else f"youtube video {video_id}"
            if language == "ar":
                search_query += " ملخص شرح summary"
            else:
                search_query += " summary review explained"

            logger.info(f"🔍 Searching web for video info: {search_query}")

            results = _search_web_sync(search_query, num_results=5)
            if results:
                combined = ""
                for i, result in enumerate(results):
                    combined += f"\n--- نتيجة {i+1} ---\n"
                    combined += f"العنوان: {result.get('name', '')}\n"
                    combined += f"{result.get('snippet', '')}\n"
                return combined
        except Exception as e:
            logger.warning(f"Web search for video info failed: {e}")

        return ""

    # ═══════════════════════════════════════
    # Summarization
    # ═══════════════════════════════════════

    async def summarize_video(self, url: str, language: str = "ar", user_id: int = None) -> str:
        """تلخيص فيديو YouTube — Pipeline كامل مع Fallback متعدد"""
        video_id = self.extract_video_id(url)
        if not video_id:
            return "❌ رابط YouTube غير صحيح." if language == "ar" else "❌ Invalid YouTube URL."

        video_info = self.get_video_info(video_id)
        title = video_info.get("title", "فيديو YouTube" if language == "ar" else "YouTube Video")
        transcript = video_info.get("transcript", "")
        description = video_info.get("description", "")
        author = video_info.get("author", "")
        duration = video_info.get("duration", 0)

        from provider_manager import call_ai
        from formatters import clean_ai_response
        from config import PDF_MAX_CHARS

        # تنسيق المدة
        duration_str = ""
        if duration:
            mins, secs = divmod(int(duration), 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                duration_str = f"{hours}:{mins:02d}:{secs:02d}"
            else:
                duration_str = f"{mins}:{secs:02d}"

        # ═══ لو عندنا transcript — تلخيص شامل ═══
        if transcript:
            content = transcript[:PDF_MAX_CHARS] if len(transcript) > PDF_MAX_CHARS else transcript

            # بناء header معلومات الفيديو
            video_header = f"🎬 <b>عنوان الفيديو:</b> {title}"
            if author:
                video_header += f"\n👤 <b>القناة:</b> {author}"
            if duration_str:
                video_header += f"\n⏱️ <b>المدة:</b> {duration_str}"

            if language == "ar":
                prompt = f"""لخص الفيديو التالي بشكل شامل ومنظم بالعربية:

{video_header}

📝 <b>محتوى الفيديو:</b>
{content}

المطلوب:
• ملخص شامل ومفصل لمحتوى الفيديو
• النقاط الرئيسية والتفاصيل المهمة
• الأفكار والمعلومات المفيدة
• استنتاجات إن وُجدت
• لو فيه خطوات أو تعليمات — اذكرها بالترتيب

🔴🔴🔴 قواعد صارمة:
• ماتستخدمش Markdown أبداً (لا *, **, #, |, []). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط
• 🔴 ماتقولش أبداً إنك مش قادر تلخص!
• 🔴 لازم تلخص المحتوى ده — ده وظيفتك!
• 🔴 ابدأ بالملخص مباشرة بدون مقدمات

أنت مساعد ذكي متخصص في تلخيص الفيديوهات. تلخص بالعربية بشكل منظم وواضح. ماتستخدمش Markdown أبداً. استخدم HTML فقط."""
            else:
                prompt = f"""Summarize the following video comprehensively in English:

{video_header}

📝 <b>Video Content:</b>
{content}

Requirements:
• Comprehensive and detailed summary
• Key points and important details
• Useful ideas and information
• Conclusions if any
• If there are steps or instructions — list them in order

🔴🔴🔴 Strict rules:
• NEVER use Markdown (no *, **, #, |, []). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets
• 🔴 NEVER say you cannot summarize!
• 🔴 You MUST summarize this content!
• 🔴 Start with the summary directly without introductions

You are a smart assistant specialized in video summarization. NEVER use Markdown. Use HTML only."""

            result = await call_ai(prompt, max_tokens=2000, user_id=user_id, task_type="summary")
            return clean_ai_response(result)

        # ═══ Fallback 1: Web Search ═══
        web_info = self._search_video_info(video_id, title, language)

        if web_info:
            if language == "ar":
                prompt = f"""بناءً على نتائج البحث التالية عن فيديو YouTube بعنوان "{title}"، لخص محتوى الفيديو:

{web_info}

لخص بشكل منظم بالعربية. ماتستخدمش Markdown أبداً. استخدم HTML فقط: <b>عريض</b> <i>مائل</i> • نقاط

🔴 ملاحظة: أنت بتلخص بناءً على معلومات من الويب لأن الترجمة مش متاحة للفيديو.
🔴 ابدأ بالملخص مباشرة بدون مقدمات."""
            else:
                prompt = f"""Based on the following search results about a YouTube video titled "{title}", summarize the video:

{web_info}

Summarize in English in an organized way. NEVER use Markdown. Use HTML only: <b>bold</b> <i>italic</i> • bullets

🔴 Note: You are summarizing based on web information because captions are not available for this video.
🔴 Start with the summary directly without introductions."""

            result = await call_ai(prompt, max_tokens=1500, user_id=user_id, task_type="summary")
            return clean_ai_response(result)

        # ═══ Fallback 2: Description + Title ═══
        if description and len(description) > 50:
            if language == "ar":
                prompt = f"""بناءً على عنوان ووصف الفيديو التالي، اكتب ملخص تقريبي لمحتوى الفيديو:

🎬 <b>العنوان:</b> {title}
👤 <b>القناة:</b> {author or "غير معروف"}
⏱️ <b>المدة:</b> {duration_str or "غير معروف"}

📝 <b>الوصف:</b>
{description[:5000]}

اكتب ملخص تقريبي بالعربية بناءً على العنوان والوصف. ماتستخدمش Markdown أبداً. استخدم HTML فقط.

🔴 ابدأ بالملخص مباشرة. 🔴 وضّح إن ده ملخص تقريبي بناءً على الوصف فقط."""
            else:
                prompt = f"""Based on the video title and description below, write an approximate summary:

🎬 <b>Title:</b> {title}
👤 <b>Channel:</b> {author or "Unknown"}
⏱️ <b>Duration:</b> {duration_str or "Unknown"}

📝 <b>Description:</b>
{description[:5000]}

Write an approximate summary in English based on the title and description. NEVER use Markdown. Use HTML only.

🔴 Start with the summary directly. 🔴 Note this is an approximate summary based on the description only."""

            result = await call_ai(prompt, max_tokens=1000, user_id=user_id, task_type="summary")
            return clean_ai_response(result)

        # ═══ Last Resort: Basic Info ═══
        if language == "ar":
            return f"🎬 <b>{title}</b>\n{f'👤 {author}' if author else ''}\n{f'⏱️ {duration_str}' if duration_str else ''}\n\n⚠️ لم أتمكن من الحصول على محتوى الفيديو. جرب فيديو فيه ترجمة (captions)."
        else:
            return f"🎬 <b>{title}</b>\n{f'👤 {author}' if author else ''}\n{f'⏱️ {duration_str}' if duration_str else ''}\n\n⚠️ Couldn't get video content. Try a video with captions."

    # ═══════════════════════════════════════
    # Quiz Creation
    # ═══════════════════════════════════════

    async def create_quiz_from_video(self, url: str, num_questions: int = 5, language: str = "ar", user_id: int = None) -> str:
        """إنشاء كويز من فيديو YouTube"""
        video_id = self.extract_video_id(url)
        if not video_id:
            return "❌ رابط YouTube غير صحيح." if language == "ar" else "❌ Invalid YouTube URL."

        video_info = self.get_video_info(video_id)
        transcript = video_info.get("transcript", "")
        title = video_info.get("title", "")
        description = video_info.get("description", "")

        # لو مفيش transcript، نجرب web search
        if not transcript:
            web_info = self._search_video_info(video_id, title, language)
            if web_info:
                transcript = web_info

        # لو مفيش حاجة، نستخدم الوصف
        if not transcript and description and len(description) > 50:
            transcript = f"وصف الفيديو:\n{description}"

        if not transcript:
            if language == "ar":
                return "❌ مش قادر أجيب محتوى الفيديو لإنشاء كويز. جرب فيديو فيه ترجمة."
            else:
                return "❌ Can't get video content for quiz creation. Try a video with captions."

        from provider_manager import call_ai
        from formatters import clean_ai_response

        if language == "ar":
            prompt = f"""أنشئ كويز من محتوى الفيديو ({num_questions} أسئلة):

🎬 عنوان الفيديو: {title}

المحتوى:
{transcript[:8000]}

تنسيق الكويز:
📝 <b>كويز: {title}</b>

❓ <b>سؤال 1:</b> [السؤال]
أ) خيار 1
ب) خيار 2
ج) خيار 3
د) خيار 4

✅ <b>الإجابة الصحيحة:</b> [الحرف]
💡 <b>الشرح:</b> [شرح مختصر]

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط.

أنت مساعد تعليمي تنشئ كويزات من محتوى الفيديوهات. ماتستخدمش Markdown أبداً."""
        else:
            prompt = f"""Create a quiz from the video content ({num_questions} questions):

🎬 Video Title: {title}

Content:
{transcript[:8000]}

Quiz format:
📝 <b>Quiz: {title}</b>

❓ <b>Question 1:</b> [question]
A) option 1
B) option 2
C) option 3
D) option 4

✅ <b>Answer:</b> [letter]
💡 <b>Explanation:</b> [brief explanation]

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only.

You are an educational assistant that creates quizzes from video content. NEVER use Markdown."""

        result = await call_ai(prompt, max_tokens=2000, user_id=user_id, task_type="chat")
        return clean_ai_response(result)

    # ═══════════════════════════════════════
    # Review Notes
    # ═══════════════════════════════════════

    async def create_review_notes(self, url: str, language: str = "ar", user_id: int = None) -> str:
        """إنشاء ملاحظات مراجعة من فيديو YouTube"""
        video_id = self.extract_video_id(url)
        if not video_id:
            return "❌ رابط YouTube غير صحيح." if language == "ar" else "❌ Invalid YouTube URL."

        video_info = self.get_video_info(video_id)
        transcript = video_info.get("transcript", "")
        title = video_info.get("title", "")
        author = video_info.get("author", "")

        if not transcript:
            web_info = self._search_video_info(video_id, title, language)
            if web_info:
                transcript = web_info

        if not transcript:
            if language == "ar":
                return "❌ مش قادر أجيب محتوى الفيديو لإنشاء ملاحظات. جرب فيديو فيه ترجمة."
            else:
                return "❌ Can't get video content for notes. Try a video with captions."

        from provider_manager import call_ai
        from formatters import clean_ai_response
        from config import PDF_MAX_CHARS

        content = transcript[:PDF_MAX_CHARS] if len(transcript) > PDF_MAX_CHARS else transcript

        if language == "ar":
            prompt = f"""أنشئ ملاحظات مراجعة شاملة من محتوى الفيديو:

🎬 عنوان الفيديو: {title}
👤 القناة: {author or "غير معروف"}

المحتوى:
{content}

تنسيق الملاحظات:
📒 <b>ملاحظات مراجعة: {title}</b>

📌 <b>المفاهيم الأساسية:</b>
• ...

📋 <b>النقاط الرئيسية:</b>
• ...

💡 <b>معلومات مهمة:</b>
• ...

🔗 <b>العلاقات والروابط:</b>
• ...

📝 <b>خلاصة:</b>
...

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط.

أنت مساعد تعليمي تنشئ ملاحظات مراجعة شاملة. ماتستخدمش Markdown أبداً."""
        else:
            prompt = f"""Create comprehensive review notes from the video content:

🎬 Video Title: {title}
👤 Channel: {author or "Unknown"}

Content:
{content}

Notes format:
📒 <b>Review Notes: {title}</b>

📌 <b>Core Concepts:</b>
• ...

📋 <b>Key Points:</b>
• ...

💡 <b>Important Information:</b>
• ...

🔗 <b>Relationships & Connections:</b>
• ...

📝 <b>Summary:</b>
...

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only.

You are an educational assistant that creates comprehensive review notes. NEVER use Markdown."""

        result = await call_ai(prompt, max_tokens=2000, user_id=user_id, task_type="summary")
        return clean_ai_response(result)
