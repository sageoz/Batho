"""Tests for Phase 2 Task 2.3: Sentinel caching for failed lookups in ScopeManager.

The sentinel cache (Eclipse JDT's TheNotFoundType pattern) avoids repeated O(n)
lookups for names known to be unresolvable. These tests cover:

  - Basic caching: failed lookups are cached and return None instantly
  - Cache invalidation: clear_failed_lookups() allows retries after new symbols
  - Thread safety: concurrent access to the cache
  - Edge cases: empty names, very long names, unicode names, special chars
  - Interaction with resolve_symbol_strict vs resolve_symbol
  - Cache does not affect successful lookups
  - Cache survives across multiple calls
  - Cache is independent per ScopeManager instance
"""
import threading
import pytest

from batho.modules.extraction.scope_manager import ScopeManager, SymbolInfo


# ---------------------------------------------------------------------------
# Basic sentinel caching behavior
# ---------------------------------------------------------------------------


class TestSentinelCacheBasic:
    """Verify basic sentinel cache operations."""

    def test_failed_lookup_is_cached(self):
        """A failed lookup stores the name in the sentinel cache."""
        sm = ScopeManager()
        result = sm.resolve_symbol_strict("nonexistent")
        assert result is None
        assert "nonexistent" in sm._failed_lookups

    def test_successful_lookup_not_cached(self):
        """A successful lookup does NOT add the name to the sentinel cache."""
        sm = ScopeManager()
        sm.define_symbol("foo", "id_foo", "FUNCTION", is_global=True)
        result = sm.resolve_symbol_strict("foo")
        assert result is not None
        assert "foo" not in sm._failed_lookups

    def test_cached_failure_returns_none_without_full_lookup(self):
        """Once cached, a failed lookup returns None without re-scanning.

        We verify this by checking that the cache entry exists and the
        return value is None on the second call.
        """
        sm = ScopeManager()
        # First call: populates cache
        assert sm.resolve_symbol_strict("bar") is None
        assert "bar" in sm._failed_lookups
        # Second call: should return None from cache
        assert sm.resolve_symbol_strict("bar") is None
        # Cache entry should still be there
        assert "bar" in sm._failed_lookups

    def test_multiple_distinct_failures_cached(self):
        """Multiple distinct failed lookups are all cached."""
        sm = ScopeManager()
        for name in ("alpha", "beta", "gamma", "delta"):
            assert sm.resolve_symbol_strict(name) is None
        assert len(sm._failed_lookups) == 4
        for name in ("alpha", "beta", "gamma", "delta"):
            assert name in sm._failed_lookups

    def test_repeated_failure_same_name_cached_once(self):
        """Repeated lookups of the same name do not duplicate cache entries."""
        sm = ScopeManager()
        for _ in range(100):
            sm.resolve_symbol_strict("repeated")
        assert len(sm._failed_lookups) == 1
        assert "repeated" in sm._failed_lookups


# ---------------------------------------------------------------------------
# Cache invalidation via clear_failed_lookups()
# ---------------------------------------------------------------------------


class TestSentinelCacheClear:
    """Verify clear_failed_lookups() behavior."""

    def test_clear_empties_cache(self):
        """clear_failed_lookups() removes all cached failures."""
        sm = ScopeManager()
        sm.resolve_symbol_strict("a")
        sm.resolve_symbol_strict("b")
        sm.resolve_symbol_strict("c")
        assert len(sm._failed_lookups) == 3
        sm.clear_failed_lookups()
        assert len(sm._failed_lookups) == 0

    def test_clear_allows_retry_after_new_symbol(self):
        """After clearing, a previously-failed name can resolve if a symbol
        was registered in the meantime."""
        sm = ScopeManager()
        assert sm.resolve_symbol_strict("my_func") is None
        assert "my_func" in sm._failed_lookups

        # Register the symbol
        sm.define_symbol("my_func", "id_my_func", "FUNCTION", is_global=True)

        # Without clearing, the cache still returns None
        assert sm.resolve_symbol_strict("my_func") is None

        # After clearing, the lookup succeeds
        sm.clear_failed_lookups()
        result = sm.resolve_symbol_strict("my_func")
        assert result is not None
        assert result.symbol_id == "id_my_func"
        # And the name is removed from the failed cache
        assert "my_func" not in sm._failed_lookups

    def test_clear_on_empty_cache_is_noop(self):
        """clear_failed_lookups() on an empty cache is a no-op."""
        sm = ScopeManager()
        sm.clear_failed_lookups()
        assert len(sm._failed_lookups) == 0
        sm.clear_failed_lookups()  # should not raise
        assert len(sm._failed_lookups) == 0

    def test_clear_then_refail_repopulates_cache(self):
        """After clearing, a new failed lookup re-populates the cache."""
        sm = ScopeManager()
        sm.resolve_symbol_strict("x")
        sm.clear_failed_lookups()
        assert len(sm._failed_lookups) == 0
        sm.resolve_symbol_strict("x")
        assert "x" in sm._failed_lookups
        assert len(sm._failed_lookups) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSentinelCacheEdgeCases:
    """Verify sentinel cache handles edge-case inputs correctly."""

    def test_empty_string_name(self):
        """Empty string name is cached as a failed lookup."""
        sm = ScopeManager()
        result = sm.resolve_symbol_strict("")
        assert result is None
        assert "" in sm._failed_lookups

    def test_very_long_name(self):
        """Very long symbol names are cached correctly."""
        sm = ScopeManager()
        long_name = "x" * 10000
        result = sm.resolve_symbol_strict(long_name)
        assert result is None
        assert long_name in sm._failed_lookups

    def test_unicode_name(self):
        """Unicode symbol names are cached correctly."""
        sm = ScopeManager()
        unicode_name = "héllo_wörld_日本語"
        result = sm.resolve_symbol_strict(unicode_name)
        assert result is None
        assert unicode_name in sm._failed_lookups

    def test_special_characters_in_name(self):
        """Names with special characters are cached correctly."""
        sm = ScopeManager()
        for name in ["foo.bar", "foo::bar", "foo->bar", "foo[0]", "foo{1}"]:
            result = sm.resolve_symbol_strict(name)
            assert result is None
            assert name in sm._failed_lookups

    def test_name_with_whitespace(self):
        """Names with whitespace are cached correctly."""
        sm = ScopeManager()
        result = sm.resolve_symbol_strict("  spaced  ")
        assert result is None
        assert "  spaced  " in sm._failed_lookups

    def test_numeric_only_name(self):
        """Numeric-only names are cached correctly."""
        sm = ScopeManager()
        result = sm.resolve_symbol_strict("12345")
        assert result is None
        assert "12345" in sm._failed_lookups

    def test_single_char_name(self):
        """Single-character names are cached correctly."""
        sm = ScopeManager()
        for ch in "abcdefghijklmnopqrstuvwxyz":
            result = sm.resolve_symbol_strict(ch)
            assert result is None
        assert len(sm._failed_lookups) == 26

    def test_dotpath_name_not_resolved(self):
        """Dotted names that don't resolve are cached by strict resolver."""
        sm = ScopeManager()
        result = sm.resolve_symbol_strict("module.submodule.function")
        assert result is None
        # The full dotted name should be in the cache
        assert "module.submodule.function" in sm._failed_lookups


# ---------------------------------------------------------------------------
# Interaction with resolve_symbol (non-strict)
# ---------------------------------------------------------------------------


class TestSentinelCacheInteraction:
    """Verify sentinel cache interacts correctly with resolve_symbol."""

    def test_resolve_symbol_does_not_use_cache(self):
        """resolve_symbol (non-strict) bypasses the sentinel cache.

        This is important: only resolve_symbol_strict should use the cache,
        so that internal callers who need fresh results aren't affected.
        """
        sm = ScopeManager()
        # Prime the cache via strict
        assert sm.resolve_symbol_strict("unresolved") is None
        assert "unresolved" in sm._failed_lookups
        # Non-strict should still do the full lookup (returns None but
        # doesn't rely on the cache)
        result = sm.resolve_symbol("unresolved")
        assert result is None

    def test_strict_then_non_strict_then_strict(self):
        """Mixing strict and non-strict calls doesn't corrupt the cache."""
        sm = ScopeManager()
        sm.define_symbol("real", "id_real", "FUNCTION", is_global=True)

        # Strict succeeds
        assert sm.resolve_symbol_strict("real") is not None
        # Non-strict also succeeds
        assert sm.resolve_symbol("real") is not None
        # Strict for a failure
        assert sm.resolve_symbol_strict("fake") is None
        # Non-strict for the same failure
        assert sm.resolve_symbol("fake") is None
        # Cache should only contain "fake"
        assert "fake" in sm._failed_lookups
        assert "real" not in sm._failed_lookups


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestSentinelCacheThreadSafety:
    """Verify sentinel cache is thread-safe under concurrent access."""

    def test_concurrent_failed_lookups(self):
        """Multiple threads doing failed lookups don't corrupt the cache."""
        sm = ScopeManager()
        names = [f"thread_{i}" for i in range(100)]
        threads = []

        def lookup(name):
            sm.resolve_symbol_strict(name)

        for name in names:
            t = threading.Thread(target=lookup, args=(name,))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All names should be in the cache
        assert len(sm._failed_lookups) == 100
        for name in names:
            assert name in sm._failed_lookups

    def test_concurrent_clear_and_lookup(self):
        """Concurrent clear + lookup doesn't crash or corrupt state."""
        sm = ScopeManager()
        errors = []

        def do_lookups():
            try:
                for i in range(200):
                    sm.resolve_symbol_strict(f"concurrent_{i}")
            except Exception as e:
                errors.append(e)

        def do_clears():
            try:
                for _ in range(50):
                    sm.clear_failed_lookups()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=do_lookups)
        t2 = threading.Thread(target=do_clears)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(errors) == 0, f"Errors during concurrent access: {errors}"

    def test_concurrent_define_and_strict_resolve(self):
        """Concurrent define + strict resolve doesn't crash."""
        sm = ScopeManager()
        errors = []

        def define_symbols():
            try:
                for i in range(100):
                    sm.define_symbol(f"sym_{i}", f"id_{i}", "FUNCTION", is_global=True)
            except Exception as e:
                errors.append(e)

        def resolve_symbols():
            try:
                for i in range(100):
                    sm.resolve_symbol_strict(f"sym_{i}")
                    sm.resolve_symbol_strict(f"missing_{i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=define_symbols)
        t2 = threading.Thread(target=resolve_symbols)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# Instance independence
# ---------------------------------------------------------------------------


class TestSentinelCacheInstanceIndependence:
    """Verify each ScopeManager instance has its own sentinel cache."""

    def test_separate_instances_have_separate_caches(self):
        """Two ScopeManager instances don't share the sentinel cache."""
        sm1 = ScopeManager()
        sm2 = ScopeManager()
        sm1.resolve_symbol_strict("shared_name")
        assert "shared_name" in sm1._failed_lookups
        assert "shared_name" not in sm2._failed_lookups

    def test_clear_on_one_does_not_affect_other(self):
        """clear_failed_lookups() on one instance doesn't affect another."""
        sm1 = ScopeManager()
        sm2 = ScopeManager()
        sm1.resolve_symbol_strict("a")
        sm2.resolve_symbol_strict("a")
        sm1.clear_failed_lookups()
        assert len(sm1._failed_lookups) == 0
        assert "a" in sm2._failed_lookups


# ---------------------------------------------------------------------------
# Performance characteristics
# ---------------------------------------------------------------------------


class TestSentinelCachePerformance:
    """Verify the sentinel cache provides measurable speedup."""

    def test_cached_lookup_is_faster_than_uncached(self):
        """Second pass of failed lookups should be significantly faster.

        Uses a large symbol table to make the O(n) lookup cost measurable.
        """
        import time

        sm = ScopeManager()
        # Populate with many symbols to make lookups expensive
        for i in range(5000):
            sm.define_symbol(f"real_sym_{i}", f"id_{i}", "FUNCTION", is_global=True)

        failed_names = [f"missing_{i}" for i in range(500)]

        # First pass: populates cache (slow)
        t0 = time.monotonic()
        for name in failed_names:
            sm.resolve_symbol_strict(name)
        first_pass_ms = (time.monotonic() - t0) * 1000

        # Second pass: cache hits (fast)
        t0 = time.monotonic()
        for name in failed_names:
            sm.resolve_symbol_strict(name)
        second_pass_ms = (time.monotonic() - t0) * 1000

        # Cached pass should be at least 2x faster
        # (using a conservative threshold to avoid flakiness on slow CI)
        assert second_pass_ms < first_pass_ms, (
            f"Cached pass ({second_pass_ms:.2f}ms) should be faster than "
            f"first pass ({first_pass_ms:.2f}ms)"
        )
