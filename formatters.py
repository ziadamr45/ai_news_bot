"""
تنسيق الرسائل - Message Formatters
رسائل جميلة ومنظمة مع إيموجي وفواصل
"""

import re


def clean_ai_response(text: str) -> str:
    """
    تنظيف رد AI من رموز Markdown الزيادة
    البوت بيستخدم HTML في تيليجرام، فـ Markdown بيبان كرموز غريبة
    بنحول الـ Markdown لـ HTML أو بنشيله لو مش محتاجينه
    + معالجة الكلام اللي بيلزق في بعضه بسبب إزالة الرموز
    """
    if not text:
        return text

    # 1. تحويل ```code block``` لـ <code>code</code> (الأول عشان ده الأطول)
    text = re.sub(r'```\w*\n?(.*?)```', r'<code>\1</code>', text, flags=re.DOTALL)

    # 2. تحويل **text** أو __text__ لـ <b>text</b> (bold)
    # مهم: نحط مسافة قبل وبعد الـ tag عشان الكلام ميلزقش
    text = re.sub(r'(?<=\s)\*\*(.+?)\*\*(?=\s)', r' <b>\1</b> ', text)
    text = re.sub(r'(?<=\s)\*\*(.+?)\*\*$', r' <b>\1</b>', text)
    text = re.sub(r'^\*\*(.+?)\*\*(?=\s)', r'<b>\1</b> ', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 3. تحويل *text* لـ <i>text</i> (italic) - بس لو مش جوا tag
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)

    # 4. تحويل _text_ لـ <i>text</i> (italic) - لو مش جوا كلمة
    text = re.sub(r'(?<!\w)_(?!_)(.+?)(<!_)_(?!\w)', r'<i>\1</i>', text)

    # 5. تحويل ~~text~~ لـ <s>text</s> (strikethrough)
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 6. تحويل `code` لـ <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # 7. شيل ### و ## و # (عناوين Markdown) - نحط سطر جديد بعدهم
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\n<b>\1</b>\n', text, flags=re.MULTILINE)

    # 8. شيل --- أو *** أو ___ (خطوط أفقية) - نحط سطر فاضي بدالها
    text = re.sub(r'^[-*_]{3,}\s*$', '\n', text, flags=re.MULTILINE)

    # 9. معالجة الجداول (pipe |) - نحولها لأسطر عادية
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # لو السطر فيه أكتر من 2 | يبقى ممكن يكون جدول
        if line.count('|') >= 2:
            # نشيل | من البداية والنهاية ونحول | لـ فاصلة
            line = line.strip('|')
            line = re.sub(r'\s*\|\s*', ' — ', line)
            # لو السطر ده فاصل بتاع جدول (---) نشيله
            if re.match(r'^[\s\-—:]+$', line):
                continue
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)

    # 10. شيل - في بداية السطور (bullet points) واستبدله بـ •
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. شيل > في بداية السطور (quotes)
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)

    # 12. شيل أي * متبقية لوحدها (مش جوا tag)
    # هنا المشكلة الأساسية: لو شلنا * من غير ما نحط مسافة مكانها، الكلام بيلزق
    # الحل: نحط مسافة مكان كل * بره الـ HTML tags
    result = []
    in_tag = False
    prev_was_star = False
    for i, char in enumerate(text):
        if char == '<':
            in_tag = True
            result.append(char)
        elif char == '>':
            in_tag = False
            result.append(char)
        elif char == '*' and not in_tag:
            # لو الـ * بين كلمتين (قبلها حرف وبعدها حرف) نحط مساحة
            if i > 0 and i < len(text) - 1:
                prev_char = text[i-1] if result else ''
                next_char = text[i+1] if i+1 < len(text) else ''
                # لو الحرف قبل وبعد مش مسافة، نحط مساحة عشان الكلام ميلزقش
                if prev_char not in (' ', '\n', '') and next_char not in (' ', '\n', ''):
                    result.append(' ')
                elif prev_char not in (' ', '\n', '') or next_char not in (' ', '\n', ''):
                    result.append(' ')
            # بس نشيل الـ * نفسها
            prev_was_star = True
        elif char == '|' and not in_tag:
            continue  # شيل أي | متبقي
        else:
            result.append(char)
            prev_was_star = False
    text = ''.join(result)

    # 13. فصل الكلمات العربية الملتصقة بالـ HTML tags
    # مثال: "كلمة<b>عريضة</b>كلمة" ← "كلمة <b>عريضة</b> كلمة"
    # قبل الـ opening tags
    text = re.sub(r'([^\s<>])(<b>|<i>|<code>|<s>)', r'\1 \2', text)
    # بعد الـ closing tags
    text = re.sub(r'(</b>|</i>|</code>|</s>)([^\s<>])', r'\1 \2', text)

    # 13b. فصل الكلمات الملتصقة بالـ HTML بشكل أوسع
    # أي حرف مش whitespace قبل < مباشرة
    text = re.sub(r'(\S)(<)', r'\1 \2', text)
    # أي > مباشرة بعدة حرف مش whitespace
    text = re.sub(r'(>)(\S)', r'\1 \2', text)

    # 14. تأكد إن كل نقطة/قائمة بعدها سطر جديد
    text = re.sub(r'(• [^\n]+)(?=[^\n•])', r'\1\n', text)

    # 14b. فصل النقاط بسطر فاضي
    text = re.sub(r'(• [^\n]+)\n(• )', r'\1\n\n\2', text)

    # 15. شيل مسافات زيادة في نهاية السطور
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)

    # 16. شيل أسطر فاضية متكررة (أكتر من 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 17. شيل مسافات مزدوجة جوا السطر (من الإصلاحات فوق)
    text = re.sub(r' {3,}', ' ', text)

    return text.strip()


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

🧠 <b>الذاكرة والمفضلات</b>
/memory — ذاكرتي عنك
/progress — تقدمك في التعلم
/favorite — احفظ آخر شيء في المفضلة
/favorites — المفضلات
/forget &lt;كلمة&gt; — امسح ذكرى محددة
/resetmemory — امسح كل الذكريات

⚙️ <b>الإعدادات</b>
/language — تغيير اللغة
/time — تغيير وقت الأخبار
/sources — المصادر المفضلة
/about — عن البوت والمؤسس

🌐 <b>بحث الويب</b>
ابحث عن أي شيء في الويب مباشرة!
مثال: "ابحث عن أحدث أخبار OpenAI"

💡 <b>ملاحظة:</b> ممكن تتكلم معايا بشكل عادي من غير أوامر! أنا ببحث في الويب تلقائياً لو سألت عن شيء يحتاج معلومات حالية 🔍
💡 <b>أنا بفتكر:</b> اهتماماتك، مواضيع تعلمتها، وشركات تتابعها تلقائياً!"""
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

🧠 <b>Memory & Favorites</b>
/memory — My memory about you
/progress — Your learning progress
/favorite — Save last item to favorites
/favorites — View favorites
/forget &lt;keyword&gt; — Delete specific memory
/resetmemory — Delete all memories

⚙️ <b>Settings</b>
/language — Change language
/time — Change news time
/sources — Preferred sources
/about — About the bot & creator

💡 <b>Note:</b> You can chat with me naturally without commands! I automatically search the web when you ask about current information 🔍
💡 <b>I Remember:</b> Your interests, learned topics, and followed companies automatically!"""


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


def about_message(language: str = "ar") -> str:
    """رسالة عن البوت والمؤسس"""
    from config import CREATOR_INFO, BOT_NAME, BOT_VERSION

    if language == "ar":
        tech_list = " • ".join(CREATOR_INFO["tech_stack"][:7])
        projects_text = ""
        for p in CREATOR_INFO.get("projects", [])[:4]:
            projects_text += f"  ▸ {p['name']} — {p['desc']}\n"
        return f"""🤖 <b>عن {BOT_NAME} v{BOT_VERSION}</b>
━━━━━━━━━━━━━━━━━

<b>{BOT_NAME}</b> — مساعدك الذكي الشخصي لمتابعة عالم الذكاء الاصطناعي 🧠

✅ أخبار AI لحظة بلحظة
✅ محادثة ذكية مع AI
✅ بحث في الويب والبحث العميق
✅ شروحات وخرائط طريق
✅ تقارير شركات AI
✅ بث أخبار يومي مجدول
✅ نظام ذاكرة ذكي بيفكرك
✅ تحليل الصور بالذكاء الاصطناعي
✅ بوت شخصي بيفتكر اهتماماتك

━━━━━━━━━━━━━━━━━

👨‍💻 <b>صانع البوت</b>

<b>{CREATOR_INFO['name_ar']}</b>
{CREATOR_INFO['title_ar']}

{CREATOR_INFO['bio_ar']}

🏢 <b>الشركة:</b> {CREATOR_INFO.get('company_ar', 'Qudra Tech')}

🔗 <b>تواصل معاه:</b>
🌐 الموقع: <a href="{CREATOR_INFO['website']}">ziadamrme.vercel.app</a>
💻 GitHub: <a href="{CREATOR_INFO['github']}">ziadamr45</a>
💼 LinkedIn: <a href="{CREATOR_INFO['linkedin']}">Ziad Amr</a>
📱 Telegram: <a href="{CREATOR_INFO['telegram']}">@ziadamr</a>
🐦 X: <a href="{CREATOR_INFO['twitter']}">@ziad90216</a>
📘 Facebook: <a href="{CREATOR_INFO['facebook']}">Ziad Amr</a>
📸 Instagram: <a href="{CREATOR_INFO['instagram']}">@ziadamr455</a>
🎬 YouTube: <a href="{CREATOR_INFO['youtube']}">الحياة على الطريق</a>
🧵 Threads: <a href="{CREATOR_INFO.get('threads', '#')}">@ziadamr455</a>
📝 DEV: <a href="{CREATOR_INFO.get('devto', '#')}">ziad_amr</a>
📧 Email: {CREATOR_INFO.get('email', '')}

🛠️ <b>التقنيات:</b>
{tech_list}

🚀 <b>من أعماله:</b>
{projects_text}
━━━━━━━━━━━━━━━━━
🤖 <i>اتعمل بحب في مصر 🇪🇬</i>"""
    else:
        tech_list = " • ".join(CREATOR_INFO["tech_stack"][:7])
        projects_text = ""
        for p in CREATOR_INFO.get("projects", [])[:4]:
            projects_text += f"  ▸ {p['name']} — {p['desc']}\n"
        return f"""🤖 <b>About {BOT_NAME} v{BOT_VERSION}</b>
━━━━━━━━━━━━━━━━━

<b>{BOT_NAME}</b> — Your smart personal AI assistant for the AI world 🧠

✅ Real-time AI news
✅ Smart AI chat
✅ Web search & Deep Search
✅ Tutorials & roadmaps
✅ AI company reports
✅ Scheduled daily news
✅ Smart memory system
✅ AI image analysis
✅ Personalized to your interests

━━━━━━━━━━━━━━━━━

👨‍💻 <b>Created by</b>

<b>{CREATOR_INFO['name_en']}</b>
{CREATOR_INFO['title_en']}

{CREATOR_INFO['bio_en']}

🏢 <b>Company:</b> {CREATOR_INFO.get('company_en', 'Qudra Tech')}

🔗 <b>Get in touch:</b>
🌐 Website: <a href="{CREATOR_INFO['website']}">ziadamrme.vercel.app</a>
💻 GitHub: <a href="{CREATOR_INFO['github']}">ziadamr45</a>
💼 LinkedIn: <a href="{CREATOR_INFO['linkedin']}">Ziad Amr</a>
📱 Telegram: <a href="{CREATOR_INFO['telegram']}">@ziadamr</a>
🐦 X: <a href="{CREATOR_INFO['twitter']}">@ziad90216</a>
📘 Facebook: <a href="{CREATOR_INFO['facebook']}">Ziad Amr</a>
📸 Instagram: <a href="{CREATOR_INFO['instagram']}">@ziadamr455</a>
🎬 YouTube: <a href="{CREATOR_INFO['youtube']}">Alhayat Ala Eltareq</a>
🧵 Threads: <a href="{CREATOR_INFO.get('threads', '#')}">@ziadamr455</a>
📝 DEV: <a href="{CREATOR_INFO.get('devto', '#')}">ziad_amr</a>
📧 Email: {CREATOR_INFO.get('email', '')}

🛠️ <b>Tech Stack:</b>
{tech_list}

🚀 <b>Notable Projects:</b>
{projects_text}
━━━━━━━━━━━━━━━━━
🤖 <i>Made with love in Egypt 🇪🇬</i>"""
