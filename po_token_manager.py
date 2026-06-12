"""
PO Token Manager — YouTube Bot Detection Bypass
=================================================
يدير PO Token (Proof of Origin Token) لتخطي حظر YouTube.

🔴 إيه الـ PO Token؟
- يوتيوب بيطلب PO Token عشان يثبت إن الطلب جاي من browser حقيقي
- الـ token ده بيتم إنشاؤه من browser challenge
- لو موجود، yt-dlp بيقدر يتخطى "Sign in to confirm you're not a bot"

🔴 إزاي بيشتغل؟
1. Admin يضيف PO Token عبر متغير بيئة PO_TOKEN أو أمر /potoken
2. الموديول بيخزن الـ token ويضيفه لـ yt-dlp options
3. لو مش متوفر → كل حاجة شغالة زي ما هي (مفيش أي تأثير)

🔴 ليه آمن؟
- لو مش متوفر: مفيش أي تغيير في السلوك
- لو متوفر: بيضاف كـ طبقة إضافية فوق الطرق الموجودة
- مش بيستبدل أي fallback موجود — بيشتغل معاهم
"""

import os
import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# إعدادات PO Token
# ═══════════════════════════════════════

# ملف تخزين PO Token
_PO_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "po_token.json")

# الـ token في الذاكرة (أسرع من القراءة من ملف كل مرة)
_current_token: Optional[str] = None
_token_source: Optional[str] = None  # "env", "file", "api", "manual"
_token_set_at: float = 0
_token_lock = threading.Lock()

# PO Token بيبطل بعد فترة — بنفترض 6 ساعات وبنعمل refresh
_TOKEN_TTL_SECONDS = 6 * 3600  # 6 ساعات

# أقصى عمر للـ token قبل ما نعتبره expired
_MAX_TOKEN_AGE_SECONDS = 12 * 3600  # 12 ساعة — بعد كده لازم token جديد


# ═══════════════════════════════════════
# إدارة PO Token
# ═══════════════════════════════════════

def _load_token_from_env() -> Optional[str]:
    """تحميل PO Token من متغير البيئة"""
    token = os.environ.get("PO_TOKEN", "").strip()
    if token:
        logger.info("🔑 PO Token: Loaded from environment variable")
        return token
    return None


def _load_token_from_file() -> Optional[str]:
    """تحميل PO Token من ملف التخزين"""
    try:
        if not os.path.exists(_PO_TOKEN_FILE):
            return None
        
        with open(_PO_TOKEN_FILE, 'r') as f:
            data = json.load(f)
        
        token = data.get("token", "").strip()
        if not token:
            return None
        
        set_at = data.get("set_at", 0)
        age = time.time() - set_at
        
        # لو الـ token قديم أكتر من الحد الأقصى → مش صالح
        if age > _MAX_TOKEN_AGE_SECONDS:
            logger.info(f"🔑 PO Token: File token expired (age: {age/3600:.1f}h)")
            return None
        
        logger.info(f"🔑 PO Token: Loaded from file (age: {age/3600:.1f}h)")
        return token
        
    except Exception as e:
        logger.debug(f"🔑 PO Token: Could not load from file: {e}")
        return None


def _save_token_to_file(token: str) -> bool:
    """حفظ PO Token في ملف التخزين"""
    try:
        data = {
            "token": token,
            "set_at": time.time(),
            "source": _token_source or "unknown",
        }
        with open(_PO_TOKEN_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.warning(f"🔑 PO Token: Could not save to file: {e}")
        return False


def init_po_token() -> Optional[str]:
    """تهيئة PO Token — بنحاول نحمله من أي مصدر متاح
    
    الترتيب:
    1. متغير البيئة PO_TOKEN
    2. ملف التخزين po_token.json
    """
    global _current_token, _token_source, _token_set_at
    
    with _token_lock:
        # 1. من متغير البيئة
        token = _load_token_from_env()
        if token:
            _current_token = token
            _token_source = "env"
            _token_set_at = time.time()
            # كمان نحفظه في الملف عشان يفضل موجود بعد الـ restart
            _save_token_to_file(token)
            logger.info(f"🔑 PO Token: Initialized from env (length: {len(token)})")
            return token
        
        # 2. من الملف
        token = _load_token_from_file()
        if token:
            _current_token = token
            _token_source = "file"
            data = {}
            try:
                with open(_PO_TOKEN_FILE, 'r') as f:
                    data = json.load(f)
            except Exception:
                pass
            _token_set_at = data.get("set_at", time.time())
            logger.info(f"🔑 PO Token: Initialized from file (length: {len(token)})")
            return token
        
        logger.info("🔑 PO Token: No token available — using standard download methods")
        return None


def get_po_token() -> Optional[str]:
    """الحصول على PO Token الحالي (لو متوفر وصالح)"""
    global _current_token, _token_set_at
    
    with _token_lock:
        if not _current_token:
            return None
        
        # نتأكد إن الـ token مش قديم
        age = time.time() - _token_set_at
        if age > _MAX_TOKEN_AGE_SECONDS:
            logger.info(f"🔑 PO Token: Expired (age: {age/3600:.1f}h)")
            _current_token = None
            return None
        
        return _current_token


def set_po_token(token: str, source: str = "manual") -> bool:
    """تعيين PO Token جديد — من أمر أدمن أو API
    
    Args:
        token: الـ PO Token الجديد
        source: مصدر الـ token (manual, api, env)
    """
    global _current_token, _token_source, _token_set_at
    
    if not token or not token.strip():
        return False
    
    token = token.strip()
    
    with _token_lock:
        _current_token = token
        _token_source = source
        _token_set_at = time.time()
        _save_token_to_file(token)
        
        logger.info(f"🔑 PO Token: Set new token (source: {source}, length: {len(token)})")
    
    return True


def clear_po_token() -> bool:
    """مسح PO Token — لو الأدمن عايز يشيله"""
    global _current_token, _token_source, _token_set_at
    
    with _token_lock:
        _current_token = None
        _token_source = None
        _token_set_at = 0
        
        # نمسح الملف كمان
        try:
            if os.path.exists(_PO_TOKEN_FILE):
                os.remove(_PO_TOKEN_FILE)
        except Exception:
            pass
        
        logger.info("🔑 PO Token: Cleared")
    
    return True


def get_po_token_status() -> dict:
    """حالة PO Token — للأدمن يعرف إيه اللي شغال"""
    with _token_lock:
        if not _current_token:
            return {
                "available": False,
                "source": None,
                "age_hours": 0,
                "ttl_hours": 0,
                "expired": False,
            }
        
        age = time.time() - _token_set_at
        ttl = max(0, _TOKEN_TTL_SECONDS - age) / 3600
        expired = age > _MAX_TOKEN_AGE_SECONDS
        
        return {
            "available": True,
            "source": _token_source,
            "age_hours": round(age / 3600, 1),
            "ttl_hours": round(ttl, 1),
            "expired": expired,
            "token_preview": f"{_current_token[:8]}..." if len(_current_token) > 8 else "***",
        }


# ═══════════════════════════════════════
# yt-dlp Integration
# ═══════════════════════════════════════

def get_ytdlp_po_token_args() -> dict:
    """إرجاع yt-dlp extractor_args مع PO Token لو متوفر
    
    Returns:
        dict: extractor_args للإضافة لـ yt-dlp options
              لو مش متوفر → dict فاضي (مش هيأثر على أي حاجة)
    
    Usage:
        opts = {...}  # yt-dlp options عادية
        po_args = get_ytdlp_po_token_args()
        if po_args:
            opts['extractor_args'] = {**opts.get('extractor_args', {}), **po_args}
    """
    token = get_po_token()
    if not token:
        return {}
    
    # yt-dlp بيقبل PO Token في extractor_args
    # Format: youtube: {po_token: ['web+TOKEN']}
    # الـ "web+" prefix بيحدد نوع الـ client
    return {'youtube': {'po_token': [f'web+{token}']}}


def should_use_po_token() -> bool:
    """هل نستخدم PO Token؟ — بنستخدمه لو متوفر وصالح"""
    return get_po_token() is not None


def add_po_token_to_opts(opts: dict) -> dict:
    """إضافة PO Token لـ yt-dlp options بطريقة آمنة
    
    🔴 آمنة لأن:
    - لو مش متوفر → بترجع الـ opts زي ما هي بدون أي تغيير
    - لو متوفر → بتضيف الـ token للـ extractor_args الموجودين
    - مش بتستبدل أي إعدادات موجودة
    
    Args:
        opts: yt-dlp options dict
    
    Returns:
        dict: نفس الـ opts مع PO Token مضاف (لو متوفر)
    """
    token = get_po_token()
    if not token:
        return opts
    
    # نجيب الـ extractor_args الموجودين (لو في)
    existing_args = opts.get('extractor_args', {})
    
    # نضيف PO Token للـ YouTube args
    yt_args = dict(existing_args.get('youtube', {}))
    yt_args['po_token'] = [f'web+{token}']
    
    # ندمج مع الـ args الموجودين
    new_args = dict(existing_args)
    new_args['youtube'] = yt_args
    
    opts = dict(opts)  # نسخة جديدة عشان مش نعدل الأصلية
    opts['extractor_args'] = new_args
    
    logger.info(f"🔑 PO Token: Added to yt-dlp options")
    return opts


# ═══════════════════════════════════════
# التهيئة عند الاستيراد
# ═══════════════════════════════════════

try:
    init_po_token()
except Exception as e:
    logger.debug(f"🔑 PO Token: Init error (non-critical): {e}")
