"""
Unit tests for whatsapp/state.py

Tests the shared state utilities:
- Phone number hashing & formatting
- Admin detection
- HTML stripping for WhatsApp
- Message splitting
- Arabic character detection
- Platform detection & URL extraction
- URL caching
- HMAC signature verification
"""

import hashlib
import hmac
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ── Mock heavy dependencies before importing the module under test ──
# whatsapp/state.py imports: aiohttp, i18n, content_safety
sys.modules['aiohttp'] = MagicMock()
sys.modules['i18n'] = MagicMock()
sys.modules['content_safety'] = MagicMock()

# Now we can import
from whatsapp.state import (
    _wa_phone_to_user_id,
    _wa_phone_to_display,
    _is_wa_admin,
    _strip_html_for_whatsapp,
    _split_whatsapp_message,
    _contains_arabic,
    _detect_platform,
    _is_youtube_url,
    _is_threads_url,
    _extract_url,
    _store_url,
    _get_url,
    _verify_signature,
    WA_MAX_MSG,
    _url_cache,
)


class TestWaPhoneToUserId(unittest.TestCase):
    """Tests for _wa_phone_to_user_id — deterministic hashing"""

    def test_deterministic_same_phone_same_id(self):
        """Same phone number must always produce the same user_id"""
        phone = "201203551789"
        id1 = _wa_phone_to_user_id(phone)
        id2 = _wa_phone_to_user_id(phone)
        self.assertEqual(id1, id2)

    def test_deterministic_across_multiple_calls(self):
        """Calling 100 times with same input must return same result"""
        phone = "201203551789"
        expected = _wa_phone_to_user_id(phone)
        for _ in range(100):
            self.assertEqual(_wa_phone_to_user_id(phone), expected)

    def test_plus_prefix_stripped(self):
        """Leading + should be stripped before hashing"""
        id_with_plus = _wa_phone_to_user_id("+201203551789")
        id_without_plus = _wa_phone_to_user_id("201203551789")
        self.assertEqual(id_with_plus, id_without_plus)

    def test_spaces_stripped(self):
        """Spaces should be stripped before hashing"""
        id_with_spaces = _wa_phone_to_user_id(" 201203551789 ")
        id_clean = _wa_phone_to_user_id("201203551789")
        self.assertEqual(id_with_spaces, id_clean)

    def test_different_phones_different_ids(self):
        """Different phone numbers should produce different IDs"""
        id1 = _wa_phone_to_user_id("201203551789")
        id2 = _wa_phone_to_user_id("201203551790")
        self.assertNotEqual(id1, id2)

    def test_result_is_negative_int(self):
        """Result should be a negative integer (matches the function logic)"""
        result = _wa_phone_to_user_id("201203551789")
        self.assertIsInstance(result, int)
        self.assertLess(result, 0)

    def test_matches_sha256_logic(self):
        """Verify the function matches the expected sha256 logic"""
        phone = "201203551789"
        clean = phone.lstrip('+').strip()
        h = hashlib.sha256(f"wa_{clean}".encode()).hexdigest()
        expected = -(int(h, 16) % (2**31))
        self.assertEqual(_wa_phone_to_user_id(phone), expected)


class TestWaPhoneToDisplay(unittest.TestCase):
    """Tests for _wa_phone_to_display — phone number formatting"""

    def test_adds_plus_prefix(self):
        self.assertEqual(_wa_phone_to_display("201203551789"), "+201203551789")

    def test_strips_existing_plus(self):
        self.assertEqual(_wa_phone_to_display("+201203551789"), "+201203551789")

    def test_strips_spaces(self):
        self.assertEqual(_wa_phone_to_display(" 201203551789 "), "+201203551789")

    def test_empty_string(self):
        self.assertEqual(_wa_phone_to_display(""), "+")


class TestIsWaAdmin(unittest.TestCase):
    """Tests for _is_wa_admin — admin detection"""

    @patch.dict(os.environ, {"ADMIN_WA_ID": "201203551789"})
    def test_admin_id_matches(self):
        """Should return True when wa_id matches ADMIN_WA_ID"""
        import whatsapp.state as state_mod
        state_mod.ADMIN_WA_ID = "201203551789"
        self.assertTrue(_is_wa_admin("201203551789"))

    @patch.dict(os.environ, {"ADMIN_WA_ID": "201203551789"})
    def test_non_admin_id(self):
        """Should return False for non-admin IDs"""
        import whatsapp.state as state_mod
        state_mod.ADMIN_WA_ID = "201203551789"
        self.assertFalse(_is_wa_admin("999999999999"))


class TestStripHtmlForWhatsapp(unittest.TestCase):
    """Tests for _strip_html_for_whatsapp — HTML tag removal and entity decoding"""

    def test_bold_tags_converted(self):
        """<b> tags should become WhatsApp *bold*"""
        self.assertEqual(_strip_html_for_whatsapp("<b>hello</b>"), "*hello*")

    def test_italic_tags_converted(self):
        """<i> tags should become WhatsApp _italic_"""
        self.assertEqual(_strip_html_for_whatsapp("<i>hello</i>"), "_hello_")

    def test_code_tags_converted(self):
        """<code> tags should become WhatsApp ```code```"""
        self.assertEqual(_strip_html_for_whatsapp("<code>x=1</code>"), "```x=1```")

    def test_strikethrough_tags_converted(self):
        """<s> tags should become WhatsApp ~strikethrough~"""
        self.assertEqual(_strip_html_for_whatsapp("<s>old</s>"), "~old~")

    def test_link_converted(self):
        """<a href> tags should become 'text (url)'"""
        result = _strip_html_for_whatsapp('<a href="https://example.com">click</a>')
        self.assertEqual(result, "click (https://example.com)")

    def test_generic_html_removed(self):
        """Generic HTML tags should be stripped"""
        self.assertEqual(_strip_html_for_whatsapp("<div>hello</div>"), "hello")

    def test_multiple_newlines_collapsed(self):
        """3+ consecutive newlines should collapse to 2"""
        self.assertEqual(_strip_html_for_whatsapp("hello\n\n\nworld"), "hello\n\nworld")

    def test_multiple_spaces_collapsed(self):
        """Multiple spaces should collapse to single"""
        self.assertEqual(_strip_html_for_whatsapp("hello   world"), "hello world")

    def test_empty_string(self):
        """Empty string should return empty string"""
        self.assertEqual(_strip_html_for_whatsapp(""), "")

    def test_none_like_empty(self):
        """Falsy input should return as-is"""
        self.assertEqual(_strip_html_for_whatsapp(""), "")

    def test_combined_html(self):
        """Combined HTML with multiple tags"""
        html = "<b>Title</b>\n<i>subtitle</i>\n<code>code</code>"
        result = _strip_html_for_whatsapp(html)
        self.assertIn("*Title*", result)
        self.assertIn("_subtitle_", result)
        self.assertIn("```code```", result)

    def test_strip_leading_trailing_whitespace(self):
        """Result should be stripped"""
        self.assertEqual(_strip_html_for_whatsapp("  hello  "), "hello")


class TestSplitWhatsappMessage(unittest.TestCase):
    """Tests for _split_whatsapp_message — message splitting at WA_MAX_MSG boundary"""

    def test_short_message_not_split(self):
        """Messages under max_length should return as single-element list"""
        text = "Short message"
        result = _split_whatsapp_message(text)
        self.assertEqual(result, [text])

    def test_exact_max_length_not_split(self):
        """Message exactly at max_length should not be split"""
        text = "a" * WA_MAX_MSG
        result = _split_whatsapp_message(text)
        self.assertEqual(result, [text])

    def test_long_message_split(self):
        """Messages over max_length should be split into multiple chunks"""
        text = "a" * (WA_MAX_MSG + 1000)
        result = _split_whatsapp_message(text)
        self.assertGreater(len(result), 1)
        # All chunks should be <= max_length
        for chunk in result:
            self.assertLessEqual(len(chunk), WA_MAX_MSG)

    def test_split_at_double_newline(self):
        """Should prefer splitting at double newlines"""
        text = "A" * (WA_MAX_MSG - 10) + "\n\n" + "B" * 100
        result = _split_whatsapp_message(text, max_length=WA_MAX_MSG)
        self.assertGreater(len(result), 1)

    def test_split_at_single_newline(self):
        """Should prefer splitting at newlines if no double newline"""
        text = "A" * (WA_MAX_MSG - 5) + "\n" + "B" * 100
        result = _split_whatsapp_message(text, max_length=WA_MAX_MSG)
        self.assertGreater(len(result), 1)

    def test_custom_max_length(self):
        """Should respect custom max_length parameter"""
        text = "A" * 50 + "\n\n" + "B" * 50
        result = _split_whatsapp_message(text, max_length=60)
        self.assertGreater(len(result), 1)
        for chunk in result:
            self.assertLessEqual(len(chunk), 60)

    def test_no_chunks_returns_original(self):
        """If splitting produces no chunks, should return original text"""
        # Edge case: text that's just whitespace over max_length
        text = "   "
        result = _split_whatsapp_message(text)
        self.assertEqual(result, [text])

    def test_chunks_join_approximate_original(self):
        """Joining chunks should approximate the original text"""
        text = "Word " * 2000  # ~10,000 chars
        result = _split_whatsapp_message(text)
        rejoined = " ".join(chunk for chunk in result)
        # Content should be preserved (whitespace may vary slightly)
        self.assertEqual(rejoined.replace(" ", ""), text.replace(" ", ""))

    def test_split_at_arabic_punctuation(self):
        """Should try splitting at Arabic punctuation (؟ ، ؛ .)"""
        text = "A" * (WA_MAX_MSG - 5) + "؟" + "B" * 100
        result = _split_whatsapp_message(text, max_length=WA_MAX_MSG)
        self.assertGreater(len(result), 1)


class TestContainsArabic(unittest.TestCase):
    """Tests for _contains_arabic — Arabic text detection"""

    def test_arabic_text_detected(self):
        self.assertTrue(_contains_arabic("مرحبا بالعالم"))

    def test_mixed_arabic_english(self):
        self.assertTrue(_contains_arabic("Hello مرحبا world"))

    def test_english_only_not_detected(self):
        self.assertFalse(_contains_arabic("Hello world"))

    def test_numbers_only_not_detected(self):
        self.assertFalse(_contains_arabic("12345"))

    def test_empty_string_not_detected(self):
        self.assertFalse(_contains_arabic(""))

    def test_arabic_presentation_forms(self):
        """Arabic presentation forms (FB50-FDFF, FE70-FEFF) should be detected"""
        # Using a character from the Arabic Presentation Forms-A block
        self.assertTrue(_contains_arabic("\uFB50"))


class TestDetectPlatform(unittest.TestCase):
    """Tests for _detect_platform — platform detection for various URLs"""

    def test_youtube(self):
        self.assertEqual(_detect_platform("https://www.youtube.com/watch?v=abc"), "youtube")

    def test_youtu_be(self):
        self.assertEqual(_detect_platform("https://youtu.be/abc"), "youtube")

    def test_facebook(self):
        self.assertEqual(_detect_platform("https://www.facebook.com/video/123"), "facebook")

    def test_instagram(self):
        self.assertEqual(_detect_platform("https://www.instagram.com/reel/abc"), "instagram")

    def test_tiktok(self):
        self.assertEqual(_detect_platform("https://www.tiktok.com/@user/video/123"), "tiktok")

    def test_twitter(self):
        self.assertEqual(_detect_platform("https://twitter.com/user/status/123"), "twitter")

    def test_x_com(self):
        self.assertEqual(_detect_platform("https://x.com/user/status/123"), "twitter")

    def test_telegram(self):
        self.assertEqual(_detect_platform("https://t.me/channel/123"), "telegram")

    def test_threads(self):
        self.assertEqual(_detect_platform("https://www.threads.net/@user/post/abc"), "threads")

    def test_reddit(self):
        self.assertEqual(_detect_platform("https://www.reddit.com/r/test/comments/abc"), "reddit")

    def test_dailymotion(self):
        self.assertEqual(_detect_platform("https://www.dailymotion.com/video/abc"), "dailymotion")

    def test_soundcloud(self):
        self.assertEqual(_detect_platform("https://soundcloud.com/user/track"), "soundcloud")

    def test_unknown_platform(self):
        self.assertEqual(_detect_platform("https://example.com/video"), "unknown")

    def test_case_insensitive(self):
        """URLs with uppercase should still be detected"""
        self.assertEqual(_detect_platform("https://WWW.YOUTUBE.COM/watch?v=abc"), "youtube")


class TestIsYoutubeUrl(unittest.TestCase):
    """Tests for _is_youtube_url — YouTube URL detection"""

    def test_youtube_com(self):
        self.assertTrue(_is_youtube_url("https://www.youtube.com/watch?v=abc"))

    def test_youtu_be(self):
        self.assertTrue(_is_youtube_url("https://youtu.be/abc123"))

    def test_youtube_shorts(self):
        self.assertTrue(_is_youtube_url("https://www.youtube.com/shorts/abc"))

    def test_not_youtube(self):
        self.assertFalse(_is_youtube_url("https://www.facebook.com/video"))


class TestIsThreadsUrl(unittest.TestCase):
    """Tests for _is_threads_url — Threads URL detection"""

    def test_threads_net(self):
        self.assertTrue(_is_threads_url("https://www.threads.net/@user/post/abc"))

    def test_threads_com(self):
        self.assertTrue(_is_threads_url("https://www.threads.com/@user/post/abc"))

    def test_not_threads(self):
        self.assertFalse(_is_threads_url("https://www.instagram.com/reel/abc"))


class TestExtractUrl(unittest.TestCase):
    """Tests for _extract_url — URL extraction from text"""

    def test_extract_http_url(self):
        text = "Check this out https://www.youtube.com/watch?v=abc"
        self.assertEqual(_extract_url(text), "https://www.youtube.com/watch?v=abc")

    def test_extract_https_url(self):
        text = "See http://example.com for more"
        self.assertEqual(_extract_url(text), "http://example.com")

    def test_no_url_returns_empty(self):
        self.assertEqual(_extract_url("Hello world"), "")

    def test_extracts_first_url(self):
        text = "First https://a.com then https://b.com"
        self.assertEqual(_extract_url(text), "https://a.com")

    def test_url_with_path(self):
        text = "Go to https://example.com/path/to/page?id=1"
        self.assertEqual(_extract_url(text), "https://example.com/path/to/page?id=1")


class TestUrlCaching(unittest.TestCase):
    """Tests for _store_url and _get_url — URL caching"""

    def setUp(self):
        """Clear URL cache before each test"""
        _url_cache.clear()

    def test_store_and_retrieve(self):
        """Storing a URL and retrieving it should return the original URL"""
        key = _store_url("https://www.youtube.com/watch?v=test123")
        retrieved = _get_url(key)
        self.assertEqual(retrieved, "https://www.youtube.com/watch?v=test123")

    def test_store_returns_key(self):
        """_store_url should return a string key"""
        key = _store_url("https://example.com")
        self.assertIsInstance(key, str)
        self.assertTrue(len(key) > 0)

    def test_same_url_same_key(self):
        """Same URL should produce the same key (MD5-based)"""
        url = "https://www.youtube.com/watch?v=abc"
        key1 = _store_url(url)
        key2 = _store_url(url)
        self.assertEqual(key1, key2)

    def test_different_urls_different_keys(self):
        """Different URLs should produce different keys"""
        key1 = _store_url("https://example.com/1")
        key2 = _store_url("https://example.com/2")
        self.assertNotEqual(key1, key2)

    def test_invalid_key_returns_empty(self):
        """Retrieving with invalid key should return empty string"""
        self.assertEqual(_get_url("nonexistent_key"), "")

    def test_key_is_md5_prefix(self):
        """Key should be first 10 chars of MD5 hash"""
        url = "https://test.com"
        expected_key = hashlib.md5(url.encode()).hexdigest()[:10]
        key = _store_url(url)
        self.assertEqual(key, expected_key)


class TestVerifySignature(unittest.TestCase):
    """Tests for _verify_signature — HMAC signature verification"""

    @patch.dict(os.environ, {"WHATSAPP_APP_SECRET": "test_secret_123"})
    def setUp(self):
        """Set up the app secret for testing"""
        import whatsapp.state as state_mod
        state_mod.WHATSAPP_APP_SECRET = "test_secret_123"

    def test_valid_signature(self):
        """Valid signature should return True"""
        payload = b"test_payload"
        expected = hmac.new(
            "test_secret_123".encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        sig_header = f"sha256={expected}"
        self.assertTrue(_verify_signature(payload, sig_header))

    def test_invalid_signature(self):
        """Invalid signature should return False"""
        self.assertFalse(_verify_signature(b"test_payload", "sha256=invalid_hex"))

    def test_missing_signature_header(self):
        """Empty signature header should return False"""
        self.assertFalse(_verify_signature(b"test_payload", ""))

    def test_wrong_prefix(self):
        """Signature without sha256= prefix should return False"""
        self.assertFalse(_verify_signature(b"test_payload", "md5=something"))

    @patch.dict(os.environ, {}, clear=False)
    def test_no_app_secret_passes(self):
        """If WHATSAPP_APP_SECRET is not set, verification should pass"""
        import whatsapp.state as state_mod
        state_mod.WHATSAPP_APP_SECRET = ""
        self.assertTrue(_verify_signature(b"test_payload", ""))

    def test_tampered_payload(self):
        """Tampered payload should fail verification"""
        payload = b"original_payload"
        sig = hmac.new(
            "test_secret_123".encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        sig_header = f"sha256={sig}"
        self.assertFalse(_verify_signature(b"tampered_payload", sig_header))


if __name__ == "__main__":
    unittest.main()
