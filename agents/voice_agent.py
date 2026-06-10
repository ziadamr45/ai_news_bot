"""
وكيل الصوت - Voice Agent
تحويل الرسائل الصوتية إلى نص ثم معالجتها
يدعم: Groq Whisper (أساسي - سريع ومجاني) → Google Speech (مجاني بس محتاج ffmpeg) → OpenRouter Whisper → OpenAI Whisper
4 fallback layers عشان يشتغل في كل الأحوال

🔴 v2: Groq Whisper بقت الأساسية لأنها مش محتاجة ffmpeg وبتقبل OGG مباشرة
"""

import asyncio
import logging
import os
import shutil
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

# فحص توفر ffmpeg — مطلوب لـ Google Speech (تحويل OGG→WAV)
_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
if _FFMPEG_AVAILABLE:
    logger.info("✅ ffmpeg found — Google Speech layer available")
else:
    logger.warning("⚠️ ffmpeg NOT found — Google Speech layer will be skipped. Groq Whisper is primary.")


class VoiceAgent:
    """وكيل الصوت - 4 طبقات fallback لتحويل الصوت لنص"""

    def __init__(self):
        # تحميل مفاتيح API من config
        self.groq_api_key = ""
        self.groq_base_url = "https://api.groq.com/openai/v1"
        self.openai_api_key = ""
        self.openrouter_api_key = ""
        self.openrouter_base_url = "https://openrouter.ai/api/v1"

        try:
            from config import GROQ_API_KEY, GROQ_BASE_URL
            self.groq_api_key = GROQ_API_KEY or ""
            self.groq_base_url = GROQ_BASE_URL or self.groq_base_url
        except (ImportError, Exception):
            try:
                self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
                self.groq_base_url = os.environ.get("GROQ_BASE_URL", self.groq_base_url)
            except Exception:
                pass

        try:
            from config import OPENAI_API_KEY
            self.openai_api_key = OPENAI_API_KEY or ""
        except (ImportError, Exception):
            self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")

        try:
            from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
            self.openrouter_api_key = OPENROUTER_API_KEY or ""
            self.openrouter_base_url = OPENROUTER_BASE_URL or self.openrouter_base_url
        except (ImportError, Exception):
            self.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
            self.openrouter_base_url = os.environ.get("OPENROUTER_BASE_URL", self.openrouter_base_url)

        # بناء قائمة المزودين المتاحين
        providers = []
        if self.groq_api_key:
            providers.append("Groq Whisper (primary)")
        if _FFMPEG_AVAILABLE:
            providers.append("Google Speech (free)")
        else:
            providers.append("Google Speech (SKIPPED — no ffmpeg)")
        if self.openrouter_api_key:
            providers.append("OpenRouter Whisper")
        if self.openai_api_key:
            providers.append("OpenAI Whisper")

        logger.info(f"🎤 VoiceAgent initialized with: {', '.join(providers)}")

    def _convert_ogg_to_wav(self, audio_bytes: bytes) -> bytes:
        """تحويل OGG (Telegram) إلى WAV (مطلوب لـ Google Speech)"""
        if not _FFMPEG_AVAILABLE:
            raise RuntimeError("ffmpeg not available — cannot convert OGG to WAV")

        from pydub import AudioSegment
        from io import BytesIO

        audio = AudioSegment.from_ogg(BytesIO(audio_bytes))
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        wav_buffer = BytesIO()
        audio.export(wav_buffer, format="wav")
        wav_bytes = wav_buffer.getvalue()
        logger.info(f"🔊 Audio converted: OGG {len(audio_bytes)} bytes → WAV {len(wav_bytes)} bytes")
        return wav_bytes

    def transcribe(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """
        تحويل الصوت إلى نص — 4 طبقات fallback
        1. Groq Whisper (سريع ومجاني، بيقبل OGG مباشرة — الأساسي)
        2. Google Speech Recognition (مجاني، محتاج ffmpeg)
        3. OpenRouter Whisper
        4. OpenAI Whisper
        """
        if not audio_bytes and not file_path:
            return {"text": "", "success": False, "error": "No audio data provided", "provider": "none"}

        # Layer 1: Groq Whisper (الأساسي — بيقبل OGG مباشرة ومش محتاج ffmpeg)
        if self.groq_api_key:
            result = self._transcribe_groq(audio_bytes, file_path, language)
            if result["success"]:
                return result
        else:
            logger.debug("Groq API key not configured, skipping")

        # Layer 2: Google Speech (مجاني بس محتاج ffmpeg لتحويل OGG→WAV)
        if _FFMPEG_AVAILABLE:
            result = self._transcribe_google(audio_bytes, file_path, language)
            if result["success"]:
                return result
        else:
            logger.debug("ffmpeg not available, skipping Google Speech")

        # Layer 3: OpenRouter Whisper
        if self.openrouter_api_key:
            result = self._transcribe_openrouter(audio_bytes, file_path, language)
            if result["success"]:
                return result
        else:
            logger.debug("OpenRouter API key not configured, skipping")

        # Layer 4: OpenAI Whisper
        if self.openai_api_key:
            result = self._transcribe_openai(audio_bytes, file_path, language)
            if result["success"]:
                return result
        else:
            logger.debug("OpenAI API key not configured, skipping")

        logger.warning("❌ All voice transcription methods failed")
        return {"text": "", "success": False, "error": "All voice transcription methods failed", "provider": "none"}

    def _transcribe_groq(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """تحويل الصوت لنص باستخدام Groq Whisper API — الأساسي (بيقبل OGG مباشرة)"""
        import requests

        try:
            # Write to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
            tmp.write(audio_bytes)
            tmp.close()
            tmp_path = tmp.name

            try:
                url = f"{self.groq_base_url}/audio/transcriptions"
                headers = {"Authorization": f"Bearer {self.groq_api_key}"}
                
                with open(tmp_path, "rb") as audio_file:
                    files = {"file": ("audio.ogg", audio_file, "audio/ogg")}
                    data = {
                        "model": "whisper-large-v3",
                        "response_format": "json",
                    }
                    if language and language != "auto":
                        data["language"] = language

                    response = requests.post(url, headers=headers, files=files, data=data, timeout=30)

                if response.status_code == 200:
                    result = response.json()
                    text = result.get("text", "").strip()
                    if text:
                        logger.info(f"✅ Groq Whisper transcription: {text[:80]}")
                        return {"text": text, "success": True, "provider": "groq"}
                    else:
                        logger.warning("Groq Whisper returned empty text")
                        return {"text": "", "success": False, "error": "Groq Whisper returned empty text", "provider": "groq"}
                else:
                    error_msg = f"Groq Whisper error: {response.status_code} - {response.text[:200]}"
                    logger.warning(error_msg)
                    return {"text": "", "success": False, "error": error_msg, "provider": "groq"}
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Groq Whisper transcription error: {e}")
            return {"text": "", "success": False, "error": str(e), "provider": "groq"}

    def _transcribe_google(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """تحويل الصوت لنص باستخدام Google Speech Recognition (مجاني، بدون API key، محتاج ffmpeg)"""
        try:
            import speech_recognition as sr
        except ImportError:
            logger.error("❌ speech_recognition library not installed! Run: pip install SpeechRecognition")
            return {"text": "", "success": False, "error": "speech_recognition not installed", "provider": "none"}

        if not _FFMPEG_AVAILABLE:
            return {"text": "", "success": False, "error": "ffmpeg not available for OGG→WAV conversion", "provider": "google"}

        try:
            wav_bytes = None

            # Convert to WAV if needed
            if audio_bytes:
                try:
                    wav_bytes = self._convert_ogg_to_wav(audio_bytes)
                except Exception as conv_err:
                    logger.error(f"❌ File conversion error: {conv_err}")
                    # Try direct file reading as fallback
                    try:
                        from pydub import AudioSegment
                        from io import BytesIO
                        audio = AudioSegment.from_file(BytesIO(audio_bytes))
                        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
                        wav_buffer = BytesIO()
                        audio.export(wav_buffer, format="wav")
                        wav_bytes = wav_buffer.getvalue()
                    except Exception as e2:
                        logger.error(f"❌ Fallback conversion also failed: {e2}")

                if not wav_bytes:
                    logger.error("❌ No audio data to convert for Google Speech")
                    return {"text": "", "success": False, "error": "conversion failed — ffmpeg may be missing", "provider": "google"}

            # Write WAV to temp file for speech_recognition
            wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            wav_tmp.write(wav_bytes)
            wav_tmp.close()

            try:
                recognizer = sr.Recognizer()
                with sr.AudioFile(wav_tmp.name) as source:
                    recognizer.adjust_for_ambient_noise(source)
                    audio_data = recognizer.record(source)

                # Language mapping
                lang_map = {
                    "ar": "ar-EG", "en": "en-US", "fr": "fr-FR",
                    "de": "de-DE", "es": "es-ES", "tr": "tr-TR",
                    "ur": "ur-PK", "id": "id-ID",
                }
                lang_code = lang_map.get(language, "ar-EG")

                # Try with specific language
                try:
                    text = recognizer.recognize_google(audio_data, language=lang_code)
                    if text and text.strip():
                        logger.info(f"✅ Google Speech transcription ({lang_code}): {text[:80]}")
                        return {"text": text.strip(), "success": True, "provider": "google"}
                except sr.UnknownValueError:
                    logger.debug(f"Google Speech couldn't understand audio in {lang_code}, trying fallback...")
                except sr.RequestError as e:
                    logger.warning(f"Google Speech API error: {e}")

                # Fallback: try Arabic then English
                if language != "ar":
                    try:
                        text = recognizer.recognize_google(audio_data, language="ar-EG")
                        if text and text.strip():
                            logger.info(f"✅ Google Speech fallback transcription (ar-EG): {text[:80]}")
                            return {"text": text.strip(), "success": True, "provider": "google"}
                    except (sr.UnknownValueError, sr.RequestError):
                        pass

                # Auto-detect
                try:
                    text = recognizer.recognize_google(audio_data)
                    if text and text.strip():
                        logger.info(f"✅ Google Speech auto-detect transcription: {text[:80]}")
                        return {"text": text.strip(), "success": True, "provider": "google"}
                except (sr.UnknownValueError, sr.RequestError):
                    pass

                return {"text": "", "success": False, "error": "Google Speech: Could not transcribe audio in any language", "provider": "google"}

            finally:
                try:
                    os.unlink(wav_tmp.name)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Google Speech transcription error: {e}")
            return {"text": "", "success": False, "error": str(e), "provider": "google"}

    def _transcribe_openrouter(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """تحويل الصوت لنص باستخدام OpenRouter (يوجه لـ OpenAI Whisper)"""
        import requests

        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
            tmp.write(audio_bytes)
            tmp.close()
            tmp_path = tmp.name

            try:
                url = f"{self.openrouter_base_url}/audio/transcriptions"
                headers = {
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "HTTP-Referer": "https://github.com/ziadamr45/ai-news-bot",
                    "X-Title": "My Bro AI Bot",
                }
                
                with open(tmp_path, "rb") as audio_file:
                    files = {"file": ("audio.ogg", audio_file, "audio/ogg")}
                    data = {
                        "model": "openai/whisper-1",
                        "response_format": "json",
                    }
                    if language and language != "auto":
                        data["language"] = language

                    response = requests.post(url, headers=headers, files=files, data=data, timeout=30)

                if response.status_code == 200:
                    result = response.json()
                    text = result.get("text", "").strip()
                    if text:
                        logger.info(f"✅ OpenRouter Whisper transcription: {text[:80]}")
                        return {"text": text, "success": True, "provider": "openrouter"}
                    else:
                        logger.warning("OpenRouter Whisper returned empty text")
                        return {"text": "", "success": False, "error": "OpenRouter Whisper returned empty text", "provider": "openrouter"}
                else:
                    error_msg = f"OpenRouter Whisper error: {response.status_code} - {response.text[:200]}"
                    logger.warning(error_msg)
                    return {"text": "", "success": False, "error": error_msg, "provider": "openrouter"}
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"OpenRouter Whisper transcription error: {e}")
            return {"text": "", "success": False, "error": str(e), "provider": "openrouter"}

    def _transcribe_openai(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """تحويل الصوت لنص باستخدام OpenAI Whisper API"""
        import requests

        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
            tmp.write(audio_bytes)
            tmp.close()
            tmp_path = tmp.name

            try:
                url = "https://api.openai.com/v1/audio/transcriptions"
                headers = {"Authorization": f"Bearer {self.openai_api_key}"}
                
                with open(tmp_path, "rb") as audio_file:
                    files = {"file": ("audio.ogg", audio_file, "audio/ogg")}
                    data = {
                        "model": "whisper-1",
                        "response_format": "json",
                    }
                    if language and language != "auto":
                        data["language"] = language

                    response = requests.post(url, headers=headers, files=files, data=data, timeout=30)

                if response.status_code == 200:
                    result = response.json()
                    text = result.get("text", "").strip()
                    if text:
                        logger.info(f"✅ OpenAI Whisper transcription: {text[:80]}")
                        return {"text": text, "success": True, "provider": "openai"}
                    else:
                        logger.warning("OpenAI Whisper returned empty text")
                        return {"text": "", "success": False, "error": "OpenAI Whisper returned empty text", "provider": "openai"}
                else:
                    error_msg = f"OpenAI Whisper error: {response.status_code} - {response.text[:200]}"
                    logger.warning(error_msg)
                    return {"text": "", "success": False, "error": error_msg, "provider": "openai"}
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"OpenAI Whisper transcription error: {e}")
            return {"text": "", "success": False, "error": str(e), "provider": "openai"}

    async def process_voice_message(self, audio_bytes: bytes, language_hint: str = "ar") -> dict:
        """
        معالجة رسالة صوتية كاملة
        Returns: {"text": str, "success": bool, "error": str, "provider": str}
        """
        try:
            lang = language_hint or "ar"
            if lang == "":
                lang = "auto"

            # Run transcription in executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.transcribe(audio_bytes, language=lang)
            )

            if result.get("success") and result.get("text", "").strip():
                return result
            else:
                error_msg = result.get("error", "transcription_failed")
                if "no_api_key" in str(error_msg).lower() or "not configured" in str(error_msg).lower():
                    return {"text": "", "success": False, "error": "no_api_key", "provider": "none"}
                return {"text": "", "success": False, "error": "All ASR providers failed to transcribe audio", "provider": "none"}

        except Exception as e:
            logger.error(f"Voice processing error: {e}")
            return {"text": "", "success": False, "error": str(e), "provider": "none"}
