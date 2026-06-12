"""
Unit tests for po_token_manager.py

Tests the PO Token management system:
- Token loading from env var and file
- Token setting, getting, clearing
- Expiration and TTL
- yt-dlp integration (add_po_token_to_opts, get_ytdlp_po_token_args)
- Thread safety
- Status reporting
"""

import json
import os
import time
import unittest
import threading
from unittest.mock import patch, MagicMock

# Ensure the project root is on the path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPOTokenLoading(unittest.TestCase):
    """Test token loading from environment and file"""
    
    def setUp(self):
        # Clear any existing token before each test
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def tearDown(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
        # Clean up token file
        if os.path.exists(ptm._PO_TOKEN_FILE):
            try:
                os.remove(ptm._PO_TOKEN_FILE)
            except Exception:
                pass
    
    @patch.dict(os.environ, {"PO_TOKEN": "env_test_token_123"})
    def test_load_from_env(self):
        """Token should be loaded from PO_TOKEN env var"""
        import po_token_manager as ptm
        ptm._current_token = None  # Reset
        token = ptm.init_po_token()
        self.assertEqual(token, "env_test_token_123")
    
    @patch.dict(os.environ, {"PO_TOKEN": "  spaced_token  "})
    def test_load_from_env_strips_whitespace(self):
        """Token from env should be stripped"""
        import po_token_manager as ptm
        ptm._current_token = None
        token = ptm.init_po_token()
        self.assertEqual(token, "spaced_token")
    
    @patch.dict(os.environ, {"PO_TOKEN": ""})
    def test_empty_env_returns_none(self):
        """Empty PO_TOKEN env should return None"""
        import po_token_manager as ptm
        ptm._current_token = None
        token = ptm.init_po_token()
        self.assertIsNone(token)
    
    @patch.dict(os.environ, {}, clear=True)
    def test_no_env_returns_none(self):
        """No PO_TOKEN env should return None"""
        import po_token_manager as ptm
        ptm._current_token = None
        token = ptm.init_po_token()
        self.assertIsNone(token)
    
    @patch.dict(os.environ, {}, clear=True)
    def test_load_from_file(self):
        """Token should be loaded from po_token.json"""
        import po_token_manager as ptm
        ptm._current_token = None
        
        # Create a valid token file
        data = {"token": "file_test_token", "set_at": time.time(), "source": "manual"}
        with open(ptm._PO_TOKEN_FILE, 'w') as f:
            json.dump(data, f)
        
        token = ptm.init_po_token()
        self.assertEqual(token, "file_test_token")
    
    @patch.dict(os.environ, {}, clear=True)
    def test_expired_file_token_returns_none(self):
        """Expired token in file should return None"""
        import po_token_manager as ptm
        ptm._current_token = None
        
        # Create an expired token file (older than max age)
        old_time = time.time() - (13 * 3600)  # 13 hours ago
        data = {"token": "old_token", "set_at": old_time, "source": "file"}
        with open(ptm._PO_TOKEN_FILE, 'w') as f:
            json.dump(data, f)
        
        token = ptm.init_po_token()
        self.assertIsNone(token)


class TestPOTokenManagement(unittest.TestCase):
    """Test setting, getting, and clearing tokens"""
    
    def setUp(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def tearDown(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def test_set_token(self):
        """set_po_token should store the token"""
        import po_token_manager as ptm
        result = ptm.set_po_token("new_token_123", source="test")
        self.assertTrue(result)
        self.assertEqual(ptm.get_po_token(), "new_token_123")
    
    def test_set_empty_token_fails(self):
        """set_po_token with empty string should fail"""
        import po_token_manager as ptm
        result = ptm.set_po_token("", source="test")
        self.assertFalse(result)
        self.assertIsNone(ptm.get_po_token())
    
    def test_set_whitespace_token_fails(self):
        """set_po_token with whitespace only should fail"""
        import po_token_manager as ptm
        result = ptm.set_po_token("   ", source="test")
        self.assertFalse(result)
    
    def test_clear_token(self):
        """clear_po_token should remove the token"""
        import po_token_manager as ptm
        ptm.set_po_token("to_be_cleared", source="test")
        self.assertIsNotNone(ptm.get_po_token())
        
        result = ptm.clear_po_token()
        self.assertTrue(result)
        self.assertIsNone(ptm.get_po_token())
    
    def test_get_po_token_when_none(self):
        """get_po_token should return None when no token is set"""
        import po_token_manager as ptm
        self.assertIsNone(ptm.get_po_token())
    
    def test_should_use_po_token(self):
        """should_use_po_token should reflect token availability"""
        import po_token_manager as ptm
        self.assertFalse(ptm.should_use_po_token())
        
        ptm.set_po_token("test_token", source="test")
        self.assertTrue(ptm.should_use_po_token())
        
        ptm.clear_po_token()
        self.assertFalse(ptm.should_use_po_token())


class TestPOTokenExpiration(unittest.TestCase):
    """Test token expiration logic"""
    
    def setUp(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def tearDown(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def test_fresh_token_is_valid(self):
        """A freshly set token should be valid"""
        import po_token_manager as ptm
        ptm.set_po_token("fresh_token", source="test")
        self.assertIsNotNone(ptm.get_po_token())
    
    def test_expired_token_returns_none(self):
        """An expired token should return None"""
        import po_token_manager as ptm
        
        # Set a token and then manually expire it
        ptm.set_po_token("will_expire", source="test")
        
        # Manually set _token_set_at to a very old time
        ptm._token_set_at = time.time() - (13 * 3600)  # 13 hours ago
        
        self.assertIsNone(ptm.get_po_token())
    
    def test_status_shows_expired(self):
        """Status should show expired=True for old tokens"""
        import po_token_manager as ptm
        ptm.set_po_token("old_token", source="test")
        ptm._token_set_at = time.time() - (13 * 3600)
        
        status = ptm.get_po_token_status()
        self.assertTrue(status["expired"])


class TestPOTokenYtdlpIntegration(unittest.TestCase):
    """Test yt-dlp integration functions"""
    
    def setUp(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def tearDown(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def test_add_po_token_to_opts_no_token(self):
        """Without token, opts should be unchanged"""
        import po_token_manager as ptm
        opts = {"format": "best", "quiet": True}
        result = ptm.add_po_token_to_opts(opts)
        self.assertEqual(result, opts)
        self.assertNotIn("extractor_args", result)
    
    def test_add_po_token_to_opts_with_token(self):
        """With token, opts should include extractor_args with po_token"""
        import po_token_manager as ptm
        ptm.set_po_token("yt_test_token", source="test")
        
        opts = {"format": "best", "quiet": True}
        result = ptm.add_po_token_to_opts(opts)
        
        self.assertIn("extractor_args", result)
        self.assertIn("youtube", result["extractor_args"])
        self.assertIn("po_token", result["extractor_args"]["youtube"])
        self.assertEqual(result["extractor_args"]["youtube"]["po_token"], ["web+yt_test_token"])
    
    def test_add_po_token_preserves_existing_args(self):
        """PO Token should be added to existing extractor_args, not replace them"""
        import po_token_manager as ptm
        ptm.set_po_token("merge_test", source="test")
        
        opts = {
            "format": "best",
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        result = ptm.add_po_token_to_opts(opts)
        
        # Both should be present
        self.assertIn("player_client", result["extractor_args"]["youtube"])
        self.assertIn("po_token", result["extractor_args"]["youtube"])
        self.assertEqual(result["extractor_args"]["youtube"]["po_token"], ["web+merge_test"])
    
    def test_add_po_token_does_not_modify_original(self):
        """add_po_token_to_opts should not modify the original dict"""
        import po_token_manager as ptm
        ptm.set_po_token("immutable_test", source="test")
        
        opts = {"format": "best", "quiet": True}
        result = ptm.add_po_token_to_opts(opts)
        
        # Original should not have extractor_args
        self.assertNotIn("extractor_args", opts)
        self.assertIn("extractor_args", result)
    
    def test_get_ytdlp_po_token_args_no_token(self):
        """Without token, should return empty dict"""
        import po_token_manager as ptm
        args = ptm.get_ytdlp_po_token_args()
        self.assertEqual(args, {})
    
    def test_get_ytdlp_po_token_args_with_token(self):
        """With token, should return proper extractor_args"""
        import po_token_manager as ptm
        ptm.set_po_token("api_test_token", source="test")
        
        args = ptm.get_ytdlp_po_token_args()
        self.assertIn("youtube", args)
        self.assertIn("po_token", args["youtube"])
        self.assertEqual(args["youtube"]["po_token"], ["web+api_test_token"])


class TestPOTokenStatus(unittest.TestCase):
    """Test status reporting"""
    
    def setUp(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def tearDown(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def test_status_no_token(self):
        """Status without token should show available=False"""
        import po_token_manager as ptm
        status = ptm.get_po_token_status()
        self.assertFalse(status["available"])
        self.assertIsNone(status["source"])
    
    def test_status_with_token(self):
        """Status with token should show available=True"""
        import po_token_manager as ptm
        ptm.set_po_token("status_test", source="manual")
        status = ptm.get_po_token_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["source"], "manual")
        self.assertGreaterEqual(status["age_hours"], 0)
        self.assertIn("status_t...", status["token_preview"])
    
    def test_status_shows_source(self):
        """Status should show the correct source"""
        import po_token_manager as ptm
        ptm.set_po_token("env_source", source="env")
        status = ptm.get_po_token_status()
        self.assertEqual(status["source"], "env")


class TestPOTokenThreadSafety(unittest.TestCase):
    """Test thread safety of token operations"""
    
    def setUp(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def tearDown(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def test_concurrent_set_and_get(self):
        """Concurrent set/get should not crash or corrupt"""
        import po_token_manager as ptm
        
        errors = []
        
        def setter():
            try:
                for i in range(50):
                    ptm.set_po_token(f"concurrent_token_{i}", source="test")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        def getter():
            try:
                for _ in range(50):
                    token = ptm.get_po_token()
                    # Token should be None or one of the concurrent tokens
                    if token is not None:
                        self.assertTrue(token.startswith("concurrent_token_"))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=setter),
            threading.Thread(target=getter),
            threading.Thread(target=getter),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")


class TestPOTokenFilePersistence(unittest.TestCase):
    """Test token file persistence"""
    
    def setUp(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def tearDown(self):
        import po_token_manager as ptm
        ptm.clear_po_token()
    
    def test_set_saves_to_file(self):
        """set_po_token should save to file"""
        import po_token_manager as ptm
        
        ptm.set_po_token("persist_test", source="test")
        
        # Check file exists
        self.assertTrue(os.path.exists(ptm._PO_TOKEN_FILE))
        
        # Check file contents
        with open(ptm._PO_TOKEN_FILE, 'r') as f:
            data = json.load(f)
        self.assertEqual(data["token"], "persist_test")
        self.assertEqual(data["source"], "test")
    
    def test_clear_removes_file(self):
        """clear_po_token should remove the file"""
        import po_token_manager as ptm
        
        ptm.set_po_token("to_be_removed", source="test")
        self.assertTrue(os.path.exists(ptm._PO_TOKEN_FILE))
        
        ptm.clear_po_token()
        self.assertFalse(os.path.exists(ptm._PO_TOKEN_FILE))


if __name__ == '__main__':
    unittest.main()
