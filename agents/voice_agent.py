"""
وكيل الصوت - Voice Agent
تحويل الرسائل الصوتية إلى نص ثم معالجتها
يدعم: Mistral Voxtral (أساسي) → NVIDIA NIM Omni (REST) → Google Speech (محتاج ffmpeg) → OpenRouter → OpenAI

🔴 v4 (2026-11-03): Groq حظرت الحساب (organization_restricted) — كل الفويس كانت بتقع على Omni
اللي بيلفّ العربي إنجليزي (شكوى زياد). المباراة اللايف على فويس عربي حقيقي:
  Voxtral-mini: 200 في 0.5s — نص عربي كامل صحيح ✅ | HF whisper: 402 خلص كريدت ❌
→ Voxtral-mini هو الأساسي الجديد.
🔴 v3 (2026-11-03): NVIDIA nemotron-3-nano-omni-30b بياخد صوت عبر REST مباشرة
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
        self.mistral_api_key = ""
        self.openai_api_key = ""
        self.openrouter_api_key = ""
        # 🔴 NVIDIA NIM Omni — STT عبر REST (المفاتيح عالمية — أي مفتاح ينادي أي نموذج)
        self.nim_omni_key = (os.environ.get("NVIDIA_OMNI_30B_KEY", "")
                             or os.environ.get("NVIDIA_NEMOTRON_BOLT_KEY", "") or "")
        # 🔴 Gemini 3.5 Transcribe — الأساسي الجديد (أمر زياد 2026-11-04)
        self.gemini_transcribe_key = ""
        try:
            from config.ai_providers import GOOGLE_TRANSCRIBE_KEY
            self.gemini_transcribe_key = GOOGLE_TRANSCRIBE_KEY or ""
        except (ImportError, Exception):
            self.gemini_transcribe_key = os.environ.get("GOOGLE_TRANSCRIBE_KEY", "")

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

        # 🔴 Mistral Voxtral — الأساسي الجديد (مختبر لايف: عربي ممتاز 0.5s)
        try:
            from config import MISTRAL_API_KEY
            self.mistral_api_key = MISTRAL_API_KEY or ""
        except (ImportError, Exception):
            self.mistral_api_key = os.environ.get("MISTRAL_API_KEY", "")

        # بناء قائمة المزودين المتاحين
        providers = []
        if self.gemini_transcribe_key:
            providers.append("Gemini 3.5 Transcribe (primary)")
        if self.mistral_api_key:
            providers.append("Mistral Voxtral (secondary)")
        if self.nim_omni_key:
            providers.append("NVIDIA NIM Omni (REST)")

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

        # باقي المزودين الاحتياطيين
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
        تحويل الصوت إلى نص — طبقات fallback
        0. Gemini 3.5 Transcribe (🔴 الأساسي — أمر زياد 2026-11-04، مفتاح مخصص)
        1. Mistral Voxtral-mini (الثانوي — عربي ممتاز، مختبر لايف 2026-11-03)
        2. NVIDIA NIM Omni (REST)
        3. Google Speech Recognition (مجاني، محتاج ffmpeg)
        4. OpenRouter Whisper / OpenAI Whisper
        """
        if not audio_bytes and not file_path:
            return {"text": "", "success": False, "error": "No audio data provided", "provider": "none"}

        # Layer 0: Gemini 3.5 Transcribe (🔴 الأساسي الجديد — أمر زياد 2026-11-04)
        if self.gemini_transcribe_key:
            result = self._transcribe_gemini(audio_bytes, file_path, language)
            if result["success"]:
                return result
        else:
            logger.debug("Gemini transcribe key not configured, skipping")

        # Layer 1: Mistral Voxtral-mini (الثانوي — عربي مظبوط، 0.5s — Groq حظرت الحساب)
        if self.mistral_api_key:
            result = self._transcribe_mistral_voxtral(audio_bytes, file_path, language)
            if result["success"]:
                return result
        else:
            logger.debug("Mistral API key not configured, skipping Voxtral")

        # Layer 1: NVIDIA NIM Omni (REST — بيقبل OGG مباشرة — منقذ لو Groq وقع)
        if self.nim_omni_key:
            result = self._transcribe_nim_omni(audio_bytes, file_path, language)
            if result["success"]:
                return result
        else:
            logger.debug("NVIDIA NIM Omni key not configured, skipping")

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

    def _transcribe_gemini(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """🔴 الأساسي: gemini-3.5-transcribe عبر generateContent (مختبر لايف 2026-11-04)
        - يقبل OGG مباشرة (مفيش ffmpeg محتاج) — أسرع طبقة ومفيش تحويل ملفات
        - النص بيرجع في candidates[0].content.parts[*].audioTranscription.text
        - مفتاح مخصص GOOGLE_TRANSCRIBE_KEY منفصل عن مفتاح الشات (قاعدة زياد)"""
        import base64 as _b64
        import requests
        try:
            mime = "audio/ogg"
            if file_path:
                fp = str(file_path).lower()
                if fp.endswith(".wav"):
                    mime = "audio/wav"
                elif fp.endswith(".mp3"):
                    mime = "audio/mpeg"
                elif fp.endswith(".m4a"):
                    mime = "audio/mp4"
                elif fp.endswith(".webm"):
                    mime = "audio/webm"
            b64 = _b64.b64encode(audio_bytes).decode()
            resp = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-transcribe:generateContent",
                headers={"x-goog-api-key": self.gemini_transcribe_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [
                        {"text": "Transcribe the audio exactly. Return only the transcript."},
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]}],
                },
                timeout=(6, 25),
            )
            if resp.status_code == 200:
                j = resp.json()
                parts = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                text = ""
                for pr in parts:
                    if "audioTranscription" in pr:
                        text += pr["audioTranscription"].get("text", "")
                    elif "text" in pr:
                        text += pr.get("text", "")
                text = (text or "").strip()
                if text:
                    logger.info(f"✅ Gemini 3.5 Transcribe: {text[:80]}")
                    return {"text": text, "success": True, "provider": "gemini-transcribe"}
                logger.warning("Gemini transcribe returned empty text")
                return {"text": "", "success": False, "error": "empty text", "provider": "gemini-transcribe"}
            logger.warning(f"Gemini transcribe HTTP {resp.status_code} — falling to next layer")
            return {"text": "", "success": False, "error": f"HTTP {resp.status_code}", "provider": "gemini-transcribe"}
        except Exception as e:
            logger.warning(f"Gemini transcribe error: {str(e)[:120]}")
            return {"text": "", "success": False, "error": str(e)[:120], "provider": "gemini-transcribe"}


    def _transcribe_mistral_voxtral(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """🔴 الأساسي: Mistral Voxtral-mini عبر /v1/audio/transcriptions
        مختبر لايف 2026-11-03 على فويس نوت عربي حقيقي: 200 في 0.5s ونص عربي كامل صحيح
        (Omni كان بيرجع 'أيوا انا زر' وGroq حظرت الحساب organization_restricted)"""
        import requests

        try:
            ext = "ogg"
            if file_path and "." in file_path:
                ext = file_path.rsplit(".", 1)[-1].lower().replace("oga", "ogg")
                if ext not in ("wav", "mp3", "ogg", "flac", "m4a", "aac", "opus", "oga"):
                    ext = "ogg"

            r = requests.post(
                "https://api.mistral.ai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.mistral_api_key}"},
                files={"file": (f"audio.{ext}", audio_bytes, f"audio/{'ogg' if ext == 'oga' else ext}")},
                data={"model": "voxtral-mini-latest"},
                timeout=45,
            )
            if r.status_code == 200:
                j = r.json()
                text = (j.get("text") or "").strip()
                detected = j.get("language", "")
                if text:
                    logger.info(f"✅ Voxtral transcription (lang={detected}): {text[:80]}")
                    return {"text": text, "success": True, "provider": "mistral_voxtral"}
                logger.warning("Voxtral returned empty text")
                return {"text": "", "success": False, "error": "Voxtral empty text", "provider": "mistral_voxtral"}
            error_msg = f"Voxtral error: {r.status_code} - {r.text[:150]}"
            logger.warning(error_msg)
            return {"text": "", "success": False, "error": error_msg, "provider": "mistral_voxtral"}
        except Exception as e:
            logger.warning(f"Voxtral transcription error: {e}")
            return {"text": "", "success": False, "error": str(e), "provider": "mistral_voxtral"}

    def _transcribe_nim_omni(self, audio_bytes: bytes, file_path: str = None, language: str = "ar") -> dict:
        """🔴 STT عبر NVIDIA NIM omni (REST chat/completions مع input_audio)
        مختبر لايف 2026-11-03: بياخد wav base64 وبيوصف حتى نغمة اختبار — 1.5s
        بيقبل صيغ متعددة (wav/ogg/mp3) — بنجرب الصيغة الأصلية الأول ثم WAV لو فشلت"""
        import requests, base64

        try:
            ext = "ogg"
            if file_path and "." in file_path:
                ext = file_path.rsplit(".", 1)[-1].lower().replace("oga", "ogg")
                if ext not in ("wav", "mp3", "ogg", "flac", "m4a", "aac", "opus"):
                    ext = "ogg"

            attempts = [ext]
            payloads = [audio_bytes]
            # لو الصيغة الأصلية اترفض — نحول WAV (لو ffmpeg متاح)
            if _FFMPEG_AVAILABLE and ext != "wav":
                try:
                    payloads.append(self._convert_ogg_to_wav(audio_bytes))
                    attempts.append("wav")
                except Exception:
                    pass

            last_err = ""
            for fmt, data in zip(attempts, payloads):
                try:
                    b64 = base64.b64encode(data).decode()
                    r = requests.post(
                        "https://integrate.api.nvidia.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.nim_omni_key}", "Content-Type": "application/json"},
                        json={
                            "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                            "max_tokens": 1024,
                            "temperature": 0,
                            "chat_template_kwargs": {"thinking": False},
                            "messages": [{"role": "user", "content": [
                                {"type": "input_audio", "input_audio": {"data": b64, "format": fmt}},
                                {"type": "text", "text": "انسخ كل الكلام المسموع في الملف الصوتي ده كتابةً كما هو بالظبط، من غير أي تعليق أو شرح. لو مفيش كلام بشري قول: (مفيش كلام)."},
                            ]}],
                        },
                        timeout=60,
                    )
                    if r.status_code == 200:
                        text = (r.json()["choices"][0]["message"].get("content") or "").strip()
                        text = text.strip("()").strip()
                        if text and "مفيش كلام" not in text:
                            logger.info(f"✅ NIM Omni transcription ({fmt}): {text[:80]}")
                            return {"text": text, "success": True, "provider": "nvidia_nim_omni"}
                        last_err = "empty/no-speech"
                    else:
                        last_err = f"{r.status_code} {r.text[:100]}"
                        logger.debug(f"NIM Omni {fmt}: {last_err}")
                except Exception as e:
                    last_err = str(e)[:100]
            logger.warning(f"⚠️ NIM Omni transcription failed: {last_err}")
            return {"text": "", "success": False, "error": f"NIM Omni: {last_err}", "provider": "nvidia_nim_omni"}
        except Exception as e:
            logger.warning(f"⚠️ NIM Omni error: {str(e)[:100]}")
            return {"text": "", "success": False, "error": str(e)[:100], "provider": "nvidia_nim_omni"}

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
