# 🤖 بوت أخبار الذكاء الاصطناعي - AI News Telegram Bot

بوت تيليجرام تلقائي يرسل ملخص يومي لأهم أخبار الذكاء الاصطناعي باللغة العربية.

## المميزات

- 📰 جلب الأخبار من مصادر RSS موثوقة (OpenAI, DeepMind, Anthropic, TechCrunch, Reuters...)
- 🔍 فلترة ذكية للأخبار المرتبطة بالذكاء الاصطناعي فقط
- 📊 نظام تقييم متعدد المعايير لاختيار الأخبار الأهم
- 🌐 تلخيص بالعربية باستخدام Gemini API
- ⏰ تشغيل تلقائي يومياً الساعة 9 صباحاً بتوقيت القاهرة
- 🔄 إعادة محاولة تلقائية عند الفشل
- 🚫 كشف الأخبار المكررة والمكررة

## الهيكل

```
ai-news-bot/
├── main.py              # نقطة البداية الرئيسية
├── news_fetcher.py      # جلب الأخبار من RSS
├── filters.py           # فلترة الأخبار
├── scorer.py            # تقييم وترتيب الأخبار
├── summarizer.py        # تلخيص الأخبار بالعربية (Gemini)
├── telegram_sender.py   # إرسال الرسائل عبر تيليجرام
├── config.py            # الإعدادات والمتغيرات
├── requirements.txt     # المكتبات المطلوبة
├── .env.example         # نموذج متغيرات البيئة
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── daily_news.yml  # GitHub Actions workflow
```

## الإعداد

### 1. إنشاء بوت تيليجرام
1. افتح [@BotFather](https://t.me/BotFather) على تيليجرام
2. أرسل `/newbot` واتبع التعليمات
3. احفظ الـ Token

### 2. الحصول على Chat ID
1. أضف البوت إلى المجموعة أو القناة
2. أرسل رسالة
3. افتح `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. ابحث عن `chat.id`

### 3. الحصول على Gemini API Key
1. اذهب إلى [Google AI Studio](https://makersuite.google.com/app/apikey)
2. أنشئ مفتاح API جديد
3. احفظ المفتاح

### 4. إعداد GitHub Secrets
في صفحة المستودع على GitHub:
1. اذهب إلى **Settings** > **Secrets and variables** > **Actions**
2. أضف الثلاثة أسرار:
   - `BOT_TOKEN` - توكن بوت تيليجرام
   - `CHAT_ID` - معرف المحادثة
   - `GEMINI_API_KEY` - مفتاح Gemini API

## التشغيل

### تلقائي (GitHub Actions)
البوت يعمل تلقائياً كل يوم الساعة 9 صباحاً بتوقيت القاهرة.

### تشغيل يدوي
يمكنك تشغيل البوت يدوياً من صفحة Actions في المستودع.

### تشغيل محلي
```bash
pip install -r requirements.txt
export BOT_TOKEN="your_token"
export CHAT_ID="your_chat_id"
export GEMINI_API_KEY="your_key"
python main.py
```

## نظام التقييم

كل خبر يتم تقييمه بناءً على 4 معايير:

| المعيار | الوزن | الوصف |
|---------|-------|-------|
| صلة بالذكاء الاصطناعي | 35% | عدد وأهمية الكلمات المفتاحية |
| أهمية الخبر | 25% | كلمات تدل على أهمية (breakthrough, launched...) |
| تأثير على الصناعة | 25% | مدى تأثير الخبر على الصناعة |
| مصداقية المصدر | 15% | تصنيف المصدر من 0-10 |

## المصادر

- OpenAI Blog
- Google AI Blog
- Anthropic
- TechCrunch AI
- Reuters AI
- The Verge AI
- Ars Technica
- VentureBeat AI
- Wired AI

## الترخيص

MIT License
