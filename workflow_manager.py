"""
نظام إدارة حالات العمل - Workflow State Management
يحفظ حالة المستخدم في قاعدة البيانات لتبقى حتى بعد إعادة تشغيل البوت

الأولوية:
1. Workflow نشط → توجيه الرسالة للخدمة المسؤولة
2. أزرار وتفاعلات → توجيه للـ callback handler
3. أوامر وخدمات → توجيه للـ command handler
4. الذكاء الاصطناعي → المحادثة الحرة

أنواع Workflow المدعومة:
- study_mode: وضع الدراسة (بانتظار الموضوع، بانتظار سؤال)
- pdf_question: سؤال عن ملف PDF
- image_edit: تعديل صورة بالذكاء الاصطناعي
- search_query: بحث (بانتظار كلمة البحث)
"""

import json
import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# تخزين مؤقت في الذاكرة + DB
# ═══════════════════════════════════════

# في الذاكرة (أسرع) — يتمسح عند الـ restart بس الداتابيز بتعوض
_workflow_cache: Dict[int, Dict[str, Any]] = {}

# مدة صلاحية الـ Workflow (30 دقيقة — لو المستخدم ساكت أكتر من كده يتمسح)
WORKFLOW_TTL = 30 * 60  # 30 minutes

# أنواع Workflow مع خطواتها
WORKFLOW_STEPS = {
    "study_mode": {
        "waiting_for_subject": "اكتب المادة أو الموضوع الذي تريد دراسته",
        "active": "أنت الآن في وضع الدراسة — اكتب سؤالك أو الموضوع",
    },
    "pdf_question": {
        "waiting_for_question": "اكتب سؤالك عن الملف",
    },
    "image_edit": {
        "waiting_for_description": "اكتب الوصف اللي عايز تعدّل بيه الصورة",
    },
    "search_query": {
        "waiting_for_query": "اكتب كلمة البحث",
    },
}


def set_workflow(user_id: int, workflow_name: str, step: str = None, data: Dict = None):
    """حفظ حالة Workflow للمستخدم في الذاكرة + الداتابيز
    
    Args:
        user_id: معرف المستخدم
        workflow_name: اسم الـ Workflow (مثلاً study_mode)
        step: المرحلة الحالية (مثلاً waiting_for_subject)
        data: بيانات إضافية (مثلاً image_base64, pdf_context)
    """
    workflow = {
        "workflow": workflow_name,
        "step": step or "active",
        "data": data or {},
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    
    # حفظ في الذاكرة
    _workflow_cache[user_id] = workflow
    
    # حفظ في الداتابيز (persistent — يفضل موجود بعد الـ restart)
    try:
        from memory import save_memory
        save_memory(user_id, "active_workflow", json.dumps({
            "workflow": workflow_name,
            "step": step or "active",
            "data": data or {},
            "created_at": workflow["created_at"],
        }), "system")
        logger.info(f"✅ Workflow saved for user {user_id}: {workflow_name}/{step}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to save workflow to DB for user {user_id}: {e}")


def get_workflow(user_id: int) -> Optional[Dict[str, Any]]:
    """استرجاع حالة Workflow النشط للمستخدم
    
    يبحث أولاً في الذاكرة، وبعدين في الداتابيز.
    لو الـ Workflow انتهت صلاحيته (أكتر من 30 دقيقة) يتم مسحه تلقائياً.
    
    Returns:
        Dict with workflow/step/data أو None لو مفيش workflow نشط
    """
    # محاولة 1: من الذاكرة (أسرع)
    cached = _workflow_cache.get(user_id)
    if cached:
        # فحص الصلاحية
        if time.time() - cached.get("updated_at", cached.get("created_at", 0)) > WORKFLOW_TTL:
            # انتهت الصلاحية
            clear_workflow(user_id)
            return None
        return cached
    
    # محاولة 2: من الداتابيز (دائم)
    try:
        from memory import get_memories
        memories = get_memories(user_id, "system")
        for m in memories:
            if m["key"] == "active_workflow":
                try:
                    workflow = json.loads(m["value"])
                    # فحص الصلاحية
                    created_at = workflow.get("created_at", 0)
                    if time.time() - created_at > WORKFLOW_TTL:
                        clear_workflow(user_id)
                        return None
                    # إضافة updated_at لو مش موجود
                    workflow["updated_at"] = time.time()
                    # cache في الذاكرة
                    _workflow_cache[user_id] = workflow
                    logger.info(f"✅ Workflow restored from DB for user {user_id}: {workflow.get('workflow')}/{workflow.get('step')}")
                    return workflow
                except (json.JSONDecodeError, TypeError):
                    pass
    except Exception as e:
        logger.debug(f"Could not load workflow from DB for user {user_id}: {e}")
    
    return None


def update_workflow_step(user_id: int, step: str, data: Dict = None):
    """تحديث مرحلة الـ Workflow بدون تغيير اسمه
    
    Args:
        user_id: معرف المستخدم
        step: المرحلة الجديدة
        data: بيانات إضافية جديدة (يتم دمجها مع القديمة)
    """
    workflow = get_workflow(user_id)
    if not workflow:
        return
    
    workflow["step"] = step
    workflow["updated_at"] = time.time()
    if data:
        workflow["data"].update(data)
    
    # حفظ في الذاكرة
    _workflow_cache[user_id] = workflow
    
    # حفظ في الداتابيز
    try:
        from memory import save_memory
        save_memory(user_id, "active_workflow", json.dumps({
            "workflow": workflow["workflow"],
            "step": step,
            "data": workflow["data"],
            "created_at": workflow.get("created_at", time.time()),
        }), "system")
    except Exception as e:
        logger.warning(f"⚠️ Failed to update workflow in DB for user {user_id}: {e}")


def clear_workflow(user_id: int):
    """مسح حالة Workflow للمستخدم من الذاكرة + الداتابيز"""
    # مسح من الذاكرة
    _workflow_cache.pop(user_id, None)
    
    # مسح من الداتابيز
    try:
        from memory import save_memory
        save_memory(user_id, "active_workflow", "", "system")
    except Exception:
        pass
    
    # مسح user_states القديم كمان (backward compatibility)
    try:
        from handlers.callbacks import user_states
        user_states.pop(user_id, None)
    except Exception:
        pass
    
    logger.info(f"🧹 Workflow cleared for user {user_id}")


def is_workflow_active(user_id: int, workflow_name: str = None) -> bool:
    """فحص هل المستخدم داخل workflow نشط
    
    Args:
        user_id: معرف المستخدم
        workflow_name: اسم workflow محدد (اختياري — لو مش محدد بيفحص أي workflow)
    """
    workflow = get_workflow(user_id)
    if not workflow:
        return False
    if workflow_name:
        return workflow.get("workflow") == workflow_name
    return True


def touch_workflow(user_id: int):
    """تحديث وقت الـ workflow عشان ما يتمسحش (تمديد الصلاحية)"""
    workflow = get_workflow(user_id)
    if workflow:
        workflow["updated_at"] = time.time()
        _workflow_cache[user_id] = workflow
