"""
إعدادات البوت - Bot Configuration
═══════════════════════════════════════
يتم قراءة جميع البيانات الحساسة من متغيرات البيئة (GitHub Secrets / Railway Env)

⚠️ تم تقسيم الملف ده لـ package منفصل:
- config/telegram.py     → إعدادات تيليجرام والهوية والجدولة
- config/ai_providers.py → مزودين AI ومسارات النماذج والـ timeouts
- config/features.py     → الميزات والأخبار والتحميل والتخزين

الملفات الخارجية بتستورد من هنا عادي:
    from config import BOT_TOKEN, CHAT_MODELS, NEWS_FETCH_HOURS
"""

# Re-export everything from sub-modules for backward compatibility
from config.telegram import *  # noqa: F401,F403
from config.ai_providers import *  # noqa: F401,F403
from config.features import *  # noqa: F401,F403
