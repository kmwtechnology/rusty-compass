"""
Pytest configuration and fixtures for Rusty Compass tests.

Provides mock fixtures for external dependencies:
- Google Gemini API (LLM and embeddings)
- OpenSearch vector store
- PostgreSQL database
- Configuration defaults
"""

import sys
from pathlib import Path

# Add langchain_agent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from datetime import datetime
from typing import List, Tuple

from langchain_core.documents import Document


# ============================================================================
# CONFIGURATION FIXTURES
# ============================================================================


@pytest.fixture
def test_config():
    """Fixture providing test configuration overrides."""
    return {
        "RETRIEVER_K": 5,
        "RETRIEVER_FETCH_K": 20,
        "RETRIEVER_ALPHA": 0.5,
        "RERANKER_BATCH_SIZE": 10,
        "RERANKER_TOP_K": 3,
        "OPENSEARCH_INDEX_NAME": "test_docs",
        "VECTOR_COLLECTION_NAME": "test_collection",
    }


# ============================================================================
# DOCUMENT FIXTURES
# ============================================================================


@pytest.fixture
def sample_documents() -> List[Document]:
    """Fixture providing sample documents for testing."""
    return [
        Document(
            page_content="This is about Apache Lucene search functionality.",
            metadata={
                "source": "lucene-docs-search",
                "url": "https://lucene.apache.org/core/",
                "doc_type": "api",
            },
        ),
        Document(
            page_content="QueryParser is used to parse search query syntax.",
            metadata={
                "source": "lucene-docs-queryparser",
                "url": "https://lucene.apache.org/core/",
                "doc_type": "api",
            },
        ),
        Document(
            page_content="Lucille is a search ETL framework built on Apache Lucene.",
            metadata={
                "source": "lucille-readme",
                "url": "https://github.com/kmwllc/lucille",
                "doc_type": "documentation",
            },
        ),
        Document(
            page_content="Indexing documents requires field definitions and tokenizers.",
            metadata={
                "source": "lucene-indexing-guide",
                "url": "https://lucene.apache.org/",
                "doc_type": "guide",
            },
        ),
        Document(
            page_content="Full-text search returns relevant results based on term matching.",
            metadata={
                "source": "lucene-search-guide",
                "url": "https://lucene.apache.org/",
                "doc_type": "guide",
            },
        ),
    ]


@pytest.fixture
def scored_documents(sample_documents: List[Document]) -> List[Tuple[Document, float]]:
    """Fixture providing documents with relevance scores."""
    scores = [0.95, 0.87, 0.76, 0.65, 0.42]
    return list(zip(sample_documents, scores))


# ============================================================================
# MOCK GOOGLE GEMINI API
# ============================================================================


@pytest.fixture
def mock_gemini_llm():
    """Mock for ChatGoogleGenerativeAI (LLM)."""
    mock_llm = MagicMock()
    mock_llm.invoke = MagicMock()
    mock_llm.stream = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_llm)
    return mock_llm


@pytest.fixture
def mock_gemini_embeddings():
    """Mock for GoogleGenerativeAIEmbeddings."""
    mock_embeddings = MagicMock()
    # Return consistent embedding vectors for deterministic testing
    mock_embeddings.embed_query = MagicMock(
        return_value=[0.1] * 768  # 768-dimensional embedding
    )
    mock_embeddings.embed_documents = MagicMock(
        return_value=[[0.1 + i * 0.01] * 768 for i in range(5)]
    )
    return mock_embeddings


# ============================================================================
# MOCK OPENSEARCH
# ============================================================================


@pytest.fixture
def mock_opensearch_client():
    """Mock for OpenSearch client."""
    mock_client = MagicMock()

    # Mock search method
    mock_client.search = MagicMock(
        return_value={
            "hits": {
                "hits": [
                    {
                        "_id": "doc1",
                        "_score": 0.95,
                        "_source": {
                            "content": "Sample content 1",
                            "url": "https://example.com/1",
                            "doc_type": "api",
                        },
                    },
                    {
                        "_id": "doc2",
                        "_score": 0.87,
                        "_source": {
                            "content": "Sample content 2",
                            "url": "https://example.com/2",
                            "doc_type": "guide",
                        },
                    },
                ]
            }
        }
    )

    # Mock count method
    mock_client.count = MagicMock(return_value={"count": 1000})

    # Mock indices.exists
    mock_client.indices = MagicMock()
    mock_client.indices.exists = MagicMock(return_value=True)

    return mock_client


# ============================================================================
# MOCK POSTGRESQL
# ============================================================================


@pytest.fixture
def mock_postgres_connection():
    """Mock for PostgreSQL connection."""
    mock_conn = AsyncMock()
    mock_cursor = AsyncMock()

    # Mock cursor operations
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_cursor.fetchall = AsyncMock(return_value=[])

    mock_conn.cursor = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock()

    return mock_conn


# ============================================================================
# PYDANTIC EVENT FIXTURES
# ============================================================================


@pytest.fixture
def sample_query_evaluation_event():
    """Fixture providing a valid QueryEvaluationEvent."""
    from api.schemas.events import QueryEvaluationEvent

    return QueryEvaluationEvent(
        type="query_evaluation",
        query="How do I use Lucille for document indexing?",
        alpha=0.6,
        query_analysis="Semantic question about Lucille features",
        search_strategy="balanced",
    )


@pytest.fixture
def sample_reranker_scores():
    """Fixture providing valid RerankerScores."""
    from reranker import RerankerScores, RerankerScore

    return RerankerScores(
        scores=[
            RerankerScore(index=0, score=0.95),
            RerankerScore(index=1, score=0.87),
            RerankerScore(index=2, score=0.72),
            RerankerScore(index=3, score=0.61),
            RerankerScore(index=4, score=0.48),
        ]
    )


# ============================================================================
# PARAMETER COMBINATIONS FOR EDGE CASE TESTING
# ============================================================================


@pytest.fixture(
    params=[
        (0.0, "lexical-heavy"),  # Pure lexical
        (0.15, "lexical-heavy"),  # Lexical-leaning
        (0.5, "balanced"),  # Perfectly balanced
        (0.85, "semantic-heavy"),  # Semantic-leaning
        (1.0, "semantic-heavy"),  # Pure semantic
    ]
)
def alpha_and_strategy_pairs(request):
    """Fixture providing (alpha, strategy) pairs for validation testing."""
    return request.param


@pytest.fixture(
    params=[
        -0.1,  # Below lower bound
        -0.5,  # Well below lower bound
        1.1,  # Above upper bound
        2.0,  # Well above upper bound
        float("inf"),  # Infinity
        float("-inf"),  # Negative infinity
        float("nan"),  # NaN
    ]
)
def invalid_score_values(request):
    """Fixture providing invalid score values for testing bounds."""
    return request.param


# ============================================================================
# CONTEXT MANAGERS FOR PATCHING
# ============================================================================


@pytest.fixture
def mock_google_gemini_imports(monkeypatch):
    """Patch Google Gemini imports."""
    mock_llm_class = MagicMock()
    mock_embeddings_class = MagicMock()

    monkeypatch.setattr(
        "langchain_google_genai.ChatGoogleGenerativeAI",
        mock_llm_class,
    )
    monkeypatch.setattr(
        "langchain_google_genai.GoogleGenerativeAIEmbeddings",
        mock_embeddings_class,
    )

    return mock_llm_class, mock_embeddings_class


@pytest.fixture
def mock_opensearch_imports(monkeypatch):
    """Patch OpenSearch imports."""
    mock_client_class = MagicMock()
    monkeypatch.setattr("opensearchpy.OpenSearch", mock_client_class)
    return mock_client_class
