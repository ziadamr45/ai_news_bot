"""
Keyboard builder functions for the Telegram bot.
All inline and reply keyboard markup constructors.
"""

from telegram import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup


def get_main_keyboard(language: str = "ar") -> ReplyKeyboardMarkup:
    """لوحة مفاتيح محسنة مع كل المزايا"""
    if language == "ar":
        keyboard = [
            ["🤖 اسأل My Bro", "📰 الأخبار"],
            ["📄 تحليل ملف", "🎬 ملخص يوتيوب"],
            ["🎨 إنشاء صورة", "🖌️ عدّل صورة"],
            ["📥 تحميل فيديو", "🔍 بحث الويب"],
            ["📚 وضع الدراسة", "🧠 ذاكرتي"],
            ["⚙️ الإعدادات", "📋 الخطة و حدود الإستخدام"],
        ]
    else:
        keyboard = [
            ["🤖 Ask My Bro", "📰 News"],
            ["📄 Analyze File", "🎬 YouTube Summary"],
            ["🎨 Create Image", "🖌️ Edit Image"],
            ["📥 Download Video", "🔍 Web Search"],
            ["📚 Study Mode", "🧠 My Memory"],
            ["⚙️ Settings", "📋 Plan & Usage"],
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_news_inline_buttons(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار رسالة الأخبار - زرار التريندات بس عشان المستخدم ينتقل للأترند"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("📈 التريندات", callback_data="cmd_trending"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📈 Trending", callback_data="cmd_trending"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_trending_inline_buttons(language: str = "ar", trends: list = None) -> InlineKeyboardMarkup:
    """أزرار رسالة الترندات - أزرار مرقمة لكل ترند عشان المستخدم يدوس ويجيب تفاصيله
    
    🔴 FIX: شيلنا زرار التريندات من رسالة التريندات نفسها لأن المستخدم أصلاً في التريندات!
    بدل كده حطينا أزرار مرقمة لكل ترند عشان المستخدم يدوس على الرقم ويجيب أخبار/تفاصيل الترند ده
    
    trends: list of (keyword, count) tuples
    """
    if not trends:
        # لو مفيش ترندات، نرجع كيبورد فاضي
        return InlineKeyboardMarkup([])
    
    keyboard = []
    # بنبنى صفوف - كل صف فيه 3 أزرار كحد أقصى عشان متكبرش
    row = []
    for i, (keyword, count) in enumerate(trends[:10]):
        # الزرار بيه الرقم والكلمة المفتاحية
        btn_text = f"{i+1}"
        # نجيب الكلمة الأولانية من الكلمة المفتاحية عشان الزرار ميطولش
        short_kw = keyword.split()[0] if len(keyword.split()) > 1 else keyword
        if len(short_kw) > 10:
            short_kw = short_kw[:8] + ".."
        btn_text = f"{i+1}. {short_kw}"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"trend_{i}"))
        
        # كل 3 أزرار ننزل صف جديد
        if len(row) == 3:
            keyboard.append(row)
            row = []
    
    # لو فضلت أزرار في الصف الأخير
    if row:
        keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)


def get_learn_inline_buttons(language: str = "ar") -> InlineKeyboardMarkup:
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("📚 تعلم المزيد", callback_data="cmd_learn"),
                InlineKeyboardButton("🗺️ Roadmap", callback_data="cmd_roadmap"),
            ],
            [
                InlineKeyboardButton("🤖 اسأل My Bro", callback_data="cmd_ask"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📚 Learn More", callback_data="cmd_learn"),
                InlineKeyboardButton("🗺️ Roadmap", callback_data="cmd_roadmap"),
            ],
            [
                InlineKeyboardButton("🤖 Ask My Bro", callback_data="cmd_ask"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_pdf_inline_buttons(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار تفاعلية بعد تحليل PDF"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("📄 تلخيص", callback_data="pdf_summarize"),
                InlineKeyboardButton("📌 نقاط رئيسية", callback_data="pdf_keypoints"),
            ],
            [
                InlineKeyboardButton("📝 كويز", callback_data="pdf_quiz"),
                InlineKeyboardButton("📒 ملاحظات دراسية", callback_data="pdf_notes"),
            ],
            [
                InlineKeyboardButton("❓ اسأل سؤال", callback_data="pdf_ask"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📄 Summarize", callback_data="pdf_summarize"),
                InlineKeyboardButton("📌 Key Points", callback_data="pdf_keypoints"),
            ],
            [
                InlineKeyboardButton("📝 Quiz", callback_data="pdf_quiz"),
                InlineKeyboardButton("📒 Study Notes", callback_data="pdf_notes"),
            ],
            [
                InlineKeyboardButton("❓ Ask Question", callback_data="pdf_ask"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_youtube_inline_buttons(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار تفاعلية بعد تحليل YouTube"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("📄 ملخص", callback_data="yt_summary"),
                InlineKeyboardButton("📌 نقاط رئيسية", callback_data="yt_keypoints"),
            ],
            [
                InlineKeyboardButton("📝 كويز", callback_data="yt_quiz"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📄 Summary", callback_data="yt_summary"),
                InlineKeyboardButton("📌 Key Points", callback_data="yt_keypoints"),
            ],
            [
                InlineKeyboardButton("📝 Quiz", callback_data="yt_quiz"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_image_inline_buttons(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار تفاعلية بعد تحليل صورة"""
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("🔬 بحث تفصيلي", callback_data="image_detail"),
                InlineKeyboardButton("🖌️ عدّل الصورة", callback_data="image_edit"),
            ],
            [
                InlineKeyboardButton("🤖 اسأل عن الصورة", callback_data="cmd_ask"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🔬 Detailed Analysis", callback_data="image_detail"),
                InlineKeyboardButton("🖌️ Edit Image", callback_data="image_edit"),
            ],
            [
                InlineKeyboardButton("🤖 Ask about image", callback_data="cmd_ask"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard(language: str = "ar", user_subscribed: bool = False) -> InlineKeyboardMarkup:
    if language == "ar":
        sub_btn_text = "❌ إلغاء اشتراك الأخبار" if user_subscribed else "📬 اشترك في الأخبار"
        sub_btn_data = "settings_unsubscribe" if user_subscribed else "settings_subscribe"
        keyboard = [
            [
                InlineKeyboardButton("🌐 اللغة", callback_data="settings_language"),
                InlineKeyboardButton("⏰ وقت الأخبار", callback_data="settings_time"),
            ],
            [
                InlineKeyboardButton("📡 المصادر", callback_data="settings_sources"),
                InlineKeyboardButton(sub_btn_text, callback_data=sub_btn_data),
            ],
            [
                InlineKeyboardButton("⭐ Premium", callback_data="premium_features"),
            ],
            [
                InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="cmd_start"),
            ],
        ]
    else:
        sub_btn_text = "❌ Unsubscribe News" if user_subscribed else "📬 Subscribe to News"
        sub_btn_data = "settings_unsubscribe" if user_subscribed else "settings_subscribe"
        keyboard = [
            [
                InlineKeyboardButton("🌐 Language", callback_data="settings_language"),
                InlineKeyboardButton("⏰ News Time", callback_data="settings_time"),
            ],
            [
                InlineKeyboardButton("📡 Sources", callback_data="settings_sources"),
                InlineKeyboardButton(sub_btn_text, callback_data=sub_btn_data),
            ],
            [
                InlineKeyboardButton("⭐ Premium", callback_data="premium_features"),
            ],
            [
                InlineKeyboardButton("🔙 Main Menu", callback_data="cmd_start"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_subscribe_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    if language == "ar":
        keyboard = [
            [
                InlineKeyboardButton("✅ اشترك الآن", callback_data="settings_subscribe"),
                InlineKeyboardButton("لا شكراً", callback_data="skip_subscribe"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("✅ Subscribe Now", callback_data="settings_subscribe"),
                InlineKeyboardButton("No Thanks", callback_data="skip_subscribe"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_language_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
            InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_companies_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    """أزرار شركات AI (لسه شغالة مع /company بس مش في الكيبورد الرئيسي)"""
    keyboard = [
        [InlineKeyboardButton("🏢 OpenAI", callback_data="company_openai"), InlineKeyboardButton("🏢 Google", callback_data="company_google")],
        [InlineKeyboardButton("🏢 Anthropic", callback_data="company_anthropic"), InlineKeyboardButton("🏢 Microsoft", callback_data="company_microsoft")],
        [InlineKeyboardButton("🏢 Meta", callback_data="company_meta"), InlineKeyboardButton("🏢 xAI", callback_data="company_xai")],
        [InlineKeyboardButton("🏢 NVIDIA", callback_data="company_nvidia"), InlineKeyboardButton("🏢 DeepMind", callback_data="company_deepmind")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_roadmap_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🤖 AI", callback_data="roadmap_ai"), InlineKeyboardButton("🧠 ML", callback_data="roadmap_machine learning")],
        [InlineKeyboardButton("🔬 Deep Learning", callback_data="roadmap_deep learning"), InlineKeyboardButton("💬 NLP", callback_data="roadmap_nlp")],
        [InlineKeyboardButton("📝 LLM", callback_data="roadmap_llm")],
    ]
    return InlineKeyboardMarkup(keyboard)
