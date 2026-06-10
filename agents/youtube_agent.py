"""
وكيل يوتيوب - YouTube Agent
تلخيص فيديوهات YouTube مع fallback للبحث في الويب
"""

import asyncio
import logging
import re
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# أنماط روابط YouTube
YOUTUBE_PATTERNS = [
    r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
    r'^([a-zA-Z0-9_-]{11})$',
]


class YouTubeAgent:
    """وكيل YouTube - تلخيص فيديوهات مع fallback متعدد"""

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

    def get_transcript(self, video_id: str, languages: list = None) -> str:
        """استخراج نص الفيديو - طرق متعددة مع fallback"""
        if not languages:
            languages = ["ar", "en"]

        # Method 1: youtube_transcript_api
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript_list = YouTubeTranscriptApi.fetch(video_id, languages=languages)

            if hasattr(transcript_list, '__iter__'):
                texts = []
                for entry in transcript_list:
                    if isinstance(entry, dict):
                        text = entry.get('text', '')
                    else:
                        text = getattr(entry, 'text', '')
                    if text:
                        texts.append(text)
                transcript = ' '.join(texts).strip()
                if transcript:
                    logger.info(f"✅ Got transcript for {video_id} (direct fetch, {len(transcript)} chars)")
                    return transcript
        except ImportError:
            logger.warning("youtube_transcript_api not installed")
        except Exception as e:
            logger.debug(f"youtube_transcript_api fetch with languages error: {e}")

        # Method 2: Try fetching transcript via HTML page
        try:
            import requests
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                # Try to find captions in the page
                captions_match = re.search(r'"captions":\s*(\{.*?\})\s*,\s*"videoDetails"', resp.text)
                if captions_match:
                    import json
                    from html import unescape
                    captions_data = json.loads(captions_match.group(1))
                    tracks = captions_data.get('playerCaptionsTracklistRenderer', {}).get('captionTracks', [])
                    for track in tracks:
                        base_url = track.get('baseUrl', '')
                        if base_url:
                            cap_resp = requests.get(base_url, headers=headers, timeout=10)
                            if cap_resp.status_code == 200:
                                texts = re.findall(r'<text[^>]*>(.*?)</text>', cap_resp.text)
                                if texts:
                                    clean_texts = [unescape(re.sub(r'<[^>]+>', '', t)) for t in texts]
                                    transcript = ' '.join(clean_texts).strip()
                                    if transcript:
                                        logger.info(f"✅ Got transcript via captions for {video_id} ({len(transcript)} chars)")
                                        return transcript
        except Exception as e:
            logger.debug(f"HTML transcript fetch error: {e}")

        return ""

    def get_video_info(self, video_id: str) -> Dict:
        """الحصول على معلومات الفيديو"""
        import requests

        info = {"title": "", "description": "", "transcript": ""}

        try:
            # oEmbed API
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                info["title"] = data.get("title", "")
        except Exception as e:
            logger.debug(f"oEmbed error: {e}")

        # If no title from oEmbed, try scraping
        if not info["title"]:
            try:
                url = f"https://www.youtube.com/watch?v={video_id}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                }
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    title_match = re.search(r'<title>(.*?)</title>', resp.text)
                    if title_match:
                        info["title"] = title_match.group(1).replace(" - YouTube", "").strip()
            except Exception:
                pass

        # Get transcript
        info["transcript"] = self.get_transcript(video_id)

        return info

    def _search_video_info(self, video_id: str, title: str = "", language: str = "ar") -> str:
        """
        بحث في الويب عن معلومات الفيديو كـ Fallback
        لما الترجمة مش متاحة - بنبحث عن الفيديو ونجيب معلومات عن محتواه
        """
        try:
            from web_search import _search_web_sync

            search_query = title if title else f"youtube video {video_id}"
            if language == "ar":
                search_query += " ملخص summary"
            else:
                search_query += " summary"

            logger.info(f"🔍 Searching web for video info: {search_query}")

            results = _search_web_sync(search_query, num_results=3)
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

    async def summarize_video(self, url: str, language: str = "ar", user_id: int = None) -> str:
        """تلخيص فيديو YouTube مع Fallback للبحث في الويب"""
        video_id = self.extract_video_id(url)
        if not video_id:
            return "❌ رابط YouTube غير صحيح." if language == "ar" else "❌ Invalid YouTube URL."

        video_info = self.get_video_info(video_id)
        title = video_info.get("title", "فيديو YouTube" if language == "ar" else "YouTube Video")
        transcript = video_info.get("transcript", "")
        description = video_info.get("description", "")

        from provider_manager import call_ai
        from formatters import clean_ai_response
        from config import PDF_MAX_CHARS

        # If we have a transcript, summarize it
        if transcript:
            content = transcript[:PDF_MAX_CHARS] if len(transcript) > PDF_MAX_CHARS else transcript

            if language == "ar":
                prompt = f"""لخص الفيديو التالي بشكل شامل ومنظم بالعربية:

🎬 <b>عنوان الفيديو:</b> {title}

📝 <b>محتوى الفيديو:</b>
{content}

المطلوب:
• ملخص شامل ومفصل لمحتوى الفيديو
• النقاط الرئيسية والتفاصيل المهمة
• الأفكار والمعلومات المفيدة
• استنتاجات إن وُجدت

🔴🔴🔴 قواعد صارمة:
• ماتستخدمش Markdown أبداً (لا *, **, #, |, []). استخدم HTML فقط: <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط
• 🔴 ماتقولش أبداً إنك مش قادر تلخص!
• 🔴 لازم تلخص المحتوى ده — ده وظيفتك!

أنت مساعد ذكي متخصص في تلخيص الفيديوهات. تلخص بالعربية بشكل منظم وواضح. ماتستخدمش Markdown أبداً. استخدم HTML فقط."""
            else:
                prompt = f"""Summarize the following video comprehensively in English:

🎬 <b>Video Title:</b> {title}

📝 <b>Video Content:</b>
{content}

Requirements:
• Comprehensive and detailed summary
• Key points and important details
• Useful ideas and information
• Conclusions if any

🔴🔴🔴 Strict rules:
• NEVER use Markdown (no *, **, #, |, []). Use HTML only: <b>bold</b> <i>italic</i> <code>code</code> • bullets
• 🔴 NEVER say you cannot summarize!
• 🔴 You MUST summarize this content!

You are a smart assistant specialized in video summarization. NEVER use Markdown. Use HTML only."""

            result = await call_ai(prompt, max_tokens=2000, user_id=user_id, task_type="summary")
            return clean_ai_response(result)

        # Fallback: search the web for video info
        web_info = self._search_video_info(video_id, title, language)

        if web_info:
            if language == "ar":
                prompt = f"""بناءً على نتائج البحث التالية عن فيديو YouTube بعنوان "{title}"، لخص محتوى الفيديو:

{web_info}

لخص بشكل منظم بالعربية. ماتستخدمش Markdown أبداً. استخدم HTML فقط: <b>عريض</b> <i>مائل</i> • نقاط

🔴 ملاحظة: أنت بتلخص بناءً على معلومات من الويب لأن الترجمة مش متاحة للفيديو."""
            else:
                prompt = f"""Based on the following search results about a YouTube video titled "{title}", summarize the video:

{web_info}

Summarize in English in an organized way. NEVER use Markdown. Use HTML only: <b>bold</b> <i>italic</i> • bullets

🔴 Note: You are summarizing based on web information because captions are not available for this video."""

            result = await call_ai(prompt, max_tokens=1500, user_id=user_id, task_type="summary")
            return clean_ai_response(result)

        # Last resort: basic info
        if language == "ar":
            return f"🎬 <b>{title}</b>\n\n⚠️ لم أتمكن من الحصول على محتوى الفيديو. جرب فيديو فيه ترجمة (captions)."
        else:
            return f"🎬 <b>{title}</b>\n\n⚠️ Couldn't get video content. Try a video with captions."

    async def create_quiz_from_video(self, url: str, num_questions: int = 5, language: str = "ar", user_id: int = None) -> str:
        """إنشاء كويز من فيديو YouTube"""
        video_id = self.extract_video_id(url)
        if not video_id:
            return "❌ رابط YouTube غير صحيح." if language == "ar" else "❌ Invalid YouTube URL."

        video_info = self.get_video_info(video_id)
        transcript = video_info.get("transcript", "")
        title = video_info.get("title", "")

        if not transcript:
            web_info = self._search_video_info(video_id, title, language)
            if web_info:
                transcript = web_info
            else:
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
📝 <b>كويز</b>

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
📝 <b>Quiz</b>

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
