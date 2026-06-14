"""SemanticCache unit tests — no network, no GPU."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def cache_file():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "test_cache.json"


class TestKeyGeneration:
    def test_same_prompt_same_key(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        k1 = c._make_key("hello world", "deepseek-chat")
        k2 = c._make_key("hello world", "deepseek-chat")
        assert k1 == k2

    def test_different_prompts_different_keys(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        k1 = c._make_key("hello", "deepseek-chat")
        k2 = c._make_key("world", "deepseek-chat")
        assert k1 != k2

    def test_different_models_different_keys(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        k1 = c._make_key("hello", "deepseek-chat")
        k2 = c._make_key("hello", "gpt-4o-mini")
        assert k1 != k2

    def test_whitespace_normalized(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        k1 = c._make_key("  hello   world  ", "m1")
        k2 = c._make_key("hello world", "m1")
        assert k1 == k2


class TestSetGet:
    def test_set_and_get(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        c.set("prompt A", "response A", model="test-model")
        # Without embedder, cache won't verify similarity — returns None
        # So we test only the set/store path here
        assert len(c._store) == 1

    def test_get_missing_key(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        assert c.get("nonexistent", model="m") is None

    def test_set_overwrites(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        c.set("p1", "r1", model="m")
        c.set("p1", "r2", model="m")
        assert len(c._store) == 1
        assert c._store[c._make_key("p1", "m")]["response"] == "r2"


class TestPersistence:
    def test_save_and_reload(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        c.set("p1", "r1", model="m")
        assert cache_file.exists()

        # Reload
        c2 = SemanticCache(cache_file=cache_file)
        assert len(c2._store) == 1
        assert c2._store[c._make_key("p1", "m")]["response"] == "r1"


class TestNormalize:
    def test_strips_whitespace(self):
        from agents.semantic_cache import _normalize

        assert _normalize("  hello   world  ") == "hello world"

    def test_truncates_long_text(self):
        from agents.semantic_cache import _normalize

        long_text = "x" * 3000
        assert len(_normalize(long_text)) <= 2000


class TestCosine:
    def test_identical_vectors(self):
        from agents.semantic_cache import _cosine

        assert _cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        from agents.semantic_cache import _cosine

        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_empty_vectors(self):
        from agents.semantic_cache import _cosine

        assert _cosine([], []) == 0.0


class TestEviction:
    def test_evicts_oldest_when_over_max(self, cache_file):
        from agents.semantic_cache import SemanticCache, MAX_ENTRIES

        c = SemanticCache(cache_file=cache_file)
        for i in range(MAX_ENTRIES + 5):
            c.set(f"prompt_{i}", f"response_{i}", model="m")
        assert len(c._store) <= MAX_ENTRIES


class TestStats:
    def test_stats(self, cache_file):
        from agents.semantic_cache import SemanticCache

        c = SemanticCache(cache_file=cache_file)
        c.set("p1", "r1", model="m")
        s = c.stats()
        assert s["entries"] == 1
        assert "threshold" in s
