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
    """

    def __init__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        stages: List[Stage],
        lang: str = "ar",
        title: str = "",
    ):
        self.update = update
        self.context = context
        self.stages = stages
        self.lang = lang
        self.title = title or ("جاري المعالجة" if lang == "ar" else "Processing")
        self.progress_msg = None
        self.typing_task = None
        self.timer_task = None
        self.start_time = time.time()
        self._current_stage_idx = 0
        self._finished = False

    async def start(self):
        """بدء نظام التقدم"""
        # إرسال رسالة التقدم الأولى
        text = self._build_progress_text(0)
        try:
            self.progress_msg = await self.update.message.reply_text(
                text, parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not send progress message: {e}")

        # بدء مؤشر الكتابة
        self.typing_task = asyncio.create_task(self._typing_indicator())

        # بدء عداد الثواني الحي
        self.timer_task = asyncio.create_task(self._live_timer())

        return self

    async def _typing_indicator(self):
        """إرسال مؤشر الكتابة بشكل متكرر"""
        try:
            while True:
                try:
                    await self.context.bot.send_chat_action(
                        chat_id=self.update.effective_chat.id,
                        action="typing"
                    )
                except Exception:
                    pass
                await asyncio.sleep(4)  # إرسال كل 4 ثواني
        except asyncio.CancelledError:
            pass

    async def _live_timer(self):
        """عداد ثواني حي - يحدث رسالة التقدم كل ثانية"""
        try:
            while not self._finished:
                await asyncio.sleep(1)
                if self._finished or not self.progress_msg:
                    break
                try:
                    text = self._build_progress_text(self._current_stage_idx)
                    await self.progress_msg.edit_text(text, parse_mode="HTML")
                except Exception as e:
                    # تجاهل أخطاء التعديل المتكرر (رسالة لم تتغير)
                    if "not modified" not in str(e).lower():
                        logger.debug(f"Timer update error: {e}")
        except asyncio.CancelledError:
            pass

    def _build_progress_text(self, stage_idx: int) -> str:
        """بناء نص رسالة التقدم"""
        total = len(self.stages)
        percentage = int((stage_idx / total) * 100) if total > 0 else 0

        # عنوان
        if self.lang == "ar":
            header = f"⏳ <b>{self.title}</b>\n"
        else:
            header = f"⏳ <b>{self.title}</b>\n"

        # شريط التقدم
        bar = progress_bar(percentage)
        header += f"{bar}\n\n"

        # المراحل
        stages_text = ""
        for i, stage in enumerate(self.stages):
            if i < stage_idx:
                stage.status = "done"
            elif i == stage_idx:
                stage.status = "in_progress"
            else:
                stage.status = "waiting"
            stages_text += stage.get_display(self.lang) + "\n"

        # الوقت المنقضي
        elapsed = int(time.time() - self.start_time)
        if self.lang == "ar":
            footer = f"\n⏱ {elapsed} ثانية"
        else:
            footer = f"\n⏱ {elapsed}s"

        return header + stages_text + footer

    async def update_stage(self, stage_idx: int):
        """تحديث المرحلة الحالية"""
        self._current_stage_idx = stage_idx

        if not self.progress_msg:
            return

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

        # إيقاف عداد الثواني الحي
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
            try:
                await self.timer_task
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
                await asyncio.sleep(4)
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
