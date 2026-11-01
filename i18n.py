"""
نظام الترجمة المركزي - Centralized Internationalization (i18n) System
يضمن إن كل حاجة في البوت تتبع لغة المستخدم (عربي/إنجليزي)

الاستخدام:
    from i18n import t
    
    # ترجمة بسيطة
    msg = t("workflow.study_waiting", lang)  # → "اكتب المادة أو الموضوع..." أو "Type the subject..."
    
    # ترجمة مع متغيرات
    msg = t("premium.expires_in_days", lang, days=5)  # → "5 يوم (ينتهي...)" أو "5 days (expires...)"
"""


# ═══════════════════════════════════════════════════════════════
# قاموس الترجمة - Translation Dictionary
# كل مفتاح = {"ar": "...", "en": "..."}
# ═══════════════════════════════════════════════════════════════

TRANSLATIONS = {
    # ─── Workflow Manager ───
    "workflow.study_waiting": {
        "ar": "اكتب المادة أو الموضوع الذي تريد دراسته",
        "en": "Type the subject or topic you want to study",
    },
    "workflow.study_active": {
        "ar": "أنت الآن في وضع الدراسة — اكتب سؤالك أو الموضوع",
        "en": "You're now in Study Mode — type your question or topic",
    },
    "workflow.pdf_waiting": {
        "ar": "اكتب سؤالك عن الملف",
        "en": "Type your question about the file",
    },
    "workflow.image_edit_waiting": {
        "ar": "اكتب الوصف اللي عايز تعدّل بيه الصورة",
        "en": "Type the description you want to edit the image with",
    },
    "workflow.search_waiting": {
        "ar": "اكتب كلمة البحث",
        "en": "Type your search query",
    },
    
    # ─── Premium - Time Strings ───
    "premium.expires_in_days": {
        "ar": "{days} يوم (ينتهي {date})",
        "en": "{days} days (expires {date})",
    },
    "premium.less_than_day": {
        "ar": "أقل من يوم ({hours} ساعة — ينتهي {date})",
        "en": "Less than a day ({hours} hours — expires {date})",
    },
    "premium.expiring_soon": {
        "ar": "بينتهي قريب ({date})",
        "en": "Expiring soon ({date})",
    },
    "premium.lifetime": {
        "ar": "مدى الحياة 🔓",
        "en": "Lifetime 🔓",
    },
    "premium.months_and_days": {
        "ar": "{months} شهر و {days} يوم",
        "en": "{months} months and {days} days",
    },
    "premium.days_only": {
        "ar": "{days} يوم",
        "en": "{days} days",
    },
    "premium.years_and_months": {
        "ar": "{years} سنة و {months} شهر",
        "en": "{years} years and {months} months",
    },
    "premium.not_specified": {
        "ar": "مش محدد",
        "en": "Not specified",
    },
    
    # ─── Media Handlers - File Types ───
    "media.file_type_txt": {
        "ar": "نصي",
        "en": "Text",
    },
    "media.file_type_pdf": {
        "ar": "PDF",
        "en": "PDF",
    },
    "media.file_type_docx": {
        "ar": "Word",
        "en": "Word",
    },
    
    # ─── Common Error Messages ───
    "error.general": {
        "ar": "❌ حصل خطأ",
        "en": "❌ Error occurred",
    },
    "error.try_again": {
        "ar": "❌ حصل خطأ. جرب تاني.",
        "en": "❌ Error occurred. Please try again.",
    },
    "error.timeout": {
        "ar": "⏰ انتهت المهلة — حاول تاني",
        "en": "⏰ Operation timed out — please try again",
    },
    "error.admin_only": {
        "ar": "❌ هذا الأمر متاح للمطور فقط.",
        "en": "❌ This command is for the developer only.",
    },
    "error.premium_only": {
        "ar": "⭐ هذه الميزة متاحة للمشتركين Premium فقط",
        "en": "⭐ This feature is available for Premium subscribers only",
    },
    
    # ─── AI Engine - Date Context ───
    "ai.date_context": {
        "ar": "التاريخ الحالي: {date} — الساعة {time}. أنت متصل بالوقت الحقيقي وعارف التاريخ الفعلي. ماتقولش إن معلوماتك قديمة أو إنك متوقف عند تاريخ معين.",
        "en": "Current date: {date} — Time: {time}. You are connected to real-time and know the actual date. Never say your knowledge is outdated or stopped at a certain date.",
    },
    
    # ─── AI Engine - System Prompts ───
    "ai.system_prompt_chat": {
        "ar": "أنت مساعد ذكي اسمك My Bro. تجيب بالعربية الفصحى. كن دقيقًا واستخدم إيموجي مناسبة. كن ودودًا ومفيدًا.",
        "en": "You are a smart assistant named My Bro. Respond in English. Be accurate and use appropriate emojis. Be friendly and helpful.",
    },
    "ai.system_prompt_researcher": {
        "ar": "أنت باحث متخصص. تجيب بالعربية بشكل شامل ومنظم مع مصادر إن أمكن. استخدم إيموجي مناسبة وعناوين واضحة.",
        "en": "You are a specialized researcher. Respond in English comprehensively and organized with sources if possible. Use appropriate emojis and clear headings.",
    },
    
    # ─── Progress Stages ───
    "progress.processing": {
        "ar": "جاري المعالجة",
        "en": "Processing",
    },
    "progress.thinking": {
        "ar": "التفكير",
        "en": "Thinking",
    },
    "progress.error_occurred": {
        "ar": "حدث خطأ",
        "en": "Error occurred",
    },
    
    # ─── Feature Names (for quota messages) ───
    "feature.ai_messages": {
        "ar": "💬 رسائل AI",
        "en": "💬 AI Messages",
    },
    "feature.pdf_analyses": {
        "ar": "📄 تحليلات PDF",
        "en": "📄 PDF Analyses",
    },
    "feature.image_analyses": {
        "ar": "🖼️ تحليلات الصور",
        "en": "🖼️ Image Analyses",
    },
    "feature.youtube_summaries": {
        "ar": "🎬 ملخصات YouTube",
        "en": "🎬 YouTube Summaries",
    },
    "feature.searches": {
        "ar": "🔍 عمليات البحث",
        "en": "🔍 Searches",
    },
    "feature.deep_searches": {
        "ar": "🔬 بحث عميق",
        "en": "🔬 Deep Search",
    },
    "feature.image_generations": {
        "ar": "🎨 إنشاء صور",
        "en": "🎨 Image Generation",
    },
    "feature.image_edits": {
        "ar": "🖌️ تعديل صور",
        "en": "🖌️ Image Editing",
    },
    "feature.downloads": {
        "ar": "📥 تحميل وسائط",
        "en": "📥 Media Downloads",
    },
    "feature.video_searches": {
        "ar": "🎬 فيديو بالبحث",
        "en": "🎬 Video Search",
    },
    "feature.audio_searches": {
        "ar": "🎵 صوت بالبحث",
        "en": "🎵 Audio Search",
    },
    "feature.photo_searches": {
        "ar": "🖼️ بحث صور",
        "en": "🖼️ Photo Search",
    },
    "feature.study_mode": {
        "ar": "📚 وضع الدراسة",
        "en": "📚 Study Mode",
    },
    
    # ─── Quota Messages ───
    "quota.limit_reached": {
        "ar": "خلصت حد الرسائل اليوم ({limit} رسالة). هيرجع بكرة!",
        "en": "You've reached the daily message limit ({limit} messages). Resets tomorrow!",
    },
    "quota.resets_tomorrow": {
        "ar": "💡 الحد بيرجع تاني بكرة!",
        "en": "💡 Limits reset tomorrow!",
    },
    "quota.upgrade_premium": {
        "ar": "⭐ ترقية لـ Premium عشان استخدام غير محدود!",
        "en": "⭐ Upgrade to Premium for unlimited usage!",
    },
    "quota.contact_dev": {
        "ar": "📩 تواصل مع المطور: @ziadamr",
        "en": "📩 Contact developer: @ziadamr",
    },
    "quota.premium_only": {
        "ar": "❌ بريميوم",
        "en": "❌ Premium",
    },
    
    # ─── Subscription Messages ───
    "sub.admin_notice": {
        "ar": "👑 أنت الأدمن — كل حاجة مفتوحة ليك!",
        "en": "👑 You're the admin — everything is open for you!",
    },
    "sub.premium_notice": {
        "ar": "⭐ أنت مشترك Premium — استمتع بكل المزايا!",
        "en": "⭐ You're a Premium subscriber — enjoy all features!",
    },
    "sub.subscribe_hint": {
        "ar": "💡 ممكن تشترك في الأخبار اليومية من ⚙️ الإعدادات",
        "en": "💡 You can subscribe to daily news from ⚙️ Settings",
    },
    
    # ─── WhatsApp Menu ───
    "wa.menu_choose_feature": {
        "ar": "اختار من الميزات:",
        "en": "Choose a feature:",
    },
    "wa.menu_features": {
        "ar": "📋 الميزات",
        "en": "📋 Features",
    },
    "wa.menu_main_features": {
        "ar": "🤖 الميزات الرئيسية",
        "en": "🤖 Main Features",
    },
    "wa.menu_chat": {
        "ar": "🤖 المحادثة",
        "en": "🤖 Chat",
    },
    "wa.menu_chat_desc": {
        "ar": "تحدث مع AI",
        "en": "Talk with AI",
    },
    "wa.menu_news": {
        "ar": "📰 الأخبار",
        "en": "📰 News",
    },
    "wa.menu_news_desc": {
        "ar": "أخبار AI لحظة بلحظة",
        "en": "Real-time AI news",
    },
    "wa.menu_download": {
        "ar": "📥 تحميل فيديو",
        "en": "📥 Download",
    },
    "wa.menu_download_desc": {
        "ar": "تحميل من يوتيوب وتيك توك",
        "en": "Download from YouTube & TikTok",
    },
    "wa.menu_video_search": {
        "ar": "🎬 فيديو بالبحث",
        "en": "🎬 Video Search",
    },
    "wa.menu_video_search_desc": {
        "ar": "ابحث Dailymotion وحمّل فيديو",
        "en": "Search Dailymotion & download",
    },
    "wa.menu_audio_search": {
        "ar": "🎵 صوت بالبحث",
        "en": "🎵 Audio Search",
    },
    "wa.menu_audio_search_desc": {
        "ar": "ابحث وحمّل صوت",
        "en": "Search & download audio",
    },
    "wa.menu_photo_search": {
        "ar": "🖼️ بحث صور",
        "en": "🖼️ Photo Search",
    },
    "wa.menu_photo_search_desc": {
        "ar": "ابحث عن صور",
        "en": "Search for images",
    },
    "wa.menu_web_search": {
        "ar": "🔍 بحث الويب",
        "en": "🔍 Web Search",
    },
    "wa.menu_web_search_desc": {
        "ar": "ابحث في الإنترنت",
        "en": "Search the internet",
    },
    "wa.menu_learning": {
        "ar": "📚 التعلم والدراسة",
        "en": "📚 Learning & Study",
    },
    "wa.menu_study": {
        "ar": "📚 وضع الدراسة",
        "en": "📚 Study Mode",
    },
    "wa.menu_study_desc": {
        "ar": "ادرس واختبر نفسك",
        "en": "Study and test yourself",
    },
    "wa.menu_memory": {
        "ar": "🧠 ذاكرتي",
        "en": "🧠 My Memory",
    },
    "wa.menu_memory_desc": {
        "ar": "عرض وإدارة الذاكرة",
        "en": "View & manage memory",
    },
    "wa.menu_media": {
        "ar": "🎨 الوسائط والصور ⭐",
        "en": "🎨 Media & Images ⭐",
    },
    "wa.menu_image_gen": {
        "ar": "🎨 إنشاء صورة",
        "en": "🎨 Generate Image",
    },
    "wa.menu_image_gen_desc": {
        "ar": "Premium — صور من وصف",
        "en": "Premium — images from description",
    },
    "wa.menu_image_edit": {
        "ar": "🖌️ تعديل صورة",
        "en": "🖌️ Edit Image",
    },
    "wa.menu_image_edit_desc": {
        "ar": "Premium — عدّل صورة بالوصف",
        "en": "Premium — edit image with text",
    },
    "wa.menu_documents": {
        "ar": "📄 المستندات واليوتيوب",
        "en": "📄 Documents & YouTube",
    },
    "wa.menu_youtube_summary": {
        "ar": "📺 ملخص يوتيوب",
        "en": "📺 YouTube Summary",
    },
    "wa.menu_youtube_summary_desc": {
        "ar": "ملخص فيديو يوتيوب",
        "en": "Summarize YouTube video",
    },
    "wa.menu_pdf": {
        "ar": "📄 تحليل PDF",
        "en": "📄 PDF Analysis",
    },
    "wa.menu_pdf_desc": {
        "ar": "ابعت PDF واسأل عنه",
        "en": "Send PDF and ask about it",
    },
    "wa.menu_settings_section": {
        "ar": "⚙️ الإعدادات",
        "en": "⚙️ Settings",
    },
    "wa.menu_settings": {
        "ar": "⚙️ الإعدادات",
        "en": "⚙️ Settings",
    },
    "wa.menu_settings_desc": {
        "ar": "تغيير اللغة والإشعارات",
        "en": "Change language & notifications",
    },
    "wa.menu_plan": {
        "ar": "📋 الخطة وحدودي",
        "en": "📋 Plan & Limits",
    },
    "wa.menu_plan_desc": {
        "ar": "عرض خطتك واستخدامك",
        "en": "View your plan & usage",
    },
    "wa.menu_footer": {
        "ar": "v9.20 — مساعدك الذكي",
        "en": "v9.20 — Your AI Assistant",
    },
    "wa.menu_admin": {
        "ar": "👑 أدمن",
        "en": "👑 Admin",
    },
    "wa.menu_admin_desc": {
        "ar": "لوحة تحكم الأدمن",
        "en": "Admin control panel",
    },
    
    # ─── Welcome Back Messages ───
    "welcome.back": {
        "ar": "أهلًا تاني يا {name}! 👋\n\nأنا فاكرك طبعًا — اختار اللي عايزه من الأزرار أو اكتبلي أي حاجة! 🤖",
        "en": "Welcome back {name}! 👋\n\nI remember you — choose from the buttons or just type anything! 🤖",
    },
    
    # ─── AI Handler Prompts ───
    "ai.ask_no_question": {
        "ar": "🤖 <b>اسأل My Bro</b>\n\nاكتب سؤالك مباشرة أو بعد الأمر\nمثال: <code>/ask ما هي علوم القرآن؟</code>\n\n💡 يمكنك أيضًا الكتابة مباشرة بدون أوامر وسأفهمك!",
        "en": "🤖 <b>Ask My Bro</b>\n\nType your question directly or after the command\nExample: <code>/ask What are the sciences of the Quran?</code>\n\n💡 You can also just type naturally without commands!",
    },
    "ai.learn_no_topic": {
        "ar": "📚 <b>تعلم الذكاء الاصطناعي</b>\n\nاكتب الموضوع بعد الأمر\nمثال: <code>/learn الفقه الإسلامي</code>\n\n💡 أو اختر من خرائط الطريق بالأسفل",
        "en": "📚 <b>Learn AI</b>\n\nType the topic after the command\nExample: <code>/learn Islamic jurisprudence</code>\n\n💡 Or choose from roadmaps below",
    },
    "ai.roadmap_no_topic": {
        "ar": "🗺️ <b>خرائط طريق التعلم</b>\n\nاختر خارطة طريق من الأزرار بالأسفل",
        "en": "🗺️ <b>Learning Roadmaps</b>\n\nChoose a roadmap from buttons below",
    },
    "ai.deepsearch_no_query": {
        "ar": "🔬 <b>البحث العميق</b>\n\nاكتب ما تريد البحث عنه بعمق\nمثال: <code>/deepsearch تاريخ الحضارة الإسلامية</code>\n\n💡 البحث العميق بيستخدم نماذج أقوى وبيبحث في أكتر من مصدر.\n⭐ متاح للمشتركين Premium فقط.",
        "en": "🔬 <b>Deep Search</b>\n\nType what you want to search in depth\nExample: <code>/deepsearch history of Islamic civilization</code>\n\n💡 Deep search uses more powerful models and searches multiple sources.\n⭐ Premium only feature.",
    },
    "ai.company_no_name": {
        "ar": "🏢 <b>تقارير شركات الذكاء الاصطناعي</b>\n\nاختر شركة من الأزرار بالأسفل أو اكتب اسمها بعد الأمر",
        "en": "🏢 <b>AI Company Reports</b>\n\nChoose a company from buttons below or type its name after the command",
    },
    
    # ─── Progress Titles ───
    "progress.title_thinking": {
        "ar": "التفكير",
        "en": "Thinking",
    },
    "progress.title_learning": {
        "ar": "تعلم: {topic}",
        "en": "Learning: {topic}",
    },
    "progress.title_roadmap": {
        "ar": "خارطة طريق: {topic}",
        "en": "Roadmap: {topic}",
    },
    "progress.title_deep_search": {
        "ar": "بحث عميق: {query}",
        "en": "Deep Search: {query}",
    },
    "progress.title_company": {
        "ar": "تقرير: {name}",
        "en": "Report: {name}",
    },
    "progress.title_youtube": {
        "ar": "تلخيص فيديو YouTube",
        "en": "Summarizing YouTube video",
    },
    
    # ─── Callback Error Messages ───
    "callback.pdf_context_lost": {
        "ar": "❌ لم أعد أملك سياق الملف. ارفع الملف مرة أخرى.",
        "en": "❌ I no longer have the file context. Please upload the file again.",
    },
    "callback.yt_context_lost": {
        "ar": "❌ لم أعد أملك سياق الفيديو. ابعث الرابط مرة أخرى.",
        "en": "❌ I no longer have the video context. Please send the link again.",
    },
    "callback.summarize_error": {
        "ar": "❌ حصل خطأ في التلخيص. جرب تاني.",
        "en": "❌ Error in summarization. Please try again.",
    },
    "callback.keypoints_error": {
        "ar": "❌ حصل خطأ. جرب تاني.",
        "en": "❌ Error occurred. Please try again.",
    },
    "callback.quiz_error": {
        "ar": "❌ حصل خطأ في إنشاء الكويز. جرب تاني.",
        "en": "❌ Error creating quiz. Please try again.",
    },
    "callback.notes_error": {
        "ar": "❌ حصل خطأ في إنشاء الملاحظات. جرب تاني.",
        "en": "❌ Error creating notes. Please try again.",
    },
    "callback.pdf_ask_prompt": {
        "ar": "❓ اكتب سؤالك عن الملف وأنا هجاوبك بناءً على محتواه!",
        "en": "❓ Type your question about the file and I'll answer based on its content!",
    },
    "callback.yt_no_transcript": {
        "ar": "❌ مش قادر أجيب نص الفيديو لاستخراج النقاط.",
        "en": "❌ Can't get video transcript for key points.",
    },
    "callback.deep_search_timeout": {
        "ar": "انتهت مهلة البحث العميق — حاول تاني",
        "en": "Deep search timed out — please try again",
    },
    "callback.deep_search_error": {
        "ar": "حدث خطأ في البحث العميق",
        "en": "Deep search error",
    },
    
    # ─── Media Handler Messages ───
    "media.pdf_instructions": {
        "ar": "📄 <b>تحليل ملفات PDF</b>\n\nارفع ملف PDF مباشرة في المحادثة وهحللوله!\n\n💡 <b>اللي هعمله:</b>\n• تلخيص المحتوى\n• استخراج النقاط الرئيسية\n• إنشاء كويز من المحتوى\n• ملاحظات دراسية\n• الإجابة على أسئلتك\n\n⭐ الحد المجاني: 2 ملفات في اليوم",
        "en": "📄 <b>PDF File Analysis</b>\n\nUpload a PDF file directly in chat and I'll analyze it!\n\n💡 <b>What I can do:</b>\n• Summarize the content\n• Extract key points\n• Create quizzes from content\n• Study notes\n• Answer your questions\n\n⭐ Free limit: 2 files per day",
    },
    "media.youtube_no_url": {
        "ar": "🎬 <b>ملخص فيديو YouTube</b>\n\nاستخدم الأمر /youtube متبوعًا برابط الفيديو\nمثال: <code>/youtube https://youtube.com/watch?v=...</code>",
        "en": "🎬 <b>YouTube Video Summary</b>\n\nUse /youtube followed by the video link\nExample: <code>/youtube https://youtube.com/watch?v=...</code>",
    },
    "media.file_too_large": {
        "ar": "❌ حجم الملف كبير جدًا! الحد الأقصى {max_size}MB",
        "en": "❌ File too large! Maximum size is {max_size}MB",
    },
    "media.file_unsupported": {
        "ar": "❌ نوع الملف مش مدعوم حاليًا. الأنواع المدعومة: PDF, DOCX, TXT",
        "en": "❌ File type is not supported yet. Supported: PDF, DOCX, TXT",
    },
    "media.download_timeout": {
        "ar": "❌ انتهى وقت تحميل الملف. جرب تاني.",
        "en": "❌ File download timed out. Please try again.",
    },
    "media.download_failed": {
        "ar": "❌ فشل تحميل الملف. جرب تاني.",
        "en": "❌ Failed to download file. Please try again.",
    },
    "media.extraction_timeout": {
        "ar": "❌ استخراج النص اخد وقت طويل. جرب ملف أصغر.",
        "en": "❌ Text extraction took too long. Try a smaller file.",
    },
    "media.no_text_extracted": {
        "ar": "❌ لم أتمكن من استخراج النص من الملف. ممكن يكون ملف ممسوح أو مش نصي.",
        "en": "❌ Couldn't extract text from the file. It might be scanned or non-text.",
    },
    "media.video_error": {
        "ar": "حدث خطأ في تلخيص الفيديو",
        "en": "Error summarizing video",
    },
    
    # ─── Search Results ───
    "search.untitled": {
        "ar": "بدون عنوان",
        "en": "Untitled",
    },
    
    # ─── WhatsApp Unsubscribe ───
    "wa.unsubscribe_success": {
        "ar": "❌ تم إلغاء الاشتراك.\n\nلو عايز تشترك تاني ابعت: اشترك",
        "en": "❌ Unsubscribed successfully.\n\nTo subscribe again, send: subscribe",
    },
    "wa.unsubscribe_error": {
        "ar": "❌ تم إلغاء الاشتراك.",
        "en": "❌ Unsubscribed.",
    },
}


# ═══════════════════════════════════════════════════════════════
# دالة الترجمة - Translation Function
# ═══════════════════════════════════════════════════════════════

def t(key: str, lang: str = "ar", **kwargs) -> str:
    """
    ترجمة مفتاح حسب اللغة مع دعم المتغيرات
    
    Args:
        key: مفتاح الترجمة (مثل "workflow.study_waiting")
        lang: اللغة ("ar" أو "en")
        **kwargs: متغيرات لاستبدالها في النص (مثل days=5, name="Ahmed")
    
    Returns:
        النص المترجم مع المتغيرات المستبدلة
        
    Example:
        t("premium.expires_in_days", "ar", days=5, date="2025-01-01")
        → "5 يوم (ينتهي 2025-01-01)"
        
        t("premium.expires_in_days", "en", days=5, date="2025-01-01")
        → "5 days (expires 2025-01-01)"
    """
    entry = TRANSLATIONS.get(key)
    
    if not entry:
        # لو المفتاح مش موجود، نرجعه زي ما هو
        return key
    
    # نختار اللغة، لو مش موجودة نرجع العربية
    text = entry.get(lang, entry.get("ar", key))
    
    # استبدال المتغيرات
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass  # لو في متغير ناقص، نرجع النص زي ما هو
    
    return text


def get_language_direction(lang: str) -> str:
    """اتجاه النص حسب اللغة"""
    return "rtl" if lang == "ar" else "ltr"


def get_language_name(lang: str, display_lang: str = None) -> str:
    """اسم اللغة باللغة المطلوبة"""
    if display_lang is None:
        display_lang = lang
    if display_lang == "ar":
        return "العربية" if lang == "ar" else "الإنجليزية"
    else:
        return "Arabic" if lang == "ar" else "English"


# ═══════════════════════════════════════════════════════════════
# أيام وشهور عربية - Arabic Day/Month Names (shared)
# ═══════════════════════════════════════════════════════════════

DAYS_AR = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS_AR = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def format_date_ar(now=None) -> str:
    """تنسيق التاريخ بالعربية"""
    from datetime import datetime
    if now is None:
        now = datetime.now()
    return f"{DAYS_AR[now.weekday()]}, {now.day} {MONTHS_AR[now.month]} {now.year}"


def format_date_en(now=None) -> str:
    """تنسيق التاريخ بالإنجليزية"""
    from datetime import datetime
    if now is None:
        now = datetime.now()
    return now.strftime("%A, %B %d, %Y")
