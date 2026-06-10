"""
نظام التقدم المتميز - Premium Progress System
يوفر تجربة تيليجرام احترافية مع:
- مؤشرات الكتابة (typing indicators)
- تحديث مباشر للرسائل (live message editing)
- نظام تقدم متعدد المراحل
- شريط تقدم بصري
- تنظيف تلقائي للرسائل المؤقتة
"""

import asyncio
import logging
import time
from typing import Optional, List, Dict

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# مراحل العمل - Workflow Stages
# ═══════════════════════════════════════

class Stage:
    """تمثيل مرحلة واحدة من مراحل العمل"""
    def __init__(self, emoji: str, name_ar: str, name_en: str):
        self.emoji = emoji
        self.name_ar = name_ar
        self.name_en = name_en
        self.status = "waiting"  # waiting, in_progress, done

    def get_display(self, lang: str = "ar") -> str:
        """عرض المرحلة حسب حالتها"""
        name = self.name_ar if lang == "ar" else self.name_en
        if self.status == "done":
            return f"  {self.emoji} {name}... ✅"
        elif self.status == "in_progress":
            return f"  {self.emoji} {name}... ⏳"
        else:  # waiting
            return f"  {self.emoji} {name}... ⏳"

    def set_in_progress(self):
        self.status = "in_progress"

    def set_done(self):
        self.status = "done"

    def set_waiting(self):
        self.status = "waiting"


# ═══════════════════════════════════════
# قوالب المراحل الجاهزة - Stage Templates
# ═══════════════════════════════════════

def NEWS_STAGES(lang: str = "ar") -> List[Stage]:
    """مراحل جلب الأخبار"""
    return [
        Stage("📡", "جلب الأخبار من المصادر", "Fetching from sources"),
        Stage("🔍", "فلترة الأخبار", "Filtering articles"),
        Stage("📊", "ترتيب الأخبار", "Ranking articles"),
        Stage("📝", "تلخيص الأخبار", "Summarizing articles"),
        Stage("✍️", "تنسيق الرسالة", "Formatting message"),
    ]

def AI_STAGES(lang: str = "ar") -> List[Stage]:
    """مراحل المحادثة الذكية"""
    return [
        Stage("🧠", "فهم السؤال", "Understanding question"),
        Stage("💭", "التفكير في الإجابة", "Thinking about answer"),
        Stage("✍️", "كتابة الرد", "Writing response"),
    ]

def SEARCH_STAGES(lang: str = "ar") -> List[Stage]:
    """مراحل البحث"""
    return [
        Stage("🔍", "البحث في المصادر", "Searching sources"),
        Stage("📚", "تحليل النتائج", "Analyzing results"),
        Stage("📝", "تجهيز الرد", "Preparing response"),
    ]

def DEEP_SEARCH_STAGES(lang: str = "ar") -> List[Stage]:
    """مراحل البحث العميق"""
    return [
        Stage("🔍", "البحث في الويب", "Searching web"),
        Stage("📰", "البحث في الأخبار", "Searching news"),
        Stage("🔬", "البحث المتقدم", "Advanced search"),
        Stage("📊", "فهرسة وتحليل النتائج", "Indexing & analyzing"),
        Stage("📝", "كتابة التقرير الشامل", "Writing comprehensive report"),
    ]

def COMPANY_STAGES(lang: str = "ar") -> List[Stage]:
    """مراحل تقرير الشركة"""
    return [
        Stage("🔍", "البحث عن الشركة", "Searching company"),
        Stage("📰", "جلب أحدث الأخبار", "Fetching latest news"),
        Stage("📊", "تحليل البيانات", "Analyzing data"),
        Stage("✍️", "كتابة التقرير", "Writing report"),
    ]

def LEARN_STAGES(lang: str = "ar") -> List[Stage]:
    """مراحل الشرح التعليمي"""
    return [
        Stage("🧠", "فهم الموضوع", "Understanding topic"),
        Stage("📚", "تجهيز الشرح", "Preparing explanation"),
        Stage("✍️", "كتابة المحتوى", "Writing content"),
    ]

def ROADMAP_STAGES(lang: str = "ar") -> List[Stage]:
    """مراحل خارطة الطريق"""
    return [
        Stage("🗺️", "تحليل المسار", "Analyzing path"),
        Stage("📋", "تجهيز خارطة الطريق", "Preparing roadmap"),
        Stage("✍️", "كتابة المحتوى", "Writing content"),
    ]


# ═══════════════════════════════════════
# شريط التقدم - Progress Bar
# ═══════════════════════════════════════

def progress_bar(percentage: int, length: int = 10) -> str:
    """شريط تقدم بصري"""
    filled = int(length * percentage / 100)
    empty = length - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {percentage}%"


# ═══════════════════════════════════════
# مدير التقدم - Progress Manager
# ═══════════════════════════════════════

class ProgressManager:
    """
    مدير التقدم المتميز
    يتحكم في:
    - إرسال مؤشر الكتابة
    - تحديث رسالة التقدم مباشرة
    - إدارة مراحل العمل
    - تنظيف الرسائل المؤقتة
    
    ⚠️ BUG FIX: Added timeout mechanism (default 120 seconds) to prevent
    background task leaks. If an operation doesn't complete within the
    timeout, background tasks are automatically stopped to prevent
    memory leaks and resource exhaustion.
    """

    DEFAULT_TIMEOUT = 120  # Maximum seconds before auto-cleanup
    DEEP_SEARCH_TIMEOUT = 300  # 5 minutes for deep search operations

    def __init__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        stages: List[Stage],
        lang: str = "ar",
        title: str = "",
        timeout: int = None,
    ):
        self.update = update
        self.context = context
        self.stages = stages
        self.lang = lang
        self.title = title or ("جاري المعالجة" if lang == "ar" else "Processing")
        self.progress_msg = None
        self.typing_task = None
        self.timeout_task = None
        self.start_time = time.time()
        self._current_stage_idx = 0
        self._finished = False
        self._timeout_seconds = timeout if timeout is not None else self.DEFAULT_TIMEOUT

    async def start(self):
        """بدء نظام التقدم — شريط تقدم بس + مؤشر كتابة
        
        🟢 v9.18: رسالة خفيفة جداً (عنوان + شريط تقدم بس)
        مؤشر الكتابة بيشتغل في الـ background
        """
        # إرسال رسالة التقدم الأولى
        text = self._build_progress_text(0)
        try:
            self.progress_msg = await self.update.message.reply_text(
                text, parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not send progress message: {e}")

        # بدء مؤشر الكتابة (كل 5 ثواني)
        self.typing_task = asyncio.create_task(self._typing_indicator())

        # مراقب المهلة لمنع تسرب المهام
        self.timeout_task = asyncio.create_task(self._timeout_watchdog())

        return self

    async def _timeout_watchdog(self):
        """مراقب المهلة — يوقف المهام الخلفية تلقائياً لو العملية طالت"""
        try:
            await asyncio.sleep(self._timeout_seconds)
            if not self._finished:
                logger.warning(
                    f"ProgressManager timeout reached ({self._timeout_seconds}s) "
                    f"for operation: {self.title}. Auto-cleaning background tasks."
                )
                await self._stop_background_tasks()
                if self.progress_msg:
                    try:
                        error_text = "⏰ انتهت المهلة — حاول تاني" if self.lang == "ar" else "⏰ Operation timed out — please try again"
                        await self.progress_msg.edit_text(f"❌ {error_text}")
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass  # Normal cancellation when complete/error is called

    async def _typing_indicator(self):
        """إرسال مؤشر الكتابة بشكل متكرر
        
        🔴 FIX v9.16: كل 5 ثواني بدل 4 — تقليل API calls
        """
        try:
            while True:
                try:
                    await self.context.bot.send_chat_action(
                        chat_id=self.update.effective_chat.id,
                        action="typing"
                    )
                except Exception:
                    pass
                await asyncio.sleep(5)  # إرسال كل 5 ثواني (بدل 4)
        except asyncio.CancelledError:
            pass

    def _build_progress_text(self, stage_idx: int) -> str:
        """بناء نص رسالة التقدم — شريط تقدم بس (أسرع)
        
        🟢 v9.18: شيلنا المراحل والوقت — كانوا بيزودوا حجم الرسالة
        وبيبطئوا التعديل. شريط التقدم بس أخف وأسرع.
        """
        total = len(self.stages)
        percentage = int((stage_idx / total) * 100) if total > 0 else 0

        # عنوان + شريط تقدم بس
        bar = progress_bar(percentage)
        return f"⏳ <b>{self.title}</b>\n{bar}"

    async def update_stage(self, stage_idx: int):
        """تحديث المرحلة الحالية — مع تعديل الرسالة
        
        🟢 FIX v9.17: بنعدل الرسالة بس لما المرحلة تتغير (2-3 edits كحد أقصى)
        مش زي القديم اللي كان بيعمل edit كل 1.5 ثانية — ده تعديل ذكي بس عند تغيير المرحلة
        ده بيخلي المستخدم يشوف التقدم بيتحرك من غير ما يبطئ التليجرام
        """
        if stage_idx == self._current_stage_idx:
            return  # مفيش تغيير — مفيش داعي نعدل
        
        self._current_stage_idx = stage_idx
        
        # تعديل رسالة التقدم لما المرحلة تتغير (2-3 edits فقط)
        if self.progress_msg:
            try:
                text = self._build_progress_text(stage_idx)
                await self.progress_msg.edit_text(text, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Could not update progress message: {e}")

    async def next_stage(self):
        """الانتقال للمرحلة التالية"""
        self._current_stage_idx += 1
        if self._current_stage_idx < len(self.stages):
            await self.update_stage(self._current_stage_idx)

    async def _stop_background_tasks(self):
        """إيقاف جميع المهام الخلفية"""
        self._finished = True

        # إيقاف مراقب المهلة
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
            try:
                await self.timeout_task
            except asyncio.CancelledError:
                pass

        # إيقاف مؤشر الكتابة
        if self.typing_task and not self.typing_task.done():
            self.typing_task.cancel()
            try:
                await self.typing_task
            except asyncio.CancelledError:
                pass

    async def complete(self, final_message: str = "", reply_markup=None, delete_progress: bool = True):
        """
        إنهاء نظام التقدم
        - إيقاف مؤشر الكتابة والعداد الحي
        - حذف رسالة التقدم أو تحديثها بالنتيجة النهائية
        - 🔴 FIX: لو الرسالة أطول من 4096 حرف، يتم حذف الـ progress وإرسالها كرسالة جديدة
        """
        # إيقاف جميع المهام الخلفية
        await self._stop_background_tasks()

        if not self.progress_msg:
            return

        try:
            if delete_progress and final_message:
                # حذف رسالة التقدم وإرسال النتيجة النهائية
                await self.progress_msg.delete()
            elif final_message:
                # 🔴 FIX: لو الرسالة طويلة جداً لتيليجرام، احذف الـ progress وابلغ إنها هتتبعت من بره
                if len(final_message) > 4096:
                    logger.warning(f"⚠️ Response too long ({len(final_message)} chars) for edit_text, deleting progress message")
                    await self.progress_msg.delete()
                    return  # الـ caller لازم يبعت الرسالة بنفسه مقسمة
                # تحديث رسالة التقدم بالنتيجة النهائية
                await self.progress_msg.edit_text(
                    final_message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
            elif delete_progress:
                # حذف رسالة التقدم فقط
                await self.progress_msg.delete()
        except Exception as e:
            logger.debug(f"Could not finalize progress message: {e}")

    async def error(self, error_message: str):
        """عرض رسالة خطأ"""
        # إيقاف جميع المهام الخلفية
        await self._stop_background_tasks()

        if self.progress_msg:
            try:
                await self.progress_msg.edit_text(f"❌ {error_message}")
            except Exception:
                pass


# ═══════════════════════════════════════
# دوال مساعدة سريعة - Quick Helpers
# ═══════════════════════════════════════

async def send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال مؤشر الكتابة مرة واحدة"""
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )
    except Exception:
        pass


class TypingIndicator:
    """مؤشر كتابة مستمر - يستخدم للعمليات القصيرة"""

    def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.update = update
        self.context = context
        self.task = None

    async def start(self):
        """بدء مؤشر الكتابة"""
        self.task = asyncio.create_task(self._keep_typing())
        return self

    async def _keep_typing(self):
        """إبقاء مؤشر الكتابة نشط"""
        try:
            while True:
                try:
                    await self.context.bot.send_chat_action(
                        chat_id=self.update.effective_chat.id,
                        action="typing"
                    )
                except Exception:
                    pass
                await asyncio.sleep(5)  # كل 5 ثواني (محسن للسرعة)
        except asyncio.CancelledError:
            pass

    async def stop(self):
        """إيقاف مؤشر الكتابة"""
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
