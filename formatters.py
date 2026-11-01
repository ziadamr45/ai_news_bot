"""
تنسيق الرسائل - Message Formatters
رسائل جميلة ومنظمة مع إيموجي وفواصل
"""

import re


def _strip_non_telegram_html(text: str) -> str:
    """
    تنظيف HTML غير المدعوم من تليجرام
    
    تليجرام بيدعم بس: b, i, u, s, code, pre, a, spoiler, blockquote, tg-spoiler
    الـ AI بيرجع HTML كامل (div, p, ol, ul, li, h1-h6, span, style...) 
    اللي بيبان كرموز غريبة في الرسالة
    
    الاستراتيجية:
    1. نحول h1-h6 لـ <b> (عناوين)
    2. نحول <li> لـ bullet points (•)
    3. نحول <p> لـ سطر فاضي
    4. نحول <br> و <hr> لـ سطر جديد
    5. نشيل كل الـ tags الباقية (div, span, ol, ul, table, style, etc.)
    6. نشيل الـ style attributes من أي tag
    """
    if not text:
        return text
    
    # 🔴 أولًا: نحول العناوين h1-h6 لـ bold
    text = re.sub(r'<h[1-6][^>]*>', '\n<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '</b>\n', text, flags=re.IGNORECASE)
    
    # 🔴 نحول <li> لـ bullet points
    text = re.sub(r'<li[^>]*>\s*', '\n• ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*</li>', '', text, flags=re.IGNORECASE)
    
    # 🔴 نحول <p> لـ سطر فاضي
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    
    # 🔴 نحول <br> و <br/> لـ سطر جديد
    text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
    
    # 🔴 نحول <hr> لـ خط فاصل
    text = re.sub(r'<hr\s*/?\s*>', '\n━━━━━━━━━━━━━\n', text, flags=re.IGNORECASE)
    
    # 🔴 نحول <tr> لـ سطر جديد (جداول)
    text = re.sub(r'<tr[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '', text, flags=re.IGNORECASE)
    
    # 🔴 نحول <td> و <th> لـ فواصل (جداول)
    text = re.sub(r'<t[dh][^>]*>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'</t[dh]>', ' ', text, flags=re.IGNORECASE)
    
    # 🔴 نحول <strong> لـ <b> و <em> لـ <i> (تليجرام مش بيدعم strong/em)
    text = re.sub(r'<strong[^>]*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'</strong>', '</b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<em[^>]*>', '<i>', text, flags=re.IGNORECASE)
    text = re.sub(r'</em>', '</i>', text, flags=re.IGNORECASE)

    # 🔴 نشيل كل opening/closing tags اللي مش مدعومة من تليجرام
    # القائمة دي كل حاجة مش: b, i, u, s, code, pre, a, spoiler, blockquote, tg-spoiler
    unsupported_tags = (
        'div', 'span', 'section', 'article', 'main', 'header', 'footer', 'nav',
        'ol', 'ul', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody', 'tfoot', 'caption',
        'style', 'script', 'noscript', 'iframe', 'object', 'embed',
        'form', 'input', 'button', 'select', 'option', 'textarea', 'label',
        'img', 'figure', 'figcaption', 'picture', 'svg', 'canvas', 'video', 'audio', 'source',
        'center', 'font', 'big', 'small', 'sub', 'sup', 'mark', 'del', 'ins',
        'abbr', 'cite', 'q', 'address', 'time', 'var', 'samp', 'kbd',
        'details', 'summary', 'dialog', 'menu', 'menuitem',
        'col', 'colgroup', 'fieldset', 'legend', 'optgroup',
        'map', 'area', 'track', 'wbr', 'ruby', 'rt', 'rp',
    )
    
    # نشيل الـ self-closing tags أولًا
    for tag in unsupported_tags:
        text = re.sub(rf'<{tag}[^>]*/\s*>', '', text, flags=re.IGNORECASE)
    
    # نشيل الـ opening tags مع أي attributes
    for tag in unsupported_tags:
        text = re.sub(rf'<{tag}[^>]*>', '', text, flags=re.IGNORECASE)
    
    # نشيل الـ closing tags
    for tag in unsupported_tags:
        text = re.sub(rf'</{tag}>', '', text, flags=re.IGNORECASE)
    
    # 🔴 نشيل style, class, id, وكل event attributes من أي tag متبقي
    # مثال: <b style="..."> ← <b>
    text = re.sub(r'<(b|i|u|s|code|pre|a|spoiler|blockquote|tg-spoiler)\s+[^>]*?>', r'<\1>', text, flags=re.IGNORECASE)
    
    # 🔴 نشيل أي tag متبقي مش في القائمة المدعومة (catch-all)
    # القائمة المسموحة: b, i, u, s, code, pre, a, spoiler, blockquote, tg-spoiler
    # (strong/em تم تحويلها لـ b/i فوق، مش محتاجين نبقيهم)
    allowed_pattern = r'/?((?:b|i|u|s|code|pre|a|spoiler|blockquote|tg-spoiler)(?:\s[^>]*)?)'
    # نشيل أي tag مش في القائمة
    def _clean_unknown_tag(match):
        tag_content = match.group(1)
        tag_name = tag_content.strip().split()[0].rstrip('/')
        allowed_names = {'b', 'i', 'u', 's', 'code', 'pre', 'a', 'spoiler', 'blockquote', 'tg-spoiler'}
        if tag_name.lower() in allowed_names:
            return match.group(0)  # نسيبه زي ما هو
        return ''  # نشيله
    
    text = re.sub(r'<([^>]+)>', _clean_unknown_tag, text)
    
    # 🔴 تنظيف نهائي
    # نشيل الـ bullet points الفاضية
    text = re.sub(r'^\s*•\s*$', '', text, flags=re.MULTILINE)
    
    # نشيل أسطر فاضية متكررة
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # 🔴 إصلاح الـ tags المفتوحة بدون إغلاق — AI بيرجع <b> بدون </b>
    # لو فيه unclosed tags (أكثر opening من closing)، نشيلهم كلهم خالص
    for tag in ('b', 'i', 'u', 's', 'code', 'pre'):
        open_count = len(re.findall(rf'<{tag}>', text, re.IGNORECASE))
        close_count = len(re.findall(rf'</{tag}>', text, re.IGNORECASE))
        if open_count > close_count:
            # Unclosed tags — نشيلهم كلهم (opening + closing)
            text = re.sub(rf'</?{tag}>', '', text, flags=re.IGNORECASE)
    
    return text


def clean_ai_response(text: str) -> str:
    """
    تنظيف رد AI من رموز Markdown الزيادة و HTML غير المدعوم
    البوت بيستخدم HTML في تيليجرام، فـ Markdown بيبان كرموز غريبة
    بنحول الـ Markdown لـ HTML أو بنشيله لو مش محتاجينه
    + معالجة الكلام اللي بيلزق في بعضه بسبب إزالة الرموز
    + إصلاح الكلمات المكسورة على سطرين
    + v2: إصلاح تنسيق العربية — أقواس [ ] من روابط Markdown، مسافات أفضل
    + v3: إصلاح شامل للنص العربي المكسور — كل كلمة على سطر لوحدها
    + v4: تنظيف HTML غير مدعوم من تليجرام (div, p, span, ol, ul, li, h1-h6, style, etc.)
    """
    if not text:
        return text

    # ═══ مرحلة -1: تنظيف HTML غير المدعوم من تيليجرام ═══
    # تليجرام بيدعم بس: b, i, u, s, code, pre, a, spoiler, blockquote, tg-spoiler
    # الـ AI بيرجع HTML كامل (div, p, ol, ul, li, h1-h6, span, style...) اللي بيبان كرموز غريبة
    text = _strip_non_telegram_html(text)

    # ═══ مرحلة 0: إصلاح النص العربي المكسور (الأهم!) ═══
    # مشكلة: الـ AI models بترجع نص عربي فيه أسطر جديدة في نص الكلمة
    # مثال: "التقنيا\nt" ← "التقنيات"
    # مثال: "موضو\nع" ← "موضوع"
    # ده بيحصل كتير مع النماذج اللي مش مدربة كويس على العربية
    text = _fix_broken_arabic_text(text)

    # 1. تحويل ```code block``` لـ <code>code</code> (الأول عشان ده الأطول)
    text = re.sub(r'```\w*\n?(.*?)```', r'<code>\1</code>', text, flags=re.DOTALL)

    # 2. تحويل **text** أو __text__ لـ <b>text</b> (bold)
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

    # 7. تحويل روابط Markdown [text](url) لـ HTML links
    # ده كان السبب الرئيسي في ظهور الأقواس [ ] الغريبة!
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7b. شيل روابط مرجعية زي [1] أو [2] اللي بتيجي من النماذج أحيانًا
    text = re.sub(r'\[(\d+)\]\s*', '', text)

    # 7c. شيل أقواس [ ] فاضية أو مليانة حاجات غريبة من النموذج
    # بس نحافظ على الأقواس اللي جواها كلام مفيد (أكتر من حرفين)
    text = re.sub(r'\[([^\]]{0,1})\]', '', text)

    # 8. شيل ### و ## و # (عناوين Markdown) - نحولها لـ bold
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\n<b>\1</b>\n', text, flags=re.MULTILINE)

    # 9. شيل --- أو *** أو ___ (خطوط أفقية)
    text = re.sub(r'^[-*_]{3,}\s*$', '\n', text, flags=re.MULTILINE)

    # ═══ مرحلة 2: تنظيف الرموز الزيادة ═══

    # 10. معالجة الجداول (pipe |) - نحولها لأسطر عادية
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.count('|') >= 2:
            line = line.strip('|')
            line = re.sub(r'\s*\|\s*', ' — ', line)
            if re.match(r'^[\s\-—:]+$', line):
                continue
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)

    # 11. شيل - في بداية السطور (bullet points) واستبدله بـ •
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 12. شيل > في بداية السطور (quotes)
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)

    # 13. شيل أي * متبقية لوحدها (مش جوا tag)
    # 🔴 v2 fix: بنشيل الـ * بس من غير ما نحط مسافات زيادة
    # لأن المسافات الزيادة بتكسر الكلام العربي
    result = []
    in_tag = False
    for i, char in enumerate(text):
        if char == '<':
            in_tag = True
            result.append(char)
        elif char == '>':
            in_tag = False
            result.append(char)
        elif char == '*' and not in_tag:
            # لو الـ * بين حرفين (مش مسافة) نحط مسافة واحدة بس
            if i > 0 and i < len(text) - 1:
                prev_char = text[i-1]
                next_char = text[i+1]
                # لو الحرف قبلها وبعدها مش مسافة — يبقى الكلام ملتصق ونحط مسافة
                if prev_char not in (' ', '\n') and next_char not in (' ', '\n'):
                    result.append(' ')
                # لو بس حرف واحد ملتصق، نحط مسافة واحدة
                elif prev_char not in (' ', '\n') or next_char not in (' ', '\n'):
                    # بس لو بعد المسافة مفيش حرف تاني مش محتاجة
                    if result and result[-1] != ' ':
                        result.append(' ')
            # نشيل الـ * نفسها — مش بنضيفها
        elif char == '|' and not in_tag:
            continue  # شيل أي | متبقي
        else:
            result.append(char)
    text = ''.join(result)

    # ═══ مرحلة 3: فصل النص العربي عن HTML بشكل ذكي ═══

    # 14. فصل الكلمات العربية الملتصقة بالـ HTML tags
    # مثال: "كلمة<b>عريضة</b>كلمة" ← "كلمة <b>عريضة</b> كلمة"
    # 🔴 v2 fix: بنفصل بس بين الحروف (مش بين كل حرف و<) عشان منكسرش الـ HTML
    # قبل opening tags — بس لو قبلها حرف عربي أو إنجليزي أو رقم
    text = re.sub(r'([\u0600-\u06FF\u0041-\u007A\u0030-\u0039])(<(?:b|i|code|s|a)\b)', r'\1 \2', text)
    # بعد closing tags — بس لو بعدها حرف عربي أو إنجليزي أو رقم
    text = re.sub(r'(</(?:b|i|code|s|a)>)([\u0600-\u06FF\u0041-\u007A\u0030-\u0039])', r'\1 \2', text)

    # 15. فصل النقاط بسطر فاضي (بدون الخطوة اللي بتكسر النص)
    text = re.sub(r'(• [^\n]+)\n(• )', r'\1\n\n\2', text)

    # ═══ مرحلة 4: تنظيف نهائي ═══

    # 17. شيل مسافات زيادة في نهاية السطور
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)

    # 18. شيل أسطر فاضية متكررة (أكتر من 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 19. شيل مسافات مزدوجة جوا السطر (من الإصلاحات فوق)
    text = re.sub(r' {3,}', '  ', text)

    # 20. فصل الأرقام عن الكلمات العربية الملتصقة بيها
    text = re.sub(r'([\u0600-\u06FF])(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([\u0600-\u06FF])', r'\1 \2', text)

    # 21. فصل الرموز عن الكلمات العربية
    text = re.sub(r'([\u0600-\u06FF])([🔥✅❌⚠️💡🤖📰🔍📈🏢📚💌📬⚡🧠💌🔗🌐⏰📡🗺️])', r'\1 \2', text)
    text = re.sub(r'([🔥✅❌⚠️💡🤖📰🔍📈🏢📚💌📬⚡🧠💌🔗🌐⏰📡🗺️])([\u0600-\u06FF])', r'\1 \2', text)

    # 22. فصل الحروف الإنجليزية عن الكلمات العربية
    text = re.sub(r'([\u0600-\u06FF])([a-zA-Z])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z])([\u0600-\u06FF])', r'\1 \2', text)

    # 23. إصلاح تنوين الفتح — حط التنوين على الحرف قبل الألف مش على الألف نفسها
    text = re.sub(r'([\u0621-\u063A\u0641-\u064A])اً', r'\1ًا', text)

    # 24. شيل أي أقواس [ ] متبقية لوحدها (من markdown refs)
    # بس لو جواها كلام مفيد (أكتر من 2 حرف) نسيبها
    text = re.sub(r'\[([^\]]{0,2})\](?!\()', '', text)

    return text.strip()


def _fix_broken_arabic_text(text: str) -> str:
    """
    إصلاح النص العربي المكسور — الكلمات اللي متقسمة على سطرين
    
    المشكلة: نماذج AI كتير بترجع نص عربي فيه سطر جديد في نص الكلمة
    مثال: "التقنيا" + سطر جديد + "ت" = "التقنيات"
    
    الحل: لو سطر قصير (1-4 حروف) بيبدأ بحرف عربي
    والسطر اللي فات بيند بحرف عربي (بدون علامة ترقيم)
    نوصلهم بدون مسافة (لأنهم نفس الكلمة)
    """
    if not text or not text.strip():
        return text
    
    ARABIC_CHAR = r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]'
    
    lines = text.split('\n')
    if len(lines) < 2:
        return text
    
    result_lines = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        if not stripped:
            result_lines.append(line)
            continue
        
        # لو السطر قصير جدًا وبيبدأ بحرف عربي والسطر اللي فات بيند بحرف عربي
        # يبقى ده تكملة كلمة — نوصلهم بدون مسافة
        if (i > 0 
            and len(stripped) <= 6
            and stripped
            and re.match(ARABIC_CHAR, stripped[0])
            and result_lines):
            prev_line = result_lines[-1] if result_lines else ""
            prev_stripped = prev_line.rstrip()
            
            if (prev_stripped 
                and re.search(ARABIC_CHAR, prev_stripped[-1])
                and not prev_stripped.endswith(('.', '!', '?', '؟', '،', ':', '؛', ')', ']', '}'))
                and not stripped.startswith(('<', '•', '→'))):
                # توصيل بدون مسافة — نفس الكلمة
                result_lines[-1] = prev_stripped + stripped
                continue
        
        result_lines.append(line)
    
    return '\n'.join(result_lines)


def smart_split_message(text: str, max_length: int = 3900) -> list:
    """
    تقسيم الرسالة الطويلة بشكل ذكي — ميكسرش كلمة ولا HTML tag
    بيدور على أماكن طبيعية للقطع (سطر جديد، مسافة، نهاية جملة)
    وبيتأكد إن كل جزء محترم الـ HTML tags (ميقفلش tag في جزء ويفتحه في جزء تاني)
    + v2: دعم أفضل للنص العربي — القطع عند نهاية جملة عربية
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    # أماكن القطع المفضلة بالترتيب — مضافة نهايات الجمل العربية
    split_markers = ['\n\n', '\n', ' • ', ' — ', ' ', '']

    # 🔴 v2: أماكن قطع إضافية للنص العربي (بعد علامات الترقيم العربية)
    arabic_sentence_ends = ['؟', '،', '؛', '.']
    
    remaining = text
    while len(remaining) > max_length:
        split_pos = -1

        # دور على أحسن مكان للقطع في الـ range المقبول
        search_end = min(max_length, len(remaining))

        for marker in split_markers:
            # دور على آخر مكان للـ marker قبل الـ max_length
            if marker == '':
                # آخر ملجأ — نقص من الحد
                split_pos = max_length
                break

            pos = remaining.rfind(marker, 0, search_end)
            if pos > 0:
                split_pos = pos + len(marker)
                break

        # 🔴 v2: لو مالقيناش مكان مناسب، دور على نهاية جملة عربية
        if split_pos <= 0 or split_pos > max_length:
            for end_char in arabic_sentence_ends:
                # دور على آخر علامة ترقيم عربية قبل الـ max_length
                pos = remaining.rfind(end_char, 0, search_end)
                if pos > 0:
                    split_pos = pos + 1  # بعد علامة الترقيم
                    break

        if split_pos <= 0:
            split_pos = max_length

        chunk = remaining[:split_pos].rstrip()
        remaining = remaining[split_pos:].lstrip()

        if chunk:
            chunks.append(chunk)

    if remaining.strip():
        chunks.append(remaining.strip())

    # إصلاح HTML tags المكسورة
    # لو جزء فيه opening tag من غير closing tag، نحط الـ closing tag
    fixed_chunks = []
    open_tags = []  # tags اللي لسه مفتوحة

    for chunk in chunks:
        # دور على tags مفتوحة في الجزء ده
        opens = re.findall(r'<(b|i|code|s|u|a)\b[^>]*>', chunk)
        closes = re.findall(r'</(b|i|code|s|u|a)>', chunk)

        # شيل من open_tags اللي اتقفلت
        for tag in closes:
            tag_name = tag
            if tag_name in open_tags:
                open_tags.remove(tag_name)

        # ضيف الـ tags الجديدة المفتوحة
        for tag_match in opens:
            tag_name = re.match(r'(\w+)', tag_match).group(1) if re.match(r'(\w+)', tag_match) else tag_match
            open_tags.append(tag_name)

        # لو في tags مفتوحة وده مش آخر جزء، اقفلهم مؤقتًا
        if open_tags and chunk != chunks[-1]:
            for tag in reversed(open_tags):
                chunk += f'</{tag}>'

        fixed_chunks.append(chunk)

    # الجزء الأول يفتح الـ tags اللي كانت مفتوحة من الجزء اللي قبله
    final_chunks = []
    pending_opens = []

    for i, chunk in enumerate(fixed_chunks):
        prefix = ''
        for tag in pending_opens:
            prefix += f'<{tag}>'

        final_chunks.append(prefix + chunk)

        # حدث الـ pending_opens
        # شيل الـ closing tags اللي اتضافت
        temp_opens = list(pending_opens)
        all_opens = re.findall(r'<(b|i|code|s|u|a)\b[^>]*>', prefix + chunk)
        all_closes = re.findall(r'</(b|i|code|s|u|a)>', prefix + chunk)

        for o in all_opens:
            temp_opens.append(o)
        for c in all_closes:
            if c in temp_opens:
                temp_opens.remove(c)

        pending_opens = temp_opens

    return final_chunks if final_chunks else [text]


def welcome_message(language: str = "ar", user_name: str = "") -> str:
    """رسالة الترحيب الاحترافية"""
    name_part = f" {user_name}" if user_name else ""
    if language == "ar":
        return f"""🤖 <b>أهلًا بك{name_part} في My Bro</b>
━━━━━━━━━━━━━━━━━

مساعدك الذكي الشامل 🧠

💬 <b>اسألني</b> — أي سؤال وهيكون عندك إجابة
📄 <b>تحليل ملفات</b> — ارفع PDF وأنا أحللهولك
🎬 <b>ملخص يوتيوب</b> — ابعت رابط فيديو وهلخصه
📥 <b>تحميل وسائط</b> — حمّل من YouTube, Insta, TikTok ⭐
🎨 <b>إنشاء صور</b> — صور بالذكاء الاصطناعي ⭐
🖌️ <b>تعديل صور</b> — عدّل أي صورة بوصف نصي ⭐
🎬 <b>فيديو بالبحث</b> — ابحث وحمّل فيديو ⭐
🎵 <b>صوت بالبحث</b> — ابحث وحمّل صوت ⭐
🖼️ <b>بحث صور</b> — ابحث عن أي صورة
📚 <b>وضع الدراسة</b> — خطط، كويزات، امتحانات ⭐
🔍 <b>بحث الويب</b> — بحث شامل في الإنترنت

━━━━━━━━━━━━━━━━━
💡 <i>اختار من الأزرار بالأسفل أو اكتب سؤالك مباشرة!</i>
⭐ <i>الميزات المعلّمة بالنجمة للمشتركين Premium بس</i>"""
    else:
        return f"""🤖 <b>Welcome{name_part} to My Bro</b>
━━━━━━━━━━━━━━━━━

Your smart AI assistant 🧠

💬 <b>Ask Me</b> — Any question, answered instantly
📄 <b>PDF Analysis</b> — Upload PDF and I'll analyze it
🎬 <b>YouTube Summary</b> — Send a video link and I'll summarize
📥 <b>Media Downloads</b> — Download from YouTube, Insta, TikTok ⭐
🎨 <b>Image Generation</b> — AI-generated images ⭐
🖌️ <b>Image Editing</b> — Edit any image with text ⭐
🎬 <b>Video Search</b> — Search & download videos ⭐
🎵 <b>Audio Search</b> — Search & download audio ⭐
🖼️ <b>Photo Search</b> — Search for any image
📚 <b>Study Mode</b> — Plans, quizzes, exams ⭐
🔍 <b>Web Search</b> — Comprehensive web search

━━━━━━━━━━━━━━━━━
💡 <i>Choose from buttons below or just type your question!</i>
⭐ <i>Features marked with ⭐ are Premium only</i>"""


def help_message(language: str = "ar") -> str:
    """رسالة المساعدة"""
    if language == "ar":
        return """🤖 <b>أوامر My Bro</b>
━━━━━━━━━━━━━━━━━

💬 <b>المحادثة والذكاء الاصطناعي</b>
/ask &lt;سؤال&gt; — سؤال مباشر
ابعت أي سؤال وهجاوبك فورًا!

📄 <b>تحليل الملفات</b>
ارفع PDF أو مستند وهحللهولك

🎬 <b>ملخص يوتيوب</b>
ابعت رابط فيديو وهلخصهولك

📥 <b>تحميل وسائط</b> ⭐
ابعت رابط من YouTube, Instagram, TikTok, Facebook, Twitter
/كمبيوتر — تحميل مباشر بالرابط

🎬 <b>فيديو بالبحث</b> ⭐
/video &lt;بحث&gt; — ابحث عن فيديو وحمّله

🎵 <b>صوت بالبحث</b> ⭐
/audio &lt;بحث&gt; — ابحث عن صوت وحمّله

🖼️ <b>بحث صور</b>
/photo &lt;بحث&gt; — ابحث عن صور (3/يوم مجاني)

🎨 <b>إنشاء صور</b> ⭐
/image &lt;وصف&gt; — صورة من وصف نصي

🖌️ <b>تعديل صور</b> ⭐
/edit &lt;وصف&gt; — عدّل صورة بوصف نصي

📚 <b>وضع الدراسة</b> ⭐
/study — خطط دراسية وكويزات وامتحانات

🔍 <b>البحث</b>
/search &lt;كلمة&gt; — بحث في الويب

🧠 <b>الذاكرة والمفضلات</b>
/memory — ذاكرتي عنك
/favorite — احفظ آخر شيء في المفضلة
/favorites — المفضلات
/forget &lt;كلمة&gt; — امسح ذكرى محددة

⚙️ <b>الإعدادات</b>
/language — تغيير اللغة
/about — عن البوت والمؤسس
/premium — حالة الاشتراك
/plan — مزايا Premium

━━━━━━━━━━━━━━━━━
⭐ = مميزات Premium بس
💡 ممكن تتكلم معايا بشكل عادي من غير أوامر!"""
    else:
        return """🤖 <b>My Bro Commands</b>
━━━━━━━━━━━━━━━━━

💬 <b>Chat & AI</b>
/ask &lt;question&gt; — Direct question
Just type anything and I'll respond!

📄 <b>File Analysis</b>
Upload a PDF or document and I'll analyze it

🎬 <b>YouTube Summary</b>
Send a video link and I'll summarize it

📥 <b>Media Downloads</b> ⭐
Send a link from YouTube, Instagram, TikTok, Facebook, Twitter

🎬 <b>Video Search</b> ⭐
/video &lt;query&gt; — Search & download videos

🎵 <b>Audio Search</b> ⭐
/audio &lt;query&gt; — Search & download audio

🖼️ <b>Photo Search</b>
/photo &lt;query&gt; — Search for images (3/day free)

🎨 <b>Image Generation</b> ⭐
/image &lt;description&gt; — Generate AI images

🖌️ <b>Image Editing</b> ⭐
/edit &lt;description&gt; — Edit images with text

📚 <b>Study Mode</b> ⭐
/study — Study plans, quizzes, exams

🔍 <b>Search</b>
/search &lt;query&gt; — Web search

🧠 <b>Memory & Favorites</b>
/memory — My memory about you
/favorite — Save last item to favorites
/favorites — View favorites
/forget &lt;keyword&gt; — Delete specific memory

⚙️ <b>Settings</b>
/language — Change language
/about — About the bot & creator
/premium — Subscription status
/plan — Premium features

━━━━━━━━━━━━━━━━━
⭐ = Premium features only
💡 You can chat with me naturally without commands!"""


def format_news_item(index: int, title: str, summary: str, url: str, is_top: bool = False, category: str = "", language: str = "ar") -> str:
    """تنسيق خبر واحد مع دعم الفئات وخبر اليوم واللغة"""
    # عرض الفئة
    category_display = ""
    if category:
        try:
            from news_editor import get_category_display
            category_display = get_category_display(category, language) + " "
        except ImportError:
            pass

    # اختيار البادج والعناوين حسب اللغة
    if is_top:
        badge = "🔥"
        top_label = "<b>خبر اليوم</b>\n" if language == "ar" else "<b>Top Story</b>\n"
    else:
        badge = "⚪️"
        top_label = ""

    # رابط اقرأ المزيد حسب اللغة
    read_more = "اقرأ المزيد" if language == "ar" else "Read more"

    return f"""{top_label}{badge} {category_display}<b>{title}</b>

{summary}

🔗 <a href="{url}">{read_more}</a>"""


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

هابعتلك أهم أخبار الذكاء الاصطناعي كل يوم الساعة 12 الظهر بتوقيت القاهرة 🌅

✅ آخر أخبار AI من مصادر عالمية
✅ ملخص بالعربية مفهوم وبسيط
✅ مجاني تمامًا

👇 اضغط على الزر بالأسفل عشان تشترك!"""
    else:
        return """📬 <b>Subscribe to Daily News!</b>
━━━━━━━━━━━━━━━━━

I'll send you the most important AI news every day at 12:00 PM Cairo time 🌅

✅ Latest AI news from global sources
✅ Clear and simple summaries
✅ Completely free

👇 Tap the button below to subscribe!"""


def subscription_confirmed(language: str = "ar") -> str:
    """رسالة تأكيد الاشتراك"""
    if language == "ar":
        return """✅ <b>تم الاشتراك بنجاح!</b>

📬 هابعتلك أخبار AI كل يوم الساعة 12 الظهر
💡 ممكن تلغي الاشتراك أي وقت من ⚙️ الإعدادات
⏰ ممكن تغير وقت الأخبار من ⚙️ الإعدادات > وقت الأخبار"""
    else:
        return """✅ <b>Subscribed successfully!</b>

📬 I'll send you AI news every day at 12:00 PM
💡 You can unsubscribe anytime from ⚙️ Settings
⏰ You can change news time from ⚙️ Settings > News Time"""


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

هابعتلك أهم أخبار الذكاء الاصطناعي كل يوم الساعة 12 الظهر بتوقيت القاهرة 🌅

✅ آخر أخبار AI من مصادر عالمية
✅ ملخص بالعربية مفهوم وبسيط
✅ مجاني تمامًا

👇 اضغط على الزر بالأسفل عشان تشترك!"""
    else:
        return """📬 <b>Subscribe to Daily News</b>
━━━━━━━━━━━━━━━━━

I'll send you the most important AI news every day at 12:00 PM Cairo time 🌅

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
⏰ موعد الإرسال: 12:00 الظهر بتوقيت القاهرة
📰 المصادر: {len(__import__('config').RSS_FEEDS)} مصدر RSS عالمي"""
    else:
        return f"""📊 <b>Subscribers Info</b>
━━━━━━━━━━━━━━━━━

📬 Daily news subscribers: <b>{count}</b>
⏰ Send time: 12:00 PM Cairo time
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
مثال: <code>12:00</code> أو <code>14:30</code>"""
    else:
        return f"""⏰ <b>Change News Time</b>

Current time: {current_time} (Cairo time)

Send the time in this format:
Example: <code>12:00</code> or <code>14:30</code>"""


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
