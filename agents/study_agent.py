"""
وكيل الدراسة - Study Agent
وضع الدراسة والتعليم مع كويز وامتحانات وخطط دراسية
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_max_tokens_for_user(user_id: int = None) -> int:
    """تحديد عدد التوكنز حسب خطة المستخدم"""
    try:
        from premium import get_user_plan
        if user_id:
            plan = get_user_plan(user_id)
            if plan in ("premium", "premium_plus"):
                return 4000
    except Exception:
        pass
    return 3000


async def _call_ai_with_retry(prompt: str, user_id: int = None, max_retries: int = 2) -> str:
    """استدعاء AI مع retry"""
    from provider_manager import call_ai
    from formatters import clean_ai_response

    for attempt in range(max_retries + 1):
        try:
            result = await call_ai(prompt, max_tokens=_get_max_tokens_for_user(user_id), user_id=user_id, task_type="chat")
            return clean_ai_response(result)
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"AI call failed (attempt {attempt+1}), retrying: {e}")
                await asyncio.sleep(1)
            else:
                raise


class StudyAgent:
    """وكيل الدراسة - شرح وكويز وامتحانات وخطط دراسية"""

    async def create_study_plan(self, subject: str, duration: str = "4 weeks", language: str = "ar", user_id: int = None) -> str:
        """إنشاء خطة دراسية"""
        if language == "ar":
            prompt = f"""أنشئ خطة دراسية شاملة لـ "{subject}" بمدة {duration}.

التنسيق:
📚 <b>خطة دراسية: {subject}</b>
⏰ المدة: {duration}
━━━━━━━━━━━━━━━━━

🗓️ <b>الأسبوع 1</b>
📌 الهدف: [الهدف الرئيسي]
→ اليوم 1: [المحتوى]
→ اليوم 2: [المحتوى]
→ اليوم 3: [المحتوى]
→ اليوم 4: [المحتوى]
→ اليوم 5: [المحتوى]
📝 مراجعة نهاية الأسبوع

🗓️ <b>الأسبوع 2</b>
📌 الهدف: [الهدف الرئيسي]
...

🎯 <b>أهداف التعلم</b>
→ هدف 1
→ هدف 2

📖 <b>مصادر مقترحة</b>
→ مصدر 1
→ مصدر 2

💡 <b>نصائح للنجاح</b>
→ نصيحة 1
→ نصيحة 2

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط.

أنت مستشار تعليمي محترف تنشئ خطط دراسية شاملة ومفصلة. ماتستخدمش Markdown أبدًا. استخدم HTML فقط."""
        else:
            prompt = f"""Create a comprehensive study plan for "{subject}" over {duration}.

Format:
📚 <b>Study Plan: {subject}</b>
⏰ Duration: {duration}
━━━━━━━━━━━━━━━━━

🗓️ <b>Week 1</b>
📌 Goal: [Main goal]
→ Day 1: [Content]
→ Day 2: [Content]
→ Day 3: [Content]
→ Day 4: [Content]
→ Day 5: [Content]
📝 End-of-week review

🗓️ <b>Week 2</b>
📌 Goal: [Main goal]
...

🎯 <b>Learning Objectives</b>
→ Objective 1
→ Objective 2

📖 <b>Suggested Resources</b>
→ Resource 1
→ Resource 2

💡 <b>Tips for Success</b>
→ Tip 1
→ Tip 2

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only.

You are a professional educational consultant who creates comprehensive and detailed study plans. NEVER use Markdown. Use HTML only."""

        try:
            return await _call_ai_with_retry(prompt, user_id)
        except Exception as e:
            logger.error(f"Study plan creation failed: {e}")
            return "❌ حصل خطأ في إنشاء الخطة الدراسية." if language == "ar" else "❌ Error creating study plan."

    async def generate_quiz(self, topic: str, num_questions: int = 5, difficulty: str = "medium", language: str = "ar", user_id: int = None) -> str:
        """إنشاء كويز"""
        difficulty_map_ar = {"easy": "سهل", "medium": "متوسط", "hard": "صعب"}
        difficulty_map_en = {"سهل": "easy", "متوسط": "medium", "صعب": "hard"}

        if language == "ar":
            diff_display = difficulty_map_ar.get(difficulty, difficulty)
            prompt = f"""أنشئ كويز في موضوع "{topic}" ({num_questions} أسئلة - مستوى {diff_display})

تنسيق الكويز:
📝 <b>كويز: {topic}</b>
📊 المستوى: {diff_display}
━━━━━━━━━━━━━━━━━

❓ <b>سؤال 1:</b> [السؤال]
أ) خيار 1
ب) خيار 2
ج) خيار 3
د) خيار 4

✅ <b>الإجابة الصحيحة:</b> [الحرف]
💡 <b>الشرح:</b> [شرح مختصر]

⚠️ ماتستخدمش Markdown (لا *, **, #, |). استخدم HTML فقط.

أنت مساعد تعليمي تنشئ كويزات متنوعة ومفيدة. ماتستخدمش Markdown أبدًا."""
        else:
            diff_display = difficulty_map_en.get(difficulty, difficulty)
            prompt = f"""Create a quiz on "{topic}" ({num_questions} questions - {diff_display} level)

Quiz format:
📝 <b>Quiz: {topic}</b>
📊 Level: {diff_display}
━━━━━━━━━━━━━━━━━

❓ <b>Question 1:</b> [question]
A) option 1
B) option 2
C) option 3
D) option 4

✅ <b>Answer:</b> [letter]
💡 <b>Explanation:</b> [brief explanation]

⚠️ NEVER use Markdown (no *, **, #, |). Use HTML only.

You are an educational assistant that creates diverse and useful quizzes. NEVER use Markdown."""

        try:
            return await _call_ai_with_retry(prompt, user_id)
        except Exception as e:
            logger.error(f"Quiz generation failed: {e}")
            return "❌ حصل خطأ في إنشاء الكويز." if language == "ar" else "❌ Error generating quiz."

    async def generate_exam(self, topic: str, num_questions: int = 20, language: str = "ar", user_id: int = None) -> str:
        """إنشاء امتحان شامل"""
        if language == "ar":
            prompt = f"""أنشئ امتحان شامل في "{topic}" ({num_questions} سؤال)

تنسيق الامتحان:
📋 <b>امتحان: {topic}</b>
⏰ الوقت: 60 دقيقة
━━━━━━━━━━━━━━━━━

<b>القسم الأول: أسئلة الاختيار من متعدد (10 درجات)</b>

❓ <b>سؤال 1:</b> [السؤال] (درجة واحدة)
أ)  ب)  ج)  د)

<b>القسم الثاني: أسئلة صح أو خطأ (5 درجات)</b>

❓ <b>سؤال 11:</b> [العبارة] (درجة واحدة)
□ صح  □ خطأ

<b>القسم الثالث: أسئلة مقالية قصيرة (5 درجات)</b>

❓ <b>سؤال 16:</b> [السؤال] (درجتين)

━━━━━━━━━━━━━━━━━
📝 <b>نموذج الإجابات</b>

[إجابات مفصلة لكل الأسئلة]

⚠️ ماتستخدمش Markdown. استخدم HTML فقط.

أنت أستاذ جامعي تنشئ امتحانات شاملة ومتنوعة. ماتستخدمش Markdown أبدًا."""
        else:
            prompt = f"""Create a comprehensive exam on "{topic}" ({num_questions} questions)

Format:
📋 <b>Exam: {topic}</b>
⏰ Time: 60 minutes
━━━━━━━━━━━━━━━━━

<b>Section 1: Multiple Choice (10 points)</b>

❓ <b>Question 1:</b> [question] (1 point)
A)  B)  C)  D)

<b>Section 2: True or False (5 points)</b>

❓ <b>Question 11:</b> [statement] (1 point)
□ True  □ False

<b>Section 3: Short Essay Questions (5 points)</b>

❓ <b>Question 16:</b> [question] (2 points)

━━━━━━━━━━━━━━━━━
📝 <b>Answer Key</b>

[Detailed answers for all questions]

⚠️ NEVER use Markdown. Use HTML only.

You are a university professor who creates comprehensive and diverse exams. NEVER use Markdown."""

        try:
            return await _call_ai_with_retry(prompt, user_id)
        except Exception as e:
            logger.error(f"Exam generation failed: {e}")
            return "❌ حصل خطأ في إنشاء الامتحان." if language == "ar" else "❌ Error generating exam."

    async def explain_lesson(self, topic: str, level: str = "beginner", language: str = "ar", user_id: int = None) -> str:
        """شرح درس"""
        level_map_ar = {"beginner": "مبتدئ", "intermediate": "متوسط", "advanced": "متقدم"}

        if language == "ar":
            level_display = level_map_ar.get(level, level)
            prompt = f"""اشرح "{topic}" بطريقة تعليمية لمستوى {level_display}.

التنسيق:
📚 <b>شرح: {topic}</b>
📊 المستوى: {level_display}
━━━━━━━━━━━━━━━━━

🎯 <b>ماذا ستتعلم؟</b>
→ هدف 1
→ هدف 2

📖 <b>الشرح</b>
→ شرح مفصل مع أمثلة
→ توضيح المفاهيم الأساسية

💡 <b>أمثلة عملية</b>
→ مثال 1
→ مثال 2

🔑 <b>النقاط المهمة</b>
→ نقطة 1
→ نقطة 2

📝 <b>تمارين للتطبيق</b>
→ تمرين 1
→ تمرين 2

⚠️ ماتستخدمش Markdown. استخدم HTML فقط.

أنت مدرس ذكي يشرح الدروس بطريقة مبسطة ومفهومة. ماتستخدمش Markdown أبدًا."""
        else:
            prompt = f"""Explain "{topic}" in an educational way for {level} level.

Format:
📚 <b>Explanation: {topic}</b>
📊 Level: {level}
━━━━━━━━━━━━━━━━━

🎯 <b>What will you learn?</b>
→ Objective 1
→ Objective 2

📖 <b>Explanation</b>
→ Detailed explanation with examples
→ Clarifying core concepts

💡 <b>Practical Examples</b>
→ Example 1
→ Example 2

🔑 <b>Key Points</b>
→ Point 1
→ Point 2

📝 <b>Practice Exercises</b>
→ Exercise 1
→ Exercise 2

⚠️ NEVER use Markdown. Use HTML only.

You are a smart teacher who explains lessons in a simple and understandable way. NEVER use Markdown."""

        try:
            return await _call_ai_with_retry(prompt, user_id)
        except Exception as e:
            logger.error(f"Lesson explanation failed: {e}")
            return "❌ حصل خطأ في الشرح." if language == "ar" else "❌ Error explaining lesson."

    async def create_revision_notes(self, topic: str, language: str = "ar", user_id: int = None) -> str:
        """إنشاء ملاحظات مراجعة"""
        if language == "ar":
            prompt = f"""أنشئ ملاحظات مراجعة سريعة لـ "{topic}"

التنسيق:
📒 <b>ملاحظات مراجعة: {topic}</b>
━━━━━━━━━━━━━━━━━

📌 <b>المفاهيم الأساسية</b>
→ مفهوم 1: شرح سريع
→ مفهوم 2: شرح سريع

📝 <b>المعادلات/القوانين المهمة</b>
→ معادلة 1
→ معادلة 2

⚠️ <b>أخطاء شائعة يجب تجنبها</b>
→ خطأ 1
→ خطأ 2

✅ <b>نصائح سريعة</b>
→ نصيحة 1
→ نصيحة 2

🧠 <b>طريقة الحفظ</b>
→ طريقة 1

⚠️ ماتستخدمش Markdown. استخدم HTML فقط.

أنت مساعد تعليمي تنشئ ملاحظات مراجعة سريعة وفعالة. ماتستخدمش Markdown أبدًا."""
        else:
            prompt = f"""Create quick revision notes for "{topic}"

Format:
📒 <b>Revision Notes: {topic}</b>
━━━━━━━━━━━━━━━━━

📌 <b>Core Concepts</b>
→ Concept 1: quick explanation
→ Concept 2: quick explanation

📝 <b>Important Formulas/Rules</b>
→ Formula 1
→ Formula 2

⚠️ <b>Common Mistakes to Avoid</b>
→ Mistake 1
→ Mistake 2

✅ <b>Quick Tips</b>
→ Tip 1
→ Tip 2

🧠 <b>Memory Technique</b>
→ Technique 1

⚠️ NEVER use Markdown. Use HTML only.

You are an educational assistant that creates quick and effective revision notes. NEVER use Markdown."""

        try:
            return await _call_ai_with_retry(prompt, user_id)
        except Exception as e:
            logger.error(f"Revision notes creation failed: {e}")
            return "❌ حصل خطأ في إنشاء ملاحظات المراجعة." if language == "ar" else "❌ Error creating revision notes."

    async def homework_help(self, question: str, language: str = "ar", user_id: int = None) -> str:
        """مساعدة في الواجبات"""
        if language == "ar":
            prompt = f"""ساعدني في حل السؤال التالي ( مش هدلك الإجابة مباشرة - هشرحلك وأوجهك):

❓ {question}

التنسيق:
📚 <b>مساعدة في الواجب</b>
━━━━━━━━━━━━━━━━━

🔍 <b>فهم السؤال</b>
→ شرح ما يطلبه السؤال

💡 <b>التلميحات</b>
→ تلميح 1
→ تلميح 2

📝 <b>خطوات الحل</b>
→ خطوة 1
→ خطوة 2
→ خطوة 3

✅ <b>الإجابة النهائية</b>
→ الإجابة مع الشرح

⚠️ ماتستخدمش Markdown. استخدم HTML فقط.

أنت معلم صبور تساعد الطلاب في واجباتهم. تشرح خطوة بخطوة ولا تعطي الإجابة مباشرة. ماتستخدمش Markdown أبدًا."""
        else:
            prompt = f"""Help me solve the following question (don't give the answer directly - guide me):

❓ {question}

Format:
📚 <b>Homework Help</b>
━━━━━━━━━━━━━━━━━

🔍 <b>Understanding the Question</b>
→ What the question is asking

💡 <b>Hints</b>
→ Hint 1
→ Hint 2

📝 <b>Solution Steps</b>
→ Step 1
→ Step 2
→ Step 3

✅ <b>Final Answer</b>
→ Answer with explanation

⚠️ NEVER use Markdown. Use HTML only.

You are a patient teacher who helps students with homework. You explain step by step. NEVER use Markdown."""

        try:
            return await _call_ai_with_retry(prompt, user_id)
        except Exception as e:
            logger.error(f"Homework help failed: {e}")
            return "لم أتمكن من المساعدة. 🤖" if language == "ar" else "Couldn't help. 🤖"
