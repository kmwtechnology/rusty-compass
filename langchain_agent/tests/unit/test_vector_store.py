"""
Phase 1 Tests: Vector store validation and hybrid search.

Tests cover:
- Alpha parameter validation (bounds checking)
- Hybrid search with valid/invalid alpha values
- Search result validation
- OpenSearch connection handling
- Error propagation (no silent failures)
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from langchain_core.documents import Document

from exceptions import SearchValidationError, SearchFailureError


# ============================================================================
# ALPHA PARAMETER VALIDATION TESTS
# ============================================================================


class TestAlphaParameterValidation:
    """Tests for alpha parameter validation in hybrid search."""

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_alpha_lower_bound_valid(self, mock_os, mock_embed):
        """Alpha of exactly 0.0 should be valid (pure lexical)."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        mock_os_instance.search.return_value = {"hits": {"hits": []}}

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        # Should not raise
        try:
            vector_store.hybrid_search("test query", alpha=0.0)
        except SearchValidationError:
            pytest.fail("Alpha=0.0 should be valid")

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_alpha_upper_bound_valid(self, mock_os, mock_embed):
        """Alpha of exactly 1.0 should be valid (pure semantic)."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        mock_os_instance.search.return_value = {"hits": {"hits": []}}

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        # Should not raise
        try:
            vector_store.hybrid_search("test query", alpha=1.0)
        except SearchValidationError:
            pytest.fail("Alpha=1.0 should be valid")

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_alpha_midrange_valid(self, mock_os, mock_embed):
        """Alpha values in middle range should be valid."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        mock_os_instance.search.return_value = {"hits": {"hits": []}}

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        for test_alpha in [0.25, 0.5, 0.75]:
            try:
                vector_store.hybrid_search("test query", alpha=test_alpha)
            except SearchValidationError:
                pytest.fail(f"Alpha={test_alpha} should be valid")

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_alpha_below_lower_bound(self, mock_os, mock_embed):
        """Alpha below 0.0 should raise SearchValidationError."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        with pytest.raises(SearchValidationError) as exc_info:
            vector_store.hybrid_search("test query", alpha=-0.1)
        assert "alpha" in str(exc_info.value).lower()

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_alpha_above_upper_bound(self, mock_os, mock_embed):
        """Alpha above 1.0 should raise SearchValidationError."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        with pytest.raises(SearchValidationError) as exc_info:
            vector_store.hybrid_search("test query", alpha=1.5)
        assert "alpha" in str(exc_info.value).lower()


# ============================================================================
# K AND FETCH_K PARAMETER VALIDATION
# ============================================================================


class TestKAndFetchKValidation:
    """Tests for k and fetch_k parameter validation."""

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_fetch_k_less_than_k_raises_error(self, mock_os, mock_embed):
        """fetch_k < k should raise SearchValidationError."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        with pytest.raises(SearchValidationError) as exc_info:
            vector_store.hybrid_search("test query", k=20, fetch_k=10)
        assert "fetch_k" in str(exc_info.value).lower() or "k" in str(exc_info.value).lower()

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_k_zero_or_negative_raises_error(self, mock_os, mock_embed):
        """k <= 0 should raise SearchValidationError."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        with pytest.raises(SearchValidationError):
            vector_store.hybrid_search("test query", k=0)

        with pytest.raises(SearchValidationError):
            vector_store.hybrid_search("test query", k=-5)


# ============================================================================
# SEARCH RESULT VALIDATION
# ============================================================================


class TestSearchResultValidation:
    """Tests for search result validation."""

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_search_returns_documents_list(self, mock_os, mock_embed, sample_documents):
        """Search should return list of Documents."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        # Mock hybrid search response
        mock_os_instance.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": f"doc{i}",
                        "_score": score,
                        "_source": {
                            "content": doc.page_content,
                            "url": doc.metadata.get("url", ""),
                        },
                    }
                    for i, (doc, score) in enumerate(zip(sample_documents, [0.9, 0.8, 0.7]))
                ]
            }
        }

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")
        results = vector_store.hybrid_search("test query", k=3)

        assert isinstance(results, list)
        assert len(results) <= 3
        assert all(isinstance(doc, Document) for doc in results)

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_search_respects_k_limit(self, mock_os, mock_embed, sample_documents):
        """Search should return at most k documents."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        # Return more documents than requested
        mock_os_instance.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": f"doc{i}",
                        "_score": 0.9 - i * 0.1,
                        "_source": {"content": f"doc {i}", "url": ""},
                    }
                    for i in range(20)  # Return 20 docs
                ]
            }
        }

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")
        results = vector_store.hybrid_search("test query", k=5)

        assert len(results) <= 5

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_empty_search_results(self, mock_os, mock_embed):
        """Search with no matches should return empty list."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        mock_os_instance.search.return_value = {"hits": {"hits": []}}

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")
        results = vector_store.hybrid_search("nonexistent query", k=5)

        assert results == []


# ============================================================================
# ERROR HANDLING (NO SILENT FAILURES)
# ============================================================================


class TestErrorHandling:
    """Tests for error handling and no silent failures."""

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_opensearch_connection_error_raises(self, mock_os, mock_embed):
        """OpenSearch connection errors should raise SearchFailureError."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        # Simulate connection error
        mock_os_instance.search.side_effect = Exception("Connection refused")

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        with pytest.raises(SearchFailureError):
            vector_store.hybrid_search("test query")

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_embedding_error_raises(self, mock_os, mock_embed):
        """Embedding generation errors should raise appropriate exception."""
        from vector_store import OpenSearchVectorStore
        from exceptions import EmbeddingError

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        # Simulate embedding error
        mock_embed_instance.embed_query.side_effect = Exception("API quota exceeded")

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        with pytest.raises((EmbeddingError, Exception)):
            vector_store.hybrid_search("test query")

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_timeout_error_raises(self, mock_os, mock_embed):
        """Search timeout should raise SearchTimeoutError."""
        from vector_store import OpenSearchVectorStore
        from exceptions import SearchTimeoutError

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        # Simulate timeout
        mock_os_instance.search.side_effect = TimeoutError("Request timed out")

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        # Should raise error, not return empty list
        with pytest.raises((SearchTimeoutError, TimeoutError)):
            vector_store.hybrid_search("test query")


# ============================================================================
# COLLECTION ID VALIDATION
# ============================================================================


class TestCollectionIDValidation:
    """Tests for collection ID validation."""

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_empty_collection_id_raises_error(self, mock_os, mock_embed):
        """Empty collection ID should raise error."""
        from vector_store import OpenSearchVectorStore

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance

        with pytest.raises(Exception):  # Should raise during __init__ or validation
            OpenSearchVectorStore(mock_embed_instance, "")

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_none_collection_id_raises_error(self, mock_os, mock_embed):
        """None collection ID should raise error."""
        from vector_store import OpenSearchVectorStore

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance

        with pytest.raises(Exception):  # Should raise during __init__ or validation
            OpenSearchVectorStore(mock_embed_instance, None)


# ============================================================================
# INTEGRATION: MULTIPLE SEARCHES
# ============================================================================


class TestMultipleSearches:
    """Tests for multiple consecutive searches."""

    @patch("vector_store.GoogleGenerativeAIEmbeddings")
    @patch("vector_store.OpenSearch")
    def test_multiple_searches_independent(self, mock_os, mock_embed):
        """Multiple searches should be independent."""
        from vector_store import OpenSearchVectorStore

        mock_os_instance = MagicMock()
        mock_os.return_value = mock_os_instance
        mock_os_instance.search.return_value = {"hits": {"hits": []}}

        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        mock_embed_instance.embed_query.return_value = [0.1] * 768

        vector_store = OpenSearchVectorStore(mock_embed_instance, "test_collection")

        # Perform multiple searches with different parameters
        results1 = vector_store.hybrid_search("query1", alpha=0.3)
        results2 = vector_store.hybrid_search("query2", alpha=0.7)
        results3 = vector_store.hybrid_search("query3", alpha=0.5)

        # All should complete without error
        assert results1 is not None
        assert results2 is not None
        assert results3 is not None
