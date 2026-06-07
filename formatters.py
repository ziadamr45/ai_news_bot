"""
تنسيق الرسائل - Message Formatters
رسائل جميلة ومنظمة مع إيموجي وفواصل
"""


def welcome_message(language: str = "ar", user_name: str = "") -> str:
    """رسالة الترحيب الاحترافية"""
    name_part = f" {user_name}" if user_name else ""
    if language == "ar":
        return f"""🤖 <b>أهلاً بك{name_part} في My Bro</b>
━━━━━━━━━━━━━━━━━

مساعدك الذكي لمتابعة عالم الذكاء الاصطناعي 🧠

📰 <b>الأخبار</b> — آخر أخبار AI لحظة بلحظة
🤖 <b>اسألني</b> — أي سؤال وهيكون عندك إجابة
📚 <b>تعلّم</b> — شروحات وخرائط طريق
🔍 <b>ابحث</b> — بحث في الأخبار والويب
📈 <b>التريندات</b> — أكثر المواضيع رواجاً
🏢 <b>الشركات</b> — تقارير عن شركات AI

━━━━━━━━━━━━━━━━━
💡 <i>اختار من الأزرار بالأسفل أو اكتب سؤالك مباشرة!</i>"""
    else:
        return f"""🤖 <b>Welcome{name_part} to My Bro</b>
━━━━━━━━━━━━━━━━━

Your smart AI assistant for the AI world 🧠

📰 <b>News</b> — Latest AI news in real-time
🤖 <b>Ask Me</b> — Any question, answered instantly
📚 <b>Learn</b> — Tutorials & learning roadmaps
🔍 <b>Search</b> — Search news & the web
📈 <b>Trending</b> — Hottest AI topics
🏢 <b>Companies</b> — AI company reports

━━━━━━━━━━━━━━━━━
💡 <i>Choose from buttons below or just type your question!</i>"""


def help_message(language: str = "ar") -> str:
    """رسالة المساعدة"""
    if language == "ar":
        return """🤖 <b>أوامر My Bro</b>
━━━━━━━━━━━━━━━━━

📰 <b>الأخبار</b>
/news — أخبار AI اليوم
/breaking — أهم خبر حالي
/weekly — ملخص الأسبوع
/trending — الترندات الآن

🔍 <b>البحث والاستكشاف</b>
/search &lt;كلمة&gt; — بحث في أخبار AI
/company &lt;اسم&gt; — تقرير عن شركة

💬 <b>المحادثة والتعلم</b>
/ask &lt;سؤال&gt; — سؤال مباشر
/learn &lt;موضوع&gt; — شرح تعليمي
/roadmap &lt;موضوع&gt; — خارطة طريق

📬 <b>الاشتراك في الأخبار</b>
/subscribe — اشترك في الأخبار اليومية
/unsubscribe — إلغاء الاشتراك
/subscribers — عدد المشتركين

⚙️ <b>الإعدادات</b>
/language — تغيير اللغة
/time — تغيير وقت الأخبار
/sources — المصادر المفضلة

🌐 <b>بحث الويب</b>
ابحث عن أي شيء في الويب مباشرة!
مثال: "ابحث عن أحدث أخبار OpenAI"

💡 <b>ملاحظة:</b> ممكن تتكلم معايا بشكل عادي من غير أوامر! أنا ببحث في الويب تلقائياً لو سألت عن شيء يحتاج معلومات حالية 🔍"""
    else:
        return """🤖 <b>My Bro Commands</b>
━━━━━━━━━━━━━━━━━

📰 <b>News</b>
/news — Today's AI news
/breaking — Most important news now
/weekly — Weekly summary
/trending — Trending topics

🔍 <b>Search & Explore</b>
/search &lt;query&gt; — Search AI news
/company &lt;name&gt; — Company report

💬 <b>Chat & Learn</b>
/ask &lt;question&gt; — Direct question
/learn &lt;topic&gt; — Educational explanation
/roadmap &lt;topic&gt; — Learning roadmap

📬 <b>News Subscription</b>
/subscribe — Subscribe to daily news
/unsubscribe — Unsubscribe
/subscribers — Subscriber count

⚙️ <b>Settings</b>
/language — Change language
/time — Change news time
/sources — Preferred sources

💡 <b>Note:</b> You can chat with me naturally without commands! I automatically search the web when you ask about current information 🔍"""


def format_news_item(index: int, title: str, summary: str, url: str, is_top: bool = False) -> str:
    """تنسيق خبر واحد"""
    badge = "🔴" if is_top else "⚪️"
    return f"""{badge} <b>{title}</b>

{summary}

🔗 <a href="{url}">اقرأ المزيد</a>"""


def format_trending_item(index: int, topic: str, explanation: str, count: int = 0) -> str:
    """تنسيق ترند"""
    return f"""{index}. 🔥 <b>{topic}</b>
   {explanation}"""


def format_error(message: str, language: str = "ar") -> str:
    """تنسيق رسالة خطأ"""
    if language == "ar":
        return f"❌ {message}"
    return f"❌ {message}"


def format_loading(language: str = "ar") -> str:
    """رسالة تحميل احترافية"""
    if language == "ar":
        return "⏳ جاري المعالجة...\n 🔴⚪⚪"
    return "⏳ Processing...\n 🔴⚪⚪"


def subscription_prompt(language: str = "ar") -> str:
    """رسالة طلب الاشتراك في الأخبار اليومية"""
    if language == "ar":
        return """📬 <b>اشترك في الأخبار اليومية!</b>
━━━━━━━━━━━━━━━━━

هابعتلك أهم أخبار الذكاء الاصطناعي كل يوم الساعة 9 الصبح بتوقيت القاهرة 🌅

✅ آخر أخبار AI من مصادر عالمية
✅ ملخص بالعربية مفهوم وبسيط
✅ مجاني تماماً

👇 اضغط على الزر بالأسفل عشان تشترك!"""
    else:
        return """📬 <b>Subscribe to Daily News!</b>
━━━━━━━━━━━━━━━━━

I'll send you the most important AI news every day at 9 AM Cairo time 🌅

✅ Latest AI news from global sources
✅ Clear and simple summaries
✅ Completely free

👇 Tap the button below to subscribe!"""


def subscription_confirmed(language: str = "ar") -> str:
    """رسالة تأكيد الاشتراك"""
    if language == "ar":
        return """✅ <b>تم الاشتراك بنجاح!</b>

📬 هابعتلك أخبار AI كل يوم الساعة 9 الصبح
💡 ممكن تلغي الاشتراك أي وقت من ⚙️ الإعدادات"""
    else:
        return """✅ <b>Subscribed successfully!</b>

📬 I'll send you AI news every day at 9 AM
💡 You can unsubscribe anytime from ⚙️ Settings"""


def unsubscription_confirmed(language: str = "ar") -> str:
    """رسالة تأكيد إلغاء الاشتراك"""
    if language == "ar":
        return """❌ <b>تم إلغاء الاشتراك</b>

لن تصلك الأخبار اليومية بعد الآن.
💡 ممكن تشترك تاني أي وقت من ⚙️ الإعدادات"""
    else:
        return """❌ <b>Unsubscribed</b>

You won't receive daily news anymore.
💡 You can re-subscribe anytime from ⚙️ Settings"""


def daily_news_header(language: str = "ar", date_str: str = "") -> str:
    """هيدر الأخبار اليومية المرسلة للمشتركين"""
    if language == "ar":
        return f"""📬 <b>أخبار الذكاء الاصطناعي اليوم</b>
📅 {date_str}

━━━━━━━━━━━━━━━━━

"""
    else:
        return f"""📬 <b>Today's AI News</b>
📅 {date_str}

━━━━━━━━━━━━━━━━━

"""


def daily_news_footer(subscriber_name: str = "", language: str = "ar") -> str:
    """فوتر الأخبار اليومية"""
    if language == "ar":
        return f"""

━━━━━━━━━━━━━━━━━
🤖 <i>My Bro — أخبارك اليومية</i>
💡 ممكن تلغي الاشتراك أي وقت من ⚙️ الإعدادات"""
    else:
        return f"""

━━━━━━━━━━━━━━━━━
🤖 <i>My Bro — Your Daily News</i>
💡 You can unsubscribe anytime from ⚙️ Settings"""


def subscribe_command_message(language: str = "ar") -> str:
    """رسالة أمر الاشتراك"""
    if language == "ar":
        return """📬 <b>الاشتراك في الأخبار اليومية</b>
━━━━━━━━━━━━━━━━━

هابعتلك أهم أخبار الذكاء الاصطناعي كل يوم الساعة 9 الصبح بتوقيت القاهرة 🌅

✅ آخر أخبار AI من مصادر عالمية
✅ ملخص بالعربية مفهوم وبسيط
✅ مجاني تماماً

👇 اضغط على الزر بالأسفل عشان تشترك!"""
    else:
        return """📬 <b>Subscribe to Daily News</b>
━━━━━━━━━━━━━━━━━

I'll send you the most important AI news every day at 9 AM Cairo time 🌅

✅ Latest AI news from global sources
✅ Clear and simple summaries
✅ Completely free

👇 Tap the button below to subscribe!"""


def unsubscribe_command_message(language: str = "ar") -> str:
    """رسالة أمر إلغاء الاشتراك"""
    if language == "ar":
        return """❌ <b>إلغاء اشتراك الأخبار اليومية</b>
━━━━━━━━━━━━━━━━━

هل أنت متأكد إنك عايز تلغي اشتراكك في الأخبار اليومية؟

💡 ممكن تشترك تاني أي وقت."""
    else:
        return """❌ <b>Unsubscribe from Daily News</b>
━━━━━━━━━━━━━━━━━

Are you sure you want to unsubscribe from daily news?

💡 You can re-subscribe anytime."""


def subscribers_info(count: int, language: str = "ar") -> str:
    """معلومات المشتركين"""
    if language == "ar":
        return f"""📊 <b>معلومات المشتركين</b>
━━━━━━━━━━━━━━━━━

📬 عدد المشتركين في الأخبار اليومية: <b>{count}</b>
⏰ موعد الإرسال: 9:00 صباحاً بتوقيت القاهرة
📰 المصادر: {len(__import__('config').RSS_FEEDS)} مصدر RSS عالمي"""
    else:
        return f"""📊 <b>Subscribers Info</b>
━━━━━━━━━━━━━━━━━

📬 Daily news subscribers: <b>{count}</b>
⏰ Send time: 9:00 AM Cairo time
📰 Sources: {len(__import__('config').RSS_FEEDS)} global RSS feeds"""


def language_selection() -> str:
    """رسالة اختيار اللغة"""
    return """🌐 <b>اختر اللغة / Choose Language</b>

1️⃣ العربية
2️⃣ English

أرسل 1 أو 2 / Send 1 or 2"""


def time_selection(current_time: str, language: str = "ar") -> str:
    """رسالة اختيار الوقت"""
    if language == "ar":
        return f"""⏰ <b>تغيير وقت الأخبار</b>

الوقت الحالي: {current_time} (توقيت القاهرة)

أرسل الوقت بالصيغة التالية:
مثال: <code>09:00</code> أو <code>14:30</code>"""
    else:
        return f"""⏰ <b>Change News Time</b>

Current time: {current_time} (Cairo time)

Send the time in this format:
Example: <code>09:00</code> or <code>14:30</code>"""


def sources_selection(language: str = "ar") -> str:
    """رسالة اختيار المصادر"""
    if language == "ar":
        return """📡 <b>المصادر المتاحة</b>

1. OpenAI Blog
2. Google AI Blog
3. TechCrunch AI
4. The Verge AI
5. Ars Technica
6. VentureBeat AI
7. Wired AI

أرسل أرقام المصادر المفضلة
مثال: <code>1 3 5</code>"""
    else:
        return """📡 <b>Available Sources</b>

1. OpenAI Blog
2. Google AI Blog
3. TechCrunch AI
4. The Verge AI
5. Ars Technica
6. VentureBeat AI
7. Wired AI

Send your preferred source numbers
Example: <code>1 3 5</code>"""
