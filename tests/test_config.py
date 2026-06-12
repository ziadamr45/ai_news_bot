"""
Unit tests for config.py

Tests the configuration module:
- NVIDIA_KEYS dictionary completeness
- get_nvidia_key() function
- DEVELOPER_WHATSAPP reads from env var
"""

import os
import sys
import unittest
from unittest.mock import patch

# config.py has no heavy external dependencies — it only uses os
# So we can import it directly, but we need to control env vars
# We'll import fresh for each test that needs specific env values


class TestNvidiaKeys(unittest.TestCase):
    """Tests for NVIDIA_KEYS dictionary"""

    def test_all_expected_keys_present(self):
        """NVIDIA_KEYS should contain all expected model keys"""
        # Import here to get fresh state
        import config
        expected_keys = [
            "deepseek_v4_pro",
            "deepseek_v4_flash",
            "kimi_k26",
            "glm_51",
            "minimax_m27",
            "llama_33_70b",
            "step_37_flash",
            "llama_32_90b_vision",
            "nemotron_nano_vl",
            "qwen_image",
            "qwen_image_edit",
            "sd35_large",
            "flux_kontext",
        ]
        for key in expected_keys:
            self.assertIn(key, config.NVIDIA_KEYS, f"Missing key: {key}")

    def test_keys_count(self):
        """NVIDIA_KEYS should have exactly 13 entries"""
        import config
        self.assertEqual(len(config.NVIDIA_KEYS), 13)

    def test_values_are_strings(self):
        """All values in NVIDIA_KEYS should be strings"""
        import config
        for key, value in config.NVIDIA_KEYS.items():
            self.assertIsInstance(value, str, f"Value for {key} is not a string")


class TestGetNvidiaKey(unittest.TestCase):
    """Tests for get_nvidia_key() function"""

    def test_existing_key_returns_value(self):
        """Should return the value for an existing key"""
        import config
        # All keys should be present (even if empty string from env)
        for key in config.NVIDIA_KEYS:
            result = config.get_nvidia_key(key)
            self.assertIsInstance(result, str)

    def test_nonexistent_key_returns_empty(self):
        """Should return empty string for non-existent key"""
        import config
        self.assertEqual(config.get_nvidia_key("nonexistent_model"), "")

    def test_empty_key_returns_empty(self):
        """Should return empty string for empty key"""
        import config
        self.assertEqual(config.get_nvidia_key(""), "")

    @patch.dict(os.environ, {"NVIDIA_DEEPSEEK_V4_PRO_KEY": "nvapi-test-key-123"})
    def test_key_from_env(self):
        """Should read key value from environment variable"""
        # Need to reimport to pick up new env var
        import importlib
        import config
        importlib.reload(config)
        self.assertEqual(config.get_nvidia_key("deepseek_v4_pro"), "nvapi-test-key-123")
        # Reload again to restore original state
        importlib.reload(config)


class TestDeveloperWhatsapp(unittest.TestCase):
    """Tests for DEVELOPER_WHATSAPP — reads from env var"""

    def test_default_value(self):
        """Should have a default value when env var is not set"""
        import config
        # The default is "01203551789"
        self.assertTrue(len(config.DEVELOPER_WHATSAPP) > 0)

    @patch.dict(os.environ, {"DEVELOPER_WHATSAPP": "1234567890"})
    def test_reads_from_env(self):
        """Should read DEVELOPER_WHATSAPP from environment variable"""
        import importlib
        import config
        importlib.reload(config)
        self.assertEqual(config.DEVELOPER_WHATSAPP, "1234567890")
        # Clean up - reload without the env var
        importlib.reload(config)

    def test_developer_whatsapp_url_format(self):
        """DEVELOPER_WHATSAPP_URL should be a valid wa.me link"""
        import config
        url = config.DEVELOPER_WHATSAPP_URL
        self.assertTrue(url.startswith("https://wa.me/"))
        # Should not have leading zero in the URL (lstrip('0') applied)
        phone_part = url.replace("https://wa.me/", "")
        self.assertFalse(phone_part.startswith("0"))


class TestNvidiaBaseUrl(unittest.TestCase):
    """Tests for NVIDIA_BASE_URL constant"""

    def test_url_is_correct(self):
        """NVIDIA_BASE_URL should point to the correct API endpoint"""
        import config
        self.assertEqual(config.NVIDIA_BASE_URL, "https://integrate.api.nvidia.com/v1")


if __name__ == "__main__":
    unittest.main()
