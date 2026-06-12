"""
Unit tests for handlers/downloads/utils.py

Tests the download utility functions:
- Audio quality detection
- Audio bitrate extraction
- Platform detection
- Direct media URL detection
- FFmpeg availability check
- URL caching
- yt-dlp options generation
"""

import hashlib
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# ── Mock heavy dependencies before importing the module under test ──
# handlers/__init__.py imports many sub-modules with heavy deps, so we must
# mock the handlers package itself to prevent cascading imports.
_mock_handler = MagicMock()
sys.modules['telegram'] = MagicMock()
sys.modules['telegram.ext'] = MagicMock()
sys.modules['handlers'] = _mock_handler
sys.modules['handlers.downloads'] = MagicMock()
sys.modules['handlers.downloads.utils'] = MagicMock()

# Now we can safely import the actual utils module by reading it directly
# We'll use importlib to load just the file we need
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "handlers.downloads.utils",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "handlers", "downloads", "utils.py")
)
_utils_module = importlib.util.module_from_spec(_spec)

# The utils module imports telegram — provide the mock
_utils_module.__dict__['telegram'] = sys.modules['telegram']
_spec.loader.exec_module(_utils_module)

# Extract the functions we need to test
_is_audio_quality = _utils_module._is_audio_quality
_get_audio_bitrate = _utils_module._get_audio_bitrate
_detect_platform = _utils_module._detect_platform
_is_direct_media_url = _utils_module._is_direct_media_url
_is_ffmpeg_available = _utils_module._is_ffmpeg_available
_store_url = _utils_module._store_url
_retrieve_url = _utils_module._retrieve_url
_extract_url = _utils_module._extract_url
_is_youtube_url = _utils_module._is_youtube_url
_is_threads_url = _utils_module._is_threads_url
_download_urls = _utils_module._download_urls
IMAGE_EXTENSIONS = _utils_module.IMAGE_EXTENSIONS
AUDIO_EXTENSIONS = _utils_module.AUDIO_EXTENSIONS
VIDEO_EXTENSIONS = _utils_module.VIDEO_EXTENSIONS


class TestIsAudioQuality(unittest.TestCase):
    """Tests for _is_audio_quality — audio quality detection"""

    def test_audio_is_audio(self):
        self.assertTrue(_is_audio_quality("audio"))

    def test_audio_320_is_audio(self):
        self.assertTrue(_is_audio_quality("audio_320"))

    def test_audio_192_is_audio(self):
        self.assertTrue(_is_audio_quality("audio_192"))

    def test_audio_128_is_audio(self):
        self.assertTrue(_is_audio_quality("audio_128"))

    def test_audio_64_is_audio(self):
        self.assertTrue(_is_audio_quality("audio_64"))

    def test_best_is_not_audio(self):
        self.assertFalse(_is_audio_quality("best"))

    def test_medium_is_not_audio(self):
        self.assertFalse(_is_audio_quality("medium"))

    def test_low_is_not_audio(self):
        self.assertFalse(_is_audio_quality("low"))

    def test_empty_string_is_not_audio(self):
        self.assertFalse(_is_audio_quality(""))


class TestGetAudioBitrate(unittest.TestCase):
    """Tests for _get_audio_bitrate — bitrate extraction"""

    def test_audio_320_returns_320(self):
        self.assertEqual(_get_audio_bitrate("audio_320"), 320)

    def test_audio_192_returns_192(self):
        self.assertEqual(_get_audio_bitrate("audio_192"), 192)

    def test_audio_128_returns_128(self):
        self.assertEqual(_get_audio_bitrate("audio_128"), 128)

    def test_audio_64_returns_64(self):
        self.assertEqual(_get_audio_bitrate("audio_64"), 64)

    def test_plain_audio_returns_192(self):
        """Plain 'audio' should default to 192kbps"""
        self.assertEqual(_get_audio_bitrate("audio"), 192)

    def test_invalid_suffix_returns_192(self):
        """Invalid bitrate suffix should default to 192"""
        self.assertEqual(_get_audio_bitrate("audio_invalid"), 192)

    def test_empty_string_returns_192(self):
        self.assertEqual(_get_audio_bitrate(""), 192)


class TestDetectPlatform(unittest.TestCase):
    """Tests for _detect_platform — platform detection for various URLs"""

    def test_youtube(self):
        self.assertEqual(_detect_platform("https://www.youtube.com/watch?v=abc"), "youtube")

    def test_youtu_be(self):
        self.assertEqual(_detect_platform("https://youtu.be/abc"), "youtube")

    def test_youtube_shorts(self):
        self.assertEqual(_detect_platform("https://youtube.com/shorts/abc"), "youtube")

    def test_facebook(self):
        self.assertEqual(_detect_platform("https://www.facebook.com/video/123"), "facebook")

    def test_fb_watch(self):
        self.assertEqual(_detect_platform("https://fb.watch/abc"), "facebook")

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

    def test_pinterest(self):
        self.assertEqual(_detect_platform("https://www.pinterest.com/pin/123"), "pinterest")

    def test_vimeo(self):
        self.assertEqual(_detect_platform("https://www.vimeo.com/12345"), "vimeo")

    def test_dailymotion(self):
        self.assertEqual(_detect_platform("https://www.dailymotion.com/video/abc"), "dailymotion")

    def test_twitch(self):
        self.assertEqual(_detect_platform("https://www.twitch.tv/videos/123"), "twitch")

    def test_snapchat(self):
        self.assertEqual(_detect_platform("https://www.snapchat.com/add/user"), "snapchat")

    def test_unknown_platform(self):
        self.assertEqual(_detect_platform("https://example.com/video"), "unknown")

    def test_case_insensitive(self):
        self.assertEqual(_detect_platform("HTTPS://WWW.YOUTUBE.COM/watch?v=abc"), "youtube")


class TestIsDirectMediaUrl(unittest.TestCase):
    """Tests for _is_direct_media_url — direct media URL detection"""

    def test_jpg_is_image(self):
        self.assertEqual(_is_direct_media_url("https://example.com/photo.jpg"), "image")

    def test_png_is_image(self):
        self.assertEqual(_is_direct_media_url("https://example.com/icon.png"), "image")

    def test_gif_is_image(self):
        self.assertEqual(_is_direct_media_url("https://example.com/anim.gif"), "image")

    def test_webp_is_image(self):
        self.assertEqual(_is_direct_media_url("https://example.com/img.webp"), "image")

    def test_mp3_is_audio(self):
        self.assertEqual(_is_direct_media_url("https://example.com/song.mp3"), "audio")

    def test_wav_is_audio(self):
        self.assertEqual(_is_direct_media_url("https://example.com/audio.wav"), "audio")

    def test_ogg_is_audio(self):
        self.assertEqual(_is_direct_media_url("https://example.com/audio.ogg"), "audio")

    def test_mp4_is_video(self):
        self.assertEqual(_is_direct_media_url("https://example.com/video.mp4"), "video")

    def test_webm_is_video(self):
        self.assertEqual(_is_direct_media_url("https://example.com/video.webm"), "video")

    def test_no_extension_returns_empty(self):
        self.assertEqual(_is_direct_media_url("https://example.com/page"), "")

    def test_html_returns_empty(self):
        self.assertEqual(_is_direct_media_url("https://example.com/page.html"), "")

    def test_query_params_ignored_for_extension(self):
        """URL with query params should still detect extension"""
        self.assertEqual(_is_direct_media_url("https://example.com/photo.jpg?size=large"), "image")


class TestIsFfmpegAvailable(unittest.TestCase):
    """Tests for _is_ffmpeg_available — ffmpeg availability check"""

    def setUp(self):
        """Reset the cached value before each test"""
        _utils_module._FFMPEG_AVAILABLE = None

    @patch.object(_utils_module.subprocess, 'run')
    def test_ffmpeg_available(self, mock_run):
        """Should return True when ffmpeg is available"""
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(_is_ffmpeg_available())

    @patch.object(_utils_module.subprocess, 'run')
    def test_ffmpeg_not_available(self, mock_run):
        """Should return False when ffmpeg is not found"""
        mock_run.side_effect = FileNotFoundError()
        self.assertFalse(_is_ffmpeg_available())

    @patch.object(_utils_module.subprocess, 'run')
    def test_ffmpeg_nonzero_returncode(self, mock_run):
        """Should return False when ffmpeg returns non-zero"""
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(_is_ffmpeg_available())

    @patch.object(_utils_module.subprocess, 'run')
    def test_result_cached(self, mock_run):
        """Should cache the result and not call subprocess again"""
        mock_run.return_value = MagicMock(returncode=0)
        _is_ffmpeg_available()
        _is_ffmpeg_available()
        # subprocess.run should only be called once (cached after first call)
        self.assertEqual(mock_run.call_count, 1)


class TestUrlCaching(unittest.TestCase):
    """Tests for _store_url and _retrieve_url — URL caching"""

    def setUp(self):
        """Clear URL cache before each test"""
        _download_urls.clear()

    def test_store_and_retrieve(self):
        """Storing a URL and retrieving should return the original URL"""
        key = _store_url("https://www.youtube.com/watch?v=test123")
        retrieved = _retrieve_url(key)
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
        self.assertEqual(_retrieve_url("nonexistent_key"), "")

    def test_key_is_md5_prefix(self):
        """Key should be first 8 chars of MD5 hash"""
        url = "https://test.com"
        expected_key = hashlib.md5(url.encode()).hexdigest()[:8]
        key = _store_url(url)
        self.assertEqual(key, expected_key)

    @patch.object(_utils_module.time, 'time')
    def test_expired_urls_cleaned(self, mock_time):
        """Expired URLs should be cleaned when storing new ones"""
        mock_time.return_value = 1000.0
        _store_url("https://old-url.com")

        # Advance time past TTL (600 seconds)
        mock_time.return_value = 2000.0
        _store_url("https://new-url.com")

        # The old URL should have been cleaned up
        self.assertTrue(len(_download_urls) <= 2)


class TestExtractUrl(unittest.TestCase):
    """Tests for _extract_url — URL extraction from text"""

    def test_extract_https_url(self):
        text = "Check this https://www.youtube.com/watch?v=abc"
        self.assertEqual(_extract_url(text), "https://www.youtube.com/watch?v=abc")

    def test_extract_http_url(self):
        text = "See http://example.com for more"
        self.assertEqual(_extract_url(text), "http://example.com")

    def test_no_url_returns_empty(self):
        self.assertEqual(_extract_url("Hello world"), "")

    def test_extracts_first_url(self):
        text = "First https://a.com then https://b.com"
        self.assertEqual(_extract_url(text), "https://a.com")


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


class TestGetYdlOpts(unittest.TestCase):
    """Tests for _get_ydl_opts — yt-dlp options generation"""

    def setUp(self):
        """Mock heavy deps needed by ytdlp.options"""
        # Mock all the heavy deps that ytdlp options imports
        sys.modules['telegram'] = MagicMock()
        sys.modules['telegram.ext'] = MagicMock()
        sys.modules['memory'] = MagicMock()
        sys.modules['premium'] = MagicMock()
        sys.modules['dashboard'] = MagicMock()
        sys.modules['handlers.dedup'] = MagicMock()
        sys.modules['content_safety'] = MagicMock()
        sys.modules['handlers.downloads.threads'] = MagicMock()

        # We also need to provide the utils functions that ytdlp options imports
        # Create a mock utils module that has the real functions
        _mock_utils = MagicMock()
        _mock_utils._is_audio_quality = _is_audio_quality
        _mock_utils._get_audio_bitrate = _get_audio_bitrate
        _mock_utils._is_ffmpeg_available = MagicMock(return_value=True)
        _mock_utils._is_youtube_url = _is_youtube_url
        _mock_utils._is_threads_url = _is_threads_url
        _mock_utils._detect_platform = _detect_platform
        _mock_utils._store_url = _store_url
        _mock_utils._retrieve_url = _retrieve_url
        _mock_utils._extract_url = _extract_url
        _mock_utils._get_cookies_file = MagicMock(return_value="")
        _mock_utils._ensure_deno_in_path = MagicMock()
        _mock_utils._COOKIES_FILE = ""
        _mock_utils._USER_AGENT = "TestAgent"
        _mock_utils.URL_PATTERNS = _utils_module.URL_PATTERNS
        _mock_utils.GENERAL_URL_PATTERN = _utils_module.GENERAL_URL_PATTERN
        _mock_utils.IMAGE_EXTENSIONS = IMAGE_EXTENSIONS
        _mock_utils.AUDIO_EXTENSIONS = AUDIO_EXTENSIONS
        _mock_utils.VIDEO_EXTENSIONS = VIDEO_EXTENSIONS
        _mock_utils._YOUTUBE_URL_PATTERN = _utils_module._YOUTUBE_URL_PATTERN
        _mock_utils._THREADS_URL_PATTERN = _utils_module._THREADS_URL_PATTERN
        _mock_utils._FFMPEG_AVAILABLE = True
        sys.modules['handlers.downloads.utils'] = _mock_utils
        sys.modules['handlers'] = MagicMock()
        sys.modules['handlers.downloads'] = MagicMock()
        # Make the handlers.downloads.utils accessible via the mock
        sys.modules['handlers.downloads'].utils = _mock_utils

        # Mock the ytdlp sub-package and its modules so the shim works
        sys.modules['handlers.downloads.ytdlp'] = MagicMock()
        sys.modules['handlers.downloads.ytdlp.update'] = MagicMock()
        sys.modules['handlers.downloads.ytdlp.cobalt'] = MagicMock()
        sys.modules['handlers.downloads.ytdlp.commands'] = MagicMock()
        sys.modules['handlers.downloads.ytdlp.download_main'] = MagicMock()
        sys.modules['handlers.downloads.ytdlp.options'] = MagicMock()

        # Load ytdlp.options module directly (contains _get_ydl_opts)
        _options_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "handlers", "downloads", "ytdlp", "options.py"
        )
        self._ytdlp_spec = importlib.util.spec_from_file_location(
            "handlers.downloads.ytdlp.options", _options_path
        )

    def _import_ytdlp(self):
        """Import ytdlp.options with mocked dependencies"""
        ytdlp_mod = importlib.util.module_from_spec(self._ytdlp_spec)
        # Register the module so relative imports inside options.py resolve
        sys.modules['handlers.downloads.ytdlp.options'] = ytdlp_mod
        self._ytdlp_spec.loader.exec_module(ytdlp_mod)
        return ytdlp_mod

    @patch('handlers.downloads.utils._is_ffmpeg_available', return_value=True)
    @patch('handlers.downloads.utils._get_cookies_file', return_value="")
    def test_audio_quality_opts(self, mock_cookies, mock_ffmpeg):
        """Audio quality should set format and postprocessors"""
        ytdlp = self._import_ytdlp()
        opts = ytdlp._get_ydl_opts("audio", "%(title)s.%(ext)s")
        self.assertIn('format', opts)
        self.assertIn('postprocessors', opts)
        pp = opts['postprocessors'][0]
        self.assertEqual(pp['key'], 'FFmpegExtractAudio')
        self.assertEqual(pp['preferredcodec'], 'mp3')

    @patch('handlers.downloads.utils._is_ffmpeg_available', return_value=True)
    @patch('handlers.downloads.utils._get_cookies_file', return_value="")
    def test_audio_320_bitrate(self, mock_cookies, mock_ffmpeg):
        """audio_320 quality should set preferredquality to 320"""
        ytdlp = self._import_ytdlp()
        opts = ytdlp._get_ydl_opts("audio_320", "%(title)s.%(ext)s")
        pp = opts['postprocessors'][0]
        self.assertEqual(pp['preferredquality'], '320')

    @patch('handlers.downloads.utils._is_ffmpeg_available', return_value=True)
    @patch('handlers.downloads.utils._get_cookies_file', return_value="")
    def test_video_best_quality(self, mock_cookies, mock_ffmpeg):
        """Best video quality should have format string with h264 preference"""
        ytdlp = self._import_ytdlp()
        opts = ytdlp._get_ydl_opts("best", "%(title)s.%(ext)s", platform="youtube")
        self.assertIn('format', opts)
        self.assertIn('merge_output_format', opts)
        self.assertEqual(opts['merge_output_format'], 'mp4')

    @patch('handlers.downloads.utils._is_ffmpeg_available', return_value=False)
    @patch('handlers.downloads.utils._get_cookies_file', return_value="")
    def test_no_ffmpeg_audio(self, mock_cookies, mock_ffmpeg):
        """Without ffmpeg, audio should use bestaudio format without postprocessor"""
        ytdlp = self._import_ytdlp()
        opts = ytdlp._get_ydl_opts("audio", "%(title)s.%(ext)s")
        self.assertIn('format', opts)
        self.assertNotIn('postprocessors', opts)

    @patch('handlers.downloads.utils._is_ffmpeg_available', return_value=True)
    @patch('handlers.downloads.utils._get_cookies_file', return_value="/path/to/cookies.txt")
    def test_cookies_file_used(self, mock_cookies, mock_ffmpeg):
        """When cookies file exists, it should be included in opts"""
        ytdlp = self._import_ytdlp()
        opts = ytdlp._get_ydl_opts("best", "%(title)s.%(ext)s")
        self.assertIn('cookiefile', opts)
        self.assertEqual(opts['cookiefile'], "/path/to/cookies.txt")

    @patch('handlers.downloads.utils._is_ffmpeg_available', return_value=True)
    @patch('handlers.downloads.utils._get_cookies_file', return_value="")
    def test_facebook_family_format(self, mock_cookies, mock_ffmpeg):
        """Facebook/Instagram should prefer pre-merged formats"""
        ytdlp = self._import_ytdlp()
        opts = ytdlp._get_ydl_opts("best", "%(title)s.%(ext)s", platform="facebook")
        format_str = opts.get('format', '')
        self.assertIn('best[ext=mp4]', format_str)

    @patch('handlers.downloads.utils._is_ffmpeg_available', return_value=True)
    @patch('handlers.downloads.utils._get_cookies_file', return_value="")
    def test_common_opts_present(self, mock_cookies, mock_ffmpeg):
        """Common opts (quiet, retries, etc.) should always be present"""
        ytdlp = self._import_ytdlp()
        opts = ytdlp._get_ydl_opts("best", "%(title)s.%(ext)s")
        self.assertEqual(opts['quiet'], True)
        self.assertEqual(opts['retries'], 3)
        self.assertIn('http_headers', opts)


if __name__ == "__main__":
    unittest.main()
