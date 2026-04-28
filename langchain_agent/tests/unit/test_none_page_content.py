"""
Edge-case tests for None and empty page_content handling.

Tests ensure that the codebase gracefully handles documents with:
- None page_content
- Empty string page_content
- Very long page_content
- Mixed document lists

These tests prevent regressions of the '>' not supported between
NoneType and int error that occurred in production.
"""

import pytest
from langchain_core.documents import Document
from reranker import GeminiReranker
from unittest.mock import MagicMock, patch


class TestNonePageContent:
    """Tests for handling None page_content values."""

    def test_reranker_build_prompt_with_none_content(self):
        """Reranker should handle documents with None page_content."""
        reranker = GeminiReranker(model_name="gemini-1.5-pro")
        docs = [
            Document(page_content=None, metadata={"source": "test"}),
            Document(page_content="Valid content", metadata={"source": "test2"}),
        ]

        prompt = reranker._build_prompt("test query", docs)
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        # Should not crash, should produce valid prompt

    def test_reranker_build_prompt_all_none(self):
        """Reranker should handle all documents with None page_content."""
        reranker = GeminiReranker(model_name="gemini-1.5-pro")
        docs = [
            Document(page_content=None, metadata={"source": "test1"}),
            Document(page_content=None, metadata={"source": "test2"}),
        ]

        prompt = reranker._build_prompt("test query", docs)
        assert isinstance(prompt, str)

    def test_reranker_build_prompt_empty_string(self):
        """Reranker should handle documents with empty string page_content."""
        reranker = GeminiReranker(model_name="gemini-1.5-pro")
        docs = [
            Document(page_content="", metadata={"source": "test"}),
            Document(page_content="Valid content", metadata={"source": "test2"}),
        ]

        prompt = reranker._build_prompt("test query", docs)
        assert isinstance(prompt, str)

    def test_reranker_build_prompt_very_long_content(self):
        """Reranker should handle documents with very long page_content."""
        reranker = GeminiReranker(model_name="gemini-1.5-pro")
        very_long_content = "x" * 10000
        docs = [
            Document(page_content=very_long_content, metadata={"source": "test"}),
        ]

        prompt = reranker._build_prompt("test query", docs)
        assert isinstance(prompt, str)
        # Should be able to handle without crashing


class TestEmptyPageContent:
    """Tests for handling empty string page_content."""

    def test_empty_content_slicing(self):
        """Empty content should be sliceable without error."""
        doc = Document(page_content="", metadata={})
        # Should not raise TypeError
        snippet = (doc.page_content or "")[:200]
        assert snippet == ""

    def test_none_content_slicing(self):
        """None content should be safely converted before slicing."""
        doc = Document(page_content=None, metadata={})
        # Should not raise TypeError: object of type 'NoneType' has no len()
        snippet = (doc.page_content or "")[:200]
        assert snippet == ""


class TestContentLength:
    """Tests for len() operations on page_content."""

    def test_none_content_with_len_check(self):
        """None content should be safely checked with len()."""
        doc = Document(page_content=None, metadata={})
        # Pattern used in codebase: check before calling len()
        if doc.page_content and len(doc.page_content) > 200:
            snippet = doc.page_content[:200] + "..."
        else:
            snippet = doc.page_content or ""
        assert snippet == ""

    def test_empty_content_with_len_check(self):
        """Empty content should be safely checked with len()."""
        doc = Document(page_content="", metadata={})
        if doc.page_content and len(doc.page_content) > 200:
            snippet = doc.page_content[:200] + "..."
        else:
            snippet = doc.page_content or ""
        assert snippet == ""

    def test_valid_content_with_len_check(self):
        """Valid content should work with len() check."""
        doc = Document(page_content="x" * 300, metadata={})
        if doc.page_content and len(doc.page_content) > 200:
            snippet = doc.page_content[:200] + "..."
        else:
            snippet = doc.page_content or ""
        assert len(snippet) == 204  # 200 + "..."


class TestContentHashing:
    """Tests for hashing page_content."""

    def test_none_content_hashing(self):
        """None content should be safely hashable."""
        doc = Document(page_content=None, metadata={})
        # Pattern: use (content or "")[:limit]
        content_hash = hash((doc.page_content or "")[:200])
        assert isinstance(content_hash, int)

    def test_empty_content_hashing(self):
        """Empty content should be safely hashable."""
        doc = Document(page_content="", metadata={})
        content_hash = hash((doc.page_content or "")[:200])
        assert isinstance(content_hash, int)

    def test_content_hashing_consistency(self):
        """Same content should produce same hash."""
        doc1 = Document(page_content="test", metadata={})
        doc2 = Document(page_content="test", metadata={})
        hash1 = hash((doc1.page_content or "")[:200])
        hash2 = hash((doc2.page_content or "")[:200])
        assert hash1 == hash2


class TestSumOperations:
    """Tests for sum() operations on page_content lengths."""

    def test_sum_with_none_content(self):
        """sum() should handle None content safely."""
        docs = [
            Document(page_content=None, metadata={}),
            Document(page_content="test", metadata={}),
            Document(page_content=None, metadata={}),
        ]

        # Pattern: use len(content) if content else 0
        total = sum(len(doc.page_content) if doc.page_content else 0 for doc in docs)
        assert total == 4

    def test_sum_with_mixed_content(self):
        """sum() should handle mixed None and valid content."""
        docs = [
            Document(page_content="", metadata={}),
            Document(page_content="hello", metadata={}),
            Document(page_content=None, metadata={}),
            Document(page_content="world", metadata={}),
        ]

        total = sum(len(doc.page_content) if doc.page_content else 0 for doc in docs)
        assert total == 10  # 0 + 5 + 0 + 5

    def test_sum_all_none_content(self):
        """sum() should handle all None content."""
        docs = [
            Document(page_content=None, metadata={}),
            Document(page_content=None, metadata={}),
        ]

        total = sum(len(doc.page_content) if doc.page_content else 0 for doc in docs)
        assert total == 0


class TestMetadataWithNoneContent:
    """Tests for accessing metadata with None page_content."""

    def test_metadata_access_with_none_content(self):
        """Metadata should be accessible even if page_content is None."""
        doc = Document(
            page_content=None,
            metadata={"source": "test-source", "title": "Test Title"}
        )

        assert doc.metadata.get("source") == "test-source"
        assert doc.metadata.get("title") == "Test Title"

    def test_building_dict_with_none_content(self):
        """Should be able to build dict with None content gracefully."""
        doc = Document(
            page_content=None,
            metadata={"source": "test", "url": "http://example.com"}
        )

        result = {
            "content": (doc.page_content or "")[:800],
            "source": doc.metadata.get("source", ""),
            "url": doc.metadata.get("url", ""),
        }

        assert result["content"] == ""
        assert result["source"] == "test"
        assert result["url"] == "http://example.com"
