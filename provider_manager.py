"""
مدير المزودين - Provider Manager
الخطه الشامله مع per-model API keys:
🧠 Chat Free: Mistral Small → Mistral Nemo → Llama 3.3 70B → DeepSeek V4 Flash (heavy) → SambaNova
🧠 Chat Premium: Mistral Large → Mistral Medium → Kimi K2.6 → MiniMax M2.7 → GLM 5.1 → DeepSeek V4 Pro (heavy)
⚡ Simple Free: Mistral Small → Llama 3.3 70B → Step 3.7 Flash → SambaNova
⚡ Simple Premium: Mistral Small → Step 3.7 Flash → Mistral Medium
🔥 Deep Search Premium: DeepSeek V4 Pro → Kimi K2.6 → MiniMax M2.7 → Mistral Large
👨‍💻 Coding Free: Step 3.7 Flash → Codestral → Mistral Small → SambaNova
👨‍💻 Coding Premium: GLM 5.1 → DeepSeek V4 Pro → Kimi K2.6 → Codestral → Mistral Large
📄 Summary Free: DeepSeek V4 Flash → Mistral Small → Nemo → SambaNova
📄 Summary Premium: DeepSeek V4 Pro → MiniMax M2.7 → Mistral Large → Medium
👁️ Vision: Llama 3.2 90B Vision → Nemotron Nano VL → Mistral Pixtral
🎨 Image Gen (Premium Only): Stable Diffusion 3.5 Large → Flux.1 Kontext → Flux.1 Dev
🖌️ Image Edit (Premium Only): Stable Diffusion 3.5 Large → Flux.1 Dev

كل نموذج NVIDIA ليه مفتاح API خاص بيه (per-model API keys)
"""

import asyncio
import logging
import re
import time
import base64
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config import (
    SAMBANOVA_API_KEY, SAMBANOVA_BASE_URL,
    MISTRAL_API_KEY, MISTRAL_BASE_URL,
    NVIDIA_BASE_URL, NVIDIA_GENAI_BASE_URL,
    CHAT_MODELS, SIMPLE_MODELS, DEEP_SEARCH_MODELS,
    CODING_MODELS, SUMMARY_MODELS, VISION_MODELS,
    FREE_CHAT_MODELS, PREMIUM_CHAT_MODELS,
    FREE_SIMPLE_MODELS, PREMIUM_SIMPLE_MODELS,
    FREE_DEEP_SEARCH_MODELS, PREMIUM_DEEP_SEARCH_MODELS,
    FREE_CODING_MODELS, PREMIUM_CODING_MODELS,
    FREE_SUMMARY_MODELS, PREMIUM_SUMMARY_MODELS,
    FREE_VISION_MODELS, PREMIUM_VISION_MODELS,
    PREMIUM_IMAGE_GEN_MODELS, PREMIUM_IMAGE_EDIT_MODELS,
    REQUEST_TIMEOUT, FAST_TIMEOUT, MAX_RETRIES, RETRY_DELAY,
    IMAGE_GEN_TIMEOUT, IMAGE_EDIT_TIMEOUT,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# أنواع المسارات - Route Types
# ═══════════════════════════════════════

@dataclass
class ModelRoute:
    """مسار نموذج - يحدد المزود والنموذج ومفتاح API"""
    provider_name: str
    model_id: str
    api_key: str = ""  # 🔴 per-model API key (للـ NVIDIA كل نموذج ليه مفتاح)
    priority: int = 0


# ═══════════════════════════════════════
# مدير المزودين - Provider Manager
# ═══════════════════════════════════════

class ProviderManager:
    """
    مدير المزودين مع per-model API keys
    + نظام cooldown لكل موديل عشان لو فشل نجرب اللي بعده
    + NVIDIA: كل نموذج ليه مفتاح API خاص
    + Mistral: مفتاح واحد لكل النماذج
    + SambaNova: مفتاح واحد لكل النماذج
    """

    def __init__(self):
        self.providers: Dict[str, Dict] = {}
        self._model_cooldowns: Dict[str, float] = {}

        # NVIDIA NIM (base_url بس — المفاتيح في كل model config)
        self.providers["nvidia"] = {
            "base_url": NVIDIA_BASE_URL,
            "api_key": "",  # 🔴 مفيش مفتاح عام — كل نموذج ليه مفتاح خاص
        }
        logger.info("✅ NVIDIA NIM provider configured (per-model API keys)")

        # NVIDIA GenAI (Visual GenAI — إنشاء وتعديل الصور)
        # 🔴 Endpoint مختلف: https://ai.api.nvidia.com/v1/genai/{model}
        self.providers["nvidia_genai"] = {
            "base_url": NVIDIA_GENAI_BASE_URL,
            "api_key": "",  # 🔴 مفيش مفتاح عام — كل نموذج ليه مفتاح خاص
        }
        logger.info("✅ NVIDIA GenAI provider configured (image gen/edit — SD 3.5 Large + Flux.1 Kontext + Flux.1 Dev)")

        # Mistral (أساسي للمجاني + fallback للبريميوم — 1B توكن/شهر)
        if MISTRAL_API_KEY:
            self.providers["mistral"] = {
                "api_key": MISTRAL_API_KEY,
                "base_url": MISTRAL_BASE_URL,
            }
            logger.info("✅ Mistral provider configured (Free primary + Premium fallback)")

        # SambaNova (fallback للمجاني — مجاني بس محدود 20 طلب/يوم)
        if SAMBANOVA_API_KEY:
            self.providers["sambanova"] = {
                "api_key": SAMBANOVA_API_KEY,
                "base_url": SAMBANOVA_BASE_URL,
            }
            logger.info("✅ SambaNova provider configured (Free fallback)")

        if not self.providers:
            logger.error("❌ No AI providers configured!")

        logger.info(f"🔧 Provider Manager initialized with {len(self.providers)} providers")

    def _get_api_key(self, provider_name: str, model_config: dict = None) -> str:
        """
        الحصول على مفتاح API المناسب
        🔴 أولوية: per-model api_key > provider-level api_key
        """
        # أولوية: مفتاح النموذج نفسه (NVIDIA per-model keys)
        if model_config and model_config.get("api_key"):
            return model_config["api_key"]

        # fallback: مفتاح المزود العام (Mistral, SambaNova)
        provider = self.providers.get(provider_name, {})
        return provider.get("api_key", "")

    def _is_provider_available(self, provider_name: str) -> bool:
        """فحص هل المزود متاح"""
        return provider_name in self.providers

    def _is_model_available(self, model_id: str, ignore_cooldown: bool = False) -> bool:
        """فحص هل الموديل متاح (مش على cooldown)"""
        if ignore_cooldown:
            return True
        cooldown = self._model_cooldowns.get(model_id, 0)
        return cooldown <= time.time()

    def _set_model_cooldown(self, model_id: str, error: str, cooldown_seconds: int = 3):
        """تعيين فترة تبريد لموديل معين بعد خطأ"""
        self._model_cooldowns[model_id] = time.time() + cooldown_seconds
        logger.warning(f"⏳ Model {model_id} on cooldown for {cooldown_seconds}s: {error[:80]}")

    def _clear_model_cooldown(self, model_id: str):
        """إزالة فترة التبريد بعد نجاح"""
        self._model_cooldowns.pop(model_id, None)

    def _get_user_plan(self, user_id: int) -> str:
        """
        تحديد خطة المستخدم: "admin", "premium", or "free"
        """
        try:
            from admin import is_admin
            if is_admin(user_id):
                return "admin"
        except Exception:
            pass

        try:
            from premium import is_premium
            if is_premium(user_id):
                return "premium"
        except Exception:
            pass

        return "free"

    def _get_model_list_for_task(self, task_type: str, user_plan: str = "premium") -> list:
        """
        الحصول على قائمة النماذج المناسبة لنوع المهمة وخطة المستخدم
        كل تخصص ليه FREE و PREMIUM منفصلين
        """
        # Admin بياخد Premium routes
        is_premium_route = user_plan in ("admin", "premium")

        routes_map = {
            "chat": PREMIUM_CHAT_MODELS if is_premium_route else FREE_CHAT_MODELS,
            "simple": PREMIUM_SIMPLE_MODELS if is_premium_route else FREE_SIMPLE_MODELS,
            "deep_search": PREMIUM_DEEP_SEARCH_MODELS if is_premium_route else FREE_DEEP_SEARCH_MODELS,
            "coding": PREMIUM_CODING_MODELS if is_premium_route else FREE_CODING_MODELS,
            "summary": PREMIUM_SUMMARY_MODELS if is_premium_route else FREE_SUMMARY_MODELS,
            "vision": PREMIUM_VISION_MODELS if is_premium_route else FREE_VISION_MODELS,
            "image_gen": PREMIUM_IMAGE_GEN_MODELS,  # 🎨 بريميوم بس
            "image_edit": PREMIUM_IMAGE_EDIT_MODELS,  # 🖌️ بريميوم بس
        }

        return routes_map.get(task_type, PREMIUM_CHAT_MODELS if is_premium_route else FREE_CHAT_MODELS)

    def get_model_routes(self, task_type: str, ignore_cooldown: bool = False, user_id: int = None) -> List[ModelRoute]:
        """
        الحصول على مسارات النماذج لنوع مهمة معين
        يجرب كل مسار بالترتيب، بيتخطى المزودين/الموديلات اللي مش متاحة
        + يدعم FREE/PREMIUM لكل تخصص
        + يدعم per-model API keys
        """
        # تحديد خطة المستخدم
        # 🔴 الأمان: الـ default لازم يكون "free" — مش "premium"!
        user_plan = "free"
        if user_id is not None:
            user_plan = self._get_user_plan(user_id)

        model_list = self._get_model_list_for_task(task_type, user_plan)

        routes = []
        for i, model_config in enumerate(model_list):
            provider_name = model_config["provider"]
            model_id = model_config["model"]
            # 🔴 per-model API key
            model_api_key = model_config.get("api_key", "")

            # فحص هل المزود متاح و الموديل مش على cooldown
            # 🔴 للـ NVIDIA: لازم يكون في api_key للنموذج (مش provider level)
            is_available = self._is_provider_available(provider_name) and self._is_model_available(model_id, ignore_cooldown=ignore_cooldown)

            # للـ NVIDIA: لازم يكون في api_key للنموذج
            if provider_name == "nvidia" and not model_api_key:
                is_available = False
                logger.debug(f"Skipping nvidia/{model_id} (no API key configured)")

            # للـ NVIDIA GenAI: لازم يكون في api_key للنموذج
            if provider_name == "nvidia_genai" and not model_api_key:
                is_available = False
                logger.debug(f"Skipping nvidia_genai/{model_id} (no API key configured)")

            if is_available:
                routes.append(ModelRoute(
                    provider_name=provider_name,
                    model_id=model_id,
                    api_key=model_api_key,
                    priority=i,
                ))
            else:
                logger.debug(f"Skipping {provider_name}/{model_id} (unavailable or on cooldown)")

        return routes

    def get_model_routes_for_user(self, user_id: int, task_type: str = "chat", ignore_cooldown: bool = False) -> List[ModelRoute]:
        """الحصول على مسارات النماذج بناءً على خطة المستخدم و التخصص"""
        user_plan = self._get_user_plan(user_id)
        model_list = self._get_model_list_for_task(task_type, user_plan)

        routes = []
        for i, model_config in enumerate(model_list):
            provider_name = model_config["provider"]
            model_id = model_config["model"]
            model_api_key = model_config.get("api_key", "")

            is_available = self._is_provider_available(provider_name) and self._is_model_available(model_id, ignore_cooldown=ignore_cooldown)

            if provider_name == "nvidia" and not model_api_key:
                is_available = False

            if provider_name == "nvidia_genai" and not model_api_key:
                is_available = False

            if is_available:
                routes.append(ModelRoute(
                    provider_name=provider_name,
                    model_id=model_id,
                    api_key=model_api_key,
                    priority=i,
                ))

        return routes

    # ═══════════════════════════════════════
    # استدعاء API - API Calls
    # ═══════════════════════════════════════

    def _call_provider_sync(
        self,
        provider_name: str,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 8192,
        timeout: int = 30,
        api_key: str = "",  # 🔴 per-model API key
    ) -> Optional[str]:
        """استدعاء مزود OpenAI-compatible (متزامن) — يدعم per-model API keys"""
        provider = self.providers.get(provider_name)
        if not provider:
            return None

        # 🔴 الحصول على API key: أولوية per-model > provider-level
        actual_api_key = api_key or provider.get("api_key", "")
        if not actual_api_key:
            logger.warning(f"❌ No API key for {provider_name}/{model}")
            self._set_model_cooldown(model, "No API key", 10)
            return None

        url = f"{provider['base_url']}/chat/completions"

        headers = {
            "Authorization": f"Bearer {actual_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            logger.info(f"🤖 Calling {provider_name}/{model}")
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()

            data = response.json()

            # معالجة الأخطاء في الاستجابة
            if "error" in data:
                error_msg = data.get("error", {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                logger.warning(f"❌ API error from {provider_name}/{model}: {error_msg[:100]}")

                if "429" in str(error_msg) or "rate limit" in str(error_msg).lower():
                    self._set_model_cooldown(model, f"Rate limited: {error_msg}", 5)
                else:
                    self._set_model_cooldown(model, f"API error: {error_msg[:60]}", 3)
                return None

            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                content = choice.get("message", {}).get("content", "")
                finish_reason = choice.get("finish_reason", "")
                if content:
                    # شيل thinking/reasoning tags من نماذج Qwen3 و DeepSeek R1
                    content = re.sub(r'<think\b[^>]*>.*?</think\s*>', '', content, flags=re.DOTALL)
                    content = content.strip()
                    if content:
                        self._clear_model_cooldown(model)
                        # ⚠️ كشف لو الرسالة اتقصت بسبب limit
                        if finish_reason == "length":
                            logger.warning(f"⚠️ Response TRUNCATED (finish_reason=length) from {provider_name}/{model} ({len(content)} chars) — max_tokens too low!")
                            continuation = self._try_continue(messages, provider_name, model, content, max_tokens, temperature, timeout, api_key=actual_api_key)
                            if continuation:
                                content = content + "\n" + continuation
                                logger.info(f"✅ Auto-continuation successful! Total: {len(content)} chars")
                        else:
                            logger.info(f"✅ Response from {provider_name}/{model} ({len(content)} chars, finish={finish_reason})")
                        return content

            logger.warning(f"⚠️ Empty response from {provider_name}/{model}")
            return None

        except requests.exceptions.Timeout:
            logger.warning(f"⏱️ Timeout ({timeout}s) for {provider_name}/{model}")
            self._set_model_cooldown(model, "Timeout", 3)
            return None

        except requests.exceptions.RequestException as e:
            error_str = str(e)
            if "403" in error_str or "401" in error_str:
                logger.error(f"🔒 Auth error for {provider_name}/{model}")
                self._set_model_cooldown(model, f"Auth error: {error_str[:80]}", 15)
            elif "429" in error_str:
                logger.warning(f"🚫 Rate limited for {provider_name}/{model}")
                self._set_model_cooldown(model, "Rate limit", 5)
            elif "404" in error_str:
                logger.warning(f"❓ Model not found: {provider_name}/{model}")
                self._set_model_cooldown(model, "Model not found", 10)
            else:
                logger.warning(f"❌ Request error for {provider_name}/{model}: {error_str[:100]}")
                self._set_model_cooldown(model, f"Request error: {error_str[:80]}", 3)
            return None

        except Exception as e:
            logger.warning(f"❌ Unexpected error for {provider_name}/{model}: {str(e)[:100]}")
            return None

    def _try_continue(self, messages: List[Dict[str, str]], provider_name: str, model: str,
                       previous_content: str, max_tokens: int, temperature: float, timeout: int,
                       api_key: str = "", _depth: int = 0) -> str:
        """محاولة إكمال الرد لو اتقص بسبب max_tokens"""
        # 🔴 حد أقصى للعمق — 5 مرات تكملة كفاية
        if _depth >= 5:
            logger.warning(f"⚠️ Auto-continuation depth limit reached (5), stopping.")
            return None

        try:
            if provider_name not in self.providers:
                return None

            provider = self.providers[provider_name]
            actual_api_key = api_key or provider.get("api_key", "")
            if not actual_api_key:
                return None

            url = f"{provider['base_url']}/chat/completions"
            headers = {
                "Authorization": f"Bearer {actual_api_key}",
                "Content-Type": "application/json"
            }

            continue_messages = list(messages)

            content_to_send = previous_content
            if len(previous_content) > 12000:
                content_to_send = "...[الجزء السابق]...\n" + previous_content[-8000:]

            continue_messages.append({"role": "assistant", "content": content_to_send})
            continue_messages.append({"role": "user", "content": "كمّل منين وقفت بالظبط — متكررش اللي قلته! كمّل الرد من آخر نقطة وصلت ليها."})

            continue_max_tokens = max(max_tokens, 8192)

            payload = {
                "model": model,
                "messages": continue_messages,
                "max_tokens": continue_max_tokens,
                "temperature": temperature,
            }

            logger.info(f"🔄 Trying auto-continuation (depth={_depth+1}) with {provider_name}/{model}...")
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)

            if response.status_code == 200:
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    continuation = data["choices"][0].get("message", {}).get("content", "")
                    finish_reason = data["choices"][0].get("finish_reason", "")
                    if continuation:
                        continuation = re.sub(r'<think\b[^>]*>.*?</think\s*>', '', continuation, flags=re.DOTALL)
                        continuation = continuation.strip()
                        if continuation:
                            if finish_reason == "length":
                                combined = previous_content + "\n" + continuation
                                deeper_continuation = self._try_continue(
                                    continue_messages, provider_name, model,
                                    continuation, continue_max_tokens, temperature, timeout,
                                    api_key=actual_api_key, _depth=_depth + 1
                                )
                                if deeper_continuation:
                                    continuation = continuation + "\n" + deeper_continuation
                            return continuation

            logger.warning(f"⚠️ Auto-continuation failed for {provider_name}/{model}")
            return None

        except Exception as e:
            logger.warning(f"⚠️ Auto-continuation error: {str(e)[:100]}")
            return None

    def _try_parallel_routes(self, routes, messages, temperature, max_tokens, timeout):
        """
        تجريب أول مسارين بالتوازي — يرجع أول نتيجة ناجحة
        ⚡ Parallel Fallback: بيشغل أول 2 models في نفس الوقت
        وياخد أول نتيجة ناجحة، ويلغي التاني
        """
        if len(routes) < 2:
            # مسار واحد بس — نجربه عادي
            if routes:
                logger.info(f"🔄 Only 1 route available, trying sequentially: {routes[0].provider_name}/{routes[0].model_id}")
                return self._call_provider_sync(
                    provider_name=routes[0].provider_name,
                    model=routes[0].model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    api_key=routes[0].api_key,
                ), routes[0]
            return None, None

        # شغّل أول 2 مسارات بالتوازي
        route1, route2 = routes[0], routes[1]
        logger.info(f"⚡ Parallel fallback: trying {route1.provider_name}/{route1.model_id} + {route2.provider_name}/{route2.model_id} simultaneously")

        def call_route(route):
            """استدعاء مسار واحد — بيترجع (route, result)"""
            try:
                result = self._call_provider_sync(
                    provider_name=route.provider_name,
                    model=route.model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    api_key=route.api_key,
                )
                return route, result
            except Exception as e:
                logger.warning(f"⚠️ Parallel call exception for {route.provider_name}/{route.model_id}: {str(e)[:80]}")
                return route, None

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(call_route, route1)
            future2 = executor.submit(call_route, route2)

            futures_map = {future1: route1, future2: route2}

            # استنى أول نتيجة تخلص
            for future in as_completed([future1, future2]):
                try:
                    route_used, result = future.result()
                    if result:
                        # نجاح! ألغي التاني
                        other_future = future2 if future == future1 else future1
                        other_route = futures_map[other_future]
                        other_future.cancel()
                        logger.info(f"⚡ Parallel fallback SUCCESS: {route_used.provider_name}/{route_used.model_id} responded first (cancelled {other_route.provider_name}/{other_route.model_id})")
                        return result, route_used
                    else:
                        # فشل — ننتظر التاني
                        failed_route = route_used
                        logger.debug(f"⚡ Parallel route {failed_route.provider_name}/{failed_route.model_id} failed, waiting for other...")
                except Exception as e:
                    logger.warning(f"⚠️ Parallel future exception: {str(e)[:80]}")

        # الاتنين فشلوا
        logger.warning(f"⚠️ Both parallel routes failed ({route1.provider_name}/{route1.model_id} + {route2.provider_name}/{route2.model_id})")
        return None, None

    def call_sync(
        self,
        messages: List[Dict[str, str]],
        task_type: str = "chat",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        timeout: int = None,
        user_id: int = None,
    ) -> Optional[str]:
        """
        استدعاء AI مع تبديل تلقائي بين المزودين والنماذج (متزامن)
        ⚡ أول 2 مسارات بالتوازي، لو فشلوا يجرب الباقي بالترتيب
        + لو كل المسارات فشلت، يجرب على cooldown كـ fallback
        """
        routes = self.get_model_routes(task_type, user_id=user_id)

        if not routes:
            logger.warning("⚠️ All routes on cooldown, trying with cooldown ignored...")
            routes = self.get_model_routes(task_type, ignore_cooldown=True, user_id=user_id)
            if not routes:
                logger.error("🚨 No routes available at all!")
                return None

        if timeout is None:
            if task_type == "simple":
                timeout = FAST_TIMEOUT
            elif task_type == "deep_search":
                timeout = 30
            elif task_type == "summary":
                timeout = 25
            else:
                if user_id:
                    try:
                        from premium import is_premium
                        from admin import is_admin
                        if is_admin(user_id) or is_premium(user_id):
                            timeout = 30
                        else:
                            timeout = 20
                    except Exception:
                        timeout = 20
                else:
                    timeout = 20

        # ⚡ حاول أول 2 مسارات بالتوازي
        parallel_routes = routes[:2]
        remaining_routes = routes[2:]

        logger.info(f"⚡ Parallel fallback: trying first {len(parallel_routes)} of {len(routes)} routes in parallel for task={task_type}")
        result, route_used = self._try_parallel_routes(
            parallel_routes, messages, temperature, max_tokens, timeout
        )
        if result:
            return result

        # لو التوازي فشل — جرب الباقي بالترتيب
        if remaining_routes:
            logger.info(f"🔄 Parallel failed, trying {len(remaining_routes)} remaining routes sequentially for task={task_type}")
            for route in remaining_routes:
                result = self._call_provider_sync(
                    provider_name=route.provider_name,
                    model=route.model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    api_key=route.api_key,  # 🔴 per-model API key
                )
                if result:
                    return result

        logger.error(f"🚨 All providers failed for task type: {task_type}")
        return None

    async def call_async(
        self,
        messages: List[Dict[str, str]],
        task_type: str = "chat",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        timeout: int = None,
        user_id: int = None,
    ) -> Optional[str]:
        """استدعاء AI (غير متزامن - لا يحجب event loop)"""
        loop = asyncio.get_event_loop()

        if user_id:
            return await loop.run_in_executor(
                None,
                lambda: self._call_sync_with_user(
                    user_id=user_id,
                    messages=messages,
                    task_type=task_type,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
            )

        return await loop.run_in_executor(
            None,
            lambda: self.call_sync(
                messages=messages,
                task_type=task_type,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        )

    def _call_sync_with_user(
        self,
        user_id: int,
        messages: List[Dict[str, str]],
        task_type: str = "chat",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        timeout: int = None,
    ) -> Optional[str]:
        """استدعاء AI مع مسارات مخصصة للمستخدم (متزامن)
        ⚡ أول 2 مسارات بالتوازي، لو فشلوا يجرب الباقي بالترتيب
        """
        routes = self.get_model_routes_for_user(user_id, task_type)

        if not routes:
            routes = self.get_model_routes_for_user(user_id, task_type, ignore_cooldown=True)
            if not routes:
                routes = self.get_model_routes(task_type)

        if not routes:
            routes = self.get_model_routes(task_type, ignore_cooldown=True)

        if not routes:
            logger.error("🚨 No routes available at all!")
            return None

        if timeout is None:
            if task_type == "simple":
                timeout = FAST_TIMEOUT
            elif task_type == "deep_search":
                timeout = 30
            elif task_type == "summary":
                timeout = 25
            else:
                if user_id:
                    try:
                        from premium import is_premium
                        from admin import is_admin
                        if is_admin(user_id) or is_premium(user_id):
                            timeout = 30
                        else:
                            timeout = 20
                    except Exception:
                        timeout = 20
                else:
                    timeout = 20

        # ⚡ حاول أول 2 مسارات بالتوازي
        parallel_routes = routes[:2]
        remaining_routes = routes[2:]

        logger.info(f"⚡ Parallel fallback: trying first {len(parallel_routes)} of {len(routes)} routes in parallel for user={user_id}, task={task_type}")
        result, route_used = self._try_parallel_routes(
            parallel_routes, messages, temperature, max_tokens, timeout
        )
        if result:
            return result

        # لو التوازي فشل — جرب الباقي بالترتيب
        if remaining_routes:
            logger.info(f"🔄 Parallel failed, trying {len(remaining_routes)} remaining routes sequentially for user={user_id}, task={task_type}")
            for route in remaining_routes:
                result = self._call_provider_sync(
                    provider_name=route.provider_name,
                    model=route.model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    api_key=route.api_key,  # 🔴 per-model API key
                )
                if result:
                    return result

        logger.error(f"🚨 All providers failed for user {user_id}, task type: {task_type}")
        return None

    def call_with_system_prompt_sync(
        self,
        prompt: str,
        system_prompt: str = "",
        task_type: str = "chat",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        timeout: int = None,
        user_id: int = None,
    ) -> Optional[str]:
        """استدعاء AI مع system prompt منفصل (متزامن)"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.call_sync(
            messages=messages,
            task_type=task_type,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            user_id=user_id,
        )

    async def call_with_system_prompt_async(
        self,
        prompt: str,
        system_prompt: str = "",
        task_type: str = "chat",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        timeout: int = None,
        user_id: int = None,
    ) -> Optional[str]:
        """استدعاء AI مع system prompt منفصل (غير متزامن)"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.call_async(
            messages=messages,
            task_type=task_type,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            user_id=user_id,
        )

    # ═══════════════════════════════════════
    # Vision - معالجة الصور
    # ═══════════════════════════════════════

    def _call_vision_sync(
        self,
        provider_name: str,
        model: str,
        text_prompt: str,
        image_url: str = None,
        image_base64: str = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        api_key: str = "",  # 🔴 per-model API key
    ) -> Optional[str]:
        """استدعاء نموذج رؤية (متزامن)"""
        user_message: Dict[str, Any] = {
            "role": "user",
            "content": [],
        }

        user_message["content"].append({
            "type": "text",
            "text": text_prompt,
        })

        if image_url:
            user_message["content"].append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })
        elif image_base64:
            user_message["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            })

        messages = [user_message]

        return self._call_provider_sync(
            provider_name=provider_name,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=REQUEST_TIMEOUT,
            api_key=api_key,  # 🔴 per-model API key
        )

    async def analyze_image_async(
        self,
        text_prompt: str,
        image_url: str = None,
        image_base64: str = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        user_id: int = None,
    ) -> Optional[str]:
        """تحليل صورة (غير متزامن) مع fallback"""
        routes = self.get_model_routes("vision", user_id=user_id)

        if not routes:
            logger.warning("⚠️ All vision routes on cooldown, trying with cooldown ignored...")
            routes = self.get_model_routes("vision", ignore_cooldown=True)

        if not routes:
            logger.error("🚨 No vision routes available!")
            return None

        loop = asyncio.get_event_loop()

        for route in routes:
            result = await loop.run_in_executor(
                None,
                lambda r=route: self._call_vision_sync(
                    provider_name=r.provider_name,
                    model=r.model_id,
                    text_prompt=text_prompt,
                    image_url=image_url,
                    image_base64=image_base64,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=r.api_key,  # 🔴 per-model API key
                )
            )
            if result:
                return result

        logger.error("🚨 All vision providers failed")
        return None

    # ═══════════════════════════════════════
    # Image Generation - إنشاء الصور 🎨
    # ═══════════════════════════════════════

    def _generate_image_sync(
        self,
        prompt: str,
        model: str,
        api_key: str,
        size: str = "1024x1024",
        n: int = 1,
        timeout: int = None,
    ) -> Optional[Dict]:
        """
        إنشاء صورة من وصف نصي (متزامن)
        🎨 بيتستخدم NVIDIA Visual GenAI API: https://ai.api.nvidia.com/v1/genai/{model}
        Payload: {"prompt": "...", "seed": N}
        Response: {"artifacts": [{"base64": "...", "finishReason": "...", "seed": N}]}
        Returns: {"base64": "..."} or None
        """
        if not api_key:
            logger.error(f"❌ No API key for image generation model {model}")
            return None

        # NVIDIA GenAI endpoint: base_url/model
        url = f"{NVIDIA_GENAI_BASE_URL}/{model}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # NVIDIA Visual GenAI payload format
        # SD 3.5 Large بيحتاج mode + steps، Flux بيحتاج prompt + seed بس
        import random
        seed = random.randint(0, 999999)

        payload = {
            "prompt": prompt,
            "mode": "base",  # أساسي لـ text-to-image (SD 3.5 + Flux بيقبلوه)
            "seed": seed,
        }

        # SD 3.5 Large بيحتاج steps صريح (30 خطوة كفاية للتوازن بين الجودة والسرعة)
        if "stable-diffusion-3.5" in model:
            payload["steps"] = 30

        actual_timeout = timeout or IMAGE_GEN_TIMEOUT

        try:
            logger.info(f"🎨 Generating image with {model} (prompt: {prompt[:50]}...)")
            response = requests.post(url, headers=headers, json=payload, timeout=actual_timeout)
            response.raise_for_status()

            data = response.json()

            # NVIDIA GenAI response format: {"artifacts": [{"base64": "...", "finishReason": "...", "seed": N}]}
            if "artifacts" in data and len(data["artifacts"]) > 0:
                artifact = data["artifacts"][0]
                if artifact.get("base64"):
                    logger.info(f"✅ Image generated successfully with {model} (base64 len: {len(artifact['base64'])})")
                    return {"base64": artifact["base64"]}

            # Fallback: OpenAI-compatible response format
            if "data" in data and len(data["data"]) > 0:
                image_data = data["data"][0]
                result = {}
                if image_data.get("b64_json"):
                    result["base64"] = image_data["b64_json"]
                elif image_data.get("base64"):
                    result["base64"] = image_data["base64"]
                if image_data.get("url"):
                    result["url"] = image_data["url"]
                if result:
                    logger.info(f"✅ Image generated successfully with {model} (OpenAI format)")
                    return result

            logger.warning(f"⚠️ No image data in response from {model}")
            logger.debug(f"Response keys: {list(data.keys())}, data: {str(data)[:200]}")
            return None

        except requests.exceptions.Timeout:
            logger.warning(f"⏱️ Image generation timed out ({actual_timeout}s) for {model}")
            return None
        except requests.exceptions.RequestException as e:
            error_str = str(e)
            logger.error(f"❌ Image generation error for {model}: {error_str[:200]}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected image generation error: {str(e)[:100]}")
            return None

    async def generate_image_async(
        self,
        prompt: str,
        size: str = "1024x1024",
        user_id: int = None,
    ) -> Optional[Dict]:
        """
        إنشاء صورة من وصف نصي (غير متزامن)
        🎨 بريميوم بس!
        Returns: {"base64": "...", "url": "..."} or None
        """
        routes = self.get_model_routes("image_gen", user_id=user_id)

        if not routes:
            logger.error("🚨 No image generation routes available!")
            return None

        loop = asyncio.get_event_loop()

        for route in routes:
            result = await loop.run_in_executor(
                None,
                lambda r=route: self._generate_image_sync(
                    prompt=prompt,
                    model=r.model_id,
                    api_key=r.api_key,
                    size=size,
                )
            )
            if result:
                return result

        logger.error("🚨 All image generation models failed")
        return None

    # ═══════════════════════════════════════
    # Image Editing - تعديل الصور 🖌️
    # ═══════════════════════════════════════

    def _edit_image_sync(
        self,
        prompt: str,
        image_base64: str,
        model: str,
        api_key: str,
        timeout: int = None,
    ) -> Optional[Dict]:
        """
        تعديل صورة بناءً على وصف نصي (متزامن)
        🖌️ بيتستخدم NVIDIA Visual GenAI API مع canny mode
        Endpoint: https://ai.api.nvidia.com/v1/genai/{model}
        Payload: {"prompt": "...", "image": "base64", "mode": "canny", "seed": N}
        Response: {"artifacts": [{"base64": "...", "finishReason": "...", "seed": N}]}
        Returns: {"base64": "..."} or None
        """
        if not api_key:
            logger.error(f"❌ No API key for image editing model {model}")
            return None

        # NVIDIA GenAI endpoint: base_url/model
        url = f"{NVIDIA_GENAI_BASE_URL}/{model}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        import random
        seed = random.randint(0, 999999)

        # بنجرب canny mode الأول — بيحافظ على حواف الصورة ويعمل تعديل
        payload = {
            "prompt": prompt,
            "image": image_base64,
            "mode": "canny",
            "seed": seed,
        }

        actual_timeout = timeout or IMAGE_EDIT_TIMEOUT

        try:
            logger.info(f"🖌️ Editing image with {model} canny mode (prompt: {prompt[:50]}...)")
            response = requests.post(url, headers=headers, json=payload, timeout=actual_timeout)

            # لو canny mode فشل، نجرب depth mode
            if response.status_code == 422:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = str(error_data.get("detail", ""))
                except Exception:
                    pass

                # لو المشكلة في صورة الـ base64 (الـ API مش بيقبل base64 مباشر)
                # نجرب نعمل text-to-image بالوصف بدل كده
                if "invalid form" in error_detail or "not supported" in error_detail or "image" in error_detail.lower():
                    logger.info(f"🔄 Image input not supported in canny mode, falling back to text-to-image with edit prompt...")
                    fallback_payload = {
                        "prompt": f"Based on an uploaded image: {prompt}",
                        "seed": seed,
                    }
                    response = requests.post(url, headers=headers, json=fallback_payload, timeout=actual_timeout)
                    response.raise_for_status()
                else:
                    # Try depth mode as fallback
                    logger.info(f"🔄 Canny mode failed, trying depth mode...")
                    payload["mode"] = "depth"
                    response = requests.post(url, headers=headers, json=payload, timeout=actual_timeout)
                    if response.status_code == 422:
                        # Fallback to text-to-image
                        logger.info(f"🔄 Depth mode also failed, falling back to text-to-image...")
                        fallback_payload = {
                            "prompt": f"Create a modified version: {prompt}",
                            "seed": seed,
                        }
                        response = requests.post(url, headers=headers, json=fallback_payload, timeout=actual_timeout)
                        response.raise_for_status()
                    else:
                        response.raise_for_status()
            else:
                response.raise_for_status()

            data = response.json()

            # NVIDIA GenAI response format
            if "artifacts" in data and len(data["artifacts"]) > 0:
                artifact = data["artifacts"][0]
                if artifact.get("base64"):
                    logger.info(f"✅ Image edited successfully with {model} (base64 len: {len(artifact['base64'])})")
                    return {"base64": artifact["base64"]}

            # Fallback: OpenAI-compatible format
            if "data" in data and len(data["data"]) > 0:
                image_data = data["data"][0]
                result = {}
                if image_data.get("b64_json"):
                    result["base64"] = image_data["b64_json"]
                elif image_data.get("base64"):
                    result["base64"] = image_data["base64"]
                if image_data.get("url"):
                    result["url"] = image_data["url"]
                if result:
                    return result

            logger.warning(f"⚠️ No image data in edit response from {model}")
            return None

        except requests.exceptions.Timeout:
            logger.warning(f"⏱️ Image editing timed out ({actual_timeout}s) for {model}")
            return None
        except requests.exceptions.RequestException as e:
            error_str = str(e)
            logger.error(f"❌ Image editing error for {model}: {error_str[:200]}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected image editing error: {str(e)[:100]}")
            return None

    async def edit_image_async(
        self,
        prompt: str,
        image_base64: str,
        user_id: int = None,
    ) -> Optional[Dict]:
        """
        تعديل صورة بناءً على وصف نصي (غير متزامن)
        🖌️ بريميوم بس!
        Returns: {"base64": "...", "url": "..."} or None
        """
        routes = self.get_model_routes("image_edit", user_id=user_id)

        if not routes:
            logger.error("🚨 No image editing routes available!")
            return None

        loop = asyncio.get_event_loop()

        for route in routes:
            result = await loop.run_in_executor(
                None,
                lambda r=route: self._edit_image_sync(
                    prompt=prompt,
                    image_base64=image_base64,
                    model=r.model_id,
                    api_key=r.api_key,
                )
            )
            if result:
                return result

        logger.error("🚨 All image editing models failed")
        return None

    # ═══════════════════════════════════════
    # معلومات الحالة - Status Info
    # ═══════════════════════════════════════

    def get_status(self) -> str:
        """الحصول على حالة المزودين"""
        parts = []
        for name in self.providers:
            parts.append(f"✅ {name}")

        if not parts:
            return "❌ No providers configured!"

        cooldowns = []
        now = time.time()
        for model, cooldown in self._model_cooldowns.items():
            if cooldown > now:
                remaining = int(cooldown - now)
                cooldowns.append(f"  ⏳ {model} (cooldown: {remaining}s)")

        result = "\n".join(parts)
        if cooldowns:
            result += "\n" + "\n".join(cooldowns)
        return result

    def get_available_routes(self, task_type: str = "chat") -> str:
        """الحصول على المسارات المتاحة لنوع مهمة"""
        routes = self.get_model_routes(task_type)
        if not routes:
            return f"❌ No routes available for {task_type}"

        parts = []
        for r in routes:
            has_key = "🔑" if r.api_key else "❌"
            parts.append(f"  {r.priority + 1}. {r.provider_name}/{r.model_id} {has_key}")
        return "\n".join(parts)


# ═══════════════════════════════════════
# Singleton Instance - نسخة واحدة من المدير
# ═══════════════════════════════════════

_manager_instance: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    """الحصول على نسخة Provider Manager الوحيدة"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ProviderManager()
    return _manager_instance


# ═══════════════════════════════════════
# Helper Functions - دوال مساعدة
# ═══════════════════════════════════════

async def call_ai(
    prompt,
    system_prompt: str = "",
    task_type: str = "chat",
    temperature: float = 0.7,
    max_tokens: int = 8192,
    prefer_arabic: bool = False,
    user_id: int = None,
) -> Optional[str]:
    """
    استدعاء AI عبر Provider Manager (غير متزامن)
    يدعم نص عادي أو قائمة رسائل (messages list)
    """
    if prefer_arabic and not system_prompt:
        system_prompt = "أنت 'My Bro' - مساعد ذكي شخصي. اسمك الوحيد My Bro ومفيش اسم تاني. لما حد يسألك مين أنت قول أنا My Bro. متدعيش إنك إنسان أو إن عندك مشاعر حقيقية. تكلم بمصري محترم ومتوازن — مش فصحى رسمية ومش عامية زيادة. 🔴 ماتستخدمش لهجة خليجية أبداً! لغتك مصري بحت. ماتقولش \"يا خوي\" ولا \"شلونك\" ولا \"زين\" ولا \"عساك بخير\" ولا \"ما قصرت\" ولا \"الله يعطيك العافية\". 🔴 ماتقولش \"خليك في تمام\" — الجملة دي ملهاش معنى. عادي تقول \"ربنا يحفظك\" بس ماتضيفش ختومات مصنوعة على كل رسالة. أمثلة: 'تمام، خليني أبص على الموضوع.' 'الفكرة هنا إن...' 'دي نقطة مهمة.' ماتستخدمش إهانات أو كلام فظ. خليك ودود وذكي ومحترم وطبيعي. ماتستخدمش Markdown أبداً (لا *, **, #, |, ~). استخدم <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط بس. 🔴 تنوين الفتح: حط التنوين (ً) على الحرف اللي قبل الألف مش على الألف نفسها! ❌ غلط: مرتفعاً ✅ صح: مرتفعًا. ده قانون إملائي عربي — التزم بيه دايماً."

    manager = get_provider_manager()

    # لو prompt قائمة رسائل (مع سياق المحادثة)
    if isinstance(prompt, list):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(prompt)
        return await manager.call_async(
            messages=messages,
            task_type=task_type,
            temperature=temperature,
            max_tokens=max_tokens,
            user_id=user_id,
        )

    # لو prompt نص عادي
    return await manager.call_with_system_prompt_async(
        prompt=prompt,
        system_prompt=system_prompt,
        task_type=task_type,
        temperature=temperature,
        max_tokens=max_tokens,
        user_id=user_id,
    )


def call_ai_sync(
    prompt: str,
    system_prompt: str = "",
    task_type: str = "chat",
    temperature: float = 0.7,
    max_tokens: int = 8192,
    prefer_arabic: bool = False,
    user_id: int = None,
) -> Optional[str]:
    """
    استدعاء AI عبر Provider Manager (متزامن)
    Compatible with the old ai_engine._call_ai_sync interface
    """
    if prefer_arabic and not system_prompt:
        system_prompt = "أنت 'My Bro' - مساعد ذكي شخصي. اسمك الوحيد My Bro ومفيش اسم تاني. لما حد يسألك مين أنت قول أنا My Bro. متدعيش إنك إنسان أو إن عندك مشاعر حقيقية. تكلم بمصري محترم ومتوازن — مش فصحى رسمية ومش عامية زيادة. 🔴 ماتستخدمش لهجة خليجية أبداً! لغتك مصري بحت. ماتقولش \"يا خوي\" ولا \"شلونك\" ولا \"زين\" ولا \"عساك بخير\" ولا \"ما قصرت\" ولا \"الله يعطيك العافية\". 🔴 ماتقولش \"خليك في تمام\" — الجملة دي ملهاش معنى. عادي تقول \"ربنا يحفظك\" بس ماتضيفش ختومات مصنوعة على كل رسالة. أمثلة: 'تمام، خليني أبص على الموضوع.' 'الفكرة هنا إن...' 'دي نقطة مهمة.' ماتستخدمش إهانات أو كلام فظ. خليك ودود وذكي ومحترم وطبيعي. ماتستخدمش Markdown أبداً (لا *, **, #, |, ~). استخدم <b>عريض</b> <i>مائل</i> <code>كود</code> • نقاط بس. 🔴 تنوين الفتح: حط التنوين (ً) على الحرف اللي قبل الألف مش على الألف نفسها! ❌ غلط: مرتفعاً ✅ صح: مرتفعًا. ده قانون إملائي عربي — التزم بيه دايماً."

    manager = get_provider_manager()
    return manager.call_with_system_prompt_sync(
        prompt=prompt,
        system_prompt=system_prompt,
        task_type=task_type,
        temperature=temperature,
        max_tokens=max_tokens,
        user_id=user_id,
    )
