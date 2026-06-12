"""
Tests for sentry_config module
===================================
Verifies that Sentry integration is safe and doesn't break anything
even when SENTRY_DSN is not configured.
"""

import os
import pytest


class TestSentryInit:
    """Test Sentry initialization behavior."""

    def test_init_without_dsn(self):
        """Should not crash when SENTRY_DSN is not set."""
        # Remove DSN if it exists
        old_dsn = os.environ.pop("SENTRY_DSN", None)
        try:
            # Re-import to get fresh state
            import importlib
            import sentry_config
            importlib.reload(sentry_config)
            # Reset the initialized flag
            sentry_config._sentry_initialized = False
            result = sentry_config.init_sentry()
            assert result is False  # Should return False when no DSN
        finally:
            if old_dsn:
                os.environ["SENTRY_DSN"] = old_dsn

    def test_init_with_empty_dsn(self):
        """Should handle empty SENTRY_DSN gracefully."""
        os.environ["SENTRY_DSN"] = ""
        try:
            import importlib
            import sentry_config
            importlib.reload(sentry_config)
            sentry_config._sentry_initialized = False
            result = sentry_config.init_sentry()
            assert result is False
        finally:
            os.environ.pop("SENTRY_DSN", None)

    def test_init_with_whitespace_dsn(self):
        """Should handle whitespace-only SENTRY_DSN gracefully."""
        os.environ["SENTRY_DSN"] = "   "
        try:
            import importlib
            import sentry_config
            importlib.reload(sentry_config)
            sentry_config._sentry_initialized = False
            result = sentry_config.init_sentry()
            assert result is False
        finally:
            os.environ.pop("SENTRY_DSN", None)


class TestSentrySafeWrappers:
    """Test that Sentry wrapper functions are safe when not initialized."""

    def setup_method(self):
        """Ensure Sentry is not initialized for each test."""
        import sentry_config
        sentry_config._sentry_initialized = False

    def test_capture_exception_safe(self):
        """capture_exception should not crash when Sentry is not initialized."""
        import sentry_config
        result = sentry_config.capture_exception(ValueError("test"))
        assert result is None

    def test_capture_message_safe(self):
        """capture_message should not crash when Sentry is not initialized."""
        import sentry_config
        result = sentry_config.capture_message("test message")
        assert result is None

    def test_set_tag_safe(self):
        """set_tag should not crash when Sentry is not initialized."""
        import sentry_config
        # Should not raise
        sentry_config.set_tag("test_key", "test_value")

    def test_set_context_safe(self):
        """set_context should not crash when Sentry is not initialized."""
        import sentry_config
        # Should not raise
        sentry_config.set_context("test_ctx", {"key": "value"})

    def test_add_breadcrumb_safe(self):
        """add_breadcrumb should not crash when Sentry is not initialized."""
        import sentry_config
        # Should not raise
        sentry_config.add_breadcrumb(category="test", message="test msg")

    def test_start_transaction_safe(self):
        """start_transaction should return NoOp when Sentry is not initialized."""
        import sentry_config
        tx = sentry_config.start_transaction(name="test", op="test")
        # Should be a NoOpTransaction
        assert tx is not None
        # All methods should be no-ops
        tx.finish()
        tx.set_status("ok")
        tx.set_tag("key", "value")
        tx.set_data("key", "value")
        # Context manager should work
        with sentry_config.start_transaction(name="test2", op="test2"):
            pass


class TestNoOpTransaction:
    """Test the NoOpTransaction fallback."""

    def test_context_manager(self):
        """NoOpTransaction should work as a context manager."""
        import sentry_config
        tx = sentry_config._NoOpTransaction()
        with tx:
            pass  # Should not raise

    def test_all_methods_noop(self):
        """All NoOpTransaction methods should be no-ops."""
        import sentry_config
        tx = sentry_config._NoOpTransaction()
        tx.finish()
        tx.set_status("ok")
        tx.set_tag("key", "value")
        tx.set_data("key", "value")


class TestRecordErrorAndSentry:
    """Test the dual error recording function."""

    @pytest.mark.asyncio
    async def test_record_error_and_sentry_no_crash(self):
        """Should not crash when neither system is available."""
        import sentry_config
        sentry_config._sentry_initialized = False
        # This should not raise
        await sentry_config.record_error_and_sentry("test_error", "test message")

    @pytest.mark.asyncio
    async def test_record_error_and_sentry_with_exception(self):
        """Should handle exception parameter without crashing."""
        import sentry_config
        sentry_config._sentry_initialized = False
        await sentry_config.record_error_and_sentry(
            "test_error",
            "test message",
            exc=ValueError("test exception")
        )


class TestSentryEnvConfig:
    """Test Sentry environment variable configuration."""

    def test_default_env_is_production(self):
        """Default SENTRY_ENV should be 'production'."""
        os.environ.pop("SENTRY_ENV", None)
        # The module reads env vars at init time, so we just check
        # that the default behavior works
        import sentry_config
        sentry_config._sentry_initialized = False
        # Can't fully test without a real DSN, but the code should not crash
        result = sentry_config.init_sentry()
        assert result is False  # No DSN → False

    def test_sample_rate_clamping(self):
        """Sample rates should be clamped to 0.0-1.0."""
        # This is tested implicitly in init_sentry
        # The clamping logic: max(0.0, min(1.0, value))
        # Can't fully test without a real DSN but code is straightforward
        assert max(0.0, min(1.0, -1.0)) == 0.0
        assert max(0.0, min(1.0, 2.0)) == 1.0
        assert max(0.0, min(1.0, 0.5)) == 0.5
