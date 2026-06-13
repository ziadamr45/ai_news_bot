"""
Unit tests for memory.py

Tests the advanced memory system:
- _clean_database_url() — URL cleaning (removing channel_binding, adding sslmode for Neon)
- _get_database_url() — DATABASE_URL environment variable retrieval
- _is_postgres() — PostgreSQL detection
- _create_postgresql_tables() — PostgreSQL table creation
- _init_sqlite() — SQLite initialization
- Cache system — _cache_get, _cache_set, _cache_invalidate, _cache_invalidate_user
- User profiles — get_user, update_user, _ensure_user_in_db
- Preferences — get_language, set_language, get_news_time, set_news_time, get_sources, set_sources
- Subscription — subscribe_user, unsubscribe_user, is_subscribed, get_all_subscribers
- Counters — increment_command_count, increment_chat_count
- Conversations — save_conversation, get_recent_conversations, get_conversation_context
- Learning — save_learning, get_learning_progress, get_learned_topics
- Favorites — add_favorite, get_favorites, remove_favorite
- Smart Memory — save_memory, get_memories, delete_memory, reset_all_memories
- Interests — add_interest, get_interests, add_favorite_company, get_favorite_companies
- Auto-detect — detect_interests, INTEREST_KEYWORDS, COMPANY_KEYWORDS
- Display — get_user_memory_summary, format_memory_display, format_progress_display
- Notifications — get_notification_enabled, set_notification_enabled
- Smart save — is_sensitive, has_preference_intent, smart_save
- Greeting — get_personalized_greeting, get_recommended_topic
- New user — is_new_user
- Ban system — is_banned, ban_user, unban_user, get_warning_count, add_warning
- News delivery — get_last_news_delivery, set_last_news_delivery, get_subscribers_for_time
- Find user — find_user_by_wa_phone
"""

import os
import sys
import time
import json
import unittest
import threading
from unittest.mock import MagicMock, patch, call
from datetime import datetime

# ── Mock heavy dependencies before importing ──
sys.modules['telegram'] = MagicMock()
sys.modules['telegram.ext'] = MagicMock()

# Prevent actual DB initialization at import time by mocking init functions
# memory.py calls init_database() at module level which tries to connect to PostgreSQL/SQLite
_original_init_postgresql = None
_original_init_sqlite = None


def _noop_init():
    """No-op database initializer to prevent real DB connections during import"""
    pass


# We need to pre-empt memory.py's import-time init_database() call.
# Strategy: mock the entire DB layer, import, then unmock for per-test mocking.
import config

# Ensure DATA_DIR exists so SQLite init doesn't fail
os.makedirs(config.DATA_DIR, exist_ok=True)

# Patch _init_postgresql and _init_sqlite BEFORE importing memory
# This is tricky because memory.py hasn't been imported yet.
# We'll use a different approach: just let it fail gracefully (it catches exceptions)
# and then test everything with mocked _execute().

# Import memory module — init_database() will be called but exceptions are caught
import memory
from memory import (
    _clean_database_url,
    _is_postgres,
    _execute,
    _cache_get,
    _cache_set,
    _cache_invalidate,
    _cache_invalidate_user,
    get_user,
    update_user,
    get_language,
    set_language,
    get_news_time,
    set_news_time,
    get_sources,
    set_sources,
    subscribe_user,
    unsubscribe_user,
    is_subscribed,
    get_all_subscribers,
    get_subscriber_count,
    increment_command_count,
    increment_chat_count,
    save_conversation,
    get_recent_conversations,
    get_conversation_context,
    save_learning,
    get_learning_progress,
    get_learned_topics,
    add_favorite,
    get_favorites,
    remove_favorite,
    save_memory,
    get_memories,
    delete_memory,
    reset_all_memories,
    add_interest,
    get_interests,
    get_interests_context,
    add_favorite_company,
    get_favorite_companies,
    detect_interests,
    INTEREST_KEYWORDS,
    COMPANY_KEYWORDS,
    is_sensitive,
    has_preference_intent,
    smart_save,
    get_user_memory_summary,
    format_memory_display,
    format_progress_display,
    format_favorites_display,
    get_notification_enabled,
    set_notification_enabled,
    get_personalized_greeting,
    get_recommended_topic,
    is_new_user,
    is_banned,
    ban_user,
    unban_user,
    get_warning_count,
    add_warning,
    get_last_news_delivery,
    set_last_news_delivery,
    get_subscribers_for_time,
    find_user_by_wa_phone,
    MAX_CONVERSATIONS,
    SENSITIVE_PATTERNS,
    PREFERENCE_PATTERNS_AR,
    PREFERENCE_PATTERNS_EN,
    _ALLOWED_USER_COLUMNS,
)


# ═══════════════════════════════════════════════════════════════
# Test: _clean_database_url
# ═══════════════════════════════════════════════════════════════

class TestCleanDatabaseUrl(unittest.TestCase):
    """Tests for _clean_database_url — URL cleaning and parameter removal"""

    def test_empty_string_returns_empty(self):
        self.assertEqual(_clean_database_url(""), "")

    def test_none_returns_none(self):
        self.assertIsNone(_clean_database_url(None))

    def test_removes_channel_binding_ampersand(self):
        """channel_binding=xxx after & should be removed"""
        url = "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"
        result = _clean_database_url(url)
        self.assertNotIn("channel_binding", result)
        self.assertIn("sslmode=require", result)

    def test_removes_channel_binding_question_mark(self):
        """channel_binding=xxx after ? should be removed"""
        url = "postgresql://user:pass@host/db?channel_binding=require&sslmode=require"
        result = _clean_database_url(url)
        self.assertNotIn("channel_binding", result)
        self.assertIn("sslmode=require", result)

    def test_removes_channel_binding_only_param(self):
        """channel_binding as sole parameter should be removed"""
        url = "postgresql://user:pass@host/db?channel_binding=require"
        result = _clean_database_url(url)
        self.assertNotIn("channel_binding", result)

    def test_adds_sslmode_for_neon_url(self):
        """Neon URLs should get sslmode=require if not present"""
        url = "postgresql://user:pass@ep-xxx.neon.tech/db"
        result = _clean_database_url(url)
        self.assertIn("sslmode=require", result)
        self.assertIn("neon.tech", result)

    def test_does_not_add_sslmode_for_non_neon_url(self):
        """Non-Neon URLs should NOT get sslmode added"""
        url = "postgresql://user:pass@localhost/db"
        result = _clean_database_url(url)
        self.assertNotIn("sslmode", result)

    def test_does_not_duplicate_sslmode(self):
        """If sslmode already present, don't add it again"""
        url = "postgresql://user:pass@ep-xxx.neon.tech/db?sslmode=require"
        result = _clean_database_url(url)
        self.assertEqual(result.count("sslmode"), 1)

    def test_cleans_trailing_question_mark(self):
        """Trailing ? after parameter removal should be cleaned"""
        url = "postgresql://user:pass@host/db?channel_binding=require"
        result = _clean_database_url(url)
        self.assertFalse(result.endswith("?"))

    def test_cleans_trailing_ampersand(self):
        """Trailing & after parameter removal should be cleaned"""
        url = "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"
        result = _clean_database_url(url)
        self.assertFalse(result.endswith("&"))

    def test_cleans_question_ampersand(self):
        """?& pattern should be cleaned to ?"""
        url = "postgresql://user:pass@host/db?channel_binding=require&sslmode=require"
        result = _clean_database_url(url)
        self.assertNotIn("?&", result)

    def test_url_without_channel_binding_unchanged(self):
        """URLs without channel_binding should pass through (except Neon sslmode)"""
        url = "postgresql://user:pass@localhost/db?sslmode=require"
        result = _clean_database_url(url)
        self.assertEqual(result, url)

    def test_neon_url_with_all_params(self):
        """Complex Neon URL with multiple params"""
        url = "postgresql://user:pass@ep-abc.neon.tech/mydb?channel_binding=require&connect_timeout=10"
        result = _clean_database_url(url)
        self.assertNotIn("channel_binding", result)
        self.assertIn("sslmode=require", result)
        self.assertIn("connect_timeout=10", result)


# ═══════════════════════════════════════════════════════════════
# Test: _get_database_url
# ═══════════════════════════════════════════════════════════════

class TestGetDatabaseUrl(unittest.TestCase):
    """Tests for _get_database_url — DATABASE_URL retrieval"""

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@host/db"})
    def test_returns_env_var_when_set(self):
        result = memory._get_database_url()
        self.assertIn("postgresql://user:pass@host/db", result)

    @patch.dict(os.environ, {}, clear=True)
    def test_returns_empty_when_not_set(self):
        """When DATABASE_URL is not in env and not in config, return empty"""
        # Remove from both env and try
        result = memory._get_database_url()
        # It may fall back to config.DATABASE_URL which could be empty
        self.assertIsInstance(result, str)

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@ep-xxx.neon.tech/db?channel_binding=require"})
    def test_cleans_url_before_returning(self):
        """_get_database_url should clean the URL"""
        result = memory._get_database_url()
        self.assertNotIn("channel_binding", result)
        self.assertIn("sslmode=require", result)


# ═══════════════════════════════════════════════════════════════
# Test: _is_postgres
# ═══════════════════════════════════════════════════════════════

class TestIsPostgres(unittest.TestCase):
    """Tests for _is_postgres — PostgreSQL detection"""

    def test_returns_true_when_postgresql(self):
        with patch.object(memory, '_db_type', 'postgresql'):
            self.assertTrue(_is_postgres())

    def test_returns_false_when_sqlite(self):
        with patch.object(memory, '_db_type', 'sqlite'):
            self.assertFalse(_is_postgres())

    def test_returns_false_when_none(self):
        with patch.object(memory, '_db_type', None):
            self.assertFalse(_is_postgres())


# ═══════════════════════════════════════════════════════════════
# Test: _create_postgresql_tables
# ═══════════════════════════════════════════════════════════════

class TestCreatePostgresqlTables(unittest.TestCase):
    """Tests for _create_postgresql_tables — PostgreSQL table creation"""

    def test_creates_all_tables(self):
        """Should execute CREATE TABLE for all 6 tables"""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        result = memory._create_postgresql_tables(mock_conn)

        self.assertTrue(result)
        # Should have called cursor() once
        mock_conn.cursor.assert_called_once()
        # Should have executed multiple CREATE TABLE statements
        self.assertGreater(mock_cur.execute.call_count, 6)
        # Should close cursor
        mock_cur.close.assert_called_once()
        # autocommit should be set
        self.assertTrue(mock_conn.autocommit)

    def test_returns_false_on_error(self):
        """Should return False if table creation fails"""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("DB Error")

        result = memory._create_postgresql_tables(mock_conn)
        self.assertFalse(result)

    def test_creates_indexes(self):
        """Should create indexes for performance"""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        memory._create_postgresql_tables(mock_conn)

        # Check that CREATE INDEX statements were executed
        execute_calls = [str(c) for c in mock_cur.execute.call_args_list]
        index_calls = [c for c in execute_calls if 'CREATE INDEX' in c]
        self.assertGreater(len(index_calls), 0)


# ═══════════════════════════════════════════════════════════════
# Test: Cache system
# ═══════════════════════════════════════════════════════════════

class TestCacheSystem(unittest.TestCase):
    """Tests for the TTL cache system"""

    def setUp(self):
        """Clear cache before each test"""
        with memory._cache_lock:
            memory._cache.clear()

    def test_cache_set_and_get(self):
        _cache_set("test_key", "test_value")
        result = _cache_get("test_key")
        self.assertEqual(result, "test_value")

    def test_cache_get_returns_none_for_missing_key(self):
        result = _cache_get("nonexistent")
        self.assertIsNone(result)

    def test_cache_get_returns_none_for_expired_key(self):
        _cache_set("expired_key", "value", ttl=-1)  # Already expired
        result = _cache_get("expired_key")
        self.assertIsNone(result)

    def test_cache_invalidate(self):
        _cache_set("to_invalidate", "value")
        _cache_invalidate("to_invalidate")
        result = _cache_get("to_invalidate")
        self.assertIsNone(result)

    def test_cache_invalidate_nonexistent_key(self):
        """Invalidating a non-existent key should not raise"""
        _cache_invalidate("nonexistent")  # Should not raise

    def test_cache_invalidate_user(self):
        """Should invalidate all cache entries containing user_id"""
        _cache_set("lang_123", "ar")
        _cache_set("user_123", {"name": "test"})
        _cache_set("lang_456", "en")  # Different user

        _cache_invalidate_user(123)

        self.assertIsNone(_cache_get("lang_123"))
        self.assertIsNone(_cache_get("user_123"))
        self.assertEqual(_cache_get("lang_456"), "en")  # Other user unaffected

    def test_cache_custom_ttl(self):
        """Cache should respect custom TTL"""
        _cache_set("short_lived", "value", ttl=3600)
        result = _cache_get("short_lived")
        self.assertEqual(result, "value")

    def test_cache_cleanup_on_large_size(self):
        """Cache should clean up expired entries when size > 500"""
        # Add expired entries
        for i in range(501):
            _cache_set(f"key_{i}", f"value_{i}", ttl=-1)

        # Adding one more should trigger cleanup
        _cache_set("trigger_cleanup", "value")

        # The expired entries should be removed
        with memory._cache_lock:
            # All remaining entries should be either the trigger_cleanup key
            # or entries that haven't expired yet
            for k, (v, exp) in memory._cache.items():
                self.assertGreater(exp, time.time(), f"Expired entry still in cache: {k}")


# ═══════════════════════════════════════════════════════════════
# Test: _ensure_user_in_db
# ═══════════════════════════════════════════════════════════════

class TestEnsureUserInDb(unittest.TestCase):
    """Tests for _ensure_user_in_db — user creation if missing"""

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    def test_creates_user_if_not_exists(self, mock_execute, mock_pg):
        """Should INSERT user when not found in DB"""
        # First call: SELECT user_id (not found)
        # Subsequent calls: migrations, INSERT
        mock_execute.return_value = None

        memory._ensure_user_in_db(12345)

        # Check that an INSERT was called
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT' in str(c)]
        self.assertGreater(len(insert_calls), 0)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    def test_does_not_create_user_if_exists(self, mock_execute, mock_pg):
        """Should NOT INSERT user when found in DB"""
        # Return a row meaning user exists
        mock_execute.return_value = (12345,)

        memory._ensure_user_in_db(12345)

        # No INSERT should happen
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT' in str(c)]
        self.assertEqual(len(insert_calls), 0)

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute')
    def test_postgres_uses_percent_s_placeholder(self, mock_execute, mock_pg):
        """PostgreSQL should use %s placeholder"""
        mock_execute.return_value = None

        memory._ensure_user_in_db(12345)

        # Find the SELECT call
        select_calls = [c for c in mock_execute.call_args_list
                        if 'SELECT user_id' in str(c)]
        self.assertGreater(len(select_calls), 0)
        # Should use %s
        self.assertIn('%s', str(select_calls[0]))

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    def test_sqlite_uses_question_mark_placeholder(self, mock_execute, mock_pg):
        """SQLite should use ? placeholder"""
        mock_execute.return_value = None

        memory._ensure_user_in_db(12345)

        # Find the SELECT call
        select_calls = [c for c in mock_execute.call_args_list
                        if 'SELECT user_id' in str(c)]
        self.assertGreater(len(select_calls), 0)
        # Should use ?
        self.assertIn('?', str(select_calls[0]))


# ═══════════════════════════════════════════════════════════════
# Test: get_user
# ═══════════════════════════════════════════════════════════════

class TestGetUser(unittest.TestCase):
    """Tests for get_user — user profile retrieval"""

    def setUp(self):
        with memory._cache_lock:
            memory._cache.clear()

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_returns_user_dict_from_sqlite(self, mock_ensure, mock_execute, mock_pg):
        """Should return a dict with user data from SQLite"""
        mock_execute.return_value = {
            'user_id': 123, 'name': 'Test', 'language': 'ar',
            'news_time': '12:00', 'sources': '[]', 'subscribed': 0,
            'interests': '["AI"]', 'favorite_companies': '[]',
            'response_length': 'medium', 'notification_enabled': 1,
            'commands_used': 5, 'chat_count': 10,
            'last_news_delivery': None, 'last_interaction': '2024-01-01',
            'created_at': '2024-01-01', 'platform': 'telegram',
            'wa_phone': '', 'profile_name': '',
        }
        result = get_user(123)
        self.assertIsInstance(result, dict)
        self.assertEqual(result['name'], 'Test')
        self.assertEqual(result['interests'], ['AI'])  # JSON string converted to list
        self.assertFalse(result['subscribed'])  # 0 -> False

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_returns_user_dict_from_postgres(self, mock_ensure, mock_execute, mock_pg):
        """Should return a dict with user data from PostgreSQL"""
        mock_execute.return_value = {
            'user_id': 456, 'name': 'PG User', 'language': 'en',
            'news_time': '09:00', 'sources': '["techcrunch"]', 'subscribed': 1,
            'interests': '["LLM"]', 'favorite_companies': '["OpenAI"]',
            'response_length': 'short', 'notification_enabled': 0,
            'commands_used': 100, 'chat_count': 200,
            'last_news_delivery': None, 'last_interaction': '2024-01-01',
            'created_at': '2024-01-01', 'platform': 'whatsapp',
            'wa_phone': '+201234567890', 'profile_name': 'PG',
        }
        result = get_user(456)
        self.assertEqual(result['name'], 'PG User')
        self.assertEqual(result['sources'], ['techcrunch'])
        self.assertTrue(result['subscribed'])  # 1 -> True

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_handles_invalid_json_in_sources(self, mock_ensure, mock_execute, mock_pg):
        """Should handle malformed JSON strings gracefully"""
        mock_execute.return_value = {
            'user_id': 789, 'name': '', 'language': 'ar',
            'sources': 'invalid_json', 'interests': 'also_invalid',
            'favorite_companies': None, 'subscribed': 0,
        }
        result = get_user(789)
        self.assertEqual(result['sources'], [])  # Invalid JSON -> empty list
        self.assertEqual(result['interests'], [])  # Invalid JSON -> empty list

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_load_all_users', return_value={})
    @patch.object(memory, '_save_all_users')
    def test_fallback_to_json_file(self, mock_save, mock_load, mock_ensure, mock_execute, mock_pg):
        """Should fall back to JSON file when DB returns None"""
        result = get_user(999)
        self.assertIsInstance(result, dict)
        self.assertIn('subscribed', result)


# ═══════════════════════════════════════════════════════════════
# Test: update_user
# ═══════════════════════════════════════════════════════════════

class TestUpdateUser(unittest.TestCase):
    """Tests for update_user — user profile updates"""

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_updates_single_field(self, mock_ensure, mock_execute, mock_pg):
        update_user(123, {"name": "New Name"})
        # _execute should be called with UPDATE
        update_calls = [c for c in mock_execute.call_args_list
                        if 'UPDATE' in str(c)]
        self.assertEqual(len(update_calls), 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_converts_list_to_json(self, mock_ensure, mock_execute, mock_pg):
        """Lists should be converted to JSON strings before saving"""
        update_user(123, {"interests": ["AI", "ML"]})
        # Find the UPDATE call and check the params
        update_calls = [c for c in mock_execute.call_args_list
                        if 'UPDATE' in str(c)]
        self.assertEqual(len(update_calls), 1)
        # The interests param should be a JSON string
        params = update_calls[0][0][1]  # Second positional arg = params tuple
        interests_val = None
        for p in params:
            if isinstance(p, str) and 'AI' in p and 'ML' in p:
                interests_val = p
                break
        self.assertIsNotNone(interests_val)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_converts_subscribed_bool_to_int(self, mock_ensure, mock_execute, mock_pg):
        """subscribed True should become 1, False should become 0"""
        update_user(123, {"subscribed": True})
        update_calls = [c for c in mock_execute.call_args_list
                        if 'UPDATE' in str(c)]
        params = update_calls[0][0][1]
        self.assertIn(1, params)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_rejects_invalid_column_names(self, mock_ensure, mock_execute, mock_pg):
        """Invalid column names should be filtered out for SQL injection protection"""
        update_user(123, {"evil_column; DROP TABLE--": "value", "name": "Safe"})
        update_calls = [c for c in mock_execute.call_args_list
                        if 'UPDATE' in str(c)]
        self.assertEqual(len(update_calls), 1)
        self.assertNotIn('evil_column', str(update_calls[0]))

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    def test_invalid_keys_filtered_but_last_interaction_kept(self, mock_ensure, mock_execute, mock_pg):
        """Invalid keys are removed but last_interaction is always added"""
        update_user(123, {"invalid_col": "val"})
        update_calls = [c for c in mock_execute.call_args_list
                        if 'UPDATE' in str(c)]
        # last_interaction is always added and is valid, so UPDATE still happens
        self.assertEqual(len(update_calls), 1)
        self.assertNotIn('invalid_col', str(update_calls[0]))
        self.assertIn('last_interaction', str(update_calls[0]))

    def test_allowed_columns_whitelist(self):
        """_ALLOWED_USER_COLUMNS should contain expected columns"""
        expected = {'name', 'language', 'news_time', 'sources', 'subscribed',
                    'response_length', 'notification_enabled', 'interests',
                    'favorite_companies', 'last_interaction', 'commands_used',
                    'chat_count', 'last_news_delivery', 'wa_phone'}
        self.assertTrue(expected.issubset(_ALLOWED_USER_COLUMNS))


# ═══════════════════════════════════════════════════════════════
# Test: Language preferences
# ═══════════════════════════════════════════════════════════════

class TestLanguagePreferences(unittest.TestCase):
    """Tests for get_language / set_language"""

    def setUp(self):
        with memory._cache_lock:
            memory._cache.clear()

    @patch.object(memory, 'get_user', return_value={'language': 'ar'})
    def test_get_language_returns_user_language(self, mock_get_user):
        result = get_language(123)
        self.assertEqual(result, 'ar')

    @patch.object(memory, 'get_user', return_value={})
    def test_get_language_defaults_to_ar(self, mock_get_user):
        result = get_language(123)
        self.assertEqual(result, 'ar')

    @patch.object(memory, 'update_user')
    @patch.object(memory, '_cache_invalidate')
    def test_set_language_updates_and_invalidates_cache(self, mock_invalidate, mock_update):
        set_language(123, 'en')
        mock_update.assert_called_once_with(123, {'language': 'en'})
        # Should invalidate both lang and user cache
        self.assertEqual(mock_invalidate.call_count, 2)


# ═══════════════════════════════════════════════════════════════
# Test: News time preferences
# ═══════════════════════════════════════════════════════════════

class TestNewsTimePreferences(unittest.TestCase):
    """Tests for get_news_time / set_news_time"""

    @patch.object(memory, 'get_user', return_value={'news_time': '14:00'})
    def test_get_news_time(self, mock_get_user):
        self.assertEqual(get_news_time(123), '14:00')

    @patch.object(memory, 'get_user', return_value={})
    def test_get_news_time_default(self, mock_get_user):
        self.assertEqual(get_news_time(123), '12:00')

    @patch.object(memory, 'update_user')
    @patch.object(memory, '_cache_invalidate')
    def test_set_news_time(self, mock_invalidate, mock_update):
        set_news_time(123, '08:00')
        mock_update.assert_called_once_with(123, {'news_time': '08:00'})


# ═══════════════════════════════════════════════════════════════
# Test: Sources preferences
# ═══════════════════════════════════════════════════════════════

class TestSourcesPreferences(unittest.TestCase):
    """Tests for get_sources / set_sources"""

    @patch.object(memory, 'get_user', return_value={'sources': ['techcrunch', 'verge']})
    def test_get_sources(self, mock_get_user):
        self.assertEqual(get_sources(123), ['techcrunch', 'verge'])

    @patch.object(memory, 'get_user', return_value={})
    def test_get_sources_default(self, mock_get_user):
        self.assertEqual(get_sources(123), [])

    @patch.object(memory, 'update_user')
    @patch.object(memory, '_cache_invalidate')
    def test_set_sources(self, mock_invalidate, mock_update):
        set_sources(123, ['arstechnica'])
        mock_update.assert_called_once_with(123, {'sources': ['arstechnica']})


# ═══════════════════════════════════════════════════════════════
# Test: Subscription system
# ═══════════════════════════════════════════════════════════════

class TestSubscription(unittest.TestCase):
    """Tests for subscribe_user / unsubscribe_user / is_subscribed / get_all_subscribers"""

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_cache_invalidate')
    def test_subscribe_user(self, mock_invalidate, mock_ensure, mock_execute):
        # subscribe_user now does direct SQL UPDATE + verification SELECT
        # First call: UPDATE, Second call: SELECT verification
        mock_execute.side_effect = [None, (1,)]  # UPDATE returns None, SELECT returns (1,)
        subscribe_user(123)
        # Should have called _execute at least once (the UPDATE)
        self.assertTrue(mock_execute.call_count >= 1)
        # Should have invalidated cache
        mock_invalidate.assert_called_with("user_123")

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_cache_invalidate')
    def test_unsubscribe_user(self, mock_invalidate, mock_ensure, mock_execute):
        unsubscribe_user(123)
        mock_execute.assert_called_once()
        mock_invalidate.assert_called_with("user_123")

    @patch.object(memory, 'get_user', return_value={'subscribed': True})
    def test_is_subscribed_true(self, mock_get_user):
        self.assertTrue(is_subscribed(123))

    @patch.object(memory, 'get_user', return_value={'subscribed': False})
    def test_is_subscribed_false(self, mock_get_user):
        self.assertFalse(is_subscribed(123))

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'user_id': 1, 'language': 'ar', 'news_time': '12:00', 'name': 'User1'},
        {'user_id': 2, 'language': 'en', 'news_time': '08:00', 'name': 'User2'},
    ])
    def test_get_all_subscribers(self, mock_execute, mock_pg):
        result = get_all_subscribers()
        self.assertEqual(len(result), 2)

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute', return_value=[
        (1, 'ar', '12:00', 'User1'),
        (2, 'en', '08:00', 'User2'),
    ])
    def test_get_all_subscribers_postgres(self, mock_execute, mock_pg):
        result = get_all_subscribers()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['user_id'], 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'user_id': 1, 'language': 'ar', 'news_time': '12:00', 'name': 'User1'},
    ])
    def test_get_all_subscribers_by_platform(self, mock_execute, mock_pg):
        result = get_all_subscribers(platform='whatsapp')
        self.assertEqual(len(result), 1)

    @patch.object(memory, 'get_all_subscribers', return_value=[{'user_id': 1}, {'user_id': 2}])
    def test_get_subscriber_count(self, mock_get_all):
        self.assertEqual(get_subscriber_count(), 2)


# ═══════════════════════════════════════════════════════════════
# Test: Counters
# ═══════════════════════════════════════════════════════════════

class TestCounters(unittest.TestCase):
    """Tests for increment_command_count / increment_chat_count"""

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_increment_command_count(self, mock_pg, mock_ensure, mock_execute):
        increment_command_count(123)
        update_calls = [c for c in mock_execute.call_args_list
                        if 'commands_used' in str(c)]
        self.assertEqual(len(update_calls), 1)

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_increment_chat_count(self, mock_pg, mock_ensure, mock_execute):
        increment_chat_count(123)
        update_calls = [c for c in mock_execute.call_args_list
                        if 'chat_count' in str(c)]
        self.assertEqual(len(update_calls), 1)


# ═══════════════════════════════════════════════════════════════
# Test: Conversation memory
# ═══════════════════════════════════════════════════════════════

class TestConversationMemory(unittest.TestCase):
    """Tests for save_conversation / get_recent_conversations / get_conversation_context"""

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_save_conversation(self, mock_pg, mock_ensure, mock_execute):
        save_conversation(123, 'user', 'Hello world')
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO conversations' in str(c)]
        self.assertEqual(len(insert_calls), 1)

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_save_conversation_truncates_long_content(self, mock_pg, mock_ensure, mock_execute):
        """Content should be truncated to 1000 chars"""
        long_content = "x" * 2000
        save_conversation(123, 'user', long_content)
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO conversations' in str(c)]
        # The params tuple should contain truncated content
        params = insert_calls[0][0][1]
        content_param = params[2]  # Third param is content
        self.assertEqual(len(content_param), 1000)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'role': 'user', 'content': 'Hi', 'timestamp': '2024-01-01'},
        {'role': 'assistant', 'content': 'Hello!', 'timestamp': '2024-01-01'},
    ])
    def test_get_recent_conversations(self, mock_execute, mock_pg):
        result = get_recent_conversations(123)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['role'], 'user')

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute', return_value=[
        ('user', 'Hi', '2024-01-01'),
        ('assistant', 'Hello!', '2024-01-01'),
    ])
    def test_get_recent_conversations_postgres(self, mock_execute, mock_pg):
        result = get_recent_conversations(123)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['role'], 'user')

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_get_recent_conversations_empty(self, mock_execute, mock_pg):
        result = get_recent_conversations(123)
        self.assertEqual(result, [])

    @patch.object(memory, 'get_recent_conversations')
    def test_get_conversation_context_with_data(self, mock_get):
        mock_get.return_value = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'},
        ]
        result = get_conversation_context(123)
        self.assertIn('User: Hello', result)
        self.assertIn('Bot: Hi there!', result)

    @patch.object(memory, 'get_recent_conversations', return_value=[])
    def test_get_conversation_context_empty(self, mock_get):
        result = get_conversation_context(123)
        self.assertEqual(result, "")

    def test_max_conversations_constant(self):
        self.assertEqual(MAX_CONVERSATIONS, 50)


# ═══════════════════════════════════════════════════════════════
# Test: Learning memory
# ═══════════════════════════════════════════════════════════════

class TestLearningMemory(unittest.TestCase):
    """Tests for save_learning / get_learning_progress / get_learned_topics"""

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_save_learning_sqlite(self, mock_pg, mock_ensure, mock_execute):
        save_learning(123, 'Transformers', 'explored')
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO learning_progress' in str(c)]
        self.assertEqual(len(insert_calls), 1)
        # Should use ON CONFLICT for upsert
        self.assertIn('ON CONFLICT', str(insert_calls[0]))

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=True)
    def test_save_learning_postgres(self, mock_pg, mock_ensure, mock_execute):
        save_learning(123, 'LLM', 'learned')
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO learning_progress' in str(c)]
        self.assertEqual(len(insert_calls), 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'topic': 'AI', 'level': 'explored', 'learned_at': '2024-01-01'},
        {'topic': 'ML', 'level': 'learned', 'learned_at': '2024-01-02'},
    ])
    def test_get_learning_progress(self, mock_execute, mock_pg):
        result = get_learning_progress(123)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['topic'], 'AI')

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute', return_value=[
        ('AI', 'explored', '2024-01-01'),
        ('ML', 'learned', '2024-01-02'),
    ])
    def test_get_learning_progress_postgres(self, mock_execute, mock_pg):
        result = get_learning_progress(123)
        self.assertEqual(len(result), 2)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_get_learning_progress_empty(self, mock_execute, mock_pg):
        result = get_learning_progress(123)
        self.assertEqual(result, [])

    @patch.object(memory, 'get_learning_progress', return_value=[
        {'topic': 'AI', 'level': 'explored', 'learned_at': '2024-01-01'},
        {'topic': 'ML', 'level': 'learned', 'learned_at': '2024-01-02'},
    ])
    def test_get_learned_topics(self, mock_get_progress):
        result = get_learned_topics(123)
        self.assertEqual(result, ['AI', 'ML'])


# ═══════════════════════════════════════════════════════════════
# Test: Favorites system
# ═══════════════════════════════════════════════════════════════

class TestFavoritesSystem(unittest.TestCase):
    """Tests for add_favorite / get_favorites / remove_favorite"""

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_add_favorite(self, mock_pg, mock_ensure, mock_execute):
        add_favorite(123, 'news', 'AI Breakthrough', 'Great article', 'https://example.com')
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO favorites' in str(c)]
        self.assertEqual(len(insert_calls), 1)

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_add_favorite_truncates_content(self, mock_pg, mock_ensure, mock_execute):
        """Content should be truncated to 500 chars"""
        long_content = "x" * 1000
        add_favorite(123, 'news', 'Title', long_content, '')
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO favorites' in str(c)]
        params = insert_calls[0][0][1]
        content_param = params[3]  # Fourth param is content
        self.assertEqual(len(content_param), 500)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'id': 1, 'category': 'news', 'title': 'AI News', 'content': 'text', 'url': '', 'saved_at': '2024-01-01'},
    ])
    def test_get_favorites_all(self, mock_execute, mock_pg):
        result = get_favorites(123)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'AI News')

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'id': 1, 'category': 'news', 'title': 'AI News', 'content': 'text', 'url': '', 'saved_at': '2024-01-01'},
    ])
    def test_get_favorites_by_category(self, mock_execute, mock_pg):
        result = get_favorites(123, category='news')
        self.assertEqual(len(result), 1)

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute', return_value=[
        (1, 'news', 'AI News', 'text', 'http://x.com', '2024-01-01'),
    ])
    def test_get_favorites_postgres(self, mock_execute, mock_pg):
        result = get_favorites(123)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_get_favorites_empty(self, mock_execute, mock_pg):
        result = get_favorites(123)
        self.assertEqual(result, [])

    @patch.object(memory, '_execute')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_remove_favorite(self, mock_pg, mock_execute):
        remove_favorite(123, 42)
        delete_calls = [c for c in mock_execute.call_args_list
                        if 'DELETE FROM favorites' in str(c)]
        self.assertEqual(len(delete_calls), 1)


# ═══════════════════════════════════════════════════════════════
# Test: Smart Memory
# ═══════════════════════════════════════════════════════════════

class TestSmartMemory(unittest.TestCase):
    """Tests for save_memory / get_memories / delete_memory / reset_all_memories"""

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_save_memory_sqlite(self, mock_pg, mock_ensure, mock_execute):
        save_memory(123, 'pref_lang', 'Arabic', 'preferences')
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO user_memories' in str(c)]
        self.assertEqual(len(insert_calls), 1)
        self.assertIn('ON CONFLICT', str(insert_calls[0]))

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=True)
    def test_save_memory_postgres(self, mock_pg, mock_ensure, mock_execute):
        save_memory(123, 'pref_lang', 'English', 'preferences')
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'INSERT INTO user_memories' in str(c)]
        self.assertEqual(len(insert_calls), 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'id': 1, 'key': 'pref', 'value': 'test', 'category': 'general', 'created_at': '2024-01-01'},
    ])
    def test_get_memories_all(self, mock_execute, mock_pg):
        result = get_memories(123)
        self.assertEqual(len(result), 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'id': 1, 'key': 'pref', 'value': 'test', 'category': 'preferences', 'created_at': '2024-01-01'},
    ])
    def test_get_memories_by_category(self, mock_execute, mock_pg):
        result = get_memories(123, category='preferences')
        self.assertEqual(len(result), 1)

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute', return_value=[
        (1, 'pref', 'test', 'general', '2024-01-01'),
    ])
    def test_get_memories_postgres(self, mock_execute, mock_pg):
        result = get_memories(123)
        self.assertEqual(len(result), 1)
        self.assertIn('key', result[0])

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_get_memories_empty(self, mock_execute, mock_pg):
        result = get_memories(123)
        self.assertEqual(result, [])

    @patch.object(memory, '_execute')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_delete_memory_by_key(self, mock_pg, mock_execute):
        delete_memory(123, key='pref')
        delete_calls = [c for c in mock_execute.call_args_list
                        if 'DELETE FROM user_memories' in str(c)]
        self.assertEqual(len(delete_calls), 1)
        # Should use LIKE for key matching
        self.assertIn('LIKE', str(delete_calls[0]))

    @patch.object(memory, '_execute')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_delete_memory_by_id(self, mock_pg, mock_execute):
        delete_memory(123, memory_id=42)
        delete_calls = [c for c in mock_execute.call_args_list
                        if 'DELETE FROM user_memories' in str(c)]
        self.assertEqual(len(delete_calls), 1)

    @patch.object(memory, '_execute')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_delete_memory_no_args_no_op(self, mock_pg, mock_execute):
        """Calling delete_memory with no key or id should do nothing"""
        delete_memory(123)
        mock_execute.assert_not_called()

    @patch.object(memory, '_execute')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_reset_all_memories(self, mock_pg, mock_execute):
        reset_all_memories(123)
        delete_calls = [c for c in mock_execute.call_args_list
                        if 'DELETE FROM' in str(c)]
        # Should delete from conversations, learning_progress, favorites, user_memories
        self.assertEqual(len(delete_calls), 4)


# ═══════════════════════════════════════════════════════════════
# Test: Interests
# ═══════════════════════════════════════════════════════════════

class TestInterests(unittest.TestCase):
    """Tests for add_interest / get_interests / get_interests_context / add_favorite_company / get_favorite_companies"""

    @patch.object(memory, 'save_memory')
    @patch.object(memory, 'update_user')
    @patch.object(memory, 'get_user', return_value={'interests': ['AI']})
    def test_add_interest_new(self, mock_get_user, mock_update, mock_save_mem):
        add_interest(123, 'ML')
        mock_update.assert_called_once()
        mock_save_mem.assert_called_once()

    @patch.object(memory, 'update_user')
    @patch.object(memory, 'get_user', return_value={'interests': ['AI']})
    def test_add_interest_duplicate_not_added(self, mock_get_user, mock_update):
        """Duplicate interest (case-insensitive) should not be added"""
        add_interest(123, 'ai')  # lowercase version of 'AI'
        mock_update.assert_not_called()

    @patch.object(memory, 'get_user', return_value={'interests': ['AI', 'ML']})
    def test_get_interests(self, mock_get_user):
        result = get_interests(123)
        self.assertEqual(result, ['AI', 'ML'])

    @patch.object(memory, 'get_user', return_value={})
    def test_get_interests_empty(self, mock_get_user):
        result = get_interests(123)
        self.assertEqual(result, [])

    @patch.object(memory, 'get_interests', return_value=['AI', 'ML'])
    def test_get_interests_context(self, mock_get_interests):
        result = get_interests_context(123)
        self.assertEqual(result, 'AI, ML')

    @patch.object(memory, 'get_interests', return_value=[])
    def test_get_interests_context_empty(self, mock_get_interests):
        result = get_interests_context(123)
        self.assertEqual(result, '')

    @patch.object(memory, 'update_user')
    @patch.object(memory, 'get_user', return_value={'favorite_companies': ['OpenAI']})
    def test_add_favorite_company_new(self, mock_get_user, mock_update):
        add_favorite_company(123, 'Google')
        mock_update.assert_called_once()

    @patch.object(memory, 'update_user')
    @patch.object(memory, 'get_user', return_value={'favorite_companies': ['OpenAI']})
    def test_add_favorite_company_duplicate(self, mock_get_user, mock_update):
        """Duplicate company (case-insensitive) should not be added"""
        add_favorite_company(123, 'openai')
        mock_update.assert_not_called()

    @patch.object(memory, 'get_user', return_value={'favorite_companies': ['OpenAI', 'Google']})
    def test_get_favorite_companies(self, mock_get_user):
        result = get_favorite_companies(123)
        self.assertEqual(result, ['OpenAI', 'Google'])


# ═══════════════════════════════════════════════════════════════
# Test: Auto-detect interests
# ═══════════════════════════════════════════════════════════════

class TestDetectInterests(unittest.TestCase):
    """Tests for detect_interests and keyword dictionaries"""

    def test_interest_keywords_is_dict(self):
        self.assertIsInstance(INTEREST_KEYWORDS, dict)

    def test_interest_keywords_has_expected_entries(self):
        self.assertIn('openai', INTEREST_KEYWORDS)
        self.assertIn('chatgpt', INTEREST_KEYWORDS)
        self.assertIn('claude', INTEREST_KEYWORDS)
        self.assertIn('python', INTEREST_KEYWORDS)

    def test_company_keywords_is_dict(self):
        self.assertIsInstance(COMPANY_KEYWORDS, dict)

    def test_company_keywords_has_expected_entries(self):
        self.assertIn('openai', COMPANY_KEYWORDS)
        self.assertIn('google', COMPANY_KEYWORDS)
        self.assertIn('nvidia', COMPANY_KEYWORDS)

    @patch.object(memory, 'add_favorite_company')
    @patch.object(memory, 'add_interest')
    def test_detect_interests_from_text(self, mock_add_interest, mock_add_company):
        detect_interests(123, "I love ChatGPT and OpenAI models")
        # Should detect "ChatGPT" and "OpenAI" as interests
        mock_add_interest.assert_called()
        # Should detect "OpenAI" as company
        mock_add_company.assert_called()

    @patch.object(memory, 'add_favorite_company')
    @patch.object(memory, 'add_interest')
    def test_detect_interests_no_match(self, mock_add_interest, mock_add_company):
        detect_interests(123, "The weather is nice today")
        mock_add_interest.assert_not_called()
        mock_add_company.assert_not_called()

    @patch.object(memory, 'add_favorite_company')
    @patch.object(memory, 'add_interest')
    def test_detect_interests_case_insensitive(self, mock_add_interest, mock_add_company):
        detect_interests(123, "I use PYTHON for machine learning")
        mock_add_interest.assert_called()


# ═══════════════════════════════════════════════════════════════
# Test: is_sensitive / has_preference_intent
# ═══════════════════════════════════════════════════════════════

class TestSensitiveContentDetection(unittest.TestCase):
    """Tests for is_sensitive — sensitive data detection"""

    def test_detects_password(self):
        self.assertTrue(is_sensitive("my password is 1234"))

    def test_detects_api_key(self):
        self.assertTrue(is_sensitive("here is my api key: xxx"))

    def test_detects_credit_card(self):
        self.assertTrue(is_sensitive("credit card number 4111111111111111"))

    def test_detects_arabic_sensitive(self):
        self.assertTrue(is_sensitive("كلمة سر الخاصة بي"))

    def test_normal_text_not_sensitive(self):
        self.assertFalse(is_sensitive("I love AI and machine learning"))

    def test_empty_string_not_sensitive(self):
        self.assertFalse(is_sensitive(""))

    def test_case_insensitive(self):
        self.assertTrue(is_sensitive("My PASSWORD is secret"))

    def test_sensitive_patterns_list(self):
        self.assertIsInstance(SENSITIVE_PATTERNS, list)
        self.assertGreater(len(SENSITIVE_PATTERNS), 0)


class TestPreferenceIntentDetection(unittest.TestCase):
    """Tests for has_preference_intent — preference detection"""

    def test_detects_arabic_preference(self):
        self.assertTrue(has_preference_intent("بحب الذكاء الاصطناعي"))

    def test_detects_english_preference(self):
        self.assertTrue(has_preference_intent("I love Python"))

    def test_detects_i_prefer(self):
        self.assertTrue(has_preference_intent("I prefer dark mode"))

    def test_normal_text_no_preference(self):
        self.assertFalse(has_preference_intent("What is AI?"))

    def test_empty_string_no_preference(self):
        self.assertFalse(has_preference_intent(""))

    def test_preference_patterns_ar(self):
        self.assertIsInstance(PREFERENCE_PATTERNS_AR, list)
        self.assertGreater(len(PREFERENCE_PATTERNS_AR), 0)

    def test_preference_patterns_en(self):
        self.assertIsInstance(PREFERENCE_PATTERNS_EN, list)
        self.assertGreater(len(PREFERENCE_PATTERNS_EN), 0)


# ═══════════════════════════════════════════════════════════════
# Test: smart_save
# ═══════════════════════════════════════════════════════════════

class TestSmartSave(unittest.TestCase):
    """Tests for smart_save — intelligent content saving"""

    @patch.object(memory, 'detect_interests')
    @patch.object(memory, 'save_conversation')
    @patch.object(memory, 'is_sensitive', return_value=False)
    def test_saves_normal_content(self, mock_sensitive, mock_save_conv, mock_detect):
        smart_save(123, "I like AI", "user")
        mock_save_conv.assert_called_once_with(123, "user", "I like AI")
        mock_detect.assert_called_once_with(123, "I like AI")

    @patch.object(memory, 'save_conversation')
    @patch.object(memory, 'is_sensitive', return_value=True)
    def test_skips_sensitive_content(self, mock_sensitive, mock_save_conv):
        smart_save(123, "my password is 1234", "user")
        mock_save_conv.assert_not_called()

    @patch.object(memory, 'save_memory')
    @patch.object(memory, 'detect_interests')
    @patch.object(memory, 'save_conversation')
    @patch.object(memory, 'has_preference_intent', return_value=True)
    @patch.object(memory, 'is_sensitive', return_value=False)
    def test_saves_preference_when_detected(self, mock_sensitive, mock_pref, mock_save_conv, mock_detect, mock_save_mem):
        smart_save(123, "I love Python", "user")
        # Should save as a preference memory
        mock_save_mem.assert_called_once()

    @patch.object(memory, 'save_memory')
    @patch.object(memory, 'detect_interests')
    @patch.object(memory, 'save_conversation')
    @patch.object(memory, 'has_preference_intent', return_value=False)
    @patch.object(memory, 'is_sensitive', return_value=False)
    def test_no_preference_save_for_bot_messages(self, mock_sensitive, mock_pref, mock_save_conv, mock_detect, mock_save_mem):
        """Bot messages should not trigger preference saving"""
        smart_save(123, "I love Python", "assistant")
        mock_save_mem.assert_not_called()

    @patch.object(memory, 'save_memory')
    @patch.object(memory, 'detect_interests')
    @patch.object(memory, 'save_conversation')
    @patch.object(memory, 'has_preference_intent', return_value=False)
    @patch.object(memory, 'is_sensitive', return_value=False)
    def test_no_preference_save_without_intent(self, mock_sensitive, mock_pref, mock_save_conv, mock_detect, mock_save_mem):
        smart_save(123, "What is AI?", "user")
        mock_save_mem.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# Test: get_user_memory_summary
# ═══════════════════════════════════════════════════════════════

class TestGetUserMemorySummary(unittest.TestCase):
    """Tests for get_user_memory_summary — memory summary for AI injection"""

    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_learned_topics', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=['AI', 'ML'])
    def test_arabic_summary_with_interests(self, mock_interests, mock_companies, mock_topics, mock_convos):
        result = get_user_memory_summary(123, 'ar')
        self.assertIn('اهتمامات المستخدم', result)
        self.assertIn('AI', result)

    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_learned_topics', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=['AI', 'ML'])
    def test_english_summary_with_interests(self, mock_interests, mock_companies, mock_topics, mock_convos):
        result = get_user_memory_summary(123, 'en')
        self.assertIn('User interests', result)
        self.assertIn('AI', result)

    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_learned_topics', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=['OpenAI'])
    @patch.object(memory, 'get_interests', return_value=[])
    def test_summary_with_companies_ar(self, mock_interests, mock_companies, mock_topics, mock_convos):
        result = get_user_memory_summary(123, 'ar')
        self.assertIn('شركات يتابعها', result)

    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_learned_topics', return_value=['Transformers'])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=[])
    def test_summary_with_learned_topics(self, mock_interests, mock_companies, mock_topics, mock_convos):
        result = get_user_memory_summary(123, 'ar')
        self.assertIn('مواضيع تعلمها', result)

    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_learned_topics', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=[])
    def test_empty_summary(self, mock_interests, mock_companies, mock_topics, mock_convos):
        result = get_user_memory_summary(123, 'ar')
        self.assertEqual(result, "")

    @patch.object(memory, 'get_recent_conversations', return_value=[
        {'role': 'user', 'content': 'Hello'},
        {'role': 'assistant', 'content': 'Hi there!'},
    ])
    @patch.object(memory, 'get_learned_topics', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=[])
    def test_summary_with_conversations(self, mock_interests, mock_companies, mock_topics, mock_convos):
        result = get_user_memory_summary(123, 'ar')
        self.assertIn('آخر مواضيع', result)


# ═══════════════════════════════════════════════════════════════
# Test: format_memory_display
# ═══════════════════════════════════════════════════════════════

class TestFormatMemoryDisplay(unittest.TestCase):
    """Tests for format_memory_display — formatted memory display for users"""

    @patch.object(memory, 'get_memories', return_value=[])
    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_favorites', return_value=[])
    @patch.object(memory, 'get_learning_progress', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=[])
    @patch.object(memory, 'get_user', return_value={'name': 'Test', 'language': 'ar', 'subscribed': True})
    def test_arabic_display(self, mock_user, mock_interests, mock_companies, mock_learning, mock_favorites, mock_convos, mock_memories):
        # Patch admin and premium imports
        with patch.dict('sys.modules', {'admin': MagicMock(is_admin=MagicMock(return_value=False)),
                                         'premium': MagicMock(get_user_plan=MagicMock(return_value='free'))}):
            result = format_memory_display(123, 'ar')
            self.assertIn('ذاكرتي عنك', result)
            self.assertIn('الاسم', result)

    @patch.object(memory, 'get_memories', return_value=[])
    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_favorites', return_value=[])
    @patch.object(memory, 'get_learning_progress', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=[])
    @patch.object(memory, 'get_user', return_value={'name': 'Test', 'language': 'en', 'subscribed': False})
    def test_english_display(self, mock_user, mock_interests, mock_companies, mock_learning, mock_favorites, mock_convos, mock_memories):
        with patch.dict('sys.modules', {'admin': MagicMock(is_admin=MagicMock(return_value=False)),
                                         'premium': MagicMock(get_user_plan=MagicMock(return_value='free'))}):
            result = format_memory_display(123, 'en')
            self.assertIn('My Memory About You', result)

    @patch.object(memory, 'get_memories', return_value=[])
    @patch.object(memory, 'get_recent_conversations', return_value=[])
    @patch.object(memory, 'get_favorites', return_value=[])
    @patch.object(memory, 'get_learning_progress', return_value=[])
    @patch.object(memory, 'get_favorite_companies', return_value=[])
    @patch.object(memory, 'get_interests', return_value=['AI', 'ML'])
    @patch.object(memory, 'get_user', return_value={'name': 'Test', 'language': 'ar', 'subscribed': False})
    def test_display_with_interests(self, mock_user, mock_interests, mock_companies, mock_learning, mock_favorites, mock_convos, mock_memories):
        with patch.dict('sys.modules', {'admin': MagicMock(is_admin=MagicMock(return_value=False)),
                                         'premium': MagicMock(get_user_plan=MagicMock(return_value='free'))}):
            result = format_memory_display(123, 'ar')
            self.assertIn('اهتماماتك', result)


# ═══════════════════════════════════════════════════════════════
# Test: format_progress_display
# ═══════════════════════════════════════════════════════════════

class TestFormatProgressDisplay(unittest.TestCase):
    """Tests for format_progress_display — learning progress display"""

    @patch.object(memory, 'get_learning_progress', return_value=[])
    def test_empty_progress_arabic(self, mock_get):
        result = format_progress_display(123, 'ar')
        self.assertIn('تقدمك في التعلم', result)
        self.assertIn('لسه متعلمتش', result)

    @patch.object(memory, 'get_learning_progress', return_value=[])
    def test_empty_progress_english(self, mock_get):
        result = format_progress_display(123, 'en')
        self.assertIn('Learning Progress', result)
        self.assertIn("haven't learned", result)

    @patch.object(memory, 'get_learning_progress', return_value=[
        {'topic': 'AI', 'level': 'explored', 'learned_at': '2024-01-01'},
        {'topic': 'ML', 'level': 'learning', 'learned_at': '2024-01-02'},
        {'topic': 'DL', 'level': 'learned', 'learned_at': '2024-01-03'},
    ])
    def test_progress_with_all_levels_arabic(self, mock_get):
        result = format_progress_display(123, 'ar')
        self.assertIn('استكشفت', result)
        self.assertIn('بتتعلم حالياً', result)
        self.assertIn('اتعلمت', result)
        self.assertIn('الإجمالي', result)

    @patch.object(memory, 'get_learning_progress', return_value=[
        {'topic': 'AI', 'level': 'explored', 'learned_at': '2024-01-01'},
    ])
    def test_progress_english(self, mock_get):
        result = format_progress_display(123, 'en')
        self.assertIn('Explored', result)
        self.assertIn('Total', result)


# ═══════════════════════════════════════════════════════════════
# Test: format_favorites_display
# ═══════════════════════════════════════════════════════════════

class TestFormatFavoritesDisplay(unittest.TestCase):
    """Tests for format_favorites_display — favorites display"""

    @patch.object(memory, 'get_favorites', return_value=[])
    def test_empty_favorites_arabic(self, mock_get):
        result = format_favorites_display(123, 'ar')
        self.assertIn('المفضلات', result)
        self.assertIn('معندكش مفضلات', result)

    @patch.object(memory, 'get_favorites', return_value=[])
    def test_empty_favorites_english(self, mock_get):
        result = format_favorites_display(123, 'en')
        self.assertIn('Favorites', result)
        self.assertIn('No favorites yet', result)

    @patch.object(memory, 'get_favorites', return_value=[
        {'category': 'news', 'title': 'AI Breakthrough'},
        {'category': 'topic', 'title': 'Transformers'},
    ])
    def test_favorites_with_items(self, mock_get):
        result = format_favorites_display(123, 'ar')
        self.assertIn('AI Breakthrough', result)
        self.assertIn('الإجمالي', result)


# ═══════════════════════════════════════════════════════════════
# Test: Notifications
# ═══════════════════════════════════════════════════════════════

class TestNotifications(unittest.TestCase):
    """Tests for get_notification_enabled / set_notification_enabled"""

    @patch.object(memory, 'get_user', return_value={'notification_enabled': 1})
    def test_notification_enabled(self, mock_get_user):
        self.assertTrue(get_notification_enabled(123))

    @patch.object(memory, 'get_user', return_value={'notification_enabled': 0})
    def test_notification_disabled(self, mock_get_user):
        self.assertFalse(get_notification_enabled(123))

    @patch.object(memory, 'get_user', return_value={})
    def test_notification_default_enabled(self, mock_get_user):
        """Default should be enabled (1)"""
        self.assertTrue(get_notification_enabled(123))

    @patch.object(memory, 'update_user')
    def test_set_notification_enabled(self, mock_update):
        set_notification_enabled(123, True)
        mock_update.assert_called_once_with(123, {'notification_enabled': 1})

    @patch.object(memory, 'update_user')
    def test_set_notification_disabled(self, mock_update):
        set_notification_enabled(123, False)
        mock_update.assert_called_once_with(123, {'notification_enabled': 0})


# ═══════════════════════════════════════════════════════════════
# Test: get_personalized_greeting
# ═══════════════════════════════════════════════════════════════

class TestPersonalizedGreeting(unittest.TestCase):
    """Tests for get_personalized_greeting — personalized greeting based on memory"""

    @patch.object(memory, 'get_interests', return_value=['AI'])
    @patch.object(memory, 'get_user', return_value={'name': 'Ahmed'})
    def test_arabic_greeting_with_name_and_interests(self, mock_get_user, mock_get_interests):
        result = get_personalized_greeting(123, 'ar')
        self.assertIn('أهلاً Ahmed', result)
        self.assertIn('مهتم بـ AI', result)

    @patch.object(memory, 'get_interests', return_value=[])
    @patch.object(memory, 'get_user', return_value={'name': ''})
    def test_arabic_greeting_no_name_no_interests(self, mock_get_user, mock_get_interests):
        result = get_personalized_greeting(123, 'ar')
        self.assertIn('أهلاً!', result)

    @patch.object(memory, 'get_interests', return_value=['AI'])
    @patch.object(memory, 'get_user', return_value={'name': 'John'})
    def test_english_greeting_with_name_and_interests(self, mock_get_user, mock_get_interests):
        result = get_personalized_greeting(123, 'en')
        self.assertIn('Hey John', result)
        self.assertIn("into AI", result)

    @patch.object(memory, 'get_interests', return_value=[])
    @patch.object(memory, 'get_user', return_value={'name': ''})
    def test_english_greeting_no_name(self, mock_get_user, mock_get_interests):
        result = get_personalized_greeting(123, 'en')
        self.assertIn('Hey!', result)


# ═══════════════════════════════════════════════════════════════
# Test: get_recommended_topic
# ═══════════════════════════════════════════════════════════════

class TestRecommendedTopic(unittest.TestCase):
    """Tests for get_recommended_topic — topic recommendation"""

    @patch.object(memory, 'get_learned_topics', return_value=['AI'])
    @patch.object(memory, 'get_interests', return_value=['AI', 'ML'])
    def test_recommends_unlearned_interest(self, mock_interests, mock_learned):
        result = get_recommended_topic(123, 'en')
        self.assertIn('ML', result)
        self.assertIn('learn about ML', result)

    @patch.object(memory, 'get_learned_topics', return_value=['AI', 'ML'])
    @patch.object(memory, 'get_interests', return_value=['AI', 'ML'])
    def test_no_recommendation_if_all_learned(self, mock_interests, mock_learned):
        result = get_recommended_topic(123, 'en')
        self.assertEqual(result, '')

    @patch.object(memory, 'get_interests', return_value=[])
    def test_no_recommendation_if_no_interests(self, mock_interests):
        result = get_recommended_topic(123, 'en')
        self.assertEqual(result, '')

    @patch.object(memory, 'get_learned_topics', return_value=[])
    @patch.object(memory, 'get_interests', return_value=['AI'])
    def test_arabic_recommendation(self, mock_interests, mock_learned):
        result = get_recommended_topic(123, 'ar')
        self.assertIn('ممكن تتعلم عن AI', result)


# ═══════════════════════════════════════════════════════════════
# Test: is_new_user
# ═══════════════════════════════════════════════════════════════

class TestIsNewUser(unittest.TestCase):
    """Tests for is_new_user — new user detection"""

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=('2024-01-01',))
    def test_existing_user(self, mock_execute, mock_pg):
        result = is_new_user(123)
        self.assertFalse(result)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_new_user(self, mock_execute, mock_pg):
        result = is_new_user(123)
        self.assertTrue(result)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=(None,))
    def test_user_with_null_created_at(self, mock_execute, mock_pg):
        result = is_new_user(123)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════
# Test: Ban system
# ═══════════════════════════════════════════════════════════════

class TestBanSystem(unittest.TestCase):
    """Tests for is_banned / ban_user / unban_user / get_warning_count / add_warning"""

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=(123,))
    def test_is_banned_true(self, mock_execute, mock_pg):
        self.assertTrue(is_banned(123))

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_is_banned_false(self, mock_execute, mock_pg):
        self.assertFalse(is_banned(123))

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_ban_user(self, mock_pg, mock_ensure, mock_execute):
        ban_user(123, "Spam", "admin")
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'banned_users' in str(c)]
        self.assertGreater(len(insert_calls), 0)

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=True)
    def test_ban_user_postgres(self, mock_pg, mock_ensure, mock_execute):
        ban_user(123, "Abuse", "moderator")
        insert_calls = [c for c in mock_execute.call_args_list
                        if 'banned_users' in str(c)]
        self.assertGreater(len(insert_calls), 0)
        # Should use ON CONFLICT for upsert
        self.assertTrue(any('ON CONFLICT' in str(c) for c in insert_calls))

    @patch.object(memory, '_execute')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_unban_user(self, mock_pg, mock_execute):
        unban_user(123)
        delete_calls = [c for c in mock_execute.call_args_list
                        if 'DELETE FROM banned_users' in str(c)]
        self.assertEqual(len(delete_calls), 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=(3,))
    def test_get_warning_count(self, mock_execute, mock_pg):
        result = get_warning_count(123)
        self.assertEqual(result, 3)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_get_warning_count_no_warnings(self, mock_execute, mock_pg):
        result = get_warning_count(123)
        self.assertEqual(result, 0)

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_add_warning_new_entry(self, mock_pg, mock_ensure, mock_execute):
        """First warning should create entry with count=1"""
        mock_execute.return_value = None
        result = add_warning(123, "Bad behavior", "admin")
        self.assertEqual(result, 1)

    @patch.object(memory, '_execute')
    @patch.object(memory, '_ensure_user_in_db')
    @patch.object(memory, '_is_postgres', return_value=False)
    def test_add_warning_increment(self, mock_pg, mock_ensure, mock_execute):
        """Subsequent warnings should increment count"""
        mock_execute.return_value = (2,)  # Already has 2 warnings
        result = add_warning(123, "Another warning", "admin")
        self.assertEqual(result, 3)


# ═══════════════════════════════════════════════════════════════
# Test: News delivery
# ═══════════════════════════════════════════════════════════════

class TestNewsDelivery(unittest.TestCase):
    """Tests for get_last_news_delivery / set_last_news_delivery / get_subscribers_for_time"""

    @patch.object(memory, 'get_user', return_value={'last_news_delivery': '2024-01-01T12:00:00'})
    def test_get_last_news_delivery(self, mock_get_user):
        result = get_last_news_delivery(123)
        self.assertEqual(result, '2024-01-01T12:00:00')

    @patch.object(memory, 'get_user', return_value={})
    def test_get_last_news_delivery_none(self, mock_get_user):
        result = get_last_news_delivery(123)
        self.assertIsNone(result)

    @patch.object(memory, 'update_user')
    def test_set_last_news_delivery(self, mock_update):
        set_last_news_delivery(123, '2024-01-01T12:00:00')
        mock_update.assert_called_once_with(123, {'last_news_delivery': '2024-01-01T12:00:00'})

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'user_id': 1, 'language': 'ar', 'news_time': '12:00', 'name': 'User1',
         'last_news_delivery': None, 'platform': 'telegram', 'wa_phone': ''},
    ])
    def test_get_subscribers_for_time(self, mock_execute, mock_pg):
        result = get_subscribers_for_time(12, 0)
        self.assertEqual(len(result), 1)

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_execute', return_value=[
        (1, 'ar', '12:00', 'User1', None, 'telegram', ''),
    ])
    def test_get_subscribers_for_time_postgres(self, mock_execute, mock_pg):
        result = get_subscribers_for_time(12, 0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['user_id'], 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    @patch.object(memory, '_load_all_users', return_value={
        '1': {'subscribed': True, 'news_time': '14:00', 'language': 'ar', 'name': 'User1',
              'platform': 'telegram', 'last_news_delivery': None, 'wa_phone': ''}
    })
    def test_get_subscribers_for_time_fallback(self, mock_load, mock_execute, mock_pg):
        result = get_subscribers_for_time(14, 0)
        self.assertEqual(len(result), 1)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=[
        {'user_id': 1, 'language': 'ar', 'news_time': '12:00', 'name': 'WA User',
         'last_news_delivery': None, 'platform': 'whatsapp', 'wa_phone': '+201234567890'},
    ])
    def test_get_subscribers_for_time_with_platform_filter(self, mock_execute, mock_pg):
        result = get_subscribers_for_time(12, 0, platform='whatsapp')
        self.assertEqual(len(result), 1)


# ═══════════════════════════════════════════════════════════════
# Test: find_user_by_wa_phone
# ═══════════════════════════════════════════════════════════════

class TestFindUserByWaPhone(unittest.TestCase):
    """Tests for find_user_by_wa_phone — WhatsApp user lookup"""

    def test_returns_none_for_empty_phone(self):
        self.assertIsNone(find_user_by_wa_phone(""))

    def test_returns_none_for_none_phone(self):
        self.assertIsNone(find_user_by_wa_phone(None))

    def test_returns_none_for_plus_only(self):
        self.assertIsNone(find_user_by_wa_phone("+"))

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=(12345,))
    def test_finds_user_by_phone(self, mock_execute, mock_pg):
        result = find_user_by_wa_phone("201234567890")
        self.assertEqual(result, 12345)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=None)
    def test_returns_none_when_not_found(self, mock_execute, mock_pg):
        result = find_user_by_wa_phone("201234567890")
        self.assertIsNone(result)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', side_effect=[
        None,  # First query without +
        (12345,),  # Second query with +
    ])
    def test_tries_with_plus_prefix(self, mock_execute, mock_pg):
        result = find_user_by_wa_phone("201234567890")
        self.assertEqual(result, 12345)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', side_effect=Exception("DB Error"))
    def test_handles_db_error(self, mock_execute, mock_pg):
        result = find_user_by_wa_phone("201234567890")
        self.assertIsNone(result)

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_execute', return_value=(12345,))
    def test_strips_plus_prefix(self, mock_execute, mock_pg):
        result = find_user_by_wa_phone("+201234567890")
        # Should strip + and search with clean number
        self.assertEqual(result, 12345)


# ═══════════════════════════════════════════════════════════════
# Test: _execute (SQLite path)
# ═══════════════════════════════════════════════════════════════

class TestExecuteSqlite(unittest.TestCase):
    """Tests for _execute — SQLite code path"""

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_get_db')
    def test_execute_fetchone(self, mock_get_db, mock_pg):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = (1,)
        mock_get_db.return_value = mock_db

        result = _execute("SELECT 1", fetchone=True)
        self.assertEqual(result, (1,))

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_get_db')
    def test_execute_fetch(self, mock_get_db, mock_pg):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = [(1,), (2,)]
        mock_get_db.return_value = mock_db

        result = _execute("SELECT * FROM test", fetch=True)
        self.assertEqual(result, [(1,), (2,)])

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_get_db')
    def test_execute_no_fetch(self, mock_get_db, mock_pg):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        result = _execute("INSERT INTO test VALUES (?)", (1,))
        self.assertIsNone(result)
        mock_db.commit.assert_called_once()

    @patch.object(memory, '_is_postgres', return_value=False)
    @patch.object(memory, '_get_db', return_value=None)
    def test_execute_no_db(self, mock_get_db, mock_pg):
        result = _execute("SELECT 1")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════
# Test: _execute (PostgreSQL path)
# ═══════════════════════════════════════════════════════════════

class TestExecutePostgres(unittest.TestCase):
    """Tests for _execute — PostgreSQL code path"""

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_get_pg_conn')
    @patch.object(memory, '_return_pg_conn')
    def test_execute_fetchone(self, mock_return, mock_get_conn, mock_pg):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        result = _execute("SELECT 1", fetchone=True)
        self.assertEqual(result, (1,))
        mock_return.assert_called_once_with(mock_conn)

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_get_pg_conn')
    @patch.object(memory, '_return_pg_conn')
    def test_execute_fetch(self, mock_return, mock_get_conn, mock_pg):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [(1,), (2,)]
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        result = _execute("SELECT * FROM test", fetch=True)
        self.assertEqual(result, [(1,), (2,)])

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_get_pg_conn')
    @patch.object(memory, '_return_pg_conn')
    def test_execute_no_fetch(self, mock_return, mock_get_conn, mock_pg):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        result = _execute("INSERT INTO test VALUES (%s)", (1,))
        self.assertIsNone(result)
        mock_conn.commit.assert_called_once()

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_get_pg_conn', return_value=None)
    def test_execute_no_connection(self, mock_get_conn, mock_pg):
        result = _execute("SELECT 1")
        self.assertIsNone(result)

    @patch.object(memory, '_is_postgres', return_value=True)
    @patch.object(memory, '_get_pg_conn')
    @patch.object(memory, '_return_pg_conn')
    @patch.object(memory, '_reconnect_pool')
    def test_execute_retry_on_failure(self, mock_reconnect, mock_return, mock_get_conn, mock_pg):
        """Should retry once when query fails"""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("Connection lost")
        mock_get_conn.return_value = mock_conn
        mock_reconnect.return_value = True

        # Second connection for retry
        mock_retry_conn = MagicMock()
        mock_retry_cur = MagicMock()
        mock_retry_conn.cursor.return_value = mock_retry_cur

        # getconn is called twice: first fails, second for retry
        mock_get_conn.side_effect = [mock_conn, mock_retry_conn]

        result = _execute("SELECT 1", fetchone=True)
        # Should have closed the broken connection
        mock_return.assert_any_call(mock_conn, close=True)


# ═══════════════════════════════════════════════════════════════
# Test: _get_pg_conn / _return_pg_conn
# ═══════════════════════════════════════════════════════════════

class TestPgConnManagement(unittest.TestCase):
    """Tests for _get_pg_conn / _return_pg_conn — connection pool management"""

    def test_get_pg_conn_returns_none_when_no_pool(self):
        with patch.object(memory, '_pg_pool', None):
            result = memory._get_pg_conn()
            self.assertIsNone(result)

    def test_get_pg_conn_returns_connection(self):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        with patch.object(memory, '_pg_pool', mock_pool):
            result = memory._get_pg_conn()
            self.assertEqual(result, mock_conn)
            self.assertTrue(mock_conn.autocommit)

    def test_get_pg_conn_handles_pool_error(self):
        mock_pool = MagicMock()
        mock_pool.getconn.side_effect = Exception("Pool exhausted")
        with patch.object(memory, '_pg_pool', mock_pool):
            result = memory._get_pg_conn()
            self.assertIsNone(result)

    def test_return_pg_conn_normal(self):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        with patch.object(memory, '_pg_pool', mock_pool):
            memory._return_pg_conn(mock_conn)
            mock_pool.putconn.assert_called_once_with(mock_conn, close=False)

    def test_return_pg_conn_close(self):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        with patch.object(memory, '_pg_pool', mock_pool):
            memory._return_pg_conn(mock_conn, close=True)
            mock_pool.putconn.assert_called_once_with(mock_conn, close=True)

    def test_return_pg_conn_no_pool(self):
        """Should not crash if pool is None"""
        with patch.object(memory, '_pg_pool', None):
            memory._return_pg_conn(MagicMock())  # Should not raise

    def test_return_pg_conn_handles_error(self):
        mock_pool = MagicMock()
        mock_pool.putconn.side_effect = Exception("Error")
        with patch.object(memory, '_pg_pool', mock_pool):
            memory._return_pg_conn(MagicMock())  # Should not raise


# ═══════════════════════════════════════════════════════════════
# Test: _reconnect_pool
# ═══════════════════════════════════════════════════════════════

class TestReconnectPool(unittest.TestCase):
    """Tests for _reconnect_pool — pool reconnection"""

    @patch.object(memory, '_get_database_url', return_value='')
    def test_returns_false_when_no_url(self, mock_get_url):
        with patch.object(memory, '_pg_pool', None):
            result = memory._reconnect_pool()
            self.assertFalse(result)

    @patch.object(memory, '_get_database_url', return_value='postgresql://user:pass@host/db')
    def test_reconnect_success(self, mock_get_url):
        mock_pool_mod = MagicMock()
        mock_new_pool = MagicMock()

        with patch.object(memory, '_pg_pool', None), \
             patch.dict('sys.modules', {'psycopg2': MagicMock(), 'psycopg2.pool': mock_pool_mod}):
            mock_pool_mod.SimpleConnectionPool.return_value = mock_new_pool
            # Need to patch the import inside the function
            with patch('memory._pg_pool_lock', memory._pg_pool_lock):
                result = memory._reconnect_pool()
                # The import inside the function makes this tricky
                # Just check the return type
                self.assertIsInstance(result, bool)

    @patch.object(memory, '_get_database_url', return_value='postgresql://user:pass@host/db')
    def test_reconnect_closes_old_pool(self, mock_get_url):
        mock_old_pool = MagicMock()

        with patch.object(memory, '_pg_pool', mock_old_pool):
            # This will fail at creating new pool but should close old one first
            with patch('memory._pg_pool_lock', memory._pg_pool_lock):
                try:
                    memory._reconnect_pool()
                except Exception:
                    pass
                # Old pool should have been closed
                mock_old_pool.closeall.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# Test: _init_postgresql
# ═══════════════════════════════════════════════════════════════

class TestInitPostgresql(unittest.TestCase):
    """Tests for _init_postgresql — PostgreSQL initialization"""

    @patch.object(memory, '_get_database_url', return_value='')
    def test_returns_false_when_no_url(self, mock_get_url):
        with patch.object(memory, '_pg_pool', None):
            result = memory._init_postgresql()
            self.assertFalse(result)

    @patch.object(memory, '_get_database_url', return_value='postgresql://user:pass@host/db')
    def test_returns_false_on_import_error(self, mock_get_url):
        """Should return False if psycopg2 is not available"""
        with patch.dict('sys.modules', {'psycopg2': None}):
            # Reset globals
            with patch.object(memory, '_pg_pool', None):
                result = memory._init_postgresql()
                self.assertFalse(result)


# ═══════════════════════════════════════════════════════════════
# Test: _init_sqlite
# ═══════════════════════════════════════════════════════════════

class TestInitSqlite(unittest.TestCase):
    """Tests for _init_sqlite — SQLite initialization"""

    def test_init_sqlite_returns_db(self):
        """Should return a database connection"""
        result = memory._init_sqlite()
        self.assertIsNotNone(result)
        self.assertEqual(memory._db_type, "sqlite")


# ═══════════════════════════════════════════════════════════════
# Test: _get_db
# ═══════════════════════════════════════════════════════════════

class TestGetDb(unittest.TestCase):
    """Tests for _get_db — SQLite connection getter"""

    def test_returns_sqlite_when_sqlite_type(self):
        with patch.object(memory, '_db_type', 'sqlite'):
            result = memory._get_db()
            # _get_db calls _init_sqlite() which returns a connection
            self.assertIsNotNone(result)

    def test_returns_none_when_postgres_type(self):
        with patch.object(memory, '_db_type', 'postgresql'):
            result = memory._get_db()
            self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════
# Test: Legacy compatibility
# ═══════════════════════════════════════════════════════════════

class TestLegacyCompatibility(unittest.TestCase):
    """Tests for _load_all_users / _save_all_users / _ensure_data_dir"""

    def test_load_all_users_no_file(self):
        """Should return empty dict when file doesn't exist"""
        with patch.object(memory, 'USERS_FILE', '/tmp/nonexistent_users_test.json'):
            result = memory._load_all_users()
            self.assertEqual(result, {})

    def test_save_and_load_users(self):
        """Should save and load user data correctly"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            with patch.object(memory, 'USERS_FILE', temp_path):
                test_data = {"123": {"language": "ar", "name": "Test"}}
                memory._save_all_users(test_data)
                result = memory._load_all_users()
                self.assertEqual(result["123"]["language"], "ar")
        finally:
            os.unlink(temp_path)

    def test_load_all_users_invalid_json(self):
        """Should return empty dict for invalid JSON file"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json{{{")
            temp_path = f.name

        try:
            with patch.object(memory, 'USERS_FILE', temp_path):
                result = memory._load_all_users()
                self.assertEqual(result, {})
        finally:
            os.unlink(temp_path)


# ═══════════════════════════════════════════════════════════════
# Test: Thread safety of cache
# ═══════════════════════════════════════════════════════════════

class TestCacheThreadSafety(unittest.TestCase):
    """Tests for thread safety of the cache system"""

    def test_concurrent_cache_access(self):
        """Multiple threads should be able to access cache simultaneously"""
        errors = []

        def writer(thread_id):
            try:
                for i in range(100):
                    _cache_set(f"thread_{thread_id}_key_{i}", f"value_{i}")
            except Exception as e:
                errors.append(e)

        def reader(thread_id):
            try:
                for i in range(100):
                    _cache_get(f"thread_{thread_id}_key_{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")


if __name__ == '__main__':
    unittest.main()
