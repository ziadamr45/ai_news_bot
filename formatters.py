"""
تنسيق الرسائل - Message Formatters
رسائل جميلة ومنظمة مع إيموجي وفواصل
"""


def welcome_message(language: str = "ar") -> str:
    """رسالة الترحيب الاحترافية"""
    if language == "ar":
        return """👋 <b>أهلاً بك في My Bro</b>

أنا مساعدك الذكي لمتابعة عالم الذكاء الاصطناعي.

يمكنني مساعدتك في:

📰 أخبار الذكاء الاصطناعي
🤖 الإجابة على الأسئلة
📚 التعلم والتطوير
🔍 البحث عن الأخبار
📈 متابعة التريندات
🏢 متابعة الشركات

اختر من الأزرار بالأسفل أو اكتب سؤالك مباشرة. 💬"""
    else:
        return """👋 <b>Welcome to My Bro</b>

I'm your smart AI assistant for following the AI world.

I can help you with:

📰 AI News
🤖 Answering Questions
📚 Learning & Development
🔍 Searching News
📈 Following Trends
🏢 Company Reports

Choose from buttons below or just type your question. 💬"""


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
