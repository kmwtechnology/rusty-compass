"""
Phase 1 Tests: Reranker validation and error handling.

Tests cover:
- Score validation (bounds checking)
- Index validation (range checking)
- Model initialization
- Structured output parsing
- Missing score handling
"""

import pytest
from pydantic import ValidationError
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from reranker import RerankerScore, RerankerScores, GeminiReranker
from exceptions import RerankerValidationError, RerankerLLMError


# ============================================================================
# RERANKER SCORE VALIDATION TESTS
# ============================================================================


class TestRerankerScoreValidation:
    """Tests for RerankerScore Pydantic model validation."""

    def test_valid_score_lower_bound(self):
        """Score of exactly 0.0 should be valid."""
        score = RerankerScore(index=0, score=0.0)
        assert score.score == 0.0
        assert score.index == 0

    def test_valid_score_upper_bound(self):
        """Score of exactly 1.0 should be valid."""
        score = RerankerScore(index=5, score=1.0)
        assert score.score == 1.0

    def test_valid_score_midrange(self):
        """Scores in the middle of range should be valid."""
        for test_score in [0.25, 0.5, 0.75]:
            score = RerankerScore(index=0, score=test_score)
            assert score.score == test_score

    def test_score_below_lower_bound(self):
        """Scores below 0.0 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            RerankerScore(index=0, score=-0.1)
        assert "greater than or equal to 0" in str(exc_info.value) or "0.0" in str(exc_info.value)

    def test_score_above_upper_bound(self):
        """Scores above 1.0 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            RerankerScore(index=0, score=1.5)
        assert "less than or equal to 1" in str(exc_info.value) or "1.0" in str(exc_info.value)

    def test_score_way_above_upper_bound(self):
        """Very high scores should raise ValidationError."""
        with pytest.raises(ValidationError):
            RerankerScore(index=0, score=100.0)

    def test_index_negative(self):
        """Negative indices should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            RerankerScore(index=-1, score=0.5)
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_index_zero_valid(self):
        """Index of 0 should be valid (first document)."""
        score = RerankerScore(index=0, score=0.5)
        assert score.index == 0

    def test_score_none_invalid(self):
        """None score should raise ValidationError."""
        with pytest.raises(ValidationError):
            RerankerScore(index=0, score=None)

    def test_index_none_invalid(self):
        """None index should raise ValidationError."""
        with pytest.raises(ValidationError):
            RerankerScore(index=None, score=0.5)


# ============================================================================
# RERANKER SCORES COLLECTION VALIDATION
# ============================================================================


class TestRerankerScoresValidation:
    """Tests for RerankerScores collection validation."""

    def test_valid_scores_collection(self):
        """Valid collection of scores should be accepted."""
        scores = RerankerScores(
            scores=[
                RerankerScore(index=0, score=0.95),
                RerankerScore(index=1, score=0.87),
                RerankerScore(index=2, score=0.72),
            ]
        )
        assert len(scores.scores) == 3

    def test_empty_scores_invalid(self):
        """Empty scores list should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            RerankerScores(scores=[])
        assert "at least one score" in str(exc_info.value)

    def test_duplicate_indices_invalid(self):
        """Duplicate document indices should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            RerankerScores(
                scores=[
                    RerankerScore(index=0, score=0.9),
                    RerankerScore(index=0, score=0.8),  # Duplicate
                ]
            )
        assert "unique" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()

    def test_single_score_valid(self):
        """Single score in collection should be valid."""
        scores = RerankerScores(scores=[RerankerScore(index=0, score=0.5)])
        assert len(scores.scores) == 1

    def test_large_collection_valid(self):
        """Large collection of unique scores should be valid."""
        scores = RerankerScores(
            scores=[RerankerScore(index=i, score=i / 100) for i in range(100)]
        )
        assert len(scores.scores) == 100


# ============================================================================
# RERANKER SCORE DOCUMENTS VALIDATION
# ============================================================================


class TestRerankerScoreDocumentsValidation:
    """Tests for GeminiReranker.score_documents validation."""

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_score_documents_valid_indices(self, mock_llm_class, sample_documents):
        """Score documents should validate index ranges."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        # Mock structured LLM to return valid indices
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = RerankerScores(
            scores=[
                RerankerScore(index=0, score=0.95),
                RerankerScore(index=1, score=0.87),
                RerankerScore(index=2, score=0.72),
            ]
        )
        mock_llm.with_structured_output.return_value = mock_structured

        reranker = GeminiReranker()
        results = reranker.score_documents("test query", sample_documents[:3])

        assert len(results) == 3
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)
        assert all(0.0 <= score <= 1.0 for _, score in results)

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_score_documents_invalid_index_raises_error(
        self, mock_llm_class, sample_documents
    ):
        """Invalid document indices should raise RerankerValidationError."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        # Mock structured LLM to return invalid (out of range) indices
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = RerankerScores(
            scores=[
                RerankerScore(index=0, score=0.95),
                RerankerScore(index=10, score=0.87),  # Invalid: batch has only 3 docs
            ]
        )
        mock_llm.with_structured_output.return_value = mock_structured

        reranker = GeminiReranker()

        with pytest.raises(RerankerValidationError) as exc_info:
            reranker.score_documents("test query", sample_documents[:3])
        assert "invalid" in str(exc_info.value).lower()

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_score_documents_missing_scores_uses_fallback(
        self, mock_llm_class, sample_documents
    ):
        """Missing scores for some documents should use fallback (0.5)."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        # Mock structured LLM returning scores for only 2 of 3 documents
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = RerankerScores(
            scores=[
                RerankerScore(index=0, score=0.95),
                RerankerScore(index=1, score=0.87),
                # index=2 is missing, should get fallback 0.5
            ]
        )
        mock_llm.with_structured_output.return_value = mock_structured

        reranker = GeminiReranker()
        results = reranker.score_documents("test query", sample_documents[:3])

        assert len(results) == 3
        # Check that scores exist and are valid
        scores = [score for _, score in results]
        assert 0.5 in scores  # Fallback score should be present

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_score_documents_llm_error_raises_reranker_error(
        self, mock_llm_class, sample_documents
    ):
        """LLM API errors should raise RerankerLLMError."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        # Mock LLM to raise an exception
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = Exception("API rate limit exceeded")
        mock_llm.with_structured_output.return_value = mock_structured

        reranker = GeminiReranker()

        with pytest.raises(RerankerLLMError) as exc_info:
            reranker.score_documents("test query", sample_documents)
        assert "rate limit" in str(exc_info.value).lower() or "llm" in str(exc_info.value).lower()


# ============================================================================
# RERANKER BATCH PROCESSING
# ============================================================================


class TestRerankerBatchProcessing:
    """Tests for batch processing in reranking."""

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_batch_size_smaller_than_documents(self, mock_llm_class, sample_documents):
        """Reranker should process documents in batches."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        mock_structured = MagicMock()
        mock_structured.invoke.return_value = RerankerScores(
            scores=[
                RerankerScore(index=0, score=0.95),
                RerankerScore(index=1, score=0.87),
            ]
        )
        mock_llm.with_structured_output.return_value = mock_structured

        reranker = GeminiReranker()
        results = reranker.score_documents("test", sample_documents[:5], batch_size=2)

        # Should process in multiple batches but return all results
        assert len(results) == 5

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_empty_documents_returns_empty(self, mock_llm_class):
        """Empty document list should return empty results."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        reranker = GeminiReranker()
        results = reranker.score_documents("test", [])

        assert results == []

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_results_sorted_by_score_descending(self, mock_llm_class, sample_documents):
        """Results should be sorted by score in descending order."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        mock_structured = MagicMock()
        mock_structured.invoke.return_value = RerankerScores(
            scores=[
                RerankerScore(index=0, score=0.50),  # Low score
                RerankerScore(index=1, score=0.95),  # High score
                RerankerScore(index=2, score=0.72),  # Medium score
            ]
        )
        mock_llm.with_structured_output.return_value = mock_structured

        reranker = GeminiReranker()
        results = reranker.score_documents("test", sample_documents[:3])

        scores = [score for _, score in results]
        # Check that scores are in descending order
        assert scores == sorted(scores, reverse=True)


# ============================================================================
# RERANKER INITIALIZATION
# ============================================================================


class TestRerankerInitialization:
    """Tests for GeminiReranker initialization."""

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_initialization_creates_structured_llm(self, mock_llm_class):
        """Reranker should create structured LLM with output schema."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        reranker = GeminiReranker()

        assert reranker.model_name == "gemini-2.5-flash-lite"
        assert reranker.device == "cloud"
        mock_llm.with_structured_output.assert_called_once()

    @patch("reranker.ChatGoogleGenerativeAI")
    def test_initialization_with_custom_model(self, mock_llm_class):
        """Reranker should accept custom model name."""
        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm

        reranker = GeminiReranker(model_name="custom-model")

        assert reranker.model_name == "custom-model"
        mock_llm_class.assert_called()
